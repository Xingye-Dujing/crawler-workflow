"""Everything 停止 promises, measured on a run rather than on a flag.

The complaint this module exists for: pressing 停止 left the run record reading
运行中 for so long that **restarting the service was faster** — and the restart was
faster for a real reason, because the only thing that ever settled an abandoned row
was `promote_stale_runs`, which ran at startup.

Measured first (``backend/test_stop_latency.py``, results in
``scratchpad/stop_latency.json``, Chrome 148):

=========================================== ==========  ==========================
what the Stop request did to a blocked worker  returned   how it died
=========================================== ==========  ==========================
``driver.quit()`` from a side thread              40.02 s  own ``page_load_timeout``
Chromium ``stopRequest`` on a 2nd connection       40.01 s  endpoint is gone (404)
``taskkill`` of that session's driver               2.25 s  socket reset
``driver.quit()`` vs an in-page fetch              30.02 s  own script timeout
``taskkill`` vs an in-page fetch                    2.25 s  socket reset
=========================================== ==========  ==========================

So a graceful close cannot interrupt a crawl — it is an in-band command queued behind
the one running — and the only reliable interrupt is killing the driver process. Hence
the design each case below checks:

1. the record leaves 运行中 **when the request lands**, not when the worker arrives;
2. the crawl itself asks "may I stop?" at its next row, so the shortfall is named as
   a stop and not as "the site sent nothing more";
3. a node cut short is 被停止, never 失败, and is excluded from the failure count;
4. a browser the Stop request does not know about is a browser that keeps working;
5. a record its worker abandoned is settled by reading the panel — not by restarting;
6. a browser that had to be reaped is a browser the crawl is told to stop using, because
   the reap frees the command in flight (1.72 s) but each command after it would pay
   selenium's connect-retry ladder against a dead port — measured 16.3 s each.

All offline: the tmp-isolated store from the `client` fixture, and a fake crawler that
receives the SAME stop predicate a real one does.
"""

import subprocess
import sys
import threading
import time
import types

import pytest
from run_wait import run_finished

from crawlers.base import Crawler, CrawlerStopped, DeadDriver
from i18n import t
from services.run_store import (
    NODE_PARTIAL,
    RUN_INTERRUPTED,
    RUN_RUNNING,
    RUN_STOPPING,
    RunStore,
    workflow_fingerprint,
)

pytestmark = [pytest.mark.api, pytest.mark.serial]

ROWS = [{'作者': f'a{i}', '正文': f'body {i}'} for i in range(6)]


class _StreamingCrawler(Crawler):
    """A crawl over a fixed page through the REAL streaming contract.

    ``gate`` stands in for a worker in the middle of a page load: the handler emits
    ``pre`` rows, signals that it has arrived, and waits to be released — so the test
    can press 停止 with rows already stored and rows still wanted. Rows go out through
    ``self.emit``, which is where the stop is actually checked, so nothing here
    imitates the behaviour under test.
    """

    domain = 'zhihu'
    login_url = 'https://www.zhihu.com/'

    def __init__(self, gate=None, rows=None, abort=None, pre=0):
        self._gate = gate
        self._pre = pre
        self._rows = list(rows if rows is not None else ROWS)
        self.started = 0
        super().__init__(headless=True, abort=abort)

    def _create_driver(self):
        # No browser: the contract under test is the executor's, not Selenium's.
        self.driver = None

    def get_detail(self, url):
        return None

    def _pause(self):
        if self._gate is None:
            return
        self._gate['inside'].set()
        assert self._gate['release'].wait(10), 'the test never released the crawl'

    def search(self, keyword=None, target_count=None, urls=None, resume=None, **kw):
        self.started += 1
        for index, row in enumerate(self._rows):
            if index == self._pre:
                self._pause()
            self.emit(row)
        return self.results()


