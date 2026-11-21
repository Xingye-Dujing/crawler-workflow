"""Per-account codebook storage with atomic writes and explicit versions.

The same codebook feeds the workflow node and the AI workspace conversation. A pass never silently
overwrites an approved version: ``save`` with an existing id and a different body creates the next
version, and every version keeps the evidence quotes the model cited so a paper can audit the code.
"""

import json
import os
import re
import uuid
from datetime import UTC, datetime

from core.atomic import replace as atomic_replace
from runtime import paths

CODEBOOK_ID_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{1,63}$')


class CodebookError(ValueError):
    """An invalid codebook id or payload; refused by name."""


def _root() -> str:
    return os.path.join(paths.active().ai_files_dir, 'codebooks')


def _path(codebook_id: str) -> str:
    text = str(codebook_id or '').strip()
    if not CODEBOOK_ID_RE.match(text):
        raise CodebookError(f'invalid codebook id {text!r}')
    return os.path.join(_root(), f'{text}.json')


def list_codebooks() -> list[dict]:
    root = _root()
    if not os.path.isdir(root):
        return []
    rows = []
    for name in sorted(os.listdir(root)):
        if not name.endswith('.json'):
            continue
        try:
            with open(os.path.join(root, name), encoding='utf-8') as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            continue  # a half-written file is not a codebook this program wrote
        rows.append(
            {'id': data.get('id') or name[:-5], 'name': data.get('name') or '', 'version': data.get('version', 1)}
        )
    return rows


def load_codebook(codebook_id: str) -> dict:
    path = _path(codebook_id)
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except OSError as exc:
        raise CodebookError(f'no codebook {codebook_id!r} in this account') from exc
    except ValueError as exc:
        raise CodebookError(f'codebook {codebook_id!r} is unreadable') from exc
    return data


def save_codebook(payload: dict, *, codebook_id: str = '') -> dict:
    """Create or version one codebook; an existing id bumps ``version`` rather than overwriting."""
    if not isinstance(payload, dict):
        raise CodebookError('a codebook must be a JSON object')
    name = str(payload.get('name') or '').strip()
    if not name:
        raise CodebookError('a codebook needs a name')
    wanted = str(codebook_id or payload.get('id') or '').strip()
    previous = None
    if wanted:
        try:
            previous = load_codebook(wanted)
        except CodebookError:
            previous = None
    identifier = wanted or f'cb_{uuid.uuid4().hex[:10]}'
    data = {
        'id': identifier,
        'name': name,
        'version': int((previous or {}).get('version', 0)) + 1,
        'phase': str(payload.get('phase') or (previous or {}).get('phase') or 'open'),
        'codes': list(payload.get('codes') or []),
        'categories': list(payload.get('categories') or []),
        'core_category': str(payload.get('core_category') or ''),
        'memo': str(payload.get('memo') or ''),
        'source': dict(payload.get('source') or {}),
        'updated_utc': datetime.now(UTC).isoformat(timespec='seconds'),
    }
    path = _path(identifier)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = f'{path}.tmp'
    with open(temporary, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    atomic_replace(temporary, path)
    return data


def save_reliability(codebook_id: str, reliability: dict) -> dict | None:
    """Attach dual-coder reliability to a codebook WITHOUT minting a new version.

    A coding run's kappa is an observation about the run, not a revision of the categories the
    researcher approved. Writing it through ``save_codebook`` bumped ``version`` on every run, so a
    codebook edited once could show version 12 after a dozen recodings with identical codes.
    """
    try:
        data = load_codebook(codebook_id)
    except CodebookError:
        return None
    data.setdefault('source', {})['reliability'] = dict(reliability)
    path = _path(codebook_id)
    temporary = f'{path}.tmp'
    with open(temporary, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    atomic_replace(temporary, path)
    return data


def delete_codebook(codebook_id: str) -> bool:
    path = _path(codebook_id)
    if not os.path.isfile(path):
        return False
    os.remove(path)
    return True
