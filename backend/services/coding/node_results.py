"""Generic per-account store for results the user edited inside a node trace conversation.

The workflow node stays the source of truth until the user explicitly applies an edited result.
The file is keyed by run and node, so a rerun reads exactly the result that was confirmed, and a
different run cannot pick up another run's edit.
"""

import json
import os
from datetime import UTC, datetime

from core.atomic import replace as atomic_replace
from runtime import paths


def _path(run_id: str, node_id: str) -> str:
    parent = os.path.join(paths.active().ai_files_dir, 'node_results', str(run_id).replace('..', '_'))
    return os.path.join(parent, f'{str(node_id).replace("..", "_")}.json')


def save(run_id: str, node_id: str, result: dict) -> dict:
    if not run_id or not node_id:
        raise ValueError('run_id and node_id are required')
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