def _crawler_factory(app_module, monkeypatch, gate=None, rows=None, pre=0):
    """Route every ``get_crawler`` of this test through the fake, keeping the built
    instances reachable (forwarding `abort` is the point, so it is not dropped)."""
    built = []

    def factory(platform, headless=True, cookie_dir=None, use_profile=None, for_login=False, abort=None, **kw):
        crawler = _StreamingCrawler(gate=gate, rows=rows, abort=abort, pre=pre)
        built.append(crawler)
        return crawler

    monkeypatch.setattr(app_module, 'get_crawler', factory)
    return built


class _SlowSession:
    """A driver process that answers nothing, the way a reaped one's port behaves.

    ``cost`` is what one command spends waiting: on a dead chromedriver that is the connect retry
    ladder, measured at 16.3 s. A test names its own number, because what is under test is that the
    crawler is never asked to pay it a second time — not how long the wait is.
    """

    def __init__(self, pid: int, cost: float = 0.0, hang: threading.Event | None = None):
        self.service = types.SimpleNamespace(process=types.SimpleNamespace(pid=pid))
        self.cost = cost
        self._hang = hang
        self.commands = 0

    def quit(self):
        self.commands += 1
        if self._hang is not None:
            assert self._hang.wait(30), 'the test never released this close'
            return
        time.sleep(self.cost)

    def execute_script(self, *_args):
        self.commands += 1
        if self._hang is not None:
            assert self._hang.wait(30), 'the test never released this command'
        else:
            time.sleep(self.cost)
        return None

    def get(self, url):
        return self.execute_script(url)

    def find_element(self, *args):
        return self.execute_script(*args)

    def find_elements(self, *args):
        return self.execute_script(*args)


def _wedged_crawler():
    """A crawler whose browser is stuck inside its own ``quit()``, plus the process standing in for it.

    The release is handed back so no thread outlives the test: the reaper leaves that side thread
    waiting by design, and a fixture that slept out the hang would make every case here take a minute.
    """
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    release = threading.Event()
    crawler = _StreamingCrawler()
    crawler.driver = _SlowSession(child.pid, hang=release)
    return child, crawler, release


def _node(nid, ntype, params):
    return {'id': nid, 'type': ntype, 'title': ntype, 'params': params}


def _source(nid='node-1', keyword='测试'):
    return _node(nid, 'source', {'platform': 'zhihu', 'keyword': keyword, 'target_count': 6, 'headless': True})


def _wf(nodes, conns=None):
    return {'nodes': nodes, 'connections': conns or [], 'settings': {'mode': 'serial'}}


def _start(client, workflow, name):
    started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': name})
    assert started.status_code == 200, started.get_json()
    return started.get_json()['run_id']


def _record(client, app_module, run_id):
    run = app_module.get_run_store().get_run(run_id)
    assert run is not None, f'{run_id} has no record at all'
    return run


def _node_row(run, nid):
    return next((n for n in run['nodes'] if n['node_id'] == nid), None)


def _logs(client):
    return '\n'.join(client.get('/api/workflow/status').get_json()['logs'])


