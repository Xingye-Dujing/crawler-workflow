"""Every crawl loop has to be able to hear 停止, and this counts that it can.

Pressing 停止 used to be a request the crawlers did not read: the Stop handler closed
the browsers and set two flags, and nothing in ``crawlers/`` or
``engine/workflow.py`` ever asked about them. The scrolls kept harvesting until a page
load happened to fail — which is the difference between "stopped" and "stopped, and it
is still crawling when I can see the window moving".

Two shapes of proof live here:

* **the sink contract** — ``Crawler.emit`` refuses to accept a row once the run has
  been stopped, raising :class:`CrawlerStopped`. It is checked there rather than at
  each call site because *every* crawl streams through it, so a hand-rolled loop and a
  platform written next month are covered without knowing;
* **the wiring audit** — each shared walk (`feed.walk_feed`, `pager.walk_pages`) takes
  a stop predicate, and the walkers had them wired to the wall flags only. The count of
  walk call sites is pinned, and each one must pass a predicate that asks
  ``may_stop``: a new walk that forgets is red, and so is deleting this test to make
  the failure go away.
"""

import ast
from pathlib import Path

import pytest
from test_crawler_base import Probe, bare

from crawlers.base import Crawler, CrawlerStopped

CRAWLERS_DIR = Path(__file__).resolve().parents[2] / 'backend' / 'crawlers'

#: `walk_feed` is asked `stopped=…`, `walk_pages` `alive=…`; both are the same question
#: pointed the other way, and both are the only ways a shared walk can end early.
PREDICATES = {'walk_feed': 'stopped', 'walk_pages': 'alive'}


def _walk_calls():
    """Every ``feed.walk_feed(…)`` / ``pager.walk_pages(…)`` call under crawlers/."""
    found = []
    for path in sorted(CRAWLERS_DIR.rglob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, 'id', '')
            if name in PREDICATES:
                found.append((path.name, name, node))
    return found


class TestSinkRefusesAfterStop:
    def test_a_row_is_still_accepted_while_the_run_is_alive(self):
        crawler = bare(None, _abort=lambda: False)
        assert crawler.emit({'标题': 'a'}) is True
        assert crawler.collected() == 1

    def test_the_stop_is_refused_at_the_row_boundary_not_the_end_of_the_crawl(self):
        crawler = bare(None, _abort=lambda: True)
        with pytest.raises(CrawlerStopped):
            crawler.emit({'标题': 'a'})
        assert crawler.collected() == 0, 'a refused row must not count as collected'

    def test_nothing_stops_a_crawler_nobody_asked(self):
        """The login window and the cookie probe pass no predicate at all: their
        browser is not a crawl, and treating an absent answer as "stop" would end
        every cookie capture the moment the user paused."""
        crawler = bare(None)
        assert crawler.may_stop() is False
        assert crawler.emit({'标题': 'a'}) is True

    def test_a_double_is_not_a_stop(self):
        crawler = bare(None, _abort=lambda: False)
        assert crawler.emit(None) is False

    def test_the_stop_is_a_base_exception_so_nothing_can_swallow_it(self):
        """``except Exception`` / ``contextlib.suppress(Exception)`` are how this
        package reads a dead session or a missing card without aborting the walk. A
        stop raised as an ordinary error would be folded into "keep going, nothing
        here", which is the silent under-collection this class exists to prevent."""
        assert issubclass(CrawlerStopped, BaseException)
        assert not issubclass(CrawlerStopped, Exception)


class TestWalkWiring:
    """The stop predicate must reach every shared walk — measured, not assumed."""

    def test_the_audit_actually_found_the_walks_it_claims_to_check(self):
        calls = _walk_calls()
        # Measured over the platform modules: zhihu/x/video comment walks by feed,
        # weibo and the comment pager by walk_pages. A lower count means the scan
        # broke, and a broken scan is what makes a green "all wired" assertion empty.
        assert len(calls) >= 6, f'only {len(calls)} walk call sites found: {sorted({c[0] for c in calls})}'
        assert {'zhihu.py', 'twitter.py', 'video.py', 'weibo.py', 'comments.py'} <= {c[0] for c in calls}

    def test_every_walk_asks_the_crawler_whether_it_may_stop(self):
        missing = []
        for file_name, walk, node in _walk_calls():
            wanted = PREDICATES[walk]
            given = {kw.arg: kw.value for kw in node.keywords}
            if wanted not in given:
                missing.append(f'{file_name}:{node.lineno} {walk}() has no {wanted}= predicate')
                continue
            text = ast.unparse(given[wanted])
            if 'may_stop' not in text:
                missing.append(f'{file_name}:{node.lineno} {walk}() {wanted}= ignores the stop: {text}')
        assert missing == [], '\n'.join(missing)

    def test_a_stopped_walk_reports_stopped_rather_than_exhausted(self):
        """`stopped_reason` is what the console prints as the reason a list ended.

        "target" or "stuck" over a run the user cut short reads as a fact about the
        site, and the site did nothing of the kind. The rows handed over before the
        stop must also survive the walk that ends on it.
        """
        from crawlers.engine import feed

        crawler = bare(None, _abort=lambda: False)
        assert crawler.emit({'标题': 'paid for'}) is True
        crawler._abort = lambda: True

        walk = feed.walk_feed(
            lambda: [],
            lambda card, index: {'标题': f'row-{card}'},
            crawler.emit,
            scroll=lambda: None,
            target=999,
            collected=crawler.collected,
            stopped=crawler.may_stop,
        )
        assert walk.stopped_reason == 'stopped', walk.stopped_reason
        assert crawler.collected() == 1, 'what the crawl already paid for is kept'

    def test_the_comment_engine_carries_its_own_predicate(self):
        """``CommentSession`` is not a ``Crawler``, and it reads hundreds of pages per
        node — so it needs the same answer, given to it by the node handler."""
        from crawlers.comments import CommentSession

        assert CommentSession(None).may_stop() is False
        assert CommentSession(None, abort=lambda: True).may_stop() is True


class TestStopPredicateIsSingleDefinition:
    def test_the_base_class_owns_the_answer(self):
        """`_abort` defaults on the CLASS, not only in ``__init__``: a double that
        builds a crawler with ``__new__`` (no browser) must still answer the question,
        and a subclass must not have to remember the attribute to avoid an error."""
        assert Crawler.__dict__['_abort'] is None
        assert Probe.__new__(Probe).may_stop() is False

    def test_no_platform_redefines_it(self):
        """One question, one answer. A platform that overrode ``may_stop`` could make
        its own crawl un-stoppable, which is the bug this whole file audits."""
        overrides = []
        for path in sorted(CRAWLERS_DIR.rglob('*.py')):
            if path.name == 'base.py':
                continue  # the definition itself
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and any(
                    isinstance(item, ast.FunctionDef) and item.name == 'may_stop' for item in node.body
                ):
                    overrides.append(f'{path.name}:{node.name}')
        assert overrides == ['comments.py:CommentSession'], (
            f'the comment engine is the only non-Crawler allowed to own the answer: {overrides}'
        )
