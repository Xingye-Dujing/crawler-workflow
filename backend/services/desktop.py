"""The desktop shell's notification sink — one process-local callback, nothing else.

The packaged launchers (``desktop/desktop_entry.py``, ``desktop/macos_entry.py``) run the Flask app
in their own process and own a tray icon / notification centre. The *decision* to notify (a run
finished, a scheduled task started) belongs to the engine, because that is where the facts are; the
*delivery* belongs to the shell, because only it knows whether a system tray exists. This module is
the seam between them and holds no platform code.

Rules:

* no shell installed means :func:`active` is ``False`` and :func:`notify` is a no-op — a source
  run (``python app.py``) and a cloud deploy have no tray and must not pretend otherwise;
* a notifier that raises is swallowed. A notification is a convenience; it may never take down the
  worker thread that just finished a multi-hour crawl.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

_notifier: Callable[[str, str], None] | None = None
_lock = threading.Lock()


def set_notifier(callback: Callable[[str, str], None] | None) -> None:
    """Install the shell's notifier (``None`` removes it). Called once per launch."""
    global _notifier
    with _lock:
        _notifier = callback if callable(callback) else None


def clear_notifier() -> None:
    set_notifier(None)


def active() -> bool:
    """Whether this process has somewhere to deliver a system notification."""
    with _lock:
        return _notifier is not None


def notify(title: str, message: str = '') -> bool:
    """Deliver one notification; ``False`` when there is no shell or the shell failed.

    Never raises: the caller is usually a run's ``finally`` block, where an exception would skip
    the queue hand-off and the log-sink disarm.
    """
    with _lock:
        callback = _notifier
    if callback is None:
        return False
    try:
        callback(str(title), str(message))
    except Exception:
        return False
    return True
