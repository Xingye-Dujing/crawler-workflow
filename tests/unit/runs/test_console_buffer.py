"""The console line buffer behind ``/api/workflow/status`` (``runtime/state.py::_push_log``).

The browser reads the console by DELTA: it remembers how many lines it has seen and
asks for the tail, because the server keeps only the last ``LOG_KEEP`` lines of the
whole run. That makes the counter and the list one mechanism — if they move apart, or
if one ``add_log`` call pushes an entry the DOM renders as three rows, the console
freezes mid-run or skips lines, and the user reads a crawl that stopped talking.

Every real crawl passes ``LOG_KEEP``; nothing in the suite used to.

``app`` is reached through the ``app_module`` fixture and never imported here: the
isolation fixture has to move ``Config.DATA_DIR`` first, while a module-level import
runs at collection, before any fixture — the app module then binds its singleton
services to the user's real ``data/`` for the rest of the session.
"""

import ast
import copy
import logging
from pathlib import Path

import pytest
from runtime.state import reset_console_state

pytestmark = pytest.mark.unit

#: Every key the tests here touch, put back afterwards. The run-claim keys are in
#: the list because one of them asserts `reset_console_state` leaves `running`
#: alone — which is only safe to test if the test itself puts the flag back. The
#: suite's own `clean_globals` fixture now fails a test that leaks a busy flag, so
#: this fixture would otherwise be the thing that tripped it.
_STATE_KEYS = (
    'logs',
    '_log_total',
    '_wf_logs',
    '_wf_log_total',
    '_wf_names',
    'total_nodes',
    'completed_nodes',
    'skipped_nodes',
    'failed_nodes',
    'running',
    'thread',
    'workflow_name',
    'results',
    'outcome',
    'cookie_expired',
)


@pytest.fixture
def console(app_module):
    """An empty console, handed back afterwards (these buffers are process-wide)."""
    state = app_module.execution_state
    saved = {key: copy.deepcopy(state[key]) for key in _STATE_KEYS if key in state}
    reset_console_state()
    yield app_module, state
    state.update(saved)


@pytest.fixture
def sink(console):
    """The console, plus a durable-sink recorder, with the global put back afterwards.

    ``_log_sink`` is a module global, not a dict key, so the ``console`` fixture does not
    restore it; leaving a recorder installed would let it leak into the next test in the
    session (and into any real run another test drives). This fixture always clears it.
    """
    from runtime import state

    received = []

    def _record(parts, wf_idx, level):
        received.append((list(parts), wf_idx, level))

    app, buffer = console
    state.set_log_sink(_record)
    try:
        yield app, buffer, state, received
    finally:
        state.set_log_sink(None)


