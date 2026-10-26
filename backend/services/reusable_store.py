"""Reusable node templates: a named subgraph saved for reuse across canvases.

A template is a small workflow fragment: its own nodes, the wires between them, and the
ordered entry nodes an instance exposes as inputs. One terminal node is the template's
output. The store is a directory of JSON files under ``data/reusable_nodes/`` — the user's
authored object, like ``data/workflows/``, not a database row. A template is therefore
readable, copyable and backed up with the data root.

What is refused here, by name:
  * an empty node list, an unknown node type, duplicate ids or dangling wires;
  * a cycle (a fragment that cannot run in a topological order);
  * zero or several terminals (an instance would have no output or pick one silently);
  * input ids that are not nodes, and a duplicate template name.

Source/upload/comment/name/resume/reusable nodes are not allowed inside a template: a
reusable node is meant to receive its input from outside and do work, not to own a login,
a crawl or another group (which would make the input mapping recursive).
"""

import json
import os
import re
import threading
import time
import uuid

from config import Config
from i18n import t

#: A fragment is a user's authored work, not a crawl, so the caps are about keeping the
#: preview and the group block readable rather than protecting disk.
MAX_TEMPLATES = 200
MAX_NODES = 80
MAX_NAME = 80
MAX_DESCRIPTION = 500

#: Types that make sense inside a reusable fragment. Sources buy a session; uploads own a
#: dataset; comments are a crawl; name/resume are canvas mechanics; a nested reusable node
#: would need its own input mapping. Refusing them keeps one meaning for "input".
ALLOWED_TYPES = frozenset({'process', 'analysis', 'visualize', 'tokenize', 'biblio', 'fuse', 'output', 'compile'})

_ID = re.compile(r'^r-[0-9a-f]{12}$')

#: The uniqueness check and the write form one critical section: two tabs saving the same
#: name at once must not both pass "not taken" and leave two files with one name.
_lock = threading.Lock()


class TemplateCorruptError(RuntimeError):
    """A stored template file exists but is not a template this store wrote."""


def _now() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%S')


def _path(template_id: str) -> str:
    return os.path.join(Config.REUSABLE_DIR, f'{template_id}.json')


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float('inf') else None


