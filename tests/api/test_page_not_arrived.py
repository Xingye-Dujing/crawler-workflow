"""What the console says when a page does not arrive, and what that does to the record.

The user's complaint this answers was specific: a slow network was blamed on the site.
The crawler now waits a patient, interruptible while and then raises
:class:`~crawlers.base.PageNotArrivedError` with what it observed — and the executor's
job is to turn that into a sentence that says something *to do*, without touching what
the run record promises. Three things can go wrong there and each is pinned below:

* the diagnosis is *asked* only when the page did not explain itself, because a probe on
  top of ``ERR_NAME_NOT_RESOLVED`` is a second opinion about a fact already on screen;
* an expired wait must not be reported as a dead cookie — that sends the user to re-save
  a session the site never saw, and it makes the 继续 banner say the wrong reason;
* the rows already streamed still decide ``partial`` over ``failed``, because a crawl
  that got 3 rows and then lost the network is resumable and must look resumable.

Everything runs against a stub crawler and a stubbed probe: no browser, no socket.
"""

import pytest

from crawlers.base import Crawler, PageNotArrivedError
from i18n import t

pytestmark = [pytest.mark.api, pytest.mark.serial]

ROWS = [{'作者': f'a{i}', '正文': f'body {i}'} for i in range(3)]


class _DyingCrawler(Crawler):
    """Streams what it is given, then watches the next page fail to arrive.

    The message it raises is the platform's own observation (the shape
    ``crawl.dy.noCardsSlow`` has); the numbers ride on the exception because the
    executor, not the platform, owns the sentence about this machine's network.
    """

    domain = 'zhihu'
    login_url = 'https://www.zhihu.com/'

    def __init__(self, rows, message, waited, verdict, gave_up):
        self._rows = list(rows)
        self._message = message
        self._waited = waited
        self._verdict = verdict
        self._gave_up = gave_up
        super().__init__(headless=True)

    def _create_driver(self):
        self.driver = None

    def get_detail(self, url):
        return None

    def search(self, keyword=None, target_count=None, urls=None, resume=None, **kw):
        for index, item in enumerate(self._rows):
            self.emit(item)
            self.mark_position(item_index=index + 1, done=self.collected())
        raise PageNotArrivedError(self._message, waited=self._waited, verdict=self._verdict, gave_up=self._gave_up)


def _workflow():
    node = {
        'id': 'node-1',
        'type': 'source',
        'title': 'source',
        'params': {'platform': 'zhihu', 'keyword': '测试', 'target_count': 10, 'headless': True},
    }
    return {'nodes': [node], 'connections': [], 'settings': {'mode': 'serial'}}


class _Probe:
    """A stand-in for the outbound probe, so no test here can reach a socket."""

    def __init__(self, verdict='region', speed=None):
        self.answer = {
            'verdict': verdict,
            'side': 'cn',
            'detail': 'www.baidu.com=ok, www.google.com=refused',
            'speed_kbps': speed,
        }
        self.error = None
        self.calls = []

    def diagnose(self, region, platform_host=''):
        self.calls.append((region, platform_host))
        if self.error is not None:
            raise self.error
        return self.answer


@pytest.fixture
def dying(monkeypatch, app_module):
    """Steers the crawler the executor builds and the probe it may consult."""
    made = []
    plan = {'rows': ROWS, 'message': '页面没有内容', 'waited': 301.0, 'verdict': '', 'gave_up': 1}
    probe = _Probe()
    monkeypatch.setattr(app_module, 'network_probe', probe)

    def _configure(**changes):
        plan.update(changes)

    def fake_get_crawler(platform, headless=True, cookie_dir=None, use_profile=None, abort=None):
        crawler = _DyingCrawler(plan['rows'], plan['message'], plan['waited'], plan['verdict'], plan['gave_up'])
        made.append(crawler)
        return crawler

    monkeypatch.setattr(app_module, 'get_crawler', fake_get_crawler)
    return _configure, made, probe


def _wait(app_module, timeout=30.0):
    import time

    thread = app_module.execution_state.get('thread')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        alive = thread is not None and thread.is_alive()
        if not app_module.execution_state['running'] and not alive:
            return True
        time.sleep(0.1)
    return False


def _run(client, app_module, name):
    started = client.post('/api/workflow/execute', json={'workflow': _workflow(), 'workflow_name': name})
    run_id = started.get_json()['run_id']
    assert _wait(app_module), 'the run did not settle'
    return run_id


def _lines(client):
    return client.get('/api/workflow/status').get_json()['logs']


