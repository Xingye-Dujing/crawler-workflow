"""The branches a run only takes when something else goes wrong.

Everything green-path about a run is covered elsewhere; what this module holds is
the machinery that decides *who may run when*, and what happens when the record
of a run disappears underneath it:

* the queue's hand-off — including the two outcomes that are not "started": the
  request that lost the slot and has to wait again, and the request that can
  never start and must be discarded instead of retried after every run;
* a claim decided by thread liveness rather than by the `running` flag, which is
  what a fast Stop → Run sequence actually looks like;
* deleting or discarding the run a live thread is still writing;
* retention that must exempt the live run, exercised by a real run rather than a
  hand-inserted row;
* a run whose store never opened.

The tests drive the real functions with `monkeypatch`, and every one of them
waits for a quiet server before and after, because a stray worker thread would
otherwise land its rows in an unrelated test's store.
"""

import contextlib
import threading

import pytest
from run_wait import run_finished

from services.run_store import RunStore

pytestmark = [pytest.mark.api, pytest.mark.serial]

RECORDS = [{'标题': f'文{i}', '正文': f'正文{i}', '点赞': i} for i in range(1, 5)]


def _wait(app_module, timeout=30.0):
    """The run this test started has settled (see tests/run_wait.py)."""
    return run_finished(app_module, timeout)


def _node(nid, ntype, params=None, operation=''):
    node = {'id': nid, 'type': ntype, 'title': ntype, 'params': params or {}}
    if operation:
        node['operation'] = operation
    return node


def _wf(nodes, conns):
    return {'nodes': nodes, 'connections': conns, 'settings': {'mode': 'serial'}}


def _upload_flow(client, paste, name='race', records=None):
    body = records or RECORDS
    ds = paste(body, name='race.csv')
    return _wf([_node('node-1', 'upload', {'dataset_id': ds, 'row_count': len(body)})], []), name


def _start(client, workflow, name, **extra):
    """POST an execute and hand back its parsed answer."""
    response = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': name, **extra})
    return response, response.get_json()


class TestQueueHandOff:
    """What `_start_next_queued` does with the request it popped.

    The happy path (pop → start → log) is covered by the end-to-end queue test;
    the three other outcomes were not, and they are the ones that decide whether
    a waiting user's press of Run is honoured, repeated or thrown away.
    """

    def _seed(self, app_module, entries):
        with app_module._queue_lock:
            app_module._RUN_QUEUE[:] = entries

    @pytest.fixture(autouse=True)
    def _drain_after(self, app_module):
        """These tests hand the queue entries by hand and never run them, so the
        queue has to be empty again before the next test looks for a quiet
        server — otherwise the scaffolding leaks as a 30s wait elsewhere."""
        yield
        with app_module._queue_lock:
            app_module._RUN_QUEUE[:] = []

    def test_a_request_that_lost_the_slot_waits_at_the_front_again(self, client, app_module, monkeypatch):
        entry = {'id': 'q1', 'workflow_name': 'loser', 'nodes': 1, 'queued_at': 0.0, 'data': {}, 'lang': 'en'}
        self._seed(app_module, [entry])
        # The slot is gone by the time the hand-off asks for it: another request
        # (a manual Run press) claimed it in between.
        lost = {'status': 200, 'body': {'ok': True, 'queued': True}}
        monkeypatch.setattr(app_module, '_begin_run', lambda data, lang: lost)
        app_module._start_next_queued()
        assert [item['id'] for item in app_module.queue_snapshot()] == ['q1'], 'the request is kept, at the front'
        blob = '\n'.join(client.get('/api/workflow/status').get_json()['logs'])
        assert 'loser' in blob and ('queue' in blob.lower() or '排队' in blob), blob

    def test_a_request_that_can_never_start_is_discarded_not_requeued(self, client, app_module, monkeypatch):
        """The 继续 whose run was purged while it waited is refused with 'drop'."""
        self._seed(
            app_module,
            [{'id': 'q1', 'workflow_name': 'stale', 'nodes': 1, 'queued_at': 0.0, 'data': {}, 'lang': 'en'}],
        )
        monkeypatch.setattr(
            app_module,
            '_begin_run',
            lambda data, lang: {'status': 400, 'body': {'ok': False, 'error': 'no such run'}, 'drop': True},
        )
        app_module._start_next_queued()
        assert app_module.queue_snapshot() == [], 'an impossible request must not wait for every future run'
        blob = '\n'.join(client.get('/api/workflow/status').get_json()['logs'])
        assert 'no such run' in blob, blob

    def test_a_payload_that_raises_does_not_strand_the_request_behind_it(self, client, app_module, monkeypatch):
        self._seed(
            app_module,
            [
                {'id': 'bad', 'workflow_name': 'broken', 'nodes': 1, 'queued_at': 0.0, 'data': {}, 'lang': 'en'},
                {'id': 'good', 'workflow_name': 'next', 'nodes': 1, 'queued_at': 0.0, 'data': {}, 'lang': 'en'},
            ],
        )

        def flaky(data, lang):
            if data.get('boom'):
                raise RuntimeError('payload exploded')
            return {'status': 200, 'body': {'ok': True, 'run_id': 'r-next'}}

        monkeypatch.setattr(app_module, '_begin_run', flaky)
        app_module._RUN_QUEUE[0]['data'] = {'boom': True}
        app_module._start_next_queued()
        assert app_module.queue_snapshot() == [], 'both entries were consumed'
        blob = '\n'.join(client.get('/api/workflow/status').get_json()['logs'])
        assert 'broken' in blob, 'the failing request is named, not silently swallowed'

    def test_the_hand_off_names_the_run_it_just_started(self, client, app_module, monkeypatch):
        second = {'id': 'q1', 'workflow_name': 'second', 'nodes': 1, 'queued_at': 0.0, 'data': {}, 'lang': 'en'}
        self._seed(app_module, [second])
        monkeypatch.setattr(
            app_module, '_begin_run', lambda data, lang: {'status': 200, 'body': {'ok': True, 'run_id': 'abc123'}}
        )
        app_module._start_next_queued()
        blob = '\n'.join(client.get('/api/workflow/status').get_json()['logs'])
        assert 'second' in blob and 'abc123' in blob, blob

    def test_an_empty_queue_hands_over_nothing(self, client, app_module, monkeypatch):
        called = []
        monkeypatch.setattr(app_module, '_begin_run', lambda data, lang: called.append(data) or {})
        app_module._start_next_queued()
        assert called == [], 'a finisher must not invent a run'


