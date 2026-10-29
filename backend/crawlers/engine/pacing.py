"""The one pacing knob: what the 慢速采集 switch actually multiplies.

Site-independent by definition — a pause is a pause on every platform — so it lives in ``engine/``
rather than on :class:`crawlers.core.crawler.Crawler`, where the DOM crawlers'
:meth:`Crawler._polite_pause` and the comment engine's ``nap`` both used to keep a second copy of the
decision. Two homes for one switch is how a setting ends up honoured by half the program.
"""

import time

from runtime.settings import get_setting

#: How much :func:`throttled_sleep` and :meth:`Crawler._polite_pause` stretch every pause
#: when the 慢速采集 (``gentle_crawl``) setting is on. It is a pure pacing multiplier — it
#: changes no header, no fingerprint, no identity — because the goal is to make the crawl
#: LOOK unhurried to a platform's 风控, not to look like something it is not. 4× was chosen
#: so a normal ~1 s per-round pause becomes a few seconds: enough to break the metronome
#: rhythm a bot-detection model reads, without turning a shallow crawl into an all-day run.
GENTLE_PAUSE_FACTOR = 4.0


def gentle_crawl_on() -> bool:
    """Whether the user asked for gentle (slowed) crawling right now."""
    return bool(get_setting('gentle_crawl'))


def throttled_sleep(seconds: float) -> None:
    """Sleep *seconds*, scaled up when gentle crawl is on.

    A negative or zero request is a no-op wait, never a raised floor: this scales a pause, it does not
    impose a minimum.
    """
    delay = max(0.0, float(seconds))
    time.sleep(delay * (GENTLE_PAUSE_FACTOR if gentle_crawl_on() else 1.0))