class TestTheRecordFlipsWithTheRequest:
    def test_stopping_lands_while_the_worker_is_still_inside_the_page(self, client, app_module, monkeypatch):
        """The row must agree with the button the user pressed, at the moment they press
        it — the worker may still be standing in a page load it cannot be pulled out of.
        """
        gate = {'inside': threading.Event(), 'release': threading.Event()}
        _crawler_factory(app_module, monkeypatch, gate=gate)
        run_id = _start(client, _wf([_source()]), 'stop-visible')
        assert gate['inside'].wait(10), 'the crawl never started'

        client.post('/api/workflow/stop')
        record = _record(client, app_module, run_id)
        assert record['status'] == RUN_STOPPING, 'the panel would still read 运行中 after 停止'
        # …and while the worker still owns it, nothing else may settle or delete it.
        assert app_module._reject_live_run(run_id) is True

        gate['release'].set()
        assert run_finished(app_module)
        assert _record(client, app_module, run_id)['status'] == RUN_INTERRUPTED

    def test_an_idle_stop_claims_nothing(self, client, app_module):
        """With no run in flight, 停止 must not leave `stopping` standing.

        That flag is what `stop_requested()` hands to every crawl (and what the record
        is flipped on), so a stop nobody needed would make the next crawl answer "the
        user stopped me" to a button pressed against an empty server.
        """
        answer = client.post('/api/workflow/stop').get_json()
        assert answer['ok'] is True and answer['idle'] is True, answer
        assert app_module.stop_requested() is False
        assert client.get('/api/workflow/status').get_json()['stopping'] is False

    def test_the_verdict_replaces_the_intermediate_word(self, client, app_module, monkeypatch):
        """`stopping` is a promise about who asked, not about how it ended."""
        gate = {'inside': threading.Event(), 'release': threading.Event()}
        _crawler_factory(app_module, monkeypatch, gate=gate)
        run_id = _start(client, _wf([_source()]), 'stop-verdict')
        assert gate['inside'].wait(10)
        client.post('/api/workflow/stop')
        gate['release'].set()
        assert run_finished(app_module)
        record = _record(client, app_module, run_id)
        assert record['status'] == RUN_INTERRUPTED
        assert record['finished_at'], 'a settled record must say when it settled'

    def test_the_crawler_is_handed_a_live_stop_predicate(self, client, app_module, monkeypatch):
        """The fake answers `may_stop` from the predicate the EXECUTOR passed it, so the
        test reads the wiring rather than a mock's own opinion."""
        gate = {'inside': threading.Event(), 'release': threading.Event()}
        built = _crawler_factory(app_module, monkeypatch, gate=gate)
        run_id = _start(client, _wf([_source()]), 'stop-predicate')
        assert gate['inside'].wait(10)
        crawler = built[-1]
        assert crawler.may_stop() is False, 'a live run answered "stopped" to its own crawl'
        client.post('/api/workflow/stop')
        assert crawler.may_stop() is True
        gate['release'].set()
        assert run_finished(app_module)
        assert _record(client, app_module, run_id)['status'] == RUN_INTERRUPTED

    def test_the_row_after_a_stop_raises_rather_than_arriving_short(self, client, app_module, monkeypatch):
        """``Crawler.emit`` is the one place every crawl passes a row through, so the
        stop is checked there — and the rows already handed over must survive.

        Without that check the crawl keeps harvesting in a browser the user believes is
        dead, and the shortfall reads as "the site sent nothing more".
        """
        gate = {'inside': threading.Event(), 'release': threading.Event()}
        _crawler_factory(app_module, monkeypatch, gate=gate, rows=ROWS, pre=2)
        run_id = _start(client, _wf([_source()]), 'stop-mid-rows')
        assert gate['inside'].wait(10)
        client.post('/api/workflow/stop')
        gate['release'].set()
        assert run_finished(app_module)

        record = _record(client, app_module, run_id)
        node = _node_row(record, 'node-1')
        assert node['status'] == NODE_PARTIAL, node['status']
        stored = app_module.get_run_store().row_count(run_id, 'node-1')
        assert stored == 2, f'the rows paid for before the stop must be stored, got {stored}'
        assert record['status'] == RUN_INTERRUPTED