class TestBusyClaimUsesThreadLiveness:
    """`running` is cleared before the finishing thread stops unwinding."""

    def test_a_still_unwinding_thread_holds_the_slot(self, client, app_module, paste):
        holder = {'started': threading.Event(), 'release': threading.Event()}
        holder['started'].set()

        def _linger():
            holder['release'].wait(10)

        thread = threading.Thread(target=_linger, daemon=True)
        thread.start()
        try:
            app_module.execution_state['running'] = False
            app_module.execution_state['thread'] = thread
            workflow, name = _upload_flow(client, paste, 'while-unwinding')
            answer = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': name})
            assert answer.status_code == 200
            assert answer.get_json().get('queued') is True, 'a live thread still writing means not-claimable'
        finally:
            holder['release'].set()
            thread.join(10)
            app_module.execution_state['thread'] = None

    def test_a_dead_thread_does_not_hold_the_slot(self, client, app_module, paste):
        """A thread that died without clearing its handle (an interpreter-level
        abort of the worker) must not queue every later request behind a ghost."""
        dead = threading.Thread(target=lambda: None)
        dead.start()
        dead.join(5)
        app_module.execution_state['running'] = False
        app_module.execution_state['thread'] = dead
        workflow, name = _upload_flow(client, paste, 'after-dead-thread')
        answer = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': name})
        assert answer.get_json().get('ok') is True
        assert not answer.get_json().get('queued'), 'the request started, it did not park'
        assert _wait(app_module)


