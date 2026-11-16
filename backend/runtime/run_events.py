"""A tiny in-process event bus for run lifecycle notifications.

The run worker publishes facts; whoever is interested subscribes. The bus exists so the AI
workspace can watch a run without the engine importing the AI package (which would invert the
dependency direction and make a crawl depend on the chat store).

Rules:

- A listener is called with a plain dict and **must not raise into the run**: an exception is
  logged and the next listener still runs. A monitoring bug may never park or kill a crawl.
- ``publish`` is a no-op when nothing is subscribed, so the cost on a normal run is one truthiness
  check per event.
- Events carry counts, ids and console lines — never crawled text. A monitor that needs rows asks
  the run store with a read-only tool, not the bus.
"""

import logging
import threading

from i18n import t

logger = logging.getLogger('runtime.run_events')

_LISTENERS: list = []
_LOCK = threading.Lock()
#: A listener failure is logged; if that log line itself reaches the console handler (which
#: publishes a run.log), the nested publish must not re-enter the listeners — the handler is the
#: same thread and the same event, and unbounded recursion is worse than a dropped nested event.
_IN_PUBLISH = threading.local()


def subscribe(listener) -> None:
    """Register a callable ``listener(payload: dict)``. Idempotent per callable."""
    with _LOCK:
        if listener not in _LISTENERS:
            _LISTENERS.append(listener)


def unsubscribe(listener) -> None:
    with _LOCK:
        if listener in _LISTENERS:
            _LISTENERS.remove(listener)


def has_listeners() -> bool:
    return bool(_LISTENERS)


def listeners() -> list:
    with _LOCK:
        return list(_LISTENERS)


def publish(event: str, **fields) -> None:
    """Deliver one event to every listener. Never raises, and never re-enters itself."""
    if not _LISTENERS:
        return
    if getattr(_IN_PUBLISH, 'busy', False):
        return
    _IN_PUBLISH.busy = True
    try:
        payload = {'event': str(event or ''), **fields}
        for listener in listeners():
            try:
                listener(payload)
            except Exception:  # a monitoring failure is logged, never raised into the run
                logger.warning(t('run.eventListenerFailed', event=event), exc_info=True)
    finally:
        _IN_PUBLISH.busy = False