class TestStoppedIsNotFailure:
    def test_a_run_the_user_ended_blames_nothing_on_the_workflow(self, client, app_module, monkeypatch):
        """The finish line used to read 「1 个失败」 for the node 停止 cut short.

        A stopped node settles `partial` (its rows stand), and `partial` is what the
        failure count is built from — so the stop needs its own counter or the user is
        told their own button press broke their canvas.
        """
        gate = {'inside': threading.Event(), 'release': threading.Event()}
        _crawler_factory(app_module, monkeypatch, gate=gate, rows=ROWS[:4])
        run_id = _start(client, _wf([_source()]), 'stop-not-failure')
        assert gate['inside'].wait(10)
        client.post('/api/workflow/stop')
        gate['release'].set()
        assert run_finished(app_module)

        status = client.get('/api/workflow/status').get_json()
        assert status['failed_nodes'] == 0, status
        line = _logs(client).splitlines()[-1]
        stopped_key = 'run.finished.stopped'
        assert t(stopped_key, n=1) in line or '被停止' in line, line
        assert t('run.finished.failed', n=1) not in line, line
        assert _record(client, app_module, run_id)['status'] == RUN_INTERRUPTED

    def test_the_stopped_node_says_what_it_kept(self, client, app_module, monkeypatch):
        gate = {'inside': threading.Event(), 'release': threading.Event()}
        _crawler_factory(app_module, monkeypatch, gate=gate, rows=ROWS, pre=3)
        run_id = _start(client, _wf([_source()]), 'stop-line')
        assert gate['inside'].wait(10)
        client.post('/api/workflow/stop')
        gate['release'].set()
        assert run_finished(app_module)
        blob = _logs(client)
        assert t('run.nodeStopped', nid='source #node-1', n=3) in blob, blob
        assert 'wf.node_failed' not in blob and t('run.failed_down', nid='source #node-1') not in blob, blob
        assert _record(client, app_module, run_id)['status'] == RUN_INTERRUPTED


class TestNoFurtherWork:
    def test_a_stopped_run_starts_no_further_crawl(self, client, app_module, monkeypatch):
        """Two nodes, one stop: the second must not buy a browser.

        The graph loops check the flag between levels and between workflows; the node
        boundary is the narrow case they cannot cover — the Stop landing after a level
        had already committed to its node list.
        """
        gate = {'inside': threading.Event(), 'release': threading.Event()}
        built = _crawler_factory(app_module, monkeypatch, gate=gate, rows=ROWS, pre=0)
        chain = [_source('node-1'), _node('node-2', 'analysis', {'steps': [{'op': 'drop_null', 'params': {}}]})]
        run_id = _start(client, _wf(chain, [{'from': 'node-1', 'to': 'node-2'}]), 'stop-two')
        assert gate['inside'].wait(10)
        client.post('/api/workflow/stop')
        gate['release'].set()
        assert run_finished(app_module)
        assert sum(c.started for c in built) == 1, 'a stopped run crawled again'
        record = _record(client, app_module, run_id)
        node2 = _node_row(record, 'node-2')
        # Either it never opened (the level loop broke first) or it opened and was
        # settled as stopped — what it must never be is `done`, which would say the
        # analysis ran over a table that never arrived.
        assert node2 is None or node2['status'] != 'done', node2

    def test_the_comment_engines_browser_is_reachable_to_a_stop(self, client, app_module, monkeypatch):
        """A browser 停止 does not know about keeps loading articles behind a run the
        user ended — and this node only asks the question between URLs."""
        built = []

        class _FakeCrawler:
            """The executor only needs a closeable session with a driver handle."""

            domain = 'zhihu'

            def __init__(self, abort=None):
                self._abort = abort
                self.driver = None
                self.closed = 0

            def close(self):
                self.closed += 1

        def factory(platform, headless=True, cookie_dir=None, use_profile=None, for_login=False, abort=None, **kw):
            crawler = _FakeCrawler(abort=abort)
            built.append(crawler)
            return crawler

        monkeypatch.setattr(app_module, 'get_crawler', factory)
        import crawlers.comments as comments_module

        gate = {'inside': threading.Event(), 'release': threading.Event()}

        class _Session:
            def __init__(self, driver, log=None, nap=None, abort=None):
                # The stop predicate must reach the engine that reads hundreds of
                # pages, not only the crawler that owns the browser.
                assert callable(abort) and abort() is False
                self.abort = abort

            def crawl_zhihu(self, url, limit):
                gate['inside'].set()
                assert gate['release'].wait(10), 'the article walk was never released'
                return [{'文章URL': url, '评论内容': 'c'}], 'ok'

        monkeypatch.setattr(comments_module, 'CommentSession', _Session)
        urls = 'https://www.zhihu.com/question/1/answer/1\nhttps://www.zhihu.com/question/2/answer/2'
        node = _node('node-1', 'comment', {'platform': 'zhihu', 'urls': urls, 'comment_limit': 5})
        run_id = _start(client, _wf([node]), 'stop-comments')
        assert gate['inside'].wait(10), 'the comment engine never reached an article'
        client.post('/api/workflow/stop')
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not built[0].closed:
            time.sleep(0.05)
        gate['release'].set()
        assert run_finished(app_module)
        assert built[0].closed, "停止 never reached the comment node's browser"
        assert _record(client, app_module, run_id)['status'] == RUN_INTERRUPTED


