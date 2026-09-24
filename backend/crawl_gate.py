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

So this gate is keyed by **platform**, not by directory. It offers the two answers
the user can actually mean, and they are not two names for one thing:

**真排队** (:func:`strict`, the setting 同平台排队采集) — one platform's crawl holds the
turn until it has *finished*, so nothing else of that platform runs at the same moment.
That is the only promise a persistent profile can keep anyway (one directory, one
browser), and taking it seriously means the per-run 「用不用 Profile」 question has no
choice left to ask: the queue is decided for the whole program.

**错峰** (with the switch off) — starts are spaced by 同平台错峰间隔 seconds and nothing
more. Two crawls of one platform may still be running over each other; that is the
真并行 the user asked for, with the one-second collision taken out of it. The spacing
is arithmetic about *overlap*: it is owed only while another crawl of that platform is
actually in flight, so a serial canvas — where the previous crawl finished before this
one was asked for — hands over seamlessly and pays nothing. The spacing is
what the wait buys, so the wait is the setting, not a constant in here.

Either way, a platform the user never runs twice at once pays nothing: an uncontended
turn sleeps for zero seconds.
"""

import contextlib
import random
import threading
import time

import crawl_capabilities as capabilities
from config import Config
from i18n import t
from settings_store import get_setting

#: One lock per platform, created on first use and never removed: a workflow that
#: finishes must not free a lock another one is already waiting on.
_LOCKS: dict[str, threading.Lock] = {}
#: A second set for the 错峰 mode, deliberately not shared with the one above: there it
#: is held only for the length of a wait, while here a strict turn is held for a whole
#: crawl. One lock serving both would let a mode switch park a crawl behind a run that
#: the new mode says it may overlap.
_START_LOCKS: dict[str, threading.Lock] = {}
#: When each platform last started a crawl, so 错峰 can space the starts.
_LAST_START: dict[str, float] = {}
#: Crawls of one platform that are inside the gate right now — waiting to start or
#: actually collecting. 错峰 is arithmetic about *overlap*: two same-platform crawls
#: that run over each other must not leave a second apart, while a serial canvas has
#: no company to wait for at all and hands over seamlessly. Without this count the
#: spacing was measured from the last start alone, so a serial node paid the gap for
#: a crawl that had finished long before it arrived.
_ACTIVE: dict[str, int] = {}
_GUARD = threading.Lock()


def _lock_for(platform: str, table: dict) -> threading.Lock:
    with _GUARD:
        lock = table.get(platform)
        if lock is None:
            lock = threading.Lock()
            table[platform] = lock
        return lock


def strict(platform: str = '') -> bool:
    """真排队 — a platform's turn is held until that crawl has finished.

    The matrix can force it per platform (:func:`crawl_capabilities.serial_only_of`):
    weibo answers one account's concurrent paging with the login wall, so 错峰
    cannot make that parallelism work whatever it is spaced by. A switch chooses a
    policy; it cannot outvote a measured wall.
    """
    return bool(get_setting('same_platform_queue')) or capabilities.serial_only_of(platform)


def stagger() -> float:
    """How far apart two starts of one platform stay, in the user's own seconds."""
    return float(get_setting('same_platform_stagger'))


def reset() -> None:
    """Forget every queue, every start time and every active seat. Test isolation, never a runtime act."""
    with _GUARD:
        _LOCKS.clear()
        _START_LOCKS.clear()
        _LAST_START.clear()
        _ACTIVE.clear()


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


def _now() -> float:
    """The clock the spacing is measured on, behind one function on purpose.

    错峰 arithmetic is arithmetic about *time passing*, and the test that stubs the sleep
    to keep the suite fast would otherwise schedule every later crawl from a clock that
    never moved — reporting a correct-looking gap of 10 s, 20 s, 30 s for three crawls
    that should start 10 s apart. A seam this small is cheaper than a fake that has to
    own the whole of :mod:`time`.
    """
    return time.monotonic()


