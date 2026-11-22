"""Temporary, per-conversation permission to read rows of one dataset.

The dataset tools are read-only, but rows are the user's crawled content and a page can be large.
``dataset_peek`` stays free (five rows); every larger row read needs a grant the user gave in THIS
conversation for THIS dataset, with a row budget. The grant lives in process memory: a restart, an
explicit revoke, or closing the conversation's turn asks again. That is the "temporary" part — it
is deliberately not a browser preference that survives a reload.

A grant is created by answering the question the runtime asked on the model's behalf. The pending
row is keyed by the synthetic question's tool-call id, exactly like ``ai.approvals``; the answer
arrives in a later request, so labels are captured when the question is asked, not when it is
answered.
"""

from __future__ import annotations

import re
import threading

from ai.errors import AIError

_LOCK = threading.Lock()
#: (conversation_id, dataset_id) → {'name', 'max_rows', 'rows_read'}
_GRANTS: dict[tuple[str, str], dict] = {}
#: synthetic ask_user_question call id → what is being asked
_PENDING: dict[str, dict] = {}


def _key(conversation_id: str, dataset_id: str) -> tuple[str, str]:
    return (str(conversation_id or ''), str(dataset_id or ''))


def active(conversation_id: str) -> list[dict]:
    """The grants this conversation holds, with the row budget and what was spent."""
    with _LOCK:
        rows = [
            {
                'dataset_id': dataset_id,
                'name': str(row.get('name') or ''),
                'max_rows': int(row.get('max_rows') or 0),
                'rows_read': int(row.get('rows_read') or 0),
            }
            for (conversation, dataset_id), row in _GRANTS.items()
            if conversation == str(conversation_id or '')
        ]
    for row in rows:
        max_rows = row['max_rows']
        row['remaining'] = max(0, max_rows - row['rows_read']) if max_rows > 0 else 0
    return sorted(rows, key=lambda row: row['dataset_id'])


def grant(conversation_id: str, dataset_id: str, max_rows: int, name: str = '') -> dict:
    """Remember the user's answer. ``max_rows=0`` means "all rows"."""
    key = _key(conversation_id, dataset_id)
    row = {'name': str(name or ''), 'max_rows': max(0, int(max_rows or 0)), 'rows_read': 0}
    with _LOCK:
        _GRANTS[key] = row
    return {**row, 'dataset_id': key[1], 'remaining': row['max_rows'] if row['max_rows'] > 0 else 0}


def revoke(conversation_id: str, dataset_id: str = '') -> int:
    """Drop one grant, or every grant of the conversation; returns how many went."""
    with _LOCK:
        keys = [
            key
            for key in _GRANTS
            if key[0] == str(conversation_id or '') and (not dataset_id or key[1] == str(dataset_id))
        ]
        for key in keys:
            _GRANTS.pop(key, None)
        if not dataset_id:
            for call_id in [
                call_id for call_id, row in _PENDING.items() if row['conversation_id'] == str(conversation_id or '')
            ]:
                _PENDING.pop(call_id, None)
    return len(keys)


def request(
    conversation_id: str,
    dataset_id: str,
    max_rows: int,
    name: str,
    tool_call_id: str,
    labels: dict,
) -> None:
    """Register the question about to be asked, with the labels it will show."""
    with _LOCK:
        _PENDING[str(tool_call_id or '')] = {
            'conversation_id': str(conversation_id or ''),
            'dataset_id': str(dataset_id or ''),
            'max_rows': max(0, int(max_rows or 0)),
            'name': str(name or ''),
            'labels': dict(labels or {}),
        }


def _custom_rows(custom: str) -> int | None:
    """A typed answer is a row count when it contains digits; otherwise it grants nothing."""
    match = re.search(r'\d+', str(custom or ''))
    return int(match.group(0)) if match else None


def settle(conversation_id: str, tool_call_id: str, answers, custom: str = '') -> dict | None:
    """Apply one answered dataset-access question; returns the created grant or ``None``."""
    with _LOCK:
        pending = _PENDING.pop(str(tool_call_id or ''), None)
    if pending is None or pending['conversation_id'] != str(conversation_id or ''):
        return None
    chosen = ''
    for answer in answers or ():
        if not isinstance(answer, dict):
            continue
        selected = answer.get('selected') or []
        chosen = str(selected[0] if selected else '') or str(answer.get('custom') or '')
        break
    if not chosen and custom:
        chosen = custom
    labels = pending['labels']
    typed = _custom_rows(custom) if custom else None
    if chosen and chosen == labels.get('deny'):
        # An explicit denial wins over anything typed in the custom box: the button is the answer.
        return None
    if chosen and chosen == labels.get('allow'):
        max_rows = typed if typed is not None else int(pending['max_rows'])
    elif typed is not None:
        # A user who typed "300" instead of clicking the button granted 300 rows, not the request's
        # number; that is the point of a custom answer.
        max_rows = typed
    else:
        return None
    return grant(pending['conversation_id'], pending['dataset_id'], max_rows, pending['name'])


def consume(conversation_id: str, dataset_id: str, wanted: int) -> tuple[int, dict]:
    """Spend up to ``wanted`` rows from the grant; returns ``(allowed, state)``.

    Every row a tool returns passes through here: ``dataset_page``, ``dataset_sample`` and a
    filtered ``dataset_query``. A call without a conversation (a direct unit-test or internal
    read) is not an agent turn and has no grant to spend.
    """
    wanted = max(1, int(wanted or 1))
    if not conversation_id:
        return wanted, {}
    key = _key(conversation_id, dataset_id)
    with _LOCK:
        row = _GRANTS.get(key)
        if row is None:
            raise AIError('ai.datasetAccessNeeded', kind='bad_request', dataset=dataset_id)
        max_rows = int(row.get('max_rows') or 0)
        used = int(row.get('rows_read') or 0)
        if max_rows > 0 and used >= max_rows:
            raise AIError(
                'ai.datasetGrantExhausted',
                kind='bad_request',
                dataset=dataset_id,
                max_rows=max_rows,
                rows_read=used,
            )
        allowed = wanted if max_rows <= 0 else min(wanted, max_rows - used)
        row['rows_read'] = used + allowed
        state = {
            'max_rows': max_rows,
            'rows_read': row['rows_read'],
            'remaining': (max_rows - row['rows_read']) if max_rows > 0 else 0,
        }
    return allowed, state


def reset() -> None:
    """Forget everything. Only tests use it: the registry is process state, not an account store."""
    with _LOCK:
        _GRANTS.clear()
        _PENDING.clear()