def _validate(raw) -> dict:
    """The stored shape for one template, or ValueError naming what is wrong."""
    if not isinstance(raw, dict):
        raise ValueError(t('reusable.invalid'))
    name = str(raw.get('name') or '').strip()
    if not name:
        raise ValueError(t('reusable.nameRequired'))
    if len(name) > MAX_NAME:
        raise ValueError(t('reusable.nameTooLong', n=MAX_NAME))
    description = str(raw.get('description') or '').strip()
    if len(description) > MAX_DESCRIPTION:
        raise ValueError(t('reusable.descriptionTooLong', n=MAX_DESCRIPTION))
    nodes = raw.get('nodes')
    if not isinstance(nodes, list) or not nodes:
        raise ValueError(t('reusable.noNodes'))
    if len(nodes) > MAX_NODES:
        raise ValueError(t('reusable.tooManyNodes', n=MAX_NODES))
    clean_nodes = []
    seen = set()
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError(t('reusable.badNode'))
        nid = str(node.get('id') or '').strip()
        if not nid or nid in seen:
            raise ValueError(t('reusable.badNodeId', id=nid or '(empty)'))
        seen.add(nid)
        ntype = str(node.get('type') or '').strip()
        if ntype not in ALLOWED_TYPES:
            raise ValueError(t('reusable.badNodeType', type=ntype or '(empty)', id=nid))
        params = node.get('params')
        if params is not None and not isinstance(params, dict):
            raise ValueError(t('reusable.badNodeParams', id=nid))
        clean = {
            'id': nid,
            'type': ntype,
            'title': str(node.get('title') or ''),
            'params': dict(params or {}),
            'x': _number(node.get('x')) or 0,
            'y': _number(node.get('y')) or 0,
        }
        width = _number(node.get('w'))
        height = _number(node.get('h'))
        if width and width > 0:
            clean['w'] = width
        if height and height > 0:
            clean['h'] = height
        clean_nodes.append(clean)

    raw_connections = raw.get('connections')
    if raw_connections is None:
        raw_connections = []
    if not isinstance(raw_connections, list):
        raise ValueError(t('reusable.badConnections'))
    connections = []
    pairs = set()
    for conn in raw_connections:
        if not isinstance(conn, dict):
            raise ValueError(t('reusable.badConnections'))
        left = str(conn.get('from') or '')
        right = str(conn.get('to') or '')
        if left not in seen or right not in seen or left == right:
            raise ValueError(t('reusable.badConnection', a=left or '(empty)', b=right or '(empty)'))
        pair = (left, right)
        if pair in pairs:
            continue
        pairs.add(pair)
        connections.append({'from': left, 'to': right})
    _require_acyclic(clean_nodes, connections)

    inputs = raw.get('inputs')
    if inputs is None:
        inputs = []
    if not isinstance(inputs, list):
        raise ValueError(t('reusable.badInputs'))
    clean_inputs = []
    for value in inputs:
        nid = str(value or '')
        if nid not in seen:
            raise ValueError(t('reusable.badInput', id=nid or '(empty)'))
        if nid not in clean_inputs:
            clean_inputs.append(nid)

    outputs = raw.get('outputs')
    if outputs is None:
        outputs = []
    if not isinstance(outputs, list):
        raise ValueError(t('reusable.badOutputs'))
    clean_outputs = []
    for value in outputs:
        nid = str(value or '')
        if nid not in seen:
            raise ValueError(t('reusable.badOutput', id=nid or '(empty)'))
        if nid not in clean_outputs:
            clean_outputs.append(nid)
    if len(clean_outputs) != 1:
        raise ValueError(t('reusable.oneOutput', n=len(clean_outputs)))
    terminal = clean_outputs[0]
    if any(conn['from'] == terminal for conn in connections):
        raise ValueError(t('reusable.outputHasNext', id=terminal))

    return {
        'name': name,
        'description': description,
        'nodes': clean_nodes,
        'connections': connections,
        'inputs': clean_inputs,
        'outputs': clean_outputs,
    }


def _require_acyclic(nodes: list, connections: list) -> None:
    outgoing = {node['id']: [] for node in nodes}
    indegree = {node['id']: 0 for node in nodes}
    for conn in connections:
        outgoing[conn['from']].append(conn['to'])
        indegree[conn['to']] += 1
    ready = [nid for nid, degree in indegree.items() if degree == 0]
    visited = 0
    while ready:
        nid = ready.pop()
        visited += 1
        for nxt in outgoing[nid]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
    if visited != len(nodes):
        raise ValueError(t('reusable.cycle'))


def _load_file(path: str) -> dict:
    with open(path, encoding='utf-8') as f:
        payload = json.load(f)
    if not isinstance(payload, dict) or not _ID.match(str(payload.get('id') or '')):
        raise TemplateCorruptError(path)
    return payload


def _summary(payload: dict) -> dict:
    return {
        'id': str(payload.get('id')),
        'name': str(payload.get('name') or ''),
        'description': str(payload.get('description') or ''),
        'nodes': len(payload.get('nodes') or []),
        'connections': len(payload.get('connections') or []),
        'inputs': len(payload.get('inputs') or []),
        'updated_at': str(payload.get('updated_at') or ''),
        'broken': False,
    }


def _write_payload(payload: dict) -> None:
    os.makedirs(Config.REUSABLE_DIR, exist_ok=True)
    target = _path(str(payload['id']))
    tmp = target + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, target)


