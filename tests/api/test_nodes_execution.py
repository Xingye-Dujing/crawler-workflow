"""Every node type through the real executor, and the Stop/kill plumbing.

The audit asked: does each node actually do its job, and do the process-control
endpoints behave under misuse? Each test below drives one node type through
``/api/workflow/execute`` (the same code path the canvas uses), asserting on
the STORED outcome — rows in the run store, files in the export dir, log lines
in the console — not on a private helper's return value.

Everything runs offline: uploads replace crawlers, the resume node reads the
tmp-isolated store, and the slow crawler is a fake that respects the stop
flag, so /api/workflow/stop is exercised without ever touching a browser.
"""

import time

import pandas as pd
import pytest

pytestmark = [pytest.mark.api, pytest.mark.serial]

RECORDS = [
    {'标题': '三亚湾日落', '城市': 'Sanya', '分数': 3, '正文': '三亚的海滩很美 三亚湾日落真棒'},
    {'标题': '海口骑楼', '城市': 'Haikou', '分数': 5, '正文': '海口的老街骑楼很有味道'},
    {'标题': '博鳌论坛', '城市': 'Boao', '分数': 2, '正文': '博鳌小镇安静整洁'},
    {'标题': '兴隆咖啡', '城市': 'Sanya', '分数': 7, '正文': '兴隆的咖啡香浓醇厚'},
]


def _node(nid, ntype, params=None, operation=''):
    node = {'id': nid, 'type': ntype, 'title': ntype, 'params': params or {}}
    if operation:
        node['operation'] = operation
    return node


def _wf(nodes, conns, settings=None):
    return {'nodes': nodes, 'connections': conns, 'settings': settings or {'mode': 'serial'}}


def _wait(app_module, timeout=30.0):
    thread = app_module.execution_state.get('thread')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if thread is not None and not thread.is_alive():
            time.sleep(0.05)  # the finally-block still settles the run record
            return True
        time.sleep(0.02)
    return False


def _upload(client, paste):
    return paste(RECORDS, name='nodes.csv')


class TestTokenizeNode:
    def test_tokenize_streams_word_frequencies_downstream(self, client, app_module, paste, data_root):
        ds = _upload(client, paste)
        workflow = _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 4}),
                _node('node-2', 'tokenize', {'text_column': '正文', 'output_mode': 'word_freq', 'top_n': 10}),
                _node('node-3', 'output', {'operation': 'save', 'format': 'json', 'filename': 'tok'}, 'save'),
            ],
            [{'from': 'node-1', 'to': 'node-2'}, {'from': 'node-2', 'to': 'node-3'}],
        )
        started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'tok'})
        assert started.get_json()['ok'] is True
        assert _wait(app_module)
        run_id = started.get_json()['run_id']
        rows = app_module._RUN_STORE.load_rows(run_id, 'node-2')
        assert rows, 'jieba must emit frequency rows for Chinese text'
        assert {'word', 'frequency'} <= set(rows[0].keys())
        assert (data_root / 'data' / 'exports' / 'tok.json').exists(), 'the chain must end in a file'

    def test_a_wrong_column_name_fails_loudly_not_silently(self, client, app_module, paste):
        ds = _upload(client, paste)
        workflow = _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 4}),
                _node('node-2', 'tokenize', {'text_column': '根本不存在的列'}),
                _node('node-3', 'output', {'operation': 'save', 'format': 'json', 'filename': 'tok-bad'}, 'save'),
            ],
            [{'from': 'node-1', 'to': 'node-2'}, {'from': 'node-2', 'to': 'node-3'}],
        )
        started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'tok-bad'})
        assert _wait(app_module)
        run_id = started.get_json()['run_id']
        assert app_module._RUN_STORE.row_count(run_id, 'node-2') == 0
        blob = '\n'.join(client.get('/api/workflow/status').get_json()['logs'])
        assert '根本不存在的列' in blob, 'the message must name the column that is missing'

    def test_an_unconfigured_tokenize_node_is_a_validation_error(self, client, app_module, paste):
        ds = _upload(client, paste)
        workflow = _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 4}),
                _node('node-2', 'tokenize', {'text_column': ''}),
                _node('node-3', 'output', {'operation': 'save', 'format': 'json', 'filename': 'tok-x'}, 'save'),
            ],
            [{'from': 'node-1', 'to': 'node-2'}, {'from': 'node-2', 'to': 'node-3'}],
        )
        client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'tok-x'})
        assert _wait(app_module)
        blob = '\n'.join(client.get('/api/workflow/status').get_json()['logs'])
        assert 'text column' in blob or '未配置' in blob


