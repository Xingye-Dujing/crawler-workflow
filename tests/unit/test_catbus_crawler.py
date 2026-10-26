"""The CatBus session object, driven without CatBus.

Everything here goes through :mod:`services.catbus_bridge`'s own seam: the fake answers with
``Outcome`` objects, so each case states what this project does with an adapter answer — which rows
reach the ledger, which refusal raises, which flag is deliberately never latched. The real subprocess
boundary is ``test_catbus_bridge.py``'s business; a real crawl is ``live_quick``'s.
"""

import pytest

from crawlers import catbus as catbus_module
from crawlers.base import UNDER_TARGET, CrawlerStopped
from services import catbus_bridge as bridge


def outcome(**fields):
    base = {'status': 'ok', 'rows': 0, 'warnings': (), 'articles': (), 'error': None, 'exit_code': 0}
    base.update(fields)
    return bridge.Outcome(**base)


def row(bvid='BV1', title='稿件'):
    return {'标题': title, 'BV号': bvid, '链接': f'https://www.bilibili.com/video/{bvid}/'}


class Ledger:
    """A row sink that answers whether an item was new, like the real one does."""

    def __init__(self):
        self.kept = []

    def __call__(self, item):
        if item.get('BV号') in {str(seen.get('BV号') or '') for seen in self.kept}:
            return False
        self.kept.append(item)
        return True


@pytest.fixture
def session(monkeypatch):
    """A session whose adapter answers by table and whose rows land in a ledger.

    The manifest questions are answered here as the real adapter answers them today — bilibili,
    identity by BV号, every cell available — because what these cases pin is *what this side does with
    the answer*, not the answer.
    """
    made = catbus_module.CatbusCrawler(platform='bilibili', params={'target_count': 5})
    made.ledger = Ledger()
    made.set_sink(made.ledger)
    monkeypatch.setattr(bridge, 'supports', lambda platform, mode: True)
    monkeypatch.setattr(bridge, 'mode_state', lambda platform, mode: ('available', ''))
    monkeypatch.setattr(bridge, 'columns_for', lambda platform, mode: ())
    monkeypatch.setattr(bridge, 'identity_for', lambda platform, mode: ('BV号',))
    return made


class TestSourceModesStreamThroughTheLedger:
    def test_rows_are_emitted_in_order_and_the_crawl_returns_them(self, session, monkeypatch):
        sent = []

        def fake_run(platform, mode, params, **kw):
            sent.append((platform, mode, params))
            for item in (row('BV1'), row('BV2')):
                kw['on_row'](item)
            return outcome(status='ok', rows=2)

        monkeypatch.setattr(bridge, 'run', fake_run)
        rows = session.search(keyword='键盘', target_count=2)
        assert [item['BV号'] for item in rows] == ['BV1', 'BV2']
        assert [item['BV号'] for item in session.ledger.kept] == ['BV1', 'BV2'], 'the ledger saw each row'
        assert sent == [('bilibili', 'posts', {'keyword': '键盘', 'target_count': 2})]

    def test_the_nodes_form_travels_and_the_mode_argument_wins(self, session, monkeypatch):
        sent = {}

        def fake_run(platform, mode, params, **kw):
            sent.update(params)
            return outcome(status='ok')

        monkeypatch.setattr(bridge, 'run', fake_run)
        session.params = {'comment_limit': 30, 'account': 'selenium-login', 'catbus_account': 'catbus-work'}
        session.search(keyword='键盘', target_count=7)
        assert sent['keyword'] == '键盘'
        assert sent['target_count'] == 7, 'the argument the walk came with beats the stored form'
        assert sent['catbus_account'] == 'catbus-work', 'the only account the adapter may read'

    def test_a_duplicate_row_counts_as_refused_not_kept(self, session, monkeypatch):
        def fake_run(platform, mode, params, **kw):
            kw['on_row'](row('BV1'))
            kw['on_row'](row('BV1'))
            return outcome(status='ok', rows=2)

        monkeypatch.setattr(bridge, 'run', fake_run)
        rows = session.search(keyword='k', target_count=5)
        assert len(rows) == 1
        assert session.walk_counts == {'scanned': 2, 'kept': 1, 'refused': 1}
        assert session.end_reason == UNDER_TARGET, 'one row of five is a shortfall, not a finished crawl'

    def test_a_target_already_in_hand_asks_nothing(self, session, monkeypatch):
        calls = []
        monkeypatch.setattr(bridge, 'run', lambda *a, **kw: calls.append(a) or outcome(status='ok'))
        session.seed([row(), row()])
        rows = session.search(keyword='k', target_count=2)
        assert len(rows) == 2
        assert calls == [], 'a resumed node that holds its target does not re-pay the site'

    def test_author_and_hot_use_their_own_mode_arguments(self, session, monkeypatch):
        sent = []

        def fake_run(platform, mode, params, **kw):
            sent.append((mode, params))
            return outcome(status='ok')

        monkeypatch.setattr(bridge, 'run', fake_run)
        session.author(author='2', target_count=3)
        session.hot(board='popular', target_count=3)
        assert sent == [
            ('author', {'author': '2', 'target_count': 3}),
            ('hot', {'board': 'popular', 'target_count': 3}),
        ]

    def test_a_short_crawl_convicts_itself_with_the_funnel(self, session, monkeypatch):
        """An adapter list that stopped growing is not proof the site ran out, so it says 「采得不足」.

        The licence to be short belongs to a site-attested end (an end-of-list marker, a board's own
        size). CatBus reports neither, and ``note_end`` refuses a loop self-summary — so a short table
        is left to convict, which is the whole point of the U1 gate.
        """
        monkeypatch.setattr(bridge, 'run', lambda *a, **kw: outcome(status='ok', warnings=('BV9: UPSTREAM',)))
        session.search(keyword='k', target_count=5)
        assert session.end_reason == UNDER_TARGET
        assert session.walk_counts['refused'] == 1
        assert session.target_total == 5


