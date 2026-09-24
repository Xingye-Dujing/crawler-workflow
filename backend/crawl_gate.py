"""One platform is one conversation, and a parallel canvas has to be told that.

Two different reasons a pair of same-platform crawls must not start together:

* :mod:`browser_profiles` stops two *browsers* from being created inside one profile
  directory at the same instant — a Chrome-level fact, and it only exists while a
  profile is in use;
* the site itself answers two searches from one account within one second the way
  weibo and zhihu do — a passport redirect, risk code 40362 — *regardless* of which
  device each browser is on. Choosing 本次不用 Profile buys true parallelism and
  walks straight into this one, which is exactly what the profile lock cannot help
  with: there is no shared directory to argue about.

So this gate is keyed by **platform**, not by directory, and covers both. It is a
setting the user owns (``same_platform_queue``) rather than a policy imposed in code,
because what it buys is correctness and what it costs is the one thing 并行 was asked
for: time. The panel and the pre-run dialog both state that trade.
"""

import contextlib
import random
import threading
import time

from config import Config
from i18n import t
from settings_store import get_setting

#: One lock per platform, created on first use and never removed: a workflow that
#: finishes must not free a lock another one is already waiting on.
_LOCKS: dict[str, threading.Lock] = {}
_GUARD = threading.Lock()


def _lock_for(platform: str) -> threading.Lock:
    with _GUARD:
        lock = _LOCKS.get(platform)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[platform] = lock
        return lock


def enabled() -> bool:
    return bool(get_setting('same_platform_queue'))


def reset() -> None:
    """Forget every queue. Test isolation, never a runtime operation."""
    with _GUARD:
        _LOCKS.clear()


def _interruptible_sleep(seconds: float, abort) -> None:
    """Sleep in one-second pieces so 停止 is not held hostage by a back-off.

    A wait that cannot be cancelled would turn the user's Stop into a lie: the node
    keeps sleeping, the run keeps its slot, and the console says nothing.
    """
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if abort is not None and abort():
            return
        time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))


@contextlib.contextmanager
def hold(platform: str, log=None, abort=None):
    """Take *platform*'s turn, waiting for it when another crawl holds it.

    Yields whether this caller had to queue. The gap is paid **only** by a caller that
    actually waited: a serial canvas never contends, so making it sleep for a policy
    that protects somebody else's parallel run would be a cost invented out of
    nothing. The jitter is what keeps two crawls that took turns from looking like a
    metronome to the site on their way out.
    """
    platform = str(platform or '')
    if not platform or not enabled():
        yield False
        return
    lock = _lock_for(platform)
    # A non-blocking try first, because "did I queue?" has to be answered by whether
    # the platform was free *at the door*, not by whether a one-second poll happened
    # to time out. Reading it off the poll instead reports the caller that waited
    # 20 ms as uncontended — which is exactly the collision this gap exists to break:
    # the previous session of this account ended milliseconds ago.
    waited = not lock.acquire(blocking=False)
    if waited:
        deadline = time.monotonic() + Config.PLATFORM_GATE_TIMEOUT
        while True:
            if lock.acquire(timeout=1.0):
                break
            if abort is not None and abort():
                raise RuntimeError(t('run.queueAbandoned', platform=platform))
            if time.monotonic() >= deadline:
                # Refused *by platform name*: the alternative is a driver stack trace
                # that never says which of the two workflows is still holding the turn.
                raise RuntimeError(t('run.platformGateTimeout', platform=platform, n=int(Config.PLATFORM_GATE_TIMEOUT)))
    try:
        if waited:
            gap = Config.SAME_PLATFORM_STAGGER * (1 + random.random() * 0.25)
            if log is not None:
                log(t('run.platformQueued', platform=platform, n=int(round(gap))))
            _interruptible_sleep(gap, abort)
        yield waited
    finally:
        lock.release()