class TestLiveRunCannotBeDeleted:
    """丢弃/删除 target a run id the UI read from a list; the live run is one click away.

    Both routes check the store first, so these use a run a real execution
    created — a hand-made id would answer 404 and prove nothing.
    """

    def _make_live(self, client, app_module, paste, name):
        workflow, _ = _upload_flow(client, paste, name)
        started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': name})
        assert _wait(app_module)
        run_id = started.get_json()['run_id']
        # A finished record, but the slot claims it: exactly the state a Stop that
        # has not settled yet, or a stale browser tab, presents to these routes.
        app_module.execution_state['running'] = True
        app_module.execution_state['run_id'] = run_id
        return run_id

    def _release(self, app_module):
        app_module.execution_state['running'] = False
        app_module.execution_state['run_id'] = ''

    def test_discarding_the_live_run_is_refused(self, client, app_module, paste):
        run_id = self._make_live(client, app_module, paste, 'live-discard')
        try:
            answer = client.post('/api/runs/discard', json={'run_id': run_id})
            assert answer.status_code == 400, answer.get_json()
            assert 'already running' in answer.get_json()['error']
            assert app_module._RUN_STORE.get_run(run_id) is not None, 'a refused discard still deleted it'
        finally:
            self._release(app_module)

    def test_deleting_the_live_run_is_refused(self, client, app_module, paste):
        run_id = self._make_live(client, app_module, paste, 'live-delete')
        try:
            answer = client.post('/api/runs/delete', json={'run_id': run_id})
            assert answer.status_code == 400, answer.get_json()
            assert app_module._RUN_STORE.get_run(run_id) is not None
        finally:
            self._release(app_module)

    def test_the_same_run_is_deletable_once_the_slot_is_free(self, client, app_module, paste):
        run_id = self._make_live(client, app_module, paste, 'then-delete')
        self._release(app_module)
        answer = client.post('/api/runs/delete', json={'run_id': run_id})
        assert answer.get_json()['ok'] is True
        assert app_module._RUN_STORE.get_run(run_id) is None


class TestPurgeProtectsTheLiveRun:
    """Retention runs on a timer and on `/api/runs/purge`; both must exempt the
    record a thread is still writing — dropping its rows mid-run destroys state
    the run itself will try to read back."""

    def test_a_real_live_run_survives_a_purge_that_keeps_nothing(self, client, app_module, paste, monkeypatch):
        """`keep_per_workflow = 0` is the adversarial setting: every run is
        beyond the cap, so the only thing standing between the live record and
        deletion is the exemption the caller passes."""
        from config import Config

        monkeypatch.setattr(Config, 'RUN_KEEP_PER_WORKFLOW', 0)
        # Two finished runs of the same workflow, so purge has real work to do.
        workflow, name = _upload_flow(client, paste, 'live-purge')
        for _ in range(2):
            response, _body = _start(client, workflow, name)
            assert response.status_code == 200
            assert _wait(app_module)
        finished = [entry['run_id'] for entry in app_module._RUN_STORE.list_resumable(include_finished=True, limit=10)]
        assert len(finished) == 2

        gate = threading.Event()
        release = threading.Event()

        class _Slow:
            def set_sink(self, sink):
                pass

            def set_cursor_sink(self, sink):
                pass

            def seed(self, rows):
                pass

            def close(self):
                pass

            def search(self, *args, **kwargs):
                gate.set()
                release.wait(20)
                return [{'标题': 'a'}]

        monkeypatch.setattr(app_module, 'get_crawler', lambda *a, **k: _Slow())
        live_flow = _wf([_node('node-1', 'source', {'platform': 'zhihu', 'keyword': 'k', 'target_count': 1})], [])
        started = client.post('/api/workflow/execute', json={'workflow': live_flow, 'workflow_name': 'live-purge'})
        assert started.status_code == 200, started.get_json()
        run_id = started.get_json()['run_id']
        assert gate.wait(20), 'the worker never reached the crawler'
        try:
            assert app_module.execution_state['running'] is True
            removed = client.post('/api/runs/purge').get_json()['removed']
            assert removed['runs'] == 2, removed
            assert app_module._RUN_STORE.get_run(run_id) is not None, 'purge deleted the run being written'
        finally:
            release.set()
            assert _wait(app_module)

    def test_the_same_purge_without_an_exemption_does_delete_it(self, client, app_module, monkeypatch):
        """The teeth for the test above: the live row is a purge candidate on the
        same rules, so the survival was the exemption, not luck."""
        from config import Config

        monkeypatch.setattr(Config, 'RUN_KEEP_PER_WORKFLOW', 0)
        store = app_module._RUN_STORE
        store.start_run('protected', 'fp-protected', 'fp')
        store.purge(keep_per_workflow=0, exclude_run_id='protected')
        assert store.get_run('protected') is not None
        store.purge(keep_per_workflow=0)
        assert store.get_run('protected') is None, 'without the exemption it goes like any other run'