class TestVisualizeNode:
    def test_echarts_spec_is_produced_and_exposed(self, client, app_module, paste):
        ds = _upload(client, paste)
        workflow = _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 4}),
                _node('node-2', 'visualize', {'chart_type': 'bar', 'x_field': '城市', 'y_field': '分数', 'agg': 'sum'}),
            ],
            [{'from': 'node-1', 'to': 'node-2'}],
        )
        client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'viz'})
        assert _wait(app_module)
        status = client.get('/api/workflow/status').get_json()
        spec = status['chart_results'].get('node-2')
        assert spec and spec['engine'] == 'echarts', 'the finished chart spec must reach the browser'
        assert 'series' in spec['option'] and 'xAxis' in spec['option']

    def test_a_bad_field_is_reported_not_as_a_crash(self, client, app_module, paste):
        ds = _upload(client, paste)
        workflow = _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 4}),
                _node('node-2', 'visualize', {'chart_type': 'bar', 'x_field': 'nope', 'y_field': 'nope2'}),
            ],
            [{'from': 'node-1', 'to': 'node-2'}],
        )
        client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'viz-bad'})
        assert _wait(app_module)
        # A refused chart carries its reason (never a half spec / traceback), it
        # reaches the console, and only RENDERABLE charts surface in chart_results.
        spec = app_module.execution_state['results'].get('node-2')
        assert isinstance(spec, dict) and 'error' in spec and 'nope' in str(spec['error'])
        status = client.get('/api/workflow/status').get_json()
        assert 'node-2' not in status['chart_results']
        assert any('Visualize failed' in line for line in status['logs'])

    def test_a_refused_node_never_settles_as_done(self, client, app_module, paste):
        """The node's own answer is a dict with 'error' — and that must not read
        as a completed node, let alone a completed run.

        The output and visualize nodes report a refusal instead of raising so
        their downstream keeps the table; the durable runner used to settle any
        non-list result DONE, which turned "the file you asked for was never
        written" into a green run.
        """
        ds = _upload(client, paste)
        workflow = _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 4}),
                _node('node-2', 'visualize', {'chart_type': 'bar', 'x_field': 'nope', 'y_field': 'nope2'}),
            ],
            [{'from': 'node-1', 'to': 'node-2'}],
        )
        started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'viz-failed'})
        assert _wait(app_module)
        run = app_module._RUN_STORE.get_run(started.get_json()['run_id'])
        node = next(entry for entry in run['nodes'] if entry['node_id'] == 'node-2')
        assert node['status'] == 'failed', f"a refused chart settled as '{node['status']}'"
        assert 'nope' in (node['error'] or '')
        assert run['status'] == 'failed', 'a run with a failed node is not completed'


class TestOutputFormats:
    @pytest.mark.parametrize(
        'fmt,ext',
        [('csv', '.csv'), ('json', '.json'), ('markdown', '.md'), ('excel', '.xlsx')],
    )
    def test_every_advertised_format_lands_a_file(self, client, app_module, paste, data_root, fmt, ext):
        ds = _upload(client, paste)
        workflow = _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 4}),
                _node('node-2', 'output', {'operation': 'save', 'format': fmt, 'filename': f'out-{fmt}'}, 'save'),
            ],
            [{'from': 'node-1', 'to': 'node-2'}],
        )
        client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': f'out-{fmt}'})
        assert _wait(app_module)
        path = data_root / 'data' / 'exports' / f'out-{fmt}{ext}'
        assert path.exists(), f'{fmt} export missing (and the extension must be normalised)'
        if fmt == 'json':
            import json as _json

            assert len(_json.loads(path.read_text(encoding='utf-8'))) == 4
        if fmt == 'csv':
            assert len(pd.read_csv(path, encoding='utf-8-sig')) == 4

    def test_a_filename_with_path_holes_cannot_escape_the_export_dir(self, client, app_module, paste, data_root):
        ds = _upload(client, paste)
        workflow = _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 4}),
                _node('node-2', 'output', {'operation': 'save', 'format': 'csv', 'filename': '../../evil'}, 'save'),
            ],
            [{'from': 'node-1', 'to': 'node-2'}],
        )
        client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'escape'})
        assert _wait(app_module)
        exports = data_root / 'data' / 'exports'
        assert not list(exports.parent.parent.glob('evil*')), 'a traversal filename must stay inside exports/'

    def test_unnamed_output_keeps_a_default_and_still_saves(self, client, app_module, paste, data_root):
        ds = _upload(client, paste)
        workflow = _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 4}),
                _node('node-2', 'output', {'operation': 'save', 'format': 'csv'}, 'save'),
            ],
            [{'from': 'node-1', 'to': 'node-2'}],
        )
        client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'defname'})
        assert _wait(app_module)
        assert any(p.suffix == '.csv' for p in (data_root / 'data' / 'exports').iterdir())


