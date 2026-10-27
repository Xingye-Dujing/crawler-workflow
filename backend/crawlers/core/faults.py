"""The failure vocabulary a crawl answers with — four names, no browser, no site.

These are the outcomes that must be *told apart* by whatever catches them, which is why they are
one module rather than four lines scattered along the class hierarchy: a caller that reaches for
``Exception`` cannot tell "the user pressed 停止" from "the site answered a plate of nothing", and
this repo's crawlers deliberately tolerate the second about sixty times per walk.

Nothing here imports selenium, a driver, or a platform. The live tier's skip/no-skip decision, the
node runner's PARTIAL-vs-FAILED settlement and the reaper's "mark the session dead" all read these
names, so the module that defines them must be importable from anywhere in ``crawlers/`` — including
from the machinery that has no browser at all (``crawlers.backends.catbus``).
"""

from i18n import t


class CrawlerStopped(BaseException):
    """The user pressed 停止 and this crawl must end, keeping what it already paid for.

    Not an ``Exception`` subclass for one structural reason: this codebase reads a
    dead session, a missing card and a refused page as "keep going without it" in
    about sixty places, nearly all of them ``except Exception`` or
    ``contextlib.suppress(Exception)`` — a stop raised as an ordinary error would be
    swallowed into a silently short table, which is the opposite of what a stop is
    for. As a ``BaseException`` it walks out of every crawl loop unharmed and is
    caught once, by the node runner, which reports 被停止.

    It is also the difference between an honest short table and a dishonest one:
    measured, a killed driver makes an in-page ``fetch`` answer ``ERR …``, and
    ``engine/pagefetch.py`` folds that into "the site sent no more rows".
    """


class DeadDriver:
    """The session left in place of a browser that had to be killed by PID.

    Measured, and the two halves come apart. The command a worker is *inside* when the kill lands is
    freed by it in about 1.7 s: a dead chromedriver resets the socket, and a request already written is
    never re-sent. Every command after that is a fresh connect to a port nobody holds, and it costs
    16.3 s — four attempts at ~4.07 s, because selenium builds the pool with urllib3's default
    ``Retry(total=3)`` and a connect failure is always allowed to retry. A crawl sends several commands
    per row, so the worker 停止 was meant to release kept walking off a browser that no longer existed,
    ~29.6 s in the middle of one feed (``docs/crawler_notes.md``).

    Answering at once is the whole point, and answering *by name* is the rest of it:
    ``CrawlerStopped`` is a ``BaseException``, so it gets out of the about sixty ``except Exception``
    tolerances a walk has for a missing card or a refused page — the ones that would otherwise fold a
    dead session into "the site had no more rows" and report a stopped run as a short, successful crawl.

    ``quit`` and ``close`` stay silent rather than refusing, because this object is installed while
    another thread may still be inside ``Crawler.close()``: raising from a teardown would replace the
    crawl's own result with a stack trace, and ``contextlib.suppress(Exception)`` would not catch it.
    """

    def __getattr__(self, _name: str):
        raise CrawlerStopped(t('crawl.driverDead'))

    def quit(self) -> None:
        return None

    def close(self) -> None:
        return None


class ProfileUnavailableError(RuntimeError):
    """The browser was never built because the platform's profile could not be taken.

    Its own type because "a Chrome is not installed" and "Chrome is installed but
    somebody still holds this profile" arrive through the same `Exception` — and the
    live tier answers the first by skipping (nothing to test here) while the second
    MUST stay red: it is this machine failing to serialize its own crawls, and a skip is
    how that becomes invisible.
    """


class PageNotArrivedError(RuntimeError):
    """One page of a crawl stayed empty for the whole patience budget.

    Its own type because the user's next step differs from every other failure, and the
    sentence worth reading carries numbers: how long this waited, which page, and what a
    probe of this machine's own network says about it. Raised as an ordinary ``Exception``
    on purpose — the node runner already settles a refused source node the right way for
    this outcome (rows already streamed stay on disk, the node is ``partial`` where there
    are rows and ``failed`` where there are none, and a failed run is what makes 继续
    appear), so all this adds is a reason that can be told apart from a typo in a
    parameter.
    """

    def __init__(self, message: str, waited: float = 0.0, verdict: str = '', gave_up: int = 0):
        super().__init__(message)
        self.waited = float(waited)
        self.verdict = str(verdict or '')
        self.gave_up = int(gave_up)