class TestDurableSink:
    """The write-through sink that backs the per-run durable console.

    It is a *pure side effect* of ``_push_log``: the live console and, above all, the
    page-refresh reattach read the in-memory buffers and their running totals, and those
    must not shift by a byte because a sink was installed. The tests below pin both halves
    — the sink gets what the buffers kept, and the buffers keep exactly what they would
    have kept with no sink at all.
    """

    def test_the_sink_receives_the_same_physical_lines_the_buffer_kept(self, sink):
        app, buffer, _state, received = sink
        app._push_log('第一行\n第二行\n\n   ')
        # Blank/whitespace lines are dropped identically for the sink and the buffer.
        assert received == [(['第一行', '第二行'], None, None)]
        assert buffer['logs'] == ['第一行', '第二行']

    def test_the_sink_is_told_the_level_and_the_workflow_index(self, sink):
        app, _buffer, _state, received = sink
        app.add_log('登录墙', wf_idx=2, level='error')
        parts, wf_idx, level = received[0]
        assert wf_idx == 2, 'a parallel run tab must be attributable'
        assert level == 'error', 'the viewer filters by level, so the handler verdict must travel'
        assert parts and parts[0].endswith('登录墙')

    def test_add_log_defaults_the_level_to_info(self, sink):
        app, _buffer, _state, received = sink
        app.add_log('普通一行')
        assert received[0][2] == 'info', 'an unclassified line is info, never None, so the filter always matches'

    def test_the_wf_index_defaults_from_the_thread_local(self, sink):
        app, _buffer, state, received = sink
        state._wf_local.idx = 5
        try:
            app._push_log('线程内的一行')
            assert received[0][1] == 5, 'the sink must route by the same thread-local the buffers use'
        finally:
            state._wf_local.idx = None

    def test_the_buffers_are_byte_identical_with_and_without_a_sink(self, sink):
        """The hard invariant behind "do not break my refresh-reattach".

        Replay the exact same pushes twice — once with the sink installed, once with it
        cleared — and every value the status endpoint ships must come out the same. If a
        sink ever altered a total or the tail, the browser's delta cursor would skip or
        repeat live console content after a reload.
        """
        app, buffer, state, _received = sink
        script = [
            ('抓取 三亚 完成', None, 'info'),
            ('节点执行失败：Message: boom\nsecond line', 0, 'error'),
            ('警告：慢', 1, 'warning'),
        ]

        def _replay():
            for msg, idx, level in script:
                app._push_log(f'[00:00:00] {msg}', idx, level)

        _replay()
        with_sink = copy.deepcopy({key: buffer[key] for key in ('logs', '_log_total', '_wf_logs', '_wf_log_total')})

        reset_console_state()
        state.set_log_sink(None)
        _replay()
        without_sink = {key: copy.deepcopy(buffer[key]) for key in with_sink}

        assert with_sink == without_sink, (
            'installing the durable sink changed a value the live console / refresh-reattach reads'
        )

    def test_a_raising_sink_leaves_the_totals_it_was_given_intact(self, sink):
        app, buffer, state, _received = sink

        def _boom(_parts, _idx, _level):
            raise RuntimeError('sink blew up')

        state.set_log_sink(_boom)
        with pytest.raises(RuntimeError):
            app._push_log('这一行', None, 'info')
        # The buffers were fully updated before the sink ran, so a failure there cannot
        # half-advance the cursor. (The real sink only appends to a list; the flush that
        # touches SQLite is buffered and guarded in app.)
        assert buffer['_log_total'] == 1
        assert buffer['logs'] == ['这一行']


class TestImportHygiene:
    def test_no_test_module_imports_app_at_module_scope(self):
        """A module-level ``import app`` defeats the suite's isolation.

        Collection runs before any fixture, so the app is built while
        ``Config.DATA_DIR`` still points at the repository: its singleton services go
        on writing into the user's real ``data/history.db`` for every later test, and
        the failure that finally notices looks like an unrelated path assertion in
        whichever test checks its paths next. This file was that bug.

        Only statements at the top of the module count — importing inside a test or a
        fixture is the correct form, and five modules already do exactly that.
        """
        tests_root = Path(__file__).resolve().parents[2]
        offenders = []
        for path in sorted(tests_root.rglob('*.py')):
            if path.name == 'conftest.py':
                continue
            for node in ast.parse(path.read_text(encoding='utf-8')).body:
                if not isinstance(node, (ast.Import, ast.ImportFrom)) or getattr(node, 'level', 0):
                    continue
                if any(alias.name == 'app' for alias in node.names):
                    offenders.append(path.relative_to(tests_root.parent).as_posix())
                    break
        assert offenders == [], 'import app inside a test or a fixture instead: ' + ', '.join(offenders)

    def test_the_scan_sees_the_shape_it_bans(self):
        """A guard that cannot fail is not a guard — and this one has a scope to get right."""
        banned = ast.parse('import app\nimport pytest\n')
        allowed = ast.parse('import pytest\n\n\ndef test_x(app_module):\n    import app as app_module\n')
        assert self._module_app_imports(banned)
        assert not self._module_app_imports(allowed)

    @staticmethod
    def _module_app_imports(tree) -> bool:
        return any(
            isinstance(node, (ast.Import, ast.ImportFrom))
            and not getattr(node, 'level', 0)
            and any(alias.name == 'app' for alias in node.names)
            for node in tree.body
        )