class TestRefusalsNameTheBackend:
    def test_an_unsupported_cell_refuses_instead_of_returning_nothing(self, session, monkeypatch):
        monkeypatch.setattr(bridge, 'supports', lambda platform, mode: False)
        monkeypatch.setattr(bridge, 'mode_state', lambda platform, mode: ('unavailable', '排行榜 ranking 未接入'))
        with pytest.raises(ValueError) as raised:
            session.search(keyword='k', target_count=5)
        assert 'ranking' in str(raised.value)
        assert session.collected() == 0

    def test_an_unauthenticated_adapter_names_its_own_login_command(self, session, monkeypatch):
        monkeypatch.setattr(
            bridge,
            'run',
            lambda *a, **kw: outcome(
                status='error',
                error={'code': 'AUTH_REQUIRED'},
                message='comment list 需要登录',
                hint='catbus bilibili auth login',
                exit_code=3,
            ),
        )
        with pytest.raises(ValueError) as raised:
            session.search(keyword='k', target_count=5)
        assert 'catbus bilibili auth login' in str(raised.value)

    def test_a_catbus_wall_never_latches_the_cookie_flags(self, session, monkeypatch):
        """The rule this class rests on: ``login_wall`` means 「our cookie died」.

        The executor turns that flag into 「重新保存 Cookie」 and into ``cookie_expired`` — the run's
        cookie toast. A node crawling through CatBus has no cookie in the path, so an auth failure
        reaches the user as the adapter's own command and the flags stay False.
        """
        monkeypatch.setattr(
            bridge,
            'run',
            lambda *a, **kw: outcome(status='blocked', message='未登录', hint='catbus bilibili auth login'),
        )
        with pytest.raises(ValueError):
            session.search(keyword='k', target_count=5)
        assert session.login_wall is False
        assert session.risk_blocked is False

    def test_risk_control_says_back_off_and_says_it_once(self, session, monkeypatch):
        monkeypatch.setattr(
            bridge,
            'run',
            lambda *a, **kw: outcome(status='error', message='触发风控', hint='稍后再试', exit_code=5),
        )
        with pytest.raises(ValueError) as raised:
            session.search(keyword='k', target_count=5)
        assert '触发风控' in str(raised.value)
        assert session.risk_blocked is False, 'the executor would otherwise print 风控 a second time'

    def test_a_stopped_run_raises_the_stops_own_exception(self, session, monkeypatch):
        monkeypatch.setattr(bridge, 'run', lambda *a, **kw: outcome(status='stopped', rows=1))
        # ``BaseException`` and not ``Exception``: about sixty crawl paths read an ordinary error as
        # "carry on without it", and a stop folded into one of them becomes a short table nobody sees.
        with pytest.raises(CrawlerStopped):
            session.search(keyword='k', target_count=5)

    def test_a_missing_backend_refuses_by_reason_not_by_number(self, session, monkeypatch):
        monkeypatch.setattr(bridge, 'run', lambda *a, **kw: outcome(status='unavailable', message='没有 Node 运行时'))
        with pytest.raises(ValueError) as raised:
            session.search(keyword='k', target_count=5)
        assert 'Node' in str(raised.value)

    def test_this_backend_does_not_fetch_a_detail_on_its_own(self, session):
        with pytest.raises(ValueError):
            session.get_detail('https://www.bilibili.com/video/BV1/')


