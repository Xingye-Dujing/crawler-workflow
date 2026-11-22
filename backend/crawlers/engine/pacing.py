"""The one pacing/tuning boundary every crawl reads.

Site-independent by definition: a pause is a pause on every platform. The measured
per-platform numbers (how long douyin needs for its skeleton rows, how many stuck
rounds zhihu tolerates before giving up) stay next to the code that was measured
against the site — they are **facts about the site**, not configuration. What the
user controls, globally, is how much extra time and patience to spend on top of those
baselines, **one dimension at a time** so a slow scroll can be separated from a slow
expand:

* ``crawl_pace_scale``     — polite pauses between network rounds, and in-walk naps;
* ``crawl_scroll_scale``   — how long a scroll's content may take to land before it is read;
* ``crawl_scroll_interval``— the pause between one scroll and the next, in **seconds**
  (paid by every scroll, never once per batch of three);
* ``crawl_expand_scale``   — the pause after 展开/更多 and the wait for it to mount;
* ``crawl_click_scale``    — the pause after any other UI click (tab, dismiss, dialog);
* ``crawl_wait_scale``     — card / panel / detail element waits;
* ``crawl_arrival_scale``  — the first-navigation settle (page arrival);
* ``crawl_page_scale``     — the pause between opening one page (note/article) and the next;
* ``crawl_jitter``         — how much each of those pauses may vary (± %), the human part;
* ``crawl_patience_scale`` — stuck rounds, retry counts.

They used to be three (pause / wait / patience) and the 慢速采集 preset wrote them as
concrete values. Painting every pause with one brush meant a user who needed a longer
scroll interval paid the same multiplier on every reply expansion and every polite
round; the split is what lets “scroll slowly, expand normally” be one settings page
instead of one compromise. Each dimension is still applied exactly once, and the
preset writes concrete values for every dimension, so no multiplier stacks.

``crawl_scroll_interval`` is the one entry stated in **seconds**, not as a multiplier:
it is the beat itself (how far apart two scrolls are), not a stretch of a measured
number, so nothing multiplies it — see :func:`scroll_nap` for how it sits beside the
mount time instead of replacing it.
"""

import random
import time

from runtime.settings import get_setting

#: The dimensions the humanising jitter applies to. A page-arrival wait and the element
#: wait are budgets, not beats: stretching them by chance buys no human rhythm, and it
#: would make "how long may this page take" a lottery.
_JITTERED_DIMENSIONS = ('scroll', 'expand', 'click')


def _raw(dimension: str) -> object:
    """The stored value for one dimension.

    Written as literal ``get_setting`` calls rather than a table lookup so the settings
    coverage gate can see every key this module really reads (it follows a literal
    argument, never a dict subscript).
    """
    if dimension == 'scroll':
        return get_setting('crawl_scroll_scale')
    if dimension == 'expand':
        return get_setting('crawl_expand_scale')
    if dimension == 'click':
        return get_setting('crawl_click_scale')
    if dimension == 'wait':
        return get_setting('crawl_wait_scale')
    if dimension == 'arrival':
        return get_setting('crawl_arrival_scale')
    if dimension == 'page':
        return get_setting('crawl_page_scale')
    if dimension == 'patience':
        return get_setting('crawl_patience_scale')
    return get_setting('crawl_pace_scale')


def _scale(dimension: str) -> float:
    """The user's multiplier for one dimension, falling back to the baseline 1.0."""
    try:
        value = float(_raw(dimension))
    except (TypeError, ValueError):
        return 1.0
    if dimension == 'patience':
        return max(1.0, value)
    return max(0.0, value)


def scroll_scale() -> float:
    """How much to stretch how long a scroll's content may take to land (and its mount time)."""
    return _scale('scroll')


def expand_scale() -> float:
    """How much to stretch the pause/wait that belongs to 展开/展开更多."""
    return _scale('expand')


def click_scale() -> float:
    """How much to stretch the settle that follows a plain UI click."""
    return _scale('click')


def scroll_interval() -> float:
    """The user's pause between one scroll and the next, in seconds.

    A plain number rather than a multiplier: "how far apart are my scrolls" is something a
    user can state, and the measured baselines it used to ride (0.12 s of mount time, which
    exists so intersection observers fire) were never a politeness interval at all — a
    three-scroll round therefore read as one burst. A missing or unparsable value is no
    extra wait, never a raise.
    """
    try:
        return max(0.0, float(get_setting('crawl_scroll_interval')))
    except (TypeError, ValueError):
        return 0.0


def wait_scale() -> float:
    """How much to stretch UI/content waits (not the page-arrival failure budget)."""
    return _scale('wait')


def arrival_scale() -> float:
    """How much to stretch a page-arrival settle (never the arrival failure budget)."""
    return _scale('arrival')


def jitter() -> float:
    """How far a beat may stray from its baseline, as a fraction (0.25 = ±25%).

    ``crawl_jitter`` is a percentage the user sets (0-90). Read on every pause, so a saved
    change applies to the next beat; a value that cannot be parsed is no jitter, never a
    reason to raise.
    """
    try:
        percent = float(get_setting('crawl_jitter'))
    except (TypeError, ValueError):
        return 0.0
    return min(90.0, max(0.0, percent)) / 100.0