class TestConsoleReset:
    """``reset_console_state`` — the one way the console is emptied.

    Two callers need the same answer: a run start (so the new console does not open
    with the previous run's lines) and the test suite's own isolation fixture (so a
    test that drives an executor function directly — no HTTP request, no run start —
    cannot leave its narration behind for the next test to read). Inline copies at
    both ends is how 25 lines from one crawl-matrix test surfaced as a failure in a
    workflow API assertion three files later.
    """

    def test_every_line_and_counter_returns_to_its_between_runs_value(self, console):
        app, state = console
        app.add_log('共享的一行')
        app.add_log('属于某个工作流的一行', wf_idx=2)
        state['_wf_names'] = {2: '评论采集'}
        state.update({'total_nodes': 5, 'completed_nodes': 3, 'skipped_nodes': 1, 'failed_nodes': 1})

        reset_console_state()

        assert state['logs'] == []
        assert state['_log_total'] == 0
        assert state['_wf_logs'] == {}
        assert state['_wf_log_total'] == {}
        assert state['_wf_names'] == {}
        assert (
            state['total_nodes'],
            state['completed_nodes'],
            state['skipped_nodes'],
            state['failed_nodes'],
        ) == (0, 0, 0, 0)

    def test_the_cleared_buffer_is_a_new_list_not_the_old_one_emptied(self, console):
        """The run worker holds a reference while it appends, so clearing in place
        would rewrite what an in-flight reader already counted."""
        app, state = console
        app.add_log('上一轮的行')
        held = state['logs']
        reset_console_state()
        assert state['logs'] is not held
        assert len(held) == 1 and held[0].endswith('上一轮的行'), (
            'the list a reader is holding must not be mutated underneath it'
        )

    def test_the_reset_clears_the_console_and_nothing_about_the_run(self, console):
        """Ownership and identity are claimed elsewhere; a reset that wiped them
        would let a run lose its own thread mid-flight."""
        app, state = console
        state.update(
            {
                'running': True,
                'thread': 'a-worker',
                'workflow_name': '我的采集',
                'results': {'node-1': [{'标题': '甲'}]},
                'outcome': 'failed',
                'cookie_expired': True,
            }
        )
        app.add_log('一行')
        untouched = {key: state[key] for key in ('running', 'thread', 'workflow_name', 'results', 'outcome')}

        reset_console_state()

        assert state['logs'] == [], 'the console itself did go'
        for key, value in untouched.items():
            assert state[key] == value, f'reset_console_state reached into the run claim: {key}'
        assert state['cookie_expired'] is True

    def test_the_baseline_names_only_keys_the_state_actually_has(self, console):
        """A key renamed on the dict and not here would silently stop being reset —
        the stale value would then outlive every run in the session."""
        # Both the baseline factory and the dict it names now live in ``state`` (the
        # console subsystem moved out of ``app`` so the services/ executors can log
        # without a Flask import cycle). A function-scope import — the file's own
        # hygiene rule allows this, it only bans a module-level one.
        from runtime import state

        missing = [key for key in state._console_baseline() if key not in state.execution_state]
        assert missing == []

    def test_the_run_start_empties_the_console_in_exactly_one_place(self, console):
        """Neither module that starts a run may re-implement the reset.

        The scan covers ``app.py`` AND ``engine/run.py`` because the run start moved to the second
        one — the rule is about the code that opens a run, not about which file it sat in.
        """
        app = console[0]
        backend = Path(app.__file__).parent
        sources = {name: (backend / name).read_text(encoding='utf-8') for name in ('app.py', 'engine/run.py')}
        for name, source in sources.items():
            assert "execution_state['logs'] = []" not in source, (
                f'{name} reset its own copy of the buffer again; call reset_console_state() '
                'so the suite and the run start cannot drift'
            )

    def test_the_shared_buffer_keeps_the_tail_but_counts_every_line(self, console):
        app, state = console
        # ``LOG_KEEP`` is the buffer's own bound and lives in ``state`` with the writers; asking
        # ``app`` for it would make the test depend on which module happens to re-export it.
        from runtime.state import LOG_KEEP

        produced = LOG_KEEP + 50
        for i in range(produced):
            app.add_log(f'第 {i} 行')
        assert len(state['logs']) == LOG_KEEP, 'the buffer is bounded, or a long crawl grows it forever'
        # The total, not the list length, is what the browser's cursor advances by:
        # counting retained lines here would make it re-read the same tail forever.
        assert state['_log_total'] == produced
        assert state['logs'][-1].endswith(f'第 {produced - 1} 行')

    def test_a_workflow_buffer_is_trimmed_and_counted_the_same_way(self, console):
        app, state = console
        from runtime.state import LOG_KEEP

        produced = LOG_KEEP + 10
        for i in range(produced):
            app.add_log(f'甲 {i}', wf_idx=0)
        assert len(state['_wf_logs'][0]) == LOG_KEEP
        assert state['_wf_log_total'][0] == produced
        # The same line belongs to 「全部」 too, and losing that pairing is how a tab
        # ends up showing rows the shared view has already forgotten.
        assert state['_log_total'] == produced

    def test_a_line_goes_to_one_workflow_buffer_only(self, console):
        app, state = console
        app.add_log('甲的行', wf_idx=0)
        app.add_log('乙的行', wf_idx=1)
        assert [line for line in state['_wf_logs'][0] if line.strip().endswith('乙的行')] == []
        assert state['_wf_log_total'] == {0: 1, 1: 1}