class TestCommentsWalkOneLinkAtATime:
    def test_a_clean_link_returns_its_rows_and_ok(self, session, monkeypatch):
        sent = {}

        def fake_run(platform, mode, params, **kw):
            sent.update(params)
            for index in (1, 2):
                kw['on_row']({'平台': 'bilibili', '评论ID': str(index), '评论内容': f'{index}'})
            return outcome(status='ok', rows=2)

        monkeypatch.setattr(bridge, 'run', fake_run)
        rows, status = session.crawl_bilibili('https://www.bilibili.com/video/BV1/', 50)
        assert status == catbus_module.OK
        assert len(rows) == 2
        assert sent['urls'] == ['https://www.bilibili.com/video/BV1/'], 'one link, one process'
        assert sent['comment_limit'] == 50
        assert session.skipped_targets == [], 'a proven link must let the cursor pass over it'

    def test_a_partial_link_is_named_so_the_cursor_stops_before_it(self, session, monkeypatch):
        """The rows stand, but the link is not proven: advancing the cursor over a hole is the laundering.

        The comment engine pins ``url_index`` on the unbroken leading run of proven inputs and reads
        ``skipped_targets`` by attribute, so naming the link here is what keeps 继续 from settling
        DONE over the gap the console already named.
        """

        def fake_run(platform, mode, params, **kw):
            for index in (1, 2, 3):
                kw['on_row']({'平台': 'bilibili', '评论ID': str(index), '评论内容': f'{index}'})
            return outcome(status='partial', rows=3, warnings=('page 2 timeout',))

        monkeypatch.setattr(bridge, 'run', fake_run)
        rows, status = session.crawl_bilibili('https://www.bilibili.com/video/BV1/', 0)
        assert status == catbus_module.OK
        assert len(rows) == 3
        assert session.skipped_targets == ['https://www.bilibili.com/video/BV1/']
        assert session.shortfall == 1

    def test_a_dead_link_reports_dead_and_names_it(self, session, monkeypatch):
        monkeypatch.setattr(bridge, 'run', lambda *a, **kw: outcome(status='dead'))
        rows, status = session.crawl_bilibili('https://www.bilibili.com/video/BVgone/', 0)
        assert status == catbus_module.DEAD
        assert rows == []
        assert session.skipped_targets == ['https://www.bilibili.com/video/BVgone/']

    def test_a_walled_link_raises_naming_the_login_instead_of_counting_blocked(self, session, monkeypatch):
        """``BLOCKED`` is the browser adapter's answer, and the engine's advice for it is a cookie.

        A CatBus login is not one, so the wall refuses with the adapter's own command rather than
        feeding the 「Cookie 已失效」 path.
        """
        monkeypatch.setattr(
            bridge,
            'run',
            lambda *a, **kw: outcome(status='blocked', message='未登录', hint='catbus bilibili auth login'),
        )
        with pytest.raises(ValueError) as raised:
            session.crawl_bilibili('https://www.bilibili.com/video/BV1/', 0)
        assert 'catbus bilibili auth login' in str(raised.value)
        assert session.skipped_targets == [], 'a refusal is not a walked link, proven or otherwise'


class TestTheWatermarkUnderThisBackend:
    def test_the_boundary_stops_the_walk_and_is_said_out_loud(self, session, monkeypatch):
        lines = []
        session._log = lines.append
        session.set_watermark('BV2')

        def fake_run(platform, mode, params, **kw):
            for item in (row('BV1'), row('BV2'), row('BV3')):
                kw['on_row'](item)
            return outcome(status='ok', rows=3)

        monkeypatch.setattr(bridge, 'run', fake_run)
        rows = session.author(author='2', target_count=9)
        assert [item['BV号'] for item in rows] == ['BV1'], 'the boundary row and everything older is not filed'
        assert any('偏移' in line for line in lines), 'the degradation is printed, never implied'

    def test_a_first_run_records_the_newest_kept_row(self, session, monkeypatch):
        def fake_run(platform, mode, params, **kw):
            kw['on_row'](row('BV7'))
            return outcome(status='ok', rows=1)

        monkeypatch.setattr(bridge, 'run', fake_run)
        session.author(author='2', target_count=1)
        assert session._watermark_candidate == 'BV7'


