"""The console line buffer behind ``/api/workflow/status`` (``app.py::_push_log``).

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
from pathlib import Path

import pytest

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
    app_module.reset_console_state()
    yield app_module, state
    state.update(saved)


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
        tests_root = Path(__file__).resolve().parents[1]
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

        app.reset_console_state()

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
        app.reset_console_state()
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

        app.reset_console_state()

        assert state['logs'] == [], 'the console itself did go'
        for key, value in untouched.items():
            assert state[key] == value, f'reset_console_state reached into the run claim: {key}'
        assert state['cookie_expired'] is True

    def test_the_baseline_names_only_keys_the_state_actually_has(self, console):
        """A key renamed on the dict and not here would silently stop being reset —
        the stale value would then outlive every run in the session."""
        app = console[0]
        missing = [key for key in app._console_baseline() if key not in app.execution_state]
        assert missing == []

    def test_app_py_empties_the_console_in_exactly_one_place(self, console):
        app = console[0]
        source = Path(app.__file__).read_text(encoding='utf-8')
        assert "execution_state['logs'] = []" not in source, (
            'the run start reset its own copy of the buffer again; call reset_console_state() '
            'so the suite and the run start cannot drift'
        )

    def test_the_shared_buffer_keeps_the_tail_but_counts_every_line(self, console):
        app, state = console
        produced = app.LOG_KEEP + 50
        for i in range(produced):
            app.add_log(f'第 {i} 行')
        assert len(state['logs']) == app.LOG_KEEP, 'the buffer is bounded, or a long crawl grows it forever'
        # The total, not the list length, is what the browser's cursor advances by:
        # counting retained lines here would make it re-read the same tail forever.
        assert state['_log_total'] == produced
        assert state['logs'][-1].endswith(f'第 {produced - 1} 行')

    def test_a_workflow_buffer_is_trimmed_and_counted_the_same_way(self, console):
        app, state = console
        produced = app.LOG_KEEP + 10
        for i in range(produced):
            app.add_log(f'甲 {i}', wf_idx=0)
        assert len(state['_wf_logs'][0]) == app.LOG_KEEP
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
