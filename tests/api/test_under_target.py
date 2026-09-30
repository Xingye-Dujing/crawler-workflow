"""U1: the executor refuses a silent under-collect; only a SITE-attested end licenses a short.

Before this, `_execute_source_node` settled a non-wall crawl as clean DONE no matter how few rows
it returned (the `rows < target_count` check only ever fired in the login-wall branch), so "the
site ran out" and "our walk came back short for no stated reason" looked identical in the record —
the §6 silent-under-collect. A real user got a short table stamped 完成.

`crawler.end_reason` is three-state, and the point of this file is that the CONVICTING state is
only ever `UNDER_TARGET`, while a "license" must be a member of the closed `LICENSED_ENDS` set —
never a summary of our own loop:

* ``None``            — handler not migrated yet; the gate stays silent (no regression).
* ``UNDER_TARGET``    — short with no site-attested end: convicted, refused by name, resumable.
* a ``LICENSED_ENDS`` word — the site said this is all: settles clean.

A loop self-summary ('stuck' / 'no_new' / a "翻了几轮") is NOT a license — and `note_end`
refuses it at the boundary (a crawler bug becomes a loud failure, not a false user verdict).

Offline throughout: the crawler is a scripted stub, no browser, no network.
"""

import pytest

import crawl_capabilities as capabilities
from crawlers.base import LICENSED_ENDS, UNDER_TARGET, Crawler
from i18n import t

pytestmark = pytest.mark.api

_ROWS = [{'标题': f'条目{i}', '链接': f'https://example.com/{i}'} for i in range(1, 3)]


class _StubCrawler:
    """Returns a fixed table and reports `end_reason` exactly as a migrated handler would."""

    def __init__(self, rows, end_reason, *, wall=False, risk=False, counts=None):
        self._rows = list(rows)
        self.end_reason = end_reason
        self.walk_counts = counts or {}
        self._wall = wall
        self.risk_blocked = risk

    def set_sink(self, sink):
        pass

    def set_cursor_sink(self, sink):
        pass

    def seed(self, saved):
        pass

    def close(self):
        pass

    @property
    def login_wall(self):
        return self._wall

    def _answer(self, *args, **kwargs):
        return self._rows

    search = author = hot = comments = _answer


def _node(target_count):
    return {
        'id': 'node-1',
        'type': 'source',
        'title': '采集',
        'platform': 'zhihu',
        'params': {
            'platform': 'zhihu',
            capabilities.MODE_KEY: 'posts',
            'keyword': '矩阵',
            'target_count': target_count,
        },
    }


def _run(app_module, monkeypatch, stub):
    monkeypatch.setattr(app_module, 'get_crawler', lambda *a, **k: stub)
    return app_module._execute_source_node(_node(5), headless=True, ctx=None)


def test_a_silent_short_is_refused_by_name_and_not_settled_done(app_module, monkeypatch):
    """2 of 5 rows with `end_reason=UNDER_TARGET` must NOT look like a finished crawl."""
    with pytest.raises(ValueError) as err:
        _run(app_module, monkeypatch, _StubCrawler(_ROWS, UNDER_TARGET, counts={'scanned': 9, 'kept': 5, 'refused': 7}))
    # have=2 (kept rows) is distinct from kept=5 (walk funnel) so a swap in the raise is caught.
    expected = t(
        'run.underTargetShort',
        platform='zhihu',
        have=2,
        want=5,
        walk=t('run.underTargetWalk', scanned=9, kept=5, refused=7),
    )
    assert expected == str(err.value)
    assert '9' in str(err.value) and '7' in str(err.value), 'the funnel must attribute the gap'


def test_a_short_without_counts_omits_the_funnel(app_module, monkeypatch):
    """No walk_counts means no parenthetical — never a fake 「扫0留0拒0」 presented as a measurement."""
    with pytest.raises(ValueError) as err:
        _run(app_module, monkeypatch, _StubCrawler(_ROWS, UNDER_TARGET))
    message = str(err.value)
    expected = t('run.underTargetShort', platform='zhihu', have=2, want=5, walk='')
    assert message == expected
    assert '走查' not in message and 'scanned' not in message, message


@pytest.mark.parametrize('reason', sorted(LICENSED_ENDS))
def test_a_site_attested_end_settles_clean(app_module, monkeypatch, reason):
    """A short the SITE named ('site_end'/'capped'/'empty') is the site's verdict, not a bug."""
    rows = _run(app_module, monkeypatch, _StubCrawler(_ROWS, reason))
    assert rows == _ROWS, 'a site-attested end must not be convicted'


