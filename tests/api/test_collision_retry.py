"""The one retry a *collision* earns — and every wall that must never get one.

Two workflows crawling one platform can be refused in two ways that look identical
on the console and demand opposite handling:

* refused **before the first row** — the account searched twice in one second, which
  is what weibo answers with a passport redirect. Nothing was paid for, so waiting a
  moment and asking again costs one crawl and can turn a red node green;
* refused **after rows were collected** — the cookie died mid-crawl. That one is a
  designed path: the node settles partial, the run fails, and 继续 picks it up from
  the stored cursor. Retrying it here would re-crawl rows the store already holds and
  hide the fact that the session needs refreshing.

So the whole decision is "was anything collected yet", plus two guards that keep a
retry from happening when the user has stopped or when the run resumed from a cursor.

``app_module`` arrives as a fixture rather than a module-level import on purpose: an
import at module scope binds the application's singletons to the user's real ``data/``
before any fixture can redirect them, which is how test rows once reached the real
execution history (pinned by ``test_console_buffer.py::TestImportHygiene``).
"""

import pytest

import i18n

pytestmark = [pytest.mark.api, pytest.mark.serial]


class _Crawler:
    """Answers the first call with a wall, the second one with rows."""

    def __init__(self, *, rows_first=(), raise_first=False, collected=0, wall=True):
        self.login_wall = False
        self.risk_blocked = False
        self.calls = 0
        self.rows_first = rows_first
        self.raise_first = raise_first
        self.wall = wall
        self._collected = collected

    def collected(self):
        return self._collected

    def search(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            if self.wall:
                self.login_wall = True
            if self.raise_first:
                raise RuntimeError('bounced to passport')
            return list(self.rows_first)
        return [{'标题': '第二条'}]


@pytest.fixture(autouse=True)
def running(app_module, monkeypatch):
    """A live run, a cheap back-off, and a console to read the announcement off."""
    import threading

    monkeypatch.setitem(app_module.execution_state, 'running', True)
    # The back-off now wakes on the run's cancel_event; a fresh unset one says
    # "nobody stopped" so the retry path is the only variable under test.
    monkeypatch.setitem(app_module.execution_state, 'cancel_event', threading.Event())
    monkeypatch.setattr(app_module.Config, 'WALL_RETRY_BACKOFF', 0.01)
    app_module.reset_console_state()
    return app_module.execution_state


def _lines(state) -> list:
    return list(state['logs'])


def test_a_wall_before_the_first_row_is_asked_again_after_a_back_off(app_module, running):
    crawler = _Crawler()
    rows = app_module._crawl_with_collision_retry(crawler, crawler.search, {'target_count': 3}, {}, 'weibo')
    assert crawler.calls == 2, 'the collision shape was not retried'
    assert rows == [{'标题': '第二条'}]
    forms = ('weibo', i18n.platform_label('weibo', 'zh'), i18n.platform_label('weibo', 'en'))
    said = [line for line in _lines(running) if any(form in line for form in forms)]
    assert len(said) == 1, f'the retry should be announced once, saw {said}'


def test_a_crawl_that_kept_rows_is_not_asked_again(app_module, running):
    """The mid-crawl cookie death: its path is 判失败 → 继续, never a second attempt."""
    crawler = _Crawler(raise_first=True, collected=7)
    with pytest.raises(RuntimeError):
        app_module._crawl_with_collision_retry(crawler, crawler.search, {}, {}, 'weibo')
    assert crawler.calls == 1
    assert _lines(running) == [], 'a refusal that is not retried must not also claim a retry'


def test_a_crawl_resumed_from_a_cursor_is_not_asked_again(app_module, running):
    """A cursor means an earlier attempt already did the work; the wall behind it is
    the cookie's, and re-running the crawl would pay for rows the store kept."""
    crawler = _Crawler(raise_first=True)
    with pytest.raises(RuntimeError):
        app_module._crawl_with_collision_retry(crawler, crawler.search, {}, {'url_index': 3}, 'weibo')
    assert crawler.calls == 1


def test_a_stopped_run_does_not_start_another_crawl(app_module, running):
    """停止 is not a pause: crawling on behind it would leave the user watching a run
    the server has already declared over."""
    running['running'] = False
    crawler = _Crawler(raise_first=True)
    with pytest.raises(RuntimeError):
        app_module._crawl_with_collision_retry(crawler, crawler.search, {}, {}, 'weibo')
    assert crawler.calls == 1


def test_an_empty_answer_with_no_wall_is_the_crawls_own(app_module, running):
    """「这个关键词就是没东西」is a result, not a refusal — retrying it would double
    every genuinely empty crawl."""
    crawler = _Crawler(rows_first=(), wall=False)
    rows = app_module._crawl_with_collision_retry(crawler, crawler.search, {}, {}, 'weibo')
    assert rows == []
    assert crawler.calls == 1


def test_the_back_off_can_be_turned_off_entirely(app_module, monkeypatch):
    """0 is a supported answer, so an operator can restore the old single attempt."""
    monkeypatch.setattr(app_module.Config, 'WALL_RETRY_BACKOFF', 0)
    crawler = _Crawler()
    rows = app_module._crawl_with_collision_retry(crawler, crawler.search, {}, {}, 'weibo')
    assert rows == []
    assert crawler.calls == 1, 'a disabled back-off must not crawl twice'


def test_the_retry_forgets_the_wall_it_just_saw(app_module, running):
    """Flags describing the failed attempt would otherwise be read as the second
    attempt's answer: the node would report a wall the retry never hit."""
    crawler = _Crawler()
    seen = {}

    def search(**kwargs):
        crawler.calls += 1
        if crawler.calls == 1:
            crawler.login_wall = True
            return []
        seen['wall_at_second_return'] = crawler.login_wall
        return [{'标题': 'x'}]

    app_module._crawl_with_collision_retry(crawler, search, {}, {}, 'weibo')
    assert seen['wall_at_second_return'] is False


def test_a_stop_cut_short_the_back_off_cancels_the_retry(app_module, running, monkeypatch):
    """The whole point of a slice-checked wait: a Stop that lands during the back-off
    must not spend a second crawl on a run the user already ended."""
    import threading
    import time

    monkeypatch.setattr(app_module.Config, 'WALL_RETRY_BACKOFF', 30)
    running['cancel_event'] = threading.Event()
    running['cancel_event'].set()
    crawler = _Crawler()
    started = time.monotonic()
    proceed = app_module._backoff_for_retry(crawler, 'weibo')
    assert proceed is False, 'a cancelled wait must refuse the retry'
    assert time.monotonic() - started < 1, 'the wait slept past the Stop instead of waking on it'


def test_a_live_back_off_ends_by_itself_and_allows_the_retry(app_module, running, monkeypatch):
    """The other answer: with no Stop, a short back-off runs out and the retry goes —
    proving the previous test's False came from the cancel, not from a broken wait."""
    import threading

    monkeypatch.setattr(app_module.Config, 'WALL_RETRY_BACKOFF', 0.05)
    running['cancel_event'] = threading.Event()
    crawler = _Crawler()
    assert app_module._backoff_for_retry(crawler, 'weibo') is True
    assert crawler.login_wall is False, 'the retry slate is still cleared on the run-out path'
