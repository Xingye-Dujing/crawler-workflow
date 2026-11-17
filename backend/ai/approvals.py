"""Per-conversation approval grants for the workspace's mutating tools.

The HTTP route and the agent loop both need one answer to "did the user allow THIS exact call?".
A setting (``ai_auto_approve``) answers the coarse question; this module answers the fine one: a
grant is keyed by the conversation, the tool and a SHA-256 of the canonical arguments, so a model
that was allowed to run one command cannot silently run a different one. Nothing is persisted —
a restart simply asks again — and no secret is ever stored here.

A pending request is kept under the synthetic ``ask_user_question`` tool-call id: the answer turns
it into a grant (or not), which is how a pause/resume turn keeps its promise after the user
answers in a later request.
"""

import hashlib
import json
import threading

ONCE = 'once'
SESSION = 'session'

_LOCK = threading.Lock()
#: (conversation_id, tool, args fingerprint) → ONCE | SESSION
_GRANTS: dict[tuple[str, str, str], str] = {}
#: ask_user_question tool-call id → what that question is asking to allow
_PENDING: dict[str, dict] = {}


def fingerprint(args) -> str:
    """The canonical form the grant is keyed by: key order is not part of the request."""
    payload = json.dumps(args or {}, sort_keys=True, ensure_ascii=False, separators=(',', ':'), default=str)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def grant(conversation_id: str, tool: str, args, scope: str) -> None:
    """Remember that this account's conversation may run this exact call."""
    chosen = SESSION if scope == SESSION else ONCE
    with _LOCK:
        _GRANTS[(conversation_id, tool, fingerprint(args))] = chosen


def consume(conversation_id: str, tool: str, args) -> bool:
    """Spend the grant for this exact call: a ``once`` grant is gone, a ``session`` one is not."""
    key = (conversation_id, tool, fingerprint(args))
    with _LOCK:
        scope = _GRANTS.get(key)
        if scope is None:
            return False
        if scope == ONCE:
            _GRANTS.pop(key, None)
        return True


def revoke(conversation_id: str) -> int:
    """Drop every grant and pending request for one conversation; returns how many grants went."""
    with _LOCK:
        keys = [key for key in _GRANTS if key[0] == conversation_id]
        for key in keys:
            _GRANTS.pop(key, None)
        for call_id in [cid for cid, row in _PENDING.items() if row['conversation_id'] == conversation_id]:
            _PENDING.pop(call_id, None)
    return len(keys)


def request(conversation_id: str, tool: str, args, tool_call_id: str, labels: dict) -> None:
    """Register the question that is about to be asked, with the labels it will show.

    The labels are captured HERE, in the language the user is reading: the answer arrives in a
    later request and may be resolved under a different language, so matching on a fresh ``t()``
    would turn an approval into a silent denial.
    """
    with _LOCK:
        _PENDING[tool_call_id] = {
            'conversation_id': conversation_id,
            'tool': tool,
            'args': dict(args or {}),
            'labels': dict(labels or {}),
        }


def settle(conversation_id: str, tool_call_id: str, answers, custom: str = '') -> str:
    """Apply one answered approval question; returns the granted scope or ``''``.

    A denial, a cancel and an unrelated answer all grant nothing — the pending row is dropped
    either way, so a question can never be answered twice."""
    with _LOCK:
        pending = _PENDING.pop(tool_call_id, None)
    if pending is None or pending['conversation_id'] != conversation_id:
        return ''
    labels = pending['labels']
    chosen = ''
    for answer in answers or ():
        if not isinstance(answer, dict):
            continue
        selected = answer.get('selected') or []
        chosen = str(selected[0] if selected else '') or str(answer.get('custom') or '')
        break
    if not chosen and custom:
        chosen = custom
    if chosen and chosen == labels.get(SESSION):
        scope = SESSION
    elif chosen and chosen == labels.get(ONCE):
        scope = ONCE
    else:
        return ''
    grant(conversation_id, pending['tool'], pending['args'], scope)
    return scope


def reset() -> None:
    """Forget everything. Only tests use it: the registry is process state, not an account store."""
    with _LOCK:
        _GRANTS.clear()
        _PENDING.clear()