class _GatedCrawler:
    """Emits a few rows, then blocks until the test says otherwise.

    The point is an interrupted run with data already settled: a crawler that
    returns nothing would exercise the empty-run path instead, which is a
    different branch with different promises.
    """

    emitted = 3
    gate = None
    release = None

    def __init__(self, *args, **kwargs):
        pass

    def set_sink(self, sink):
        self._sink = sink

    def set_cursor_sink(self, sink):
        pass

    def seed(self, rows):
        pass

    def close(self):
        pass

    def search(self, *args, **kwargs):
        kept = []
        for index in range(type(self).emitted):
            row = {'标题': f'r{index}', '正文': f'正文{index}'}
            if self._sink is None or self._sink(row):
                kept.append(row)
        type(self).gate.set()
        type(self).release.wait(30)
        return kept


class TestResumeAfterInterruption:
    """The promise 断点续跑 makes: stop now, press 继续 later, pay for nothing twice."""

    @pytest.fixture(autouse=True)
    def _crawler_class(self, app_module, monkeypatch):
        _GatedCrawler.gate = threading.Event()
        _GatedCrawler.release = threading.Event()
        _GatedCrawler.emitted = 3
        monkeypatch.setattr(app_module, 'get_crawler', lambda *a, **k: _GatedCrawler(*a, **k))
        yield
        # Whatever the test did, the crawler must not stay parked on its gate:
        # a worker thread still inside `search` would make the NEXT test wait for
        # a quiet server on a timeout rather than on a real finish.
        _GatedCrawler.release.set()

    def _interrupted_run(self, client, app_module):
        workflow = _wf([_node('node-1', 'source', {'platform': 'zhihu', 'keyword': 'k', 'target_count': 9})], [])
        started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'interrupted'})
        assert started.status_code == 200, started.get_json()
        run_id = started.get_json()['run_id']
        if not _GatedCrawler.gate.wait(20):
            record = app_module._RUN_STORE.get_run(run_id) or {}
            pytest.fail(
                f'crawler never built; run={record.get("status")} '
                f'nodes={[(n["node_id"], n["status"], n.get("error")) for n in record.get("nodes", [])]} '
                f'logs={client.get("/api/workflow/status").get_json()["logs"]}'
            )
        assert client.post('/api/workflow/stop').get_json()['ok'] is True
        _GatedCrawler.release.set()
        assert _wait(app_module)
        return workflow, run_id

    def test_a_stopped_run_is_offered_for_continue_with_its_rows_intact(self, client, app_module):
        workflow, run_id = self._interrupted_run(client, app_module)
        resumable = client.post('/api/runs/resumable', json={'workflow': workflow}).get_json()
        assert run_id in [entry['run_id'] for entry in resumable['runs']], resumable
        assert app_module._RUN_STORE.row_count(run_id, 'node-1') == 3

    def test_a_second_attempt_accumulates_instead_of_duplicating(self, client, app_module):
        _GatedCrawler.emitted = 2
        workflow, run_id = self._interrupted_run(client, app_module)
        _GatedCrawler.emitted = 5
        continued = client.post(
            '/api/workflow/execute',
            json={'workflow': workflow, 'workflow_name': 'interrupted', 'resume_run_id': run_id},
        )
        assert continued.status_code == 200, continued.get_json()
        assert continued.get_json()['run_id'] == run_id, 'a continue reuses the record, not a new one'
        assert _wait(app_module)
        rows = app_module._RUN_STORE.load_rows(run_id, 'node-1')
        titles = [row['标题'] for row in rows]
        assert len(titles) == len(set(titles)), f'the ledger let a row be stored twice: {titles}'
        assert app_module._RUN_STORE.get_run(run_id)['status'] == 'completed'

    def test_a_restart_with_the_same_database_still_offers_the_continue(self, client, app_module, monkeypatch):
        """The process died rather than being stopped: the next one reopens
        runs.db, promotes the orphaned record, and the banner must still find it."""
        _workflow, run_id = self._interrupted_run(client, app_module)
        db_path = app_module._RUN_STORE.db_path
        # A second record left claiming to run — precisely what a killed process
        # stores, because its `finally` never got to settle anything.
        app_module._RUN_STORE.start_run('orphan', 'crashed', 'fp-crashed')
        try:
            # Opening the store *is* the boot-time promotion (RunStore.__init__
            # calls promote_stale_runs), so the assertion is about its effect.
            restarted = RunStore(str(db_path))
            monkeypatch.setattr(app_module, '_RUN_STORE', restarted)
            assert restarted.get_run('orphan')['status'] == 'interrupted', 'a dead process record still claims to run'
            assert restarted.get_run(run_id)['status'] == 'interrupted', 'a settled run was re-labelled'
            listed = [entry['run_id'] for entry in restarted.list_resumable()]
            assert {run_id, 'orphan'} <= set(listed), listed
            assert restarted.row_count(run_id, 'node-1') == 3, 'the paid-for rows did not survive the restart'
        finally:
            with contextlib.suppress(Exception):
                restarted._conn.close()