class TestAbandonedRecords:
    """A row its worker never settled must become continuable without a restart."""

    def _abandon(self, app_module, monkeypatch, store, run_id, status=RUN_RUNNING):
        store.start_run(run_id, 'orphan', f'fp-{run_id}')
        if status == RUN_STOPPING:
            store.mark_stopping(run_id)
        monkeypatch.setitem(app_module.execution_state, 'running', False)
        monkeypatch.setitem(app_module.execution_state, 'thread', None)
        monkeypatch.setitem(app_module.execution_state, 'owned_records', {run_id})
        return store.get_run(run_id)['status']

    def test_the_panel_read_settles_a_row_of_its_own_process(self, client, app_module, monkeypatch):
        store = app_module.get_run_store()
        started = self._abandon(app_module, monkeypatch, store, 'orphan-run')
        assert started == RUN_RUNNING
        listed = client.get('/api/runs/list?limit=50').get_json()['runs']
        row = next(r for r in listed if r['run_id'] == 'orphan-run')
        assert row['status'] == RUN_INTERRUPTED, 'the repair still needed a service restart'
        assert row['note'] == t('run.interrupted_by_dead_worker'), row['note']

    def test_a_stopping_row_whose_worker_died_is_settled_too(self, client, app_module, monkeypatch):
        store = app_module.get_run_store()
        started = self._abandon(app_module, monkeypatch, store, 'stopping-orphan', status=RUN_STOPPING)
        assert started == RUN_STOPPING
        listed = client.get('/api/runs/list?limit=50').get_json()['runs']
        assert next(r for r in listed if r['run_id'] == 'stopping-orphan')['status'] == RUN_INTERRUPTED

    def test_a_row_this_process_never_opened_is_left_alone(self, client, app_module, monkeypatch):
        """Another server instance may be writing that one right now. The reconciler
        runs against a live store, so its authority is the ids this process owns."""
        store = app_module.get_run_store()
        store.start_run('stranger-run', 'other', 'fp-stranger')
        monkeypatch.setitem(app_module.execution_state, 'running', False)
        monkeypatch.setitem(app_module.execution_state, 'thread', None)
        monkeypatch.setitem(app_module.execution_state, 'owned_records', set())
        listed = client.get('/api/runs/list?limit=50').get_json()['runs']
        assert next(r for r in listed if r['run_id'] == 'stranger-run')['status'] == RUN_RUNNING

    def test_a_live_worker_is_never_settled_from_outside(self, client, app_module, monkeypatch):
        store = app_module.get_run_store()
        store.start_run('live-run', 'live', 'fp-live')
        keeper = threading.Thread(target=lambda: threading.Event().wait(30), daemon=True)
        keeper.start()
        monkeypatch.setitem(app_module.execution_state, 'running', False)
        monkeypatch.setitem(app_module.execution_state, 'thread', keeper)
        monkeypatch.setitem(app_module.execution_state, 'owned_records', {'live-run'})
        try:
            listed = client.get('/api/runs/list?limit=50').get_json()['runs']
            assert next(r for r in listed if r['run_id'] == 'live-run')['status'] == RUN_RUNNING
        finally:
            keeper.join(0.1)

    def test_the_resume_banner_offers_a_settled_row_only(self, client, app_module, monkeypatch):
        """A row still being written is never continuable: 继续 would open a second
        writer over the same run id."""
        store = app_module.get_run_store()
        workflow = _wf([_source('node-1')])
        fp = workflow_fingerprint(workflow)
        store.start_run('banner-run', 'banner', fp)
        monkeypatch.setitem(app_module.execution_state, 'running', False)
        monkeypatch.setitem(app_module.execution_state, 'thread', None)
        monkeypatch.setitem(app_module.execution_state, 'owned_records', {'banner-run'})
        found = client.post('/api/runs/resumable', json={'workflow': workflow}).get_json()['runs']
        assert [r['run_id'] for r in found] == ['banner-run'], found
        assert found[0]['status'] == RUN_INTERRUPTED

    def test_the_resume_banner_waits_for_a_row_whose_worker_is_alive(self, client, app_module, monkeypatch):
        store = app_module.get_run_store()
        workflow = _wf([_source('node-1')])
        fp = workflow_fingerprint(workflow)
        store.start_run('unsettled-run', 'unsettled', fp)
        keeper = threading.Thread(target=lambda: threading.Event().wait(30), daemon=True)
        keeper.start()
        monkeypatch.setitem(app_module.execution_state, 'owned_records', set())
        monkeypatch.setitem(app_module.execution_state, 'thread', keeper)
        monkeypatch.setitem(app_module.execution_state, 'running', True)
        try:
            found = client.post('/api/runs/resumable', json={'workflow': workflow}).get_json()['runs']
            assert found == [], 'a run in flight was offered to 继续'
        finally:
            keeper.join(0.1)