def test_an_unmigrated_handler_is_left_alone(app_module, monkeypatch):
    """`end_reason=None` (a handler that has not adopted the contract) keeps today's behaviour —
    this is what lets the gate land before every platform is wired, without a false red."""
    rows = _run(app_module, monkeypatch, _StubCrawler(_ROWS, None))
    assert rows == _ROWS, 'the gate must stay silent for an unmigrated handler'


def test_a_full_table_is_never_a_short(app_module, monkeypatch):
    """collected >= target is success even with UNDER_TARGET set: the gate only speaks on a gap."""
    five = _ROWS + [{'标题': 'x', '链接': 'y'}] * 3
    rows = _run(app_module, monkeypatch, _StubCrawler(five, UNDER_TARGET))
    assert len(rows) == 5, 'a crawl that met its target has nothing to refuse'


def test_a_wall_short_uses_the_cookie_path_not_this_gate(app_module, monkeypatch):
    """A short under a login wall is `run.cookieExpired` (the existing named path), not U1 — the
    wall branch raises and returns before the gate, so the two refusals never collide."""
    with pytest.raises(ValueError) as err:
        _run(app_module, monkeypatch, _StubCrawler(_ROWS, UNDER_TARGET, wall=True))
    assert t('run.cookieExpired', platform='zhihu') == str(err.value)


def test_a_risk_short_is_named_as_risk_control_not_a_silent_done(app_module, monkeypatch):
    """#1: a crawl that 风控 blocked (``risk_blocked``, NOT a login wall) and came back short
    must FAIL by name with the back-off verdict — never settle DONE over a thin table, and never
    the cookie re-save advice (the session may be fine)."""
    with pytest.raises(ValueError) as err:
        _run(app_module, monkeypatch, _StubCrawler(_ROWS, None, risk=True))
    assert str(err.value) == t('run.riskControlled', platform='zhihu')
    assert 'COOKIE' not in str(err.value), 'risk control must not be misadvised as a dead cookie'


def test_risk_control_outranks_the_under_target_wording(app_module, monkeypatch):
    """When BOTH signals could fire, the actionable one wins: a risk short reports 风控 (back
    off), not 「采得不足」 (which would invite the exact immediate re-run this repo forbids)."""
    with pytest.raises(ValueError) as err:
        _run(app_module, monkeypatch, _StubCrawler(_ROWS, UNDER_TARGET, risk=True))
    assert str(err.value) == t('run.riskControlled', platform='zhihu')


def test_a_risk_crawl_that_met_its_target_is_not_a_failure(app_module, monkeypatch):
    """风控 only refuses a GAP: a full table is a finished crawl even if the flag was set."""
    five = _ROWS + [{'标题': 'x', '链接': 'y'}] * 3
    rows = _run(app_module, monkeypatch, _StubCrawler(five, None, risk=True))
    assert len(rows) == 5, 'a crawl that met its target has nothing to refuse'


# ─── note_end: the boundary that keeps a loop self-summary from becoming a license ───


class _Host:
    """Duck-typed receiver so `Crawler.note_end` can be exercised without a real browser."""

    end_reason = None
    walk_counts = None


def test_note_end_refuses_a_loop_self_summary():
    """'stuck' is our loop's summary, not the site's answer — note_end refuses to license on it.

    This is the whole §6 discipline enforced at the boundary: a crawler that tries to excuse a
    shortfall with its own pager can only crash the test, never stamp 完成 on a thin table.
    """
    with pytest.raises(ValueError):
        Crawler.note_end(_Host(), 'stuck')
    for liar in ('no_new', 'no_cards', 'target', 'walk_done', 'drained'):
        with pytest.raises(ValueError):
            Crawler.note_end(_Host(), liar)


def test_note_end_refuses_a_non_string_so_a_bool_cannot_slip_past_falsiness():
    """A truthiness test would let ``note_end(result.hit_cap)`` (a bool) fall through as falsy
    and go silently UNlicensed — the pre-change §6 hole, reached by accident. The type is
    checked, not the truthiness."""
    for not_a_token in (False, True, 0, 1, 42):
        with pytest.raises(TypeError):
            Crawler.note_end(_Host(), not_a_token)


def test_note_end_accepts_the_three_legal_shapes():
    h = _Host()
    Crawler.note_end(h, UNDER_TARGET)
    assert h.end_reason == UNDER_TARGET, 'convicted short'

    h = _Host()
    Crawler.note_end(h, 'site_end')
    assert h.end_reason == 'site_end', 'a site-attested end licenses'

    h = _Host()
    Crawler.note_end(h, None)
    assert h.end_reason is None, 'None is "no opinion", NOT the convicting empty string'


def test_note_end_stores_no_fake_zero_funnel():
    h = _Host()
    Crawler.note_end(h, UNDER_TARGET)
    assert h.walk_counts == {}, 'all-zero counts must not masquerade as a measurement'

    h = _Host()
    Crawler.note_end(h, UNDER_TARGET, scanned=8, kept=3, refused=5)
    assert h.walk_counts == {'scanned': 8, 'kept': 3, 'refused': 5}


