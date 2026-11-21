"""Generic per-account store for results the user edited inside a node trace conversation.

The workflow node stays the source of truth until the user explicitly applies an edited result.
The file is keyed by run and node, so a rerun reads exactly the result that was confirmed, and a
different run cannot pick up another run's edit.

``consume`` is what the rerun path calls: the edit is applied ONCE, then removed so a later rerun
actually re-executes the node instead of replaying a stale edit forever.
"""

import contextlib
import json
import os
import re
from datetime import UTC, datetime

from core.atomic import replace as atomic_replace
from runtime import paths

# Run/node ids come from the workflow file and from AI tool arguments. They are path components, so
# the same strict shape codebooks use is enforced here — an absolute path or a slash must never let
# a caller write outside this account's node_results directory.
_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$')


def _clean_id(value: str, name: str) -> str:
    text = str(value or '').strip()
    if not text or not _ID_RE.fullmatch(text):
        raise ValueError(f'invalid {name}: {text!r}')
    return text


def _path(run_id: str, node_id: str) -> str:
    parent = os.path.join(paths.active().ai_files_dir, 'node_results', _clean_id(run_id, 'run_id'))
    return os.path.join(parent, f'{_clean_id(node_id, "node_id")}.json')


def save(run_id: str, node_id: str, result) -> dict:
    """Persist an edited node result. ``result`` is normally a list of row dicts."""
    run_id = _clean_id(run_id, 'run_id')
    node_id = _clean_id(node_id, 'node_id')
    if not isinstance(result, (dict, list)):
        raise ValueError('result must be a JSON object or array')
    path = _path(run_id, node_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {
        'schema': 1,
        'run_id': run_id,
        'node_id': node_id,
        'result': result,
        'applied_utc': datetime.now(UTC).isoformat(timespec='seconds'),
    }
    temporary = f'{path}.tmp'
    with open(temporary, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    atomic_replace(temporary, path)
    return data


def load(run_id: str, node_id: str) -> dict | None:
    try:
        with open(_path(run_id, node_id), encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def consume(run_id: str, node_id: str) -> dict | None:
    """Read and remove an applied edit; a later rerun then executes the node normally again."""
    path = _path(run_id, node_id)
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    # Best effort: a locked file must not block the rerun that already read the edit.
    with contextlib.suppress(OSError):
        os.remove(path)
    return data