class TestTheReapedSession:
    """A browser that had to be killed by PID is a browser the crawl is no longer asked to use (#134).

    Measured on a real Chrome (``backend/test_dead_driver.py``, payload
    ``scratchpad/dead_driver.json``): the kill frees the command the worker is *inside* in about
    1.7 s — a dead driver resets the socket, and a request already written is never re-sent. Every
    command after it is a fresh connect to a port nobody holds, and selenium builds its pool with
    urllib3's default ``Retry(total=3)``: measured 16.3 s each, four attempts at ~4.07 s. A walk
    sends several commands per row, and that is what made a 停止 in the middle of a feed take the
    measured 29.6 s to settle — the worker failing, slowly, against a browser that had stopped
    existing seconds earlier.
    """

    def test_a_reaped_browser_holds_a_session_that_refuses_at_once(self, app_module):
        child, crawler, release = _wedged_crawler()
        try:
            app_module._close_login_browser(crawler, quit_timeout=0.3)
            assert isinstance(crawler.driver, DeadDriver), (
                'the reap left the crawler holding the session it just killed, so its next command '
                'is a retry ladder against a dead port'
            )
            started = time.monotonic()
            with pytest.raises(CrawlerStopped) as err:
                crawler.driver.execute_script('return 1;')
            took = time.monotonic() - started
            assert took < 1.0, f'a dead session needed {took:.2f} s to refuse; the ladder is back'
            assert str(err.value) == t('crawl.driverDead')
        finally:
            release.set()
            child.terminate()
            child.wait(10)

    def test_the_same_reaped_browser_may_be_asked_about_again(self, app_module):
        """The stop thread and the worker's own finally both reach this for one browser.

        Asked a second time without the guard, the reaper reads ``driver.service.process.pid`` off the
        session it installed, that read raises ``CrawlerStopped``, and the ``suppress(Exception)``
        around it catches no BaseException — so the thread dies on its way to the NEXT browser,
        leaving that one scrolled to death.
        """
        child, crawler, release = _wedged_crawler()
        try:
            app_module._close_login_browser(crawler, quit_timeout=0.3)
            started = time.monotonic()
            app_module._close_login_browser(crawler, quit_timeout=0.3)
            took = time.monotonic() - started
            assert took < 0.3, f'the second call spent {took:.2f} s on a grace for a browser already reaped'
        finally:
            release.set()
            child.terminate()
            child.wait(10)

    def test_its_own_teardown_is_silent(self):
        """``Crawler.close()`` runs in a ``finally`` after the reap; raising from there would replace
        the crawl's result — the rows it already paid for — with a teardown stack trace."""
        crawler = _StreamingCrawler()
        crawler.driver = DeadDriver()
        crawler.close()
        assert crawler.driver is None

    def test_a_reap_landing_while_close_waits_is_not_erased(self):
        """The order the kill actually produces: ``close()`` is inside ``quit()``, the reaper swaps in
        the dead session, and that swap is what lets ``quit()`` return. A ``close()`` that then wrote
        ``self.driver = None`` would hand the worker an ``AttributeError`` on None — an ordinary
        ``Exception``, folded into "the page gave nothing" by exactly the tolerance above."""
        crawler = _StreamingCrawler()

        class _SwapOnQuit:
            service = types.SimpleNamespace(process=types.SimpleNamespace(pid=0))

            def quit(self):
                crawler.driver = DeadDriver()

        crawler.driver = _SwapOnQuit()
        Crawler.close(crawler)
        assert isinstance(crawler.driver, DeadDriver), 'close() erased the session the reap installed'

    def test_a_browser_that_closed_itself_is_left_alone(self, app_module):
        """The guard the other direction: marking a live session dead, or reaping a process that quit
        politely, would break the next crawl of that platform for a reason nobody asked for."""
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        crawler = _StreamingCrawler()
        crawler.driver = _SlowSession(child.pid)
        try:
            app_module._close_login_browser(crawler, quit_timeout=5.0)
            assert crawler.driver is None, 'a session that closed itself was replaced with a dead one'
            assert child.poll() is None, 'a browser that quit politely had its process reaped anyway'
        finally:
            child.terminate()
            child.wait(10)


