"""Run monitors: an AI-requested watch on a running (or next) workflow.

The AI proposes a monitor as an artifact; the user arms it. From then on the run publishes
lifecycle events (``runtime.run_events``), this module matches them against the armed specs and
writes one durable delivery row per match. The browser is the reaction: it polls for pending
deliveries, shows the event in its conversation, and — when the monitor was armed for automatic
analysis — starts a turn with the stored key. The server never spends a token on its own and never
holds an API key, which is why a trigger can wait for hours without costing anything.

A monitor carries no crawled text: an event is an id, a status and counts. The automatic turn's
prompt tells the model to read the run through its read-only tools, so the evidence still comes
from the run store.
"""

import logging
import queue
import threading
import time

from runtime import paths, run_events

from ai import store
from ai.errors import AIError
from i18n import t

logger = logging.getLogger('ai.monitors')

#: The event names a monitor may ask for. ``node.finished`` carries status/rows; ``run.log`` needs a
#: needle or it would fire on every line.
EVENTS = ('run.started', 'node.finished', 'run.finished', 'run.log')
STATUSES = ('done', 'restored', 'partial', 'failed', 'skipped')
OUTCOMES = ('completed', 'failed', 'interrupted')

_MAX_TRIGGERS = 50
_CACHE: dict = {}
_CACHE_SECONDS = 10.0
_CACHE_LOCK = threading.Lock()


def invalidate() -> None:
    """Drop the armed-monitor cache after a create/delete."""
    with _CACHE_LOCK:
        _CACHE.clear()


def _armed() -> list:
    """The armed monitors for the account this event belongs to, cached briefly.

    A run emits one ``run.log`` per console line; opening SQLite per line would put a disk commit
    in front of the console. The cache is keyed by the account's ai.db path and invalidated the
    moment this process creates or deletes a monitor.
    """
    path = paths.active().ai_db
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(path)
        if cached is not None and cached[0] > now:
            return cached[1]
    rows = store.list_monitors(active_only=True)
    with _CACHE_LOCK:
        _CACHE[path] = (now + _CACHE_SECONDS, rows)
    return rows


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


def create(conversation_id: str, payload: dict, auto_analyze: bool = False) -> dict:
    if store.get_conversation(conversation_id) is None:
        raise AIError('ai.apiNoConversation', kind='not_found', conversation=conversation_id)
    spec = validate_spec(payload)
    row = store.add_monitor(conversation_id, spec, auto_analyze)
    invalidate()
    return row


def cancel(monitor_id: str) -> bool:
    deleted = store.delete_monitor(monitor_id)
    invalidate()
    return deleted


def _run_id_matches(spec: dict, payload: dict) -> bool:
    wanted = str(spec.get('run_id') or '').strip()
    if not wanted or wanted == '*':
        return True
    records = payload.get('records') or []
    return wanted == str(payload.get('run_id') or '') or wanted in {str(item) for item in records}


def matches(spec: dict, payload: dict) -> bool:
    if not isinstance(spec, dict):
        return False
    event = str(payload.get('event') or '')
    if event not in (spec.get('events') or ()):
        return False
    if not _run_id_matches(spec, payload):
        return False
    if event == 'node.finished':
        node_ids = spec.get('node_ids') or []
        if node_ids and str(payload.get('node_id') or '') not in node_ids:
            return False
        statuses = spec.get('statuses') or []
        if statuses and str(payload.get('status') or '') not in statuses:
            return False
        if int(payload.get('rows') or 0) < int(spec.get('min_rows') or 0):
            return False
    elif event == 'run.finished':
        outcomes = spec.get('outcomes') or []
        if outcomes and str(payload.get('outcome') or '') not in outcomes:
            return False
    elif event == 'run.log':
        needle = str(spec.get('console_contains') or '').strip().lower()
        if not needle or needle not in str(payload.get('line') or '').lower():
            return False
    return True


def _compact(payload: dict) -> dict:
    """What a delivery keeps: ids, status and counts — never the run's text.

    ``run.log`` used to keep the matched console line, which can quote a crawled post or a
    script's stderr; the automatic turn reads the console through ``run_console`` instead.
    """
    keep = (
        'event',
        'run_id',
        'workflow',
        'node_id',
        'node_type',
        'label',
        'status',
        'rows',
        'outcome',
        'done',
        'total',
        'failed',
        'skipped',
        'resume',
    )
    return {key: payload.get(key) for key in keep if payload.get(key) not in (None, '')}


def _cached_armed() -> list | None:
    """Armed monitors only while the cache is warm; ``None`` means "ask the worker"."""
    path = paths.active().ai_db
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(path)
        if cached is not None and cached[0] > now:
            return cached[1]
    return None


def _deliver(payload: dict) -> None:
    event = str(payload.get('event') or '')
    for monitor in _armed():
        spec = monitor.get('spec') or {}
        if not matches(spec, payload):
            continue
        body = _compact(payload)
        store.add_monitor_event(monitor['id'], monitor['conversation_id'], event, body)
        store.touch_monitor(monitor['id'], int(spec.get('max_triggers') or 20))


def _on_event(payload: dict) -> None:
    """Queue one matching event. Never opens SQLite on the run thread.

    The run emits one ``run.log`` per console line; a listener that wrote a row inline put a disk
    commit in front of the crawl. Filtering uses the warm cache when it has one and otherwise
    defers to the worker, which loads the list off the run thread.
    """
    if str(payload.get('event') or '') not in EVENTS:
        return
    armed = _cached_armed()
    if armed is not None and not armed:
        return
    _QUEUE.put(payload)


_QUEUE: queue.Queue = queue.Queue()
_WORKER: threading.Thread | None = None
_STARTED = False
_LOCK = threading.Lock()


def _work() -> None:
    while True:
        payload = _QUEUE.get()
        try:
            try:
                _deliver(payload)
            except Exception:  # a monitoring failure is logged, never raised into the run
                logger.warning(t('run.eventListenerFailed', event=payload.get('event') or ''), exc_info=True)
        finally:
            _QUEUE.task_done()


def drain(timeout: float | None = None) -> bool:
    """Wait until queued deliveries are written; used by tests and shutdown."""
    started = time.monotonic()
    while _QUEUE.unfinished_tasks:
        if timeout is not None and time.monotonic() - started > timeout:
            return False
        time.sleep(0.01)
    return True


def start() -> None:
    """Subscribe once and start the one delivery worker. Called when the AI blueprint is imported."""
    global _STARTED, _WORKER
    with _LOCK:
        if _STARTED:
            return
        _STARTED = True
        _WORKER = threading.Thread(target=_work, name='ai-monitors', daemon=True)
        _WORKER.start()
    run_events.subscribe(_on_event)