class TestContinueAfterAnEdit:
    """Editing a node is the case 断点续跑 must get wrong in one direction only.

    Reusing the stored rows of a node the user has since changed would show old
    results under new settings and call them "restored from the last attempt";
    dropping them is the safe side, so the node has to actually run again.
    """

    STEPS_A = [{'op': 'filter_rows', 'params': {'column': '城市', 'op': 'eq', 'value': '三亚'}}]
    STEPS_B = [{'op': 'filter_rows', 'params': {'column': '城市', 'op': 'eq', 'value': '海口'}}]

    def _flow(self, steps, export_format):
        return _wf(
            [
                _node('node-1', 'upload', {'dataset_id': self.dataset, 'row_count': 3}),
                _node('node-2', 'analysis', {'steps': steps}),
                _node('node-3', 'output', {'format': export_format, 'filename': 'edit'}, 'save'),
            ],
            [{'from': 'node-1', 'to': 'node-2'}, {'from': 'node-2', 'to': 'node-3'}],
        )

    @pytest.fixture(autouse=True)
    def _data(self, paste):
        type(self).dataset = paste(
            [{'城市': '三亚', '分数': 1}, {'城市': '海口', '分数': 2}, {'城市': '三亚', '分数': 3}], name='edit.csv'
        )
        yield

    def test_a_continued_run_re_runs_the_node_whose_settings_changed(self, client, app_module):
        # Attempt 1: the analysis node finishes, the export refuses -> resumable.
        started = client.post(
            '/api/workflow/execute',
            json={'workflow': self._flow(self.STEPS_A, 'parquet'), 'workflow_name': 'edit'},
        )
        assert started.status_code == 200
        run_id = started.get_json()['run_id']
        assert _wait(app_module)
        first = app_module._RUN_STORE.get_run(run_id)
        assert first['status'] == 'failed'
        nodes = {node['node_id']: node for node in first['nodes']}
        assert nodes['node-2']['status'] == 'done' and nodes['node-2']['row_count'] == 2

        # Attempt 2: same shape, different analysis settings, working export.
        continued = client.post(
            '/api/workflow/execute',
            json={'workflow': self._flow(self.STEPS_B, 'csv'), 'workflow_name': 'edit', 'resume_run_id': run_id},
        )
        assert continued.status_code == 200, continued.get_json()
        assert _wait(app_module)
        second = app_module._RUN_STORE.get_run(run_id)
        assert second['status'] == 'completed', second['note']
        after = {node['node_id']: node for node in second['nodes']}
        assert after['node-2']['status'] != 'restored', 'an edited node must not be reported as reused'
        rows = app_module._RUN_STORE.load_rows(run_id, 'node-2')
        assert [row['城市'] for row in rows] == ['海口'], 'the edited filter is what ran'

    def test_an_unchanged_node_is_restored_not_recomputed(self, client, app_module):
        """The other side of the same rule: with nothing edited, the work an
        earlier attempt paid for comes back rather than running again."""
        started = client.post(
            '/api/workflow/execute',
            json={'workflow': self._flow(self.STEPS_A, 'parquet'), 'workflow_name': 'same'},
        )
        run_id = started.get_json()['run_id']
        assert _wait(app_module)
        client.post(
            '/api/workflow/execute',
            json={'workflow': self._flow(self.STEPS_A, 'csv'), 'workflow_name': 'same', 'resume_run_id': run_id},
        )
        assert _wait(app_module)
        nodes = app_module._RUN_STORE.node_statuses(run_id)
        assert nodes['node-2']['status'] == 'restored', nodes['node-2']
        blob = '\n'.join(client.get('/api/workflow/status').get_json()['logs'])
        assert 'analysis #node-2' in blob, blob