class TestTheGuidanceLine:
    def test_an_unexplained_wait_is_answered_with_a_diagnosis(self, client, app_module, dying):
        configure, _made, probe = dying
        configure(message='这一页一直没有内容')
        _run(client, app_module, 'pending-region')
        text = ' \n '.join(_lines(client))
        # The crawler's observation and the machine's answer in one line; the node's own
        # name is added by the executor that prints every failure, so nothing says the
        # reason twice.
        assert '这一页一直没有内容' in text, text
        assert t('net.region') in text, text
        assert probe.calls == [('cn', 'zhihu')], 'the region came from the matrix, not a guess'

    def test_a_measured_speed_is_offered_and_an_unmeasured_one_is_not(self, client, app_module, dying):
        configure, _made, probe = dying
        probe.answer['speed_kbps'] = 2048
        _run(client, app_module, 'pending-speed')
        assert t('net.speed', speed=2048) in ' \n '.join(_lines(client))

    def test_a_line_that_refused_to_be_measured_prints_no_figure(self, client, app_module, dying):
        _run(client, app_module, 'pending-nospeed')
        assert 'kB/s' not in ' \n '.join(_lines(client))

    def test_a_probe_that_cannot_run_does_not_eat_the_refusal(self, client, app_module, dying):
        """A diagnosis is an addition to the sentence about the page, never a reason the
        sentence disappears: a machine that cannot ask its own control hosts still owes
        the user the truth that this page did not arrive."""
        configure, _made, probe = dying
        probe.error = OSError('no route to host')
        configure(rows=[], message='这一页一直没有内容')
        run_id = _run(client, app_module, 'pending-probe-broken')
        nodes = {node['node_id']: node for node in app_module._RUN_STORE.get_run(run_id)['nodes']}
        assert nodes['node-1']['status'] == 'failed'
        text = ' \n '.join(_lines(client))
        assert '这一页一直没有内容' in text, text
        assert '诊断' not in text, 'no advice may be claimed when nothing was measured'


class TestTheOutcome:
    def test_nothing_about_the_cookie_is_claimed(self, client, app_module, dying):
        _run(client, app_module, 'pending-cookie')
        status = client.get('/api/workflow/status').get_json()
        assert status['cookie_expired'] is False, (
            'a page that never arrived says nothing about a session; flagging the cookie '
            'would send the user to re-save one that is fine'
        )
        assert 'Cookie' not in ' \n '.join(_lines(client)), 'no line may blame the cookie'

    def test_with_no_rows_the_node_fails_and_the_run_stays_resumable(self, client, app_module, dying):
        configure, _made, _probe = dying
        configure(rows=[])
        run_id = _run(client, app_module, 'pending-empty')
        store = app_module._RUN_STORE
        run = store.get_run(run_id)
        nodes = {node['node_id']: node for node in run['nodes']}
        assert run['status'] == 'failed'
        assert nodes['node-1']['status'] == 'failed'
        found = client.post('/api/runs/resumable', json={'workflow': _workflow(), 'limit': 10}).get_json()
        assert any(item['run_id'] == run_id for item in found['runs']), 'a lost page must be re-triable'

    def test_with_rows_already_streamed_the_node_is_partial_and_keeps_them(self, client, app_module, dying):
        run_id = _run(client, app_module, 'pending-rows')
        store = app_module._RUN_STORE
        nodes = {node['node_id']: node for node in store.get_run(run_id)['nodes']}
        assert nodes['node-1']['status'] == 'partial'
        assert store.row_count(run_id, 'node-1') == len(ROWS), 'the paid-for rows are the whole point'
        assert store.get_cursor(run_id, 'node-1')['item_index'] == len(ROWS)

    def test_a_page_that_named_its_own_cause_is_not_probed_twice(self, client, app_module, dying):
        """``unreachable`` is the browser's own words; a network probe on top of them
        would add a second, weaker opinion about the same event."""
        configure, _made, probe = dying
        configure(verdict='unreachable', message='[抖音] 浏览器自己拒绝了这一页：ERR_NAME_NOT_RESOLVED')
        _run(client, app_module, 'pending-refused')
        assert probe.calls == []
        assert 'ERR_NAME_NOT_RESOLVED' in ' \n '.join(_lines(client))

    def test_the_second_lost_page_says_so(self, client, app_module, dying):
        configure, _made, _probe = dying
        configure(gave_up=2)
        _run(client, app_module, 'pending-streak')
        assert t('run.pageStreak', n=2) in ' \n '.join(_lines(client))

    def test_the_first_lost_page_does_not_claim_a_streak(self, client, app_module, dying):
        _run(client, app_module, 'pending-single')
        assert '连续' not in ' \n '.join(_lines(client))


class TestThePanelSaysTheSameThing:
    def test_an_unreachable_probe_line_is_never_the_praise(self, app_module):
        """The panel's 验证 Cookie answers from the same facts, and its three old answers
        had no shape for 'never tested' — 「无法核对」 was closest but says the wrong
        thing, because what could not be checked was not the cookie."""
        lines = app_module._verify_lines('zhihu', {'url': 'https://www.zhihu.com/', 'unreachable': True})
        assert t('cookie.verify.unreachable', platform='zhihu') in lines
        assert t('cookie.verify.ok', platform='zhihu') not in lines

    def test_a_reachable_page_still_answers_the_three_old_ways(self, app_module):
        assert t('cookie.verify.ok', platform='zhihu') in app_module._verify_lines(
            'zhihu', {'url': 'https://www.zhihu.com/', 'unreachable': False}
        )
        assert t('cookie.verify.loginWall', platform='zhihu') in app_module._verify_lines(
            'zhihu', {'url': 'x', 'login_wall': True}
        )
        assert t('cookie.verify.unclear', platform='zhihu') in app_module._verify_lines(
            'zhihu', {'url': 'x', 'risk_blocked': True}
        )