# ─── end-to-end through the real executor (the product, not a re-implementation) ───


class _SimCrawler(Crawler):
    """A real ``Crawler`` subclass (offline driver) that under-collects and names nothing.

    Subclassing the production class — not a hand-built stand-in — is the point: it
    exercises ``Crawler.__init__``'s default for ``end_reason`` and the ``note_end``/sink
    contract the gate reads, so a broken default or a mis-set verdict fails here rather than
    passing a mock that supplies its own state.
    """

    domain = 'zhihu'
    login_url = 'https://www.zhihu.com/'

    def __init__(self, supply):
        self._supply = list(supply)
        super().__init__(headless=True)

    def _create_driver(self):
        self.driver = None

    def get_detail(self, url):
        return None

    def search(self, keyword=None, target_count=None, resume=None, **kw):
        for item in self._supply:
            self.emit(item)
        self.note_end(UNDER_TARGET, scanned=len(self._supply), kept=len(self._supply), refused=0)
        return self.results()


def _workflow(target):
    return {
        'nodes': [
            {
                'id': 'node-1',
                'type': 'source',
                'title': 'source',
                'params': {'platform': 'zhihu', 'keyword': '测试', 'target_count': target, 'headless': True},
            }
        ],
        'connections': [],
        'settings': {'mode': 'serial'},
    }


def _drain(app_module, timeout=30.0):
    import time

    thread = app_module.execution_state.get('thread')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        alive = thread is not None and thread.is_alive()
        if not app_module.execution_state['running'] and not alive:
            return True
        time.sleep(0.1)
    return False


def test_a_real_crawler_states_no_opinion_until_it_notes(app_module, monkeypatch):
    """``Crawler.__init__`` must default ``end_reason`` to ``None`` (the dormant state).

    Pinned on a real subclass: flip the default to ``UNDER_TARGET`` in ``base.py`` and every
    short crawl would start getting refused — this test is what catches that, where the
    seam tests above supply their own value and could not.
    """
    monkeypatch.setattr(app_module, 'stop_requested', lambda: False)
    crawler = _SimCrawler([{'作者': 'a', '正文': 'b'}])
    assert crawler.end_reason is None, 'a fresh crawl has not run — it must state no opinion'
    assert crawler.walk_counts == {}


@pytest.mark.serial
@pytest.mark.usefixtures('seeded_logins')
def test_executor_settles_a_silent_short_as_partial_with_rows_kept(client, app_module, monkeypatch):
    """The §6 fix in the product path: 4 of 10 with no site end → node PARTIAL, run FAILED,
    4 rows kept — not a clean DONE. This is what a stub returning rows could not prove.
    """
    monkeypatch.setattr(
        app_module,
        'get_crawler',
        lambda *a, **k: _SimCrawler([{'作者': f'a{i}', '正文': f'body {i}'} for i in range(4)]),
    )
    started = client.post('/api/workflow/execute', json={'workflow': _workflow(10), 'workflow_name': 'u1-short'})
    run_id = started.get_json()['run_id']
    assert _drain(app_module)

    store = app_module._RUN_STORE
    run = store.get_run(run_id)
    nodes = {node['node_id']: node for node in run['nodes']}
    assert run['status'] == 'failed', 'a silent under-collect must never settle the run complete'
    assert nodes['node-1']['status'] == 'partial', 'the node is partial (resumable), not done'
    assert store.row_count(run_id, 'node-1') == 4, 'the rows collected before the gap stay on disk'
    assert '站点没说到底' in nodes['node-1']['error'] or 'ran out' in nodes['node-1']['error'].lower()


class _RiskSimCrawler(_SimCrawler):
    """A real ``Crawler`` that came back short because 风控 blocked it — #1's product shape.

    Sets ``risk_blocked`` (what douyin's captcha latch and ``wall.classify`` both reach) and
    names no site-attested end, so the executor must report 风控-back-off: never a clean DONE,
    and never the cookie re-save a login wall would warrant (the session may be perfectly fine).
    """

    def search(self, keyword=None, target_count=None, resume=None, **kw):
        for item in self._supply:
            self.emit(item)
        self.risk_blocked = True
        return self.results()