class TestStoreFailures:
    """A database that will not open is a run that must still end cleanly."""

    def test_a_store_that_refuses_to_open_fails_the_run_and_frees_the_slot(
        self, client, app_module, paste, monkeypatch
    ):
        """``ctx`` is built inside the worker's try: when the store raises, the
        run has no record to settle, and the console line is the only trace. What
        must not happen is the slot staying claimed."""

        def refuse():
            raise OSError('runs.db is not a database')

        monkeypatch.setattr(app_module, 'get_run_store', refuse)
        workflow, name = _upload_flow(client, paste, 'no-store')
        started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': name})
        assert started.status_code == 200, started.get_json()
        assert _wait(app_module), 'the worker never finished'
        assert app_module.execution_state['running'] is False, 'a failed store left the slot claimed'
        assert app_module.execution_state['outcome'] == 'failed'
        blob = '\n'.join(client.get('/api/workflow/status').get_json()['logs'])
        assert 'store' in blob.lower() or 'run record' in blob.lower(), blob
        # The next run must be able to start at all.
        monkeypatch.setattr(app_module, 'get_run_store', lambda: app_module._RUN_STORE)
        again = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': name})
        assert again.get_json().get('ok') is True and not again.get_json().get('queued')
        assert _wait(app_module)

    def test_losing_the_end_of_a_run_does_not_lose_the_run(self, client, app_module, paste):
        """``_close_run`` is the last write of a run. If settling the record
        throws, the rows are already stored — so the failure has to stay inside
        that one function rather than escape the worker's ``finally`` and leave
        the slot, the tee and the console in whatever state the exception hit."""
        store = app_module._RUN_STORE

        def explode(*args, **kwargs):
            raise OSError('the database went away')

        store.settle_nodes = explode
        store.finish_run = explode
        workflow, name = _upload_flow(client, paste, 'close-explodes')
        run_id = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': name}).get_json()[
            'run_id'
        ]
        assert _wait(app_module), 'the worker died in its own finally'
        assert app_module.execution_state['running'] is False
        assert app_module._RUN_STORE.row_count(run_id, 'node-1') == len(RECORDS), 'the rows went with the record'

    def test_a_run_record_that_cannot_be_settled_is_still_readable(self, app_module, paste, client):
        """The narrower promise, on the function itself: it never propagates."""

        class _Broken:
            def settle_nodes(self, *a, **k):
                raise OSError('locked')

            def finish_run(self, *a, **k):
                raise OSError('locked')

        app_module._close_run({'store': _Broken(), 'run_id': 'r1'}, 'completed')


class TestStopWithoutABrowser:
    """Stop has two very different things to interrupt."""

    def test_stopping_a_run_with_an_llm_executor_but_no_crawler_is_safe(self, client, app_module, paste, monkeypatch):
        """No crawl means nothing to close, but the executor still has to be
        told, the cancel flag still has to go up, and the route still must not
        raise on the empty crawler set."""
        stopped = {'executor': False}

        class _Executor:
            def stop(self):
                stopped['executor'] = True

        app_module.execution_state['running'] = True
        app_module.execution_state['executor'] = _Executor()
        app_module.execution_state['cancel_event'].clear()
        app_module.execution_state['active_crawlers'].clear()
        try:
            answer = client.post('/api/workflow/stop')
            assert answer.status_code == 200, answer.get_json()
        finally:
            app_module.execution_state['running'] = False
            app_module.execution_state['executor'] = None
        assert stopped['executor'] is True, 'the row-by-row LLM loop was never told to bail'
        assert app_module.execution_state['cancel_event'].is_set(), 'Stop must raise the row-boundary flag'

        cancelled = app_module.execution_state['cancel_event']
        workflow, name = _upload_flow(client, paste, 'after-stop')
        response, _body = _start(client, workflow, name)
        assert response.status_code == 200
        assert _wait(app_module)
        assert app_module.execution_state['cancel_event'] is not cancelled, 'the next run gets a fresh flag'
        assert not app_module.execution_state['cancel_event'].is_set(), 'a Stop cannot cancel a later run'