class TestResumeNode:
    def test_explicit_pick_adopts_a_finished_runs_table(self, client, app_module, paste):
        ds = _upload(client, paste)
        first = _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 4}),
                _node('node-2', 'analysis', {'steps': [{'op': 'drop_null', 'params': {'columns': ['分数']}}]}),
                _node('node-3', 'output', {'operation': 'save', 'format': 'csv', 'filename': 'r1'}, 'save'),
            ],
            [{'from': 'node-1', 'to': 'node-2'}, {'from': 'node-2', 'to': 'node-3'}],
        )
        started = client.post('/api/workflow/execute', json={'workflow': first, 'workflow_name': 'r1'})
        assert _wait(app_module)
        run1 = started.get_json()['run_id']

        second = _wf(
            [
                _node('node-1', 'resume', {'resume_run_id': run1, 'resume_node_id': 'node-2', 'resume_limit': 0}),
                _node('node-2', 'output', {'operation': 'save', 'format': 'csv', 'filename': 'r2'}, 'save'),
            ],
            [{'from': 'node-1', 'to': 'node-2'}],
        )
        started2 = client.post('/api/workflow/execute', json={'workflow': second, 'workflow_name': 'r2'})
        assert _wait(app_module)
        rows = app_module._RUN_STORE.load_rows(started2.get_json()['run_id'], 'node-1')
        assert len(rows) == 4
        blob = '\n'.join(client.get('/api/workflow/status').get_json()['logs'])
        assert run1 in blob, 'the adoption must name its source run'

    def test_auto_discovery_adopts_the_biggest_table_of_a_broken_same_shape_run(self, client, app_module, data_root):
        from services.run_store import NODE_DONE, RUN_INTERRUPTED, RunStore, workflow_fingerprint

        # A prior run of EXACTLY this shape (what "继续" re-executes) is
        # forged straight into the store: node-1 is the resume node's own id
        # and its stored table is what the newest attempt must adopt.
        lonely = _wf([_node('node-1', 'resume', {})], [])
        fp = workflow_fingerprint(lonely)
        db = str(data_root / 'data' / 'forged-runs.db')
        maker = RunStore(db)
        maker.start_run('forged-1', 'auto-resume', fp, mode='serial', headless=True, llm=None, lang='en', node_total=1)
        maker.begin_node('forged-1', 'node-1', 'resume')
        maker.append_rows('forged-1', 'node-1', [{'x': 1}, {'x': 2}, {'x': 3}])
        maker.finish_node('forged-1', 'node-1', NODE_DONE)
        maker.finish_run('forged-1', RUN_INTERRUPTED)
        maker._conn.close()

        app_module._RUN_STORE = RunStore(db)
        started = client.post('/api/workflow/execute', json={'workflow': lonely, 'workflow_name': 'auto-resume'})
        assert _wait(app_module)
        rows = app_module._RUN_STORE.load_rows(started.get_json()['run_id'], 'node-1')
        assert [r['x'] for r in rows] == [1, 2, 3]

    def test_a_resume_node_with_nothing_to_adopt_produces_no_rows_no_crash(self, client, app_module):
        lonely = _wf([_node('node-1', 'resume', {})], [])
        started = client.post('/api/workflow/execute', json={'workflow': lonely, 'workflow_name': 'no-run'})
        assert _wait(app_module)
        assert app_module._RUN_STORE.row_count(started.get_json()['run_id'], 'node-1') == 0
        blob = '\n'.join(client.get('/api/workflow/status').get_json()['logs'])
        assert 'no run selected' in blob or '没有选择运行记录' in blob


class TestBrowserReaper:
    def test_a_browser_ignoring_close_is_killed_by_pid_and_the_call_returns(self, app_module):
        """Stop must not hang on a wedged driver — and the fallback kill is
        PID-targeted (tree included), never a global chromedriver massacre."""
        import subprocess
        import sys
        import types

        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])

        class _Stuck:
            def __init__(self, proc):
                self.driver = types.SimpleNamespace(service=types.SimpleNamespace(process=proc))

            def close(self):
                time.sleep(30)  # the wedged quit this path exists for

        started = time.monotonic()
        app_module._close_login_browser(_Stuck(child), quit_timeout=0.5)
        assert time.monotonic() - started < 20, 'the bounded close must return'
        child.wait(timeout=10)
        assert child.poll() is not None, 'the ignored driver process must be reaped by PID'

    def test_a_null_crawler_is_nothing_to_do(self, app_module):
        app_module._close_login_browser(None)  # must not raise