@pytest.mark.serial
@pytest.mark.usefixtures('seeded_logins')
def test_executor_names_a_risk_short_as_backoff_not_cookie(client, app_module, monkeypatch):
    """4 of 10 under a 风控 block → node PARTIAL, run FAILED, 4 rows kept, and the error names
    风控 (back off) — the opposite advice from a dead cookie, proven in the product path."""
    monkeypatch.setattr(
        app_module,
        'get_crawler',
        lambda *a, **k: _RiskSimCrawler([{'作者': f'a{i}', '正文': f'body {i}'} for i in range(4)]),
    )
    started = client.post('/api/workflow/execute', json={'workflow': _workflow(10), 'workflow_name': 'risk-short'})
    run_id = started.get_json()['run_id']
    assert _drain(app_module)

    store = app_module._RUN_STORE
    run = store.get_run(run_id)
    nodes = {node['node_id']: node for node in run['nodes']}
    assert run['status'] == 'failed', 'a risk-blocked short must not settle the run complete'
    assert nodes['node-1']['status'] == 'partial', 'the node stays resumable (继续 later, after back-off)'
    assert store.row_count(run_id, 'node-1') == 4, 'rows collected before the block stay on disk'
    error = nodes['node-1']['error']
    assert '风控' in error or 'risk control' in error.lower(), error
    assert 'COOKIE' not in error and 'cookie' not in error.lower(), 'a 风控 block must not advise re-saving a cookie'


def test_a_login_wall_outranks_risk_on_the_source_path(app_module, monkeypatch):
    """Both flags on a short source crawl → the cookie verdict wins, because the wall branch
    raises first: a re-savable session is the actionable fix, and the two refusals stay mutually
    exclusive rather than double-reporting the same node."""
    with pytest.raises(ValueError) as err:
        _run(app_module, monkeypatch, _StubCrawler(_ROWS, UNDER_TARGET, wall=True, risk=True))
    assert str(err.value) == t('run.cookieExpired', platform='zhihu')


# ─── the comment node's 风控-vs-cookie split (the regression B1 would have hidden) ───

import crawlers.comments as _comments  # noqa: E402  (module object, for monkeypatching its name)


class _FakeCommentCrawler:
    """The owning browser a comment session is built on — just enough surface for the split."""

    def __init__(self, *, risk=False, wall=False):
        self.risk_blocked = risk
        self.login_wall = wall
        self.driver = None

    def close(self):
        return None


class _BlockingSession:
    """Stand-in for CommentSession: the douyin panel adapter answers BLOCKED for every URL."""

    def __init__(self, driver, log=None, nap=None, abort=None, owner=None):
        self._owner = owner

    def crawl_douyin(self, url, limit):
        return [], _comments.BLOCKED


def _comment_node():
    return {
        'id': 'node-1',
        'type': 'source',
        'title': '评论',
        'platform': 'douyin',
        'params': {
            'platform': 'douyin',
            capabilities.MODE_KEY: 'comments',
            'urls': 'https://www.douyin.com/video/7000000000000000001',
            'comment_limit': 10,
        },
    }


def _drive_comment_block(app_module, monkeypatch, crawler):
    monkeypatch.setitem(app_module.execution_state, 'running', True)
    # The flag is what the two assertions read, so it must start clean rather than inherit a
    # value some earlier source-wall test left on the shared execution_state (a state test that
    # passes for the wrong reason — the suite shares ONE dict across the whole run).
    monkeypatch.setitem(app_module.execution_state, 'cookie_expired', False)
    monkeypatch.setattr(app_module, 'get_crawler', lambda *a, **k: crawler)
    monkeypatch.setattr(_comments, 'CommentSession', _BlockingSession)
    with pytest.raises(ValueError) as err:
        app_module._execute_comment_node(_comment_node(), headless=True, ctx=None)
    return str(err.value)


@pytest.mark.usefixtures('clean_globals')
def test_a_comment_risk_block_names_backoff_and_keeps_the_cookie_flag_down(app_module, monkeypatch):
    """A douyin comment crawl blocked by a captcha (owner latched risk, not a login wall) reports
    风控-back-off and must NOT raise the cookie-death toast — the session may be perfectly fine."""
    message = _drive_comment_block(app_module, monkeypatch, _FakeCommentCrawler(risk=True))
    assert '风控' in message or 'risk control' in message.lower(), message
    assert app_module.execution_state['cookie_expired'] is not True, (
        'a 风控 comment block must not raise the cookie toast'
    )


@pytest.mark.usefixtures('clean_globals')
def test_a_comment_block_that_named_nothing_keeps_the_cookie_verdict(app_module, monkeypatch):
    """The behaviour every platform that does NOT latch 风控 depends on must survive B1's split:
    a bare BLOCKED is still the cookie-death path (toast flag raised AND cookieExpired wording)."""
    message = _drive_comment_block(app_module, monkeypatch, _FakeCommentCrawler(risk=False, wall=False))
    assert 'COOKIE' in message or 'cookie' in message.lower(), message
    assert app_module.execution_state['cookie_expired'] is True, 'a cookie block must still raise the toast flag'