class TestStoreStatusMachine:
    def test_stopping_only_replaces_a_running_row(self, tmp_path):
        store = RunStore(str(tmp_path / 'runs.db'))
        store.start_run('s-1', 'wf', 'fp')
        assert store.mark_stopping('s-1') is True
        store.finish_run('s-1', RUN_INTERRUPTED)
        assert store.mark_stopping('s-1') is False, 'a late Stop must not reopen a settled run'
        assert store.get_run('s-1')['status'] == RUN_INTERRUPTED

    def test_startup_promotion_covers_a_stopping_row(self, tmp_path):
        store = RunStore(str(tmp_path / 'runs.db'))
        store.start_run('s-2', 'wf', 'fp')
        store.mark_stopping('s-2')
        assert store.promote_stale_runs() == ['s-2']
        assert store.get_run('s-2')['status'] == RUN_INTERRUPTED

    def test_retention_never_trims_what_has_no_verdict(self, tmp_path):
        """`stopping` is not "finished": trimming it would destroy the cursor of a run
        somebody still means to continue, and both rows here are the same workflow so
        the per-workflow cap forces the choice."""
        store = RunStore(str(tmp_path / 'runs.db'))
        store.start_run('p-stop', 'same', 'fp-a')
        store.mark_stopping('p-stop')
        store.start_run('p-done', 'same', 'fp-b')
        store.finish_run('p-done', 'completed')
        removed = store.purge(keep_per_workflow=1, keep_days=365)
        assert removed['runs'] == 1, removed
        assert store.get_run('p-stop')['status'] == RUN_STOPPING
        assert store.get_run('p-done') is None

    def test_a_stopping_row_is_not_offered_as_resumable_by_the_store(self, tmp_path):
        store = RunStore(str(tmp_path / 'runs.db'))
        store.start_run('s-3', 'wf', 'fp-x')
        store.mark_stopping('s-3')
        listed = store.list_resumable('fp-x')
        assert listed == [], 'a row with no verdict must not be offered to 继续'
        everything = store.list_resumable(limit=10, include_finished=True)
        assert [r['run_id'] for r in everything] == ['s-3'], 'but the panel must still show it'
        assert everything[0]['resumable'] is False