class TestLineShape:
    def test_a_multi_line_payload_lands_as_one_entry_per_line(self, console):
        """A driver's ``Message: …`` block is one error spread over several lines.

        Kept as a single entry it counted 1 toward the cursor while the DOM rendered
        three rows (``.console-line`` is ``white-space: pre-wrap``), so the next poll
        re-showed or dropped console content, and the 200-line tail could be spent by
        one traceback.
        """
        app, state = console
        app.add_log('节点执行失败：Message: session not created\n\nchrome! [0x1]\nntdll!')
        assert len(state['logs']) == 3, state['logs']
        assert state['_log_total'] == 3, 'the counter moves by lines, not by add_log calls'
        assert not any('\n' in line for line in state['logs'])
        assert all(line.strip() for line in state['logs']), 'blank rows came back through this path'

    def test_a_blank_message_produces_no_console_row(self, console):
        app, state = console
        app.add_log('')
        app.add_log('   \n  ')
        app.add_log(None)
        assert state['logs'] == []
        assert state['_log_total'] == 0


class TestTransportNoiseFilter:
    """The console is filtered by LOGGER NAME, not by message text (#186).

    Killing a chromedriver mid-command makes selenium's own urllib3 client retry the
    dead port and discard the pooled connection, so a Stop sprayed red lines that
    described no real failure. Those come from the ``urllib3`` logger; a real failure
    comes from the crawler/executor loggers and must survive. Pinning the boundary by
    name means a re-worded urllib3 message can never smuggle itself back in.
    """

    @staticmethod
    def _emit(app, name, msg):
        app._log_handler.emit(logging.LogRecord(name, logging.WARNING, 'x.py', 1, msg, None, None))

    def test_urllib3_retry_and_pool_noise_never_reach_the_console(self, console):
        app, state = console
        self._emit(
            app,
            'urllib3.connectionpool',
            'Retrying (Retry(total=2, connect=None)) after connection broken by '
            "'NewConnectionError(\"HTTPConnection(host='localhost', port=12332)\")': /session/abc",
        )
        self._emit(app, 'urllib3', 'Connection pool is full, discarding connection: localhost. Connection pool size: 1')
        assert state['logs'] == []
        assert state['_log_total'] == 0, 'the filtered lines must not even advance the cursor'

    def test_werkzeug_request_log_stays_out_of_the_console(self, console):
        app, state = console
        self._emit(app, 'werkzeug', 'GET /api/workflow/status HTTP/1.1" 200')
        assert state['logs'] == []

    def test_a_real_crawler_failure_still_reaches_the_console(self, console):
        app, state = console
        self._emit(app, 'crawlers.platforms.douyin.crawler', '节点 3 执行失败：连接被拒')
        assert len(state['logs']) == 1
        assert '执行失败' in state['logs'][0]
