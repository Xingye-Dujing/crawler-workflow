"""One browser at a time per Chrome profile: the lane a directory owns.

chromedriver writes into ``<user-data-dir>/Default/Preferences`` *before* the browser starts,
so two sessions created in the same profile at the same moment cannot both come up: one of
them dies with ``session not created / failed to write prefs file`` (measured 2026-09: 2
failures in 8 barrier-synchronised attempts, and the failure is a race, not a schedule — it
can pass ten times in a row then take down a node). A parallel canvas is exactly where this
bites, because two workflows that crawl the same platform are started by the same thread pool.

The profile is what makes the run "the same device" to a site, so the answer is not a second
directory per consumer: it is one browser at a time per profile, which is also what the user's
own browser does. Different platforms keep running in parallel — only the same profile
serialises.

The lane is keyed on the **normalized absolute path**, because a directory is the device: not
the platform name (``<root>/<platform>`` moves when the root setting moves) and not the account
label (a rename is a new directory only once it has moved). ``sessions.profiles`` owns the path
policy and re-exports these names; this module owns the bookkeeping, and the wait's clock is
injectable so a bounded acquire can be tested without spending the wait.
"""

import contextlib
import os
import threading
import time

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def dir_key(path: str) -> str:
    """The lane identity of a directory: absolute, case-folded where the OS folds case."""
    return os.path.normcase(os.path.abspath(str(path or '')))


def lock_for(path: str) -> threading.Lock:
    """The lock that owns *path*, created on first use.

    A plain ``Lock``, deliberately **not** an ``RLock``: the browser is closed from a helper
    thread (``_close_login_browser`` gives ``quit()`` a bounded grace on a side thread so a
    hand-closed window cannot hang the run), and an RLock can only be released by the thread
    that took it — with one, every real crawl finished and left its profile claimed, so the
    next crawl of that platform waited out the whole timeout. The reentrancy an RLock would
    buy is not needed either: a workflow never holds two browsers for one platform at a time.
    """
    key = dir_key(path)
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


def forget_lock(path: str) -> None:
    """Drop the lane registered for a directory that no longer exists.

    Only a rename needs this today: the map is keyed on an absolute path, so a directory that
    moved leaves its old key behind. Nothing breaks by keeping it (an unheld ``Lock`` answers
    any later acquirer), but a rename done twice with the same name would otherwise hand back
    the lane of a device that was replaced — and the whole point of the key is that one path
    is one device.
    """
    with _LOCKS_GUARD:
        _LOCKS.pop(dir_key(path), None)


def acquire(path: str, timeout: float, abort=None, clock=time.monotonic):
    """Take exclusive use of *path*; return the lock, or None if it stayed busy.

    None is an answer the caller must not ignore: proceeding anyway is the crash this
    prevents. The timeout exists because a browser that was killed without closing would
    otherwise park every later run of that platform.

    ``abort`` makes the wait cancellable in half-second slices: a run the user stopped must
    not sit out the timeout behind a browser the stop has already closed — the wait ending on
    Stop is what lets the worker reach its finally and turn the record from 运行中 into its
    verdict. ``clock`` is :func:`time.monotonic` by default and injectable so the deadline
    rule (a wait that has run out answers None) is testable without waiting.
    """
    lock = lock_for(path)
    if abort is None:
        return lock if lock.acquire(timeout=timeout) else None
    deadline = clock() + float(timeout)
    while True:
        if abort():
            return None
        left = deadline - clock()
        if left <= 0:
            return None
        if lock.acquire(timeout=min(0.5, left)):
            return lock


def release_profile(lock) -> None:
    if lock is not None:
        with contextlib.suppress(RuntimeError):
            lock.release()


def is_busy(path: str) -> bool:
    """Whether some browser holds *path* at this instant.

    Advisory only — the answer is stale the moment it is returned, and a caller that *needed*
    ownership would take :func:`acquire` instead. It exists for the pre-run cookie probe:
    opening a second browser into a profile a live crawl owns would park that probe behind
    ``PROFILE_LOCK_TIMEOUT`` (longer than any crawl) and tell the user nothing about their
    cookie they could act on.
    """
    lock = lock_for(path)
    if lock.acquire(blocking=False):
        release_profile(lock)
        return False
    return True