class TestStopAndKill:
    def test_stop_while_idle_is_safe(self, client, app_module):
        resp = client.post('/api/workflow/stop')
        assert resp.status_code == 200 and resp.get_json()['ok'] is True
        assert app_module.execution_state['running'] is False
        assert client.get('/api/workflow/status').get_json()['logs'] == []

    def test_stop_aborts_a_crawl_keeps_rows_and_marks_the_run_interrupted(self, client, app_module, monkeypatch):
        class _Slow:
            def __init__(self, *a, **k):
                self._s = None

            def set_sink(self, s):
                self._s = s

            def set_cursor_sink(self, s):
                pass

            def seed(self, rows):
                pass

            def close(self):
                pass

            def search(self, *a, **k):
                kept = []
                i = 0
                while app_module.execution_state['running'] and i < 100000:
                    row = {'标题': f'r{i}'}
                    i += 1
                    if self._s is None or self._s(row):
                        kept.append(row)
                    if i % 50 == 0:
                        time.sleep(0.01)
                return kept

        monkeypatch.setattr(app_module, 'get_crawler', lambda *a, **k: _Slow())
        workflow = _wf([_node('node-1', 'source', {'platform': 'zhihu', 'keyword': 'k', 'target_count': 99999})], [])
        started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'slow'})
        assert started.get_json()['ok'] is True
        run_id = started.get_json()['run_id']
        for _ in range(200):
            if app_module._RUN_STORE.row_count(run_id, 'node-1') > 0:
                break
            time.sleep(0.05)
        stopped = client.post('/api/workflow/stop')
        assert stopped.get_json()['ok'] is True
        assert _wait(app_module)
        run = app_module._RUN_STORE.get_run(run_id)
        assert run['status'] == 'interrupted', 'a stopped run must be resumable, not completed'
        assert run['nodes'][0]['row_count'] > 0, 'everything the stopped crawl kept must stay stored'

    def test_stopping_keeps_the_console_that_explains_it(self, client, app_module, monkeypatch):
        """Stop used to wipe the console and zero the node counters.

        The consequence was a summary line that read "运行结束（0/0 个节点完成）"
        for a run that had just finished two nodes, printed into a console the
        user had been watching — the record of what the run did, deleted by the
        act of stopping it.
        """
        class _Slow:
            def __init__(self, *a, **k):
                self._s = None

            def set_sink(self, s):
                self._s = s

            def search(self, *a, **k):
                for i in range(500):
                    if self._s:
                        self._s({'标题': f'row {i}', '链接': f'https://www.zhihu.com/question/{i}'})
                    time.sleep(0.01)
                return []

            def close(self):
                pass

        monkeypatch.setattr(app_module, 'get_crawler', lambda *a, **k: _Slow())
        workflow = _wf([_node('node-1', 'source', {'platform': 'zhihu', 'keyword': 'k', 'target_count': 99999})], [])
        client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'slow-console'})
        for _ in range(200):
            if app_module.execution_state['logs']:
                break
            time.sleep(0.05)
        before = list(client.get('/api/workflow/status').get_json()['logs'])
        client.post('/api/workflow/stop')
        assert _wait(app_module)
        after = client.get('/api/workflow/status').get_json()['logs']
        assert after, 'stopping must not erase the console the user was reading'
        assert before and after[: len(before)] == before, 'the lines already earned must survive in order'
        assert app_module.execution_state['total_nodes'] > 0, 'the summary must still know the run had nodes'

    def test_kill_protects_the_main_thread_and_answers_honestly(self, client):
        import threading

        main_ident = threading.main_thread().ident
        resp = client.post('/api/workflow/processes/kill', json={'ident': main_ident})
        assert resp.status_code == 403, 'MainThread must never be killable'

        resp = client.post('/api/workflow/processes/kill', json={'ident': 1234567890})
        assert resp.status_code == 404

        resp = client.post('/api/workflow/processes/kill', json={})
        assert resp.status_code == 400

    def test_kill_terminates_a_chosen_worker_thread(self, client):
        import threading

        started_evt = threading.Event()

        def _idle():
            # The kill raises SystemExit asynchronously — it lands at the next
            # bytecode boundary. A thread parked in one long C-level sleep()
            # cannot be interrupted, so the worker ticks instead. Catching the
            # SystemExit is what a well-behaved worker does: the thread exits
            # cleanly (and pytest is not polluted by an "unhandled" warning).
            started_evt.set()
            try:
                for _ in range(3000):
                    time.sleep(0.01)
            except SystemExit:
                return

        t = threading.Thread(target=_idle, name='disposable-worker', daemon=True)
        t.start()
        assert started_evt.wait(5)
        resp = client.post('/api/workflow/processes/kill', json={'ident': t.ident})
        assert resp.status_code == 200 and resp.get_json()['ok'] is True
        t.join(timeout=5)
        assert not t.is_alive(), 'the killed thread must actually die'