def list_templates() -> list:
    directory = Config.REUSABLE_DIR
    if not os.path.isdir(directory):
        return []
    out = []
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith('.json'):
            continue
        path = os.path.join(directory, filename)
        stem = filename[:-5]
        if not _ID.match(stem):
            continue
        try:
            payload = _load_file(path)
            out.append(_summary(payload))
        except (OSError, ValueError, TemplateCorruptError):
            # A broken file is still a row: the picker must be able to delete it.
            out.append(
                {
                    'id': stem,
                    'name': stem,
                    'description': '',
                    'nodes': 0,
                    'connections': 0,
                    'inputs': 0,
                    'updated_at': '',
                    'broken': True,
                }
            )
    out.sort(key=lambda row: (row['broken'], str(row['updated_at']), str(row['name']).lower()), reverse=True)
    return out


def get_template(template_id: str) -> dict | None:
    wanted = str(template_id or '')
    if not _ID.match(wanted):
        return None
    path = _path(wanted)
    try:
        return _load_file(path)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        raise TemplateCorruptError(wanted) from e


def validate_template(raw) -> dict:
    """The validated shape of one template, without writing it (used by import)."""
    return _validate(raw)


def save_template(raw) -> dict:
    """Create or update one template. ``id`` in the payload means update."""
    clean = _validate(raw)
    wanted = str((raw or {}).get('id') or '').strip() if isinstance(raw, dict) else ''
    if wanted and not _ID.match(wanted):
        raise ValueError(t('reusable.badId', id=wanted))
    template_id = wanted if _ID.match(wanted) else f'r-{uuid.uuid4().hex[:12]}'
    with _lock:
        existing = None
        if _ID.match(wanted):
            try:
                existing = _load_file(_path(template_id))
            except FileNotFoundError:
                existing = None
            except (OSError, ValueError) as e:
                raise ValueError(t('reusable.corrupt', id=template_id)) from e

        with_id = list_templates()
        if len(with_id) >= MAX_TEMPLATES and existing is None:
            raise ValueError(t('reusable.full', max=MAX_TEMPLATES))
        duplicate = next(
            (
                row
                for row in with_id
                if not row['broken'] and row['id'] != template_id and row['name'].casefold() == clean['name'].casefold()
            ),
            None,
        )
        if duplicate is not None:
            raise ValueError(t('reusable.nameTaken', name=clean['name']))

        now = _now()
        payload = {
            'version': 1,
            'id': template_id,
            **clean,
            'created_at': str((existing or {}).get('created_at') or now),
            'updated_at': now,
        }
        _write_payload(payload)
        return payload


def rename_template(template_id: str, name: str) -> dict | None:
    """Rename one template without touching its nodes, wiring or timestamps.

    An empty name is refused here like it is on save; a blank label is not a valid
    identity for the picker. ``None`` means the id names no stored template.
    """
    wanted = str(template_id or '')
    if not _ID.match(wanted):
        raise ValueError(t('reusable.badId', id=wanted or '(empty)'))
    clean_name = str(name or '').strip()
    if not clean_name:
        raise ValueError(t('reusable.nameRequired'))
    if len(clean_name) > MAX_NAME:
        raise ValueError(t('reusable.nameTooLong', n=MAX_NAME))
    with _lock:
        try:
            payload = _load_file(_path(wanted))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as e:
            raise ValueError(t('reusable.corrupt', id=wanted)) from e
        duplicate = next(
            (
                row
                for row in list_templates()
                if not row['broken'] and row['id'] != wanted and row['name'].casefold() == clean_name.casefold()
            ),
            None,
        )
        if duplicate is not None:
            raise ValueError(t('reusable.nameTaken', name=clean_name))
        payload['name'] = clean_name
        payload['updated_at'] = _now()
        _write_payload(payload)
        return _summary(payload)


def delete_template(template_id: str) -> bool:
    wanted = str(template_id or '')
    if not _ID.match(wanted):
        return False
    with _lock:
        path = _path(wanted)
        if not os.path.exists(path):
            return False
        os.remove(path)
        return True