class TestTheStopPathReachesTheChild:
    def test_close_reaps_the_token_this_session_runs_under(self, session, monkeypatch):
        seen = []
        monkeypatch.setattr(bridge, 'kill_running', lambda token: seen.append(token) or True)
        session.close()
        assert seen == [session._token], '停止 must aim at this process, not at a browser that does not exist'

    def test_the_token_is_unique_per_session(self):
        first = catbus_module.CatbusCrawler(platform='bilibili')._token
        second = catbus_module.CatbusCrawler(platform='bilibili')._token
        assert first != second, 'one reaper aim must not end a two-session run early'

    def test_may_stop_is_the_adapters_abort_predicate(self, session):
        session._abort = lambda: True
        assert session.may_stop() is True
        with pytest.raises(CrawlerStopped):
            session.emit(row())


class TestNoBrowserIsBought:
    def test_the_session_claims_no_profile_and_holds_no_driver(self):
        made = catbus_module.CatbusCrawler(platform='bilibili', account='work')
        assert made.driver is None
        assert made.profile_dir is None, 'a CatBus crawl never takes a Chrome profile lock'
        assert made.cookie_path is None, 'and never plants a cookie the adapter would not read'
        assert made.node_account == 'work', 'the Selenium account is remembered, never used'

    def test_the_abort_answer_is_a_plain_predicate(self):
        assert catbus_module.CatbusCrawler(platform='bilibili').may_stop() is False, 'an idle server is not a 停止'


class TestItIsNotBilibiliSpecific:
    """Nothing in this class is about one platform: the adapter's manifest decides platform, columns
    and which column identifies a row. The day CatBus maps another site, this side crawls it without a
    new branch — so these cases ask for a different platform's answers and read what comes back.
    """

    @staticmethod
    def _weibo(monkeypatch, identity=('链接',), supported=True):
        monkeypatch.setattr(bridge, 'supports', lambda platform, mode: supported and platform == 'weibo')
        monkeypatch.setattr(
            bridge,
            'mode_state',
            lambda platform, mode: ('available', '') if supported else ('planned', '列映射未实现'),
        )
        monkeypatch.setattr(bridge, 'identity_for', lambda platform, mode: tuple(identity))
        made = catbus_module.CatbusCrawler(platform='weibo', params={'target_count': 2})
        made.ledger = Ledger()
        made.set_sink(made.ledger)
        return made

    def test_a_platform_the_adapter_newly_supports_already_has_its_comment_adapter(self, monkeypatch):
        made = self._weibo(monkeypatch)
        assert callable(made.crawl_weibo), 'the engine looks the adapter up by name; no list is kept here'

    def test_a_platform_it_does_not_offer_raises_like_a_missing_method_would(self, monkeypatch):
        """The named refusal stays the engine's ``comment.noAdapter``, not a silent fallback."""
        made = self._weibo(monkeypatch)
        assert not hasattr(made, 'crawl_zhihu'), 'an unsupported platform looks like no adapter at all'

    def test_the_watermark_keys_on_the_column_the_manifest_named(self, monkeypatch):
        made = self._weibo(monkeypatch, identity=('文章URL',))
        sent = []

        def fake_run(platform, mode, params, **kw):
            sent.append((platform, mode))
            kw['on_row']({'文章URL': 'https://weibo.com/1', '正文': '甲'})
            return outcome(status='ok', rows=1)

        monkeypatch.setattr(bridge, 'run', fake_run)
        made.author(author='abc', target_count=5)
        assert made.watermark_column == '文章URL', 'the store keeps the column this site promised'
        assert made._watermark_candidate == 'https://weibo.com/1'
        assert sent == [('weibo', 'author')], 'the crawl is asked of the platform on the node'

    def test_a_refusal_names_the_platform_that_was_asked(self, monkeypatch):
        made = self._weibo(monkeypatch, supported=False)
        with pytest.raises(ValueError) as raised:
            made.search(keyword='x', target_count=2)
        assert 'weibo' in str(raised.value) or '微博' in str(raised.value)
        assert '列映射未实现' in str(raised.value), "the adapter's own reason travels, not one written here"
