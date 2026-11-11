"""The one pacing/tuning boundary every crawl reads.

Site-independent by definition: a pause is a pause on every platform. The measured
per-platform numbers (how long douyin needs for its skeleton rows, how many stuck
rounds zhihu tolerates before giving up) stay next to the code that was measured
against the site — they are **facts about the site**, not configuration. What the
user controls, globally, is how much extra time and patience to spend on top of those
baselines:

* ``crawl_pace_scale``    — polite pauses and in-walk naps;
* ``crawl_wait_scale``    — card / modal / detail / arrival waits;
* ``crawl_patience_scale``— stuck rounds, retry counts.

The 慢速采集 preset writes these three plus a few safety switches as concrete values,
which is why nothing here multiplies a second "gentle" factor: one scale, one result.
"""

import random
import time

from runtime.settings import get_setting


def pace_scale() -> float:
    """How much to stretch every politeness pause and in-walk nap."""
    try:
        return max(0.0, float(get_setting('crawl_pace_scale')))
    except (TypeError, ValueError):
        return 1.0


def wait_scale() -> float:
    """How much to stretch UI/content waits (not the page-arrival failure budget)."""
    try:
        return max(0.0, float(get_setting('crawl_wait_scale')))
    except (TypeError, ValueError):
        return 1.0


def patience_scale() -> float:
    """How many more rounds/retries to allow on top of the measured baseline."""
    try:
        return max(1.0, float(get_setting('crawl_patience_scale')))
    except (TypeError, ValueError):
        return 1.0


def page_wait_timeout() -> float:
    """One page's first-content budget (the user's setting, in seconds)."""
    try:
        return max(1.0, float(get_setting('page_wait_timeout')))
    except (TypeError, ValueError):
        return 300.0


def max_pending_waits() -> int:
    """How many consecutive pages may fail to arrive before the breaker trips."""
    try:
        return max(1, int(get_setting('max_pending_waits')))
    except (TypeError, ValueError):
        return 2


def wait(base: float) -> float:
    """A UI/content wait (card, modal, detail) scaled by the user's choice."""
    return max(0.0, float(base)) * wait_scale()


def arrival(base: float) -> float:
    """A page-arrival style wait scaled by the user's choice."""
    return max(0.0, float(base)) * wait_scale()


def rounds(base: int | float) -> int:
    """A loop/retry count scaled by the user's patience setting, never below one."""
    return max(1, int(round(float(base) * patience_scale())))


def throttled_sleep(seconds: float) -> None:
    """Sleep *seconds*, stretched by the global pace scale.

    A negative or zero request is a no-op wait, never a raised floor: this scales a
    pause, it does not impose a minimum.
    """
    delay = max(0.0, float(seconds)) * pace_scale()
    if delay > 0:
        time.sleep(delay)


def nap(seconds: float) -> None:
    """A pause inside a walk (comment engines, platform screens) — same rule as sleep."""
    throttled_sleep(seconds)


def poll_tick(seconds: float) -> None:
    """A fixed poll cadence, deliberately NOT scaled.

    A loop whose iteration count is derived from a budget must keep the same total
    wall-clock (a longer tick would silently stretch the budget). Pacing belongs in the
    pauses *between* network rounds, which is what :func:`nap` is for.
    """
    delay = max(0.0, float(seconds))
    if delay > 0:
        time.sleep(delay)


def polite(base: float = 1.0, spread: float = 0.4) -> None:
    """Jittered pause between rounds that hit the network.

    The jitter is what keeps a run of crawls from looking like a metronome; the scale
    is what turns the same rhythm into the 慢速采集 template.
    """
    throttled_sleep(max(0.2, float(base) + random.uniform(-float(spread), float(spread))))


def gentle_crawl_on() -> bool:
    """Compatibility read: whether the user has stretched pacing beyond the baseline."""
    return pace_scale() > 1.0
