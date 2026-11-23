"""Run-monitor vocabulary: the names the panel offers and the rule the workspace matches.

The framework owns the monitor store, the delivery rows and the polling surface; this module owns
only the product's *vocabulary* — which run events exist, which node statuses and run outcomes a
rule may name — plus the normalization every door (preview, arm) shares. A monitor carries ids,
statuses and counts, never crawled text.
"""

from __future__ import annotations

from ai.errors import AIError

#: The event names a monitor may ask for. ``node.finished`` carries status/rows; ``run.log`` needs a
#: needle or it would fire on every line.
EVENTS = ('run.started', 'node.finished', 'run.finished', 'run.log')
STATUSES = ('done', 'restored', 'partial', 'failed', 'skipped')
OUTCOMES = ('completed', 'failed', 'interrupted')

_MAX_TRIGGERS = 50


def public_catalog() -> dict:
    """The names a manual monitor builder may offer, read from the SAME tables ``validate_spec``
    checks. The browser holds no second copy: a new event or status is offered only when the server
    can actually match it."""
    return {'events': list(EVENTS), 'statuses': list(STATUSES), 'outcomes': list(OUTCOMES)}


def _clean_events(raw) -> list:
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.split(',') if part.strip()]
    events = []
    for item in raw or ():
        name = str(item or '').strip()
        if name and name not in events:
            events.append(name)
    unknown = [name for name in events if name not in EVENTS]
    if unknown:
        raise AIError('ai.monitorEvent', kind='bad_request', event=unknown[0])
    return events or ['run.finished']


def _clean_list(raw) -> list:
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.split(',') if part.strip()]
    return [str(item or '').strip() for item in raw or () if str(item or '').strip()]


def validate_spec(payload: dict) -> dict:
    """Normalize and refuse a monitor that could not do what it says."""
    source = payload if isinstance(payload, dict) else {}
    events = _clean_events(source.get('events'))
    statuses = _clean_list(source.get('statuses'))
    outcomes = _clean_list(source.get('outcomes'))
    bad_status = [status for status in statuses if status not in STATUSES]
    if bad_status:
        raise AIError('ai.monitorStatus', kind='bad_request', status=bad_status[0])
    bad_outcome = [outcome for outcome in outcomes if outcome not in OUTCOMES]
    if bad_outcome:
        raise AIError('ai.monitorOutcome', kind='bad_request', outcome=bad_outcome[0])
    needle = str(source.get('console_contains') or '').strip()[:200]
    if 'run.log' in events and not needle:
        raise AIError('ai.monitorNeedle', kind='bad_request')
    if needle and 'run.log' not in events:
        events.append('run.log')
    try:
        min_rows = max(0, int(source.get('min_rows') or 0))
    except (TypeError, ValueError) as exc:
        raise AIError('ai.monitorRows', kind='bad_request') from exc
    try:
        max_triggers = max(1, min(_MAX_TRIGGERS, int(source.get('max_triggers') or 20)))
    except (TypeError, ValueError) as exc:
        raise AIError('ai.monitorRows', kind='bad_request') from exc
    return {
        'run_id': str(source.get('run_id') or '').strip()[:120],
        'events': events,
        'node_ids': _clean_list(source.get('node_ids'))[:50],
        'statuses': statuses,
        'outcomes': outcomes,
        'min_rows': min_rows,
        'console_contains': needle,
        'note': str(source.get('note') or '').strip()[:500],
        'max_triggers': max_triggers,
    }


def conditions(spec: dict, auto_analyze: bool = False) -> dict:
    """The product rule as the framework's monitor conditions.

    The framework matches one ``subject``; ``'*'`` is its "whatever run starts next", which is what
    a rule with a blank run id means. ``auto_analyze`` rides along so the delivery path can start a
    turn after the user armed it for that; it is never a server-side model call.
    """
    normalized = validate_spec(spec)
    return {
        **normalized,
        'subject': normalized.get('run_id') or '*',
        'auto_analyze': bool(auto_analyze),
    }


def public_monitor(row: dict) -> dict:
    """One framework monitor as the panel's shape (armed/stopped, spec, auto flag)."""
    conditions_row = row.get('conditions') or {}
    return {
        'id': str(row.get('id') or ''),
        'conversation_id': str(row.get('conversation_id') or ''),
        'status': 'armed' if str(row.get('status') or '') == 'active' else str(row.get('status') or ''),
        'spec': {key: value for key, value in conditions_row.items() if key not in ('subject', 'auto_analyze')},
        'auto_analyze': bool(conditions_row.get('auto_analyze')),
        'created_at': row.get('created_at') or '',
    }


def public_delivery(row: dict, monitor: dict | None) -> dict:
    """One delivery as the poller reads it: id, monitor, conversation and the run facts it names."""
    payload = dict(row.get('payload') or {})
    fields = payload.pop('fields', {}) or {}
    meta = {
        'event': payload.get('event') or '',
        'run_id': fields.get('run_id') or payload.get('subject') or '',
        'workflow': fields.get('workflow') or '',
        'node_id': fields.get('node_id') or '',
        'label': fields.get('label') or '',
        'status': fields.get('status') or payload.get('status') or '',
        'outcome': fields.get('outcome') or '',
    }
    meta.update(payload.get('counts') or {})
    return {
        'id': str(row.get('id') or ''),
        'monitor_id': str(row.get('monitor_id') or ''),
        'conversation_id': str((monitor or {}).get('conversation_id') or ''),
        'payload': meta,
        'event': meta['event'],
        'created_at': row.get('created_at') or '',
        'ack': bool(row.get('ack')),
    }