def _space_the_start(platform: str, log=None, abort=None) -> bool:
    """错峰: keep this crawl's *start* away from the last one, then let it run.

    The spacing lock is released before the crawl begins, which is the whole
    difference from 真排队: two crawls of one platform may still be running over each
    other here, and only their departures are ordered. It is held *during* the wait,
    because two crawls that arrive together must not both decide "the gap is mine" and
    leave at the same instant — that is the collision this mode exists to remove.

    The gap is arithmetic about **overlap**: it is owed only while another crawl of
    this platform is actually in flight. A serial canvas has no company to wait for,
    and spacing its hand-offs would charge the user's seconds for a collision that
    cannot happen — the previous crawl finished before this one was even asked for.

    The start is recorded at its scheduled moment rather than at release, so a third
    arrival measures its own gap from a queue it cannot see finished.
    """
    gap = stagger()
    lock = _lock_for(platform, _START_LOCKS)
    blocked = not lock.acquire(blocking=False)
    if blocked:
        deadline = time.monotonic() + gap + Config.PLATFORM_GATE_TIMEOUT
        while not lock.acquire(timeout=0.5):
            if abort is not None and abort():
                raise RuntimeError(t('run.queueAbandoned', platform=platform))
            if time.monotonic() >= deadline:
                raise RuntimeError(t('run.platformGateTimeout', platform=platform, n=int(Config.PLATFORM_GATE_TIMEOUT)))
    try:
        now = _now()
        with _GUARD:
            others = _ACTIVE.get(platform, 0) - 1
        # Only *this* caller is in flight: the platform's earlier crawls have all
        # finished, so there is nothing left to collide with and no gap to pay.
        previous = _LAST_START.get(platform) if others > 0 else None
        ahead = max(0.0, gap - (now - previous)) if previous is not None else 0.0
        _LAST_START[platform] = now + ahead
        if ahead > 0:
            if log is not None:
                log(t('run.platformStaggered', platform=platform, n=int(round(ahead))))
            _interruptible_sleep(ahead, abort)
    finally:
        lock.release()
    # "Did I wait?" is the fact the console reports, and waiting for the lock is only
    # one way to wait: a crawl that found the platform free and still had to sit out the
    # gap was delayed just as much.
    return blocked or ahead > 0


@contextlib.contextmanager
def hold(platform: str, log=None, abort=None):
    """Take *platform*'s turn — held for the crawl when 真排队, for the wait when not.

    A serial-only platform (weibo: one account paging two sessions at once is answered
    by the login wall) takes the 真排队 branch whatever the switch says, and says why
    on the console the first time a second crawl has to wait behind it.

    Yields whether this caller had to wait, which is the fact the console reports, and
    the gap is paid **only** by a caller that actually waited: a serial canvas never
    contends, so making it sleep for a policy that protects somebody else's parallel run
    would be a cost invented out of nothing. The jitter is what keeps two crawls that
    took turns from looking like a metronome to the site on their way out.
    """
    platform = str(platform or '')
    if not platform:
        yield False
        return
    forced_serial = capabilities.serial_only_of(platform) and not get_setting('same_platform_queue')
    if not strict(platform):
        if stagger() <= 0:
            # No spacing asked for and no queue: this is the pre-feature behaviour, and
            # the canvas really does run both at once.
            yield False
            return
        # The seat is taken *before* the wait and held for the whole crawl: a caller
        # is company for another start-spacing from the moment it commits to this
        # platform, until its last page is on disk.
        with _GUARD:
            _ACTIVE[platform] = _ACTIVE.get(platform, 0) + 1
        try:
            yield _space_the_start(platform, log=log, abort=abort)
        finally:
            with _GUARD:
                _ACTIVE[platform] -= 1
        return
    lock = _lock_for(platform, _LOCKS)
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
        if waited and forced_serial and log is not None:
            # The user's switch said 错峰; this line is the difference between a
            # policy obeyed and a mystery stall.
            log(t('run.serialForced', platform=platform))
        if waited and stagger() > 0:
            gap = stagger() * (1 + random.random() * 0.25)
            if log is not None:
                log(t('run.platformQueued', platform=platform, n=int(round(gap))))
            _interruptible_sleep(gap, abort)
        yield waited
    finally:
        lock.release()