def patience_scale() -> float:
    """How many more rounds/retries to allow on top of the measured baseline."""
    return _scale('patience')


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


# ─── sleeps ─────────────────────────────────────────────────────────────────
# Every pause below is ``measured baseline × that dimension's multiplier``. A negative
# request is a no-op wait, never a raised floor: this scales a pause, it does not impose
# a minimum.


def _sleep_scaled(seconds: float, dimension: str) -> None:
    delay = max(0.0, float(seconds)) * _scale(dimension)
    if dimension in _JITTERED_DIMENSIONS:
        # The human part: the same beat is never the same length twice. A zero jitter is
        # exactly the measured baseline, which is what every existing test pins.
        amount = jitter()
        if amount:
            delay *= random.uniform(1.0 - amount, 1.0 + amount)
    if delay > 0:
        time.sleep(delay)


def throttled_sleep(seconds: float) -> None:
    """Sleep *seconds*, stretched by the politeness (pause) multiplier."""
    _sleep_scaled(seconds, 'pause')


def nap(seconds: float) -> None:
    """A pause inside a walk (a polite page interval) — same rule as sleep."""
    throttled_sleep(seconds)


def scroll_nap(seconds: float) -> None:
    """One scroll's own beat: its mount time, then the interval before the next scroll.

    Two different quantities, each paid once, which is why this is not ``_sleep_scaled``:
    *seconds* is how long this site's content needs to mount (0.12 s for a viewport step,
    a longer figure where a comment panel is slower), scaled by ``crawl_scroll_scale``; the
    interval is the user's seconds between scrolls and is deliberately **not** multiplied,
    or a 3× preset would turn their 1.2 s into 3.6 s of arithmetic they never asked for.
    The jitter covers the whole beat — one scroll is one human pause.
    """
    delay = max(0.0, float(seconds)) * _scale('scroll') + scroll_interval()
    amount = jitter()
    if amount:
        delay *= random.uniform(1.0 - amount, 1.0 + amount)
    if delay > 0:
        time.sleep(delay)


def expand_nap(seconds: float) -> None:
    """The pause that lets a clicked 展开/更多 batch mount before the next read."""
    _sleep_scaled(seconds, 'expand')


def click_nap(seconds: float) -> None:
    """The settle after a plain UI click (a tab, a dialog's close control, a menu)."""
    _sleep_scaled(seconds, 'click')


def arrival_nap(seconds: float) -> None:
    """The settle after a navigation, before the page is read for the first time."""
    _sleep_scaled(seconds, 'arrival')


def wait_nap(seconds: float) -> None:
    """A poll pause while waiting for content to hydrate inside an already-open page."""
    _sleep_scaled(seconds, 'wait')


def page_nap(seconds: float) -> None:
    """A pause in the interval between two pages (a note, an article) being opened."""
    _sleep_scaled(seconds, 'page')


def navigation_budget() -> float:
    """How long one page load may stay outstanding before the renderer is called wedged.

    Measured failure (chromedriver sitting in ``WaitForPendingNavigations``) is silence, not
    a timeout: the browser command never returns, so no later line is ever printed. This is
    the budget a caller uses to turn that silence into a named failure; it scales with the
    user's page-load timeout but is capped, because a page that has not answered in three
    minutes is not "slow", it is stuck.
    """
    try:
        base = float(get_setting('page_load_timeout'))
    except (TypeError, ValueError):
        base = 40.0
    return min(180.0, max(60.0, base * 2.0))


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


def between_pages(base: float = 1.6, spread: float = 0.6) -> None:
    """A human-like pause between opening one page and the next.

    Measured complaint (2026-11-14): 小红书 watches how fast pages are opened, not only how
    the panel is scrolled, so a comment batch that opens note after note with no interval
    between them reads as a machine. The jitter is the human part — a constant 5 s is still
    a metronome — and the page-interval multiplier is what makes the interval a choice.
    Called by the executors between links, never for the first page of a batch.
    """
    drawn = max(0.4, float(base) + random.uniform(-float(spread), float(spread)))
    amount = jitter()
    if amount:
        drawn *= random.uniform(1.0 - amount, 1.0 + amount)
    page_nap(drawn)


# ─── waits and round counts ─────────────────────────────────────────────────


def wait(base: float) -> float:
    """A UI/content wait (card, panel, detail element) scaled by the wait multiplier."""
    return max(0.0, float(base)) * wait_scale()


def scroll_wait(base: float) -> float:
    """How long one scroll's content may take to arrive, scaled by the scroll multiplier."""
    return max(0.0, float(base)) * scroll_scale()


def expand_wait(base: float) -> float:
    """How long one expand batch may take to mount, scaled by the expand multiplier."""
    return max(0.0, float(base)) * expand_scale()


def click_wait(base: float) -> float:
    """How long a click-triggered surface (a modal, a menu) may take, scaled by the click multiplier."""
    return max(0.0, float(base)) * click_scale()


def arrival(base: float) -> float:
    """A page-arrival wait scaled by the arrival multiplier."""
    return max(0.0, float(base)) * arrival_scale()


def rounds(base: int | float) -> int:
    """A loop/retry count scaled by the user's patience setting, never below one."""
    return max(1, int(round(float(base) * patience_scale())))
