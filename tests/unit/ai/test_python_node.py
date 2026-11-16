"""The Python node and the cost-bounded dataset reads, without a browser or a real script run."""

import pytest

pytestmark = pytest.mark.unit


def _call(rows=None):
    from nodes.context import NodeCall

    return NodeCall(
        headless=True,
        current_input=rows or [],
        run_ctx={'cancel_event': None},
        upstream=None,
        ctx={'run_id': 'r1'},
        platform_of=None,
        label_of=None,
    )


def test_the_python_node_runs_a_saved_script_and_returns_its_rows(monkeypatch):
    from nodes.executors import python_node

    from services import python_runtime, python_scripts

    monkeypatch.setattr(python_scripts, 'find_script', lambda ref: {'id': ref, 'name': 'demo', 'code': 'pass'})
    monkeypatch.setattr(
        python_runtime,
        'run_script',
        lambda script, rows, args, **kwargs: {
            'rows': [{'a': 1}],
            'stdout': '',
            'stderr': '',
            'duration_ms': 3,
            'interpreter': '3.11',
        },
    )
    node = {'id': 'n1', 'type': 'python', 'params': {'script_id': 'demo', 'args': '{"x": 1}'}}
    assert python_node.run(node, _call([{'raw': 'x'}])) == [{'a': 1}]


def test_a_missing_script_is_refused_by_name(monkeypatch):
    from nodes.executors import python_node

    from services import python_scripts

    monkeypatch.setattr(python_scripts, 'find_script', lambda ref: None)
    node = {'id': 'n1', 'type': 'python', 'params': {'script_id': 'missing'}}
    with pytest.raises(RuntimeError) as refusal:
        python_node.run(node, _call())
    assert 'missing' in str(refusal.value)


def test_a_cloud_host_refuses_the_python_node(monkeypatch):
    from core.config import Config
    from nodes.executors import python_node

    monkeypatch.setattr(Config, 'CLOUD_MODE', True)
    node = {'id': 'n1', 'type': 'python', 'params': {'script_id': 'demo'}}
    with pytest.raises(RuntimeError):
        python_node.run(node, _call())


def test_the_node_reads_the_runs_own_cancel_event(monkeypatch):
    """停止 lives on ``execution_state``; the engine passes no ``run_ctx`` to an executor."""
    from nodes.executors import python_node
    from runtime.state import execution_state

    from services import python_runtime, python_scripts

    monkeypatch.setattr(python_scripts, 'find_script', lambda ref: {'id': ref, 'name': 'demo', 'code': 'pass'})
    seen = {}

    def run_script(*_args, **kwargs):
        seen.update(kwargs)
        return {'rows': [], 'stdout': '', 'stderr': '', 'duration_ms': 1, 'interpreter': '3.11'}

    monkeypatch.setattr(python_runtime, 'run_script', run_script)
    marker = object()
    monkeypatch.setitem(execution_state, 'cancel_event', marker)
    node = {'id': 'n1', 'type': 'python', 'params': {'script_id': 'demo'}}
    python_node.run(node, _call())
    assert seen.get('cancel_event') is marker


def test_a_noisy_script_finishes_instead_of_being_reported_as_a_timeout(monkeypatch):
    """A child that fills the pipe blocks in ``write``; the parent must drain it, not poll it."""
    import os

    from core.config import Config

    from services import python_runtime

    monkeypatch.setattr(Config, 'CLOUD_MODE', False)
    monkeypatch.setattr(python_runtime, 'get_setting', lambda key: True if key == 'ai_allow_python' else '')
    code = (
        'import os\n'
        'with open(os.environ["CIXI_OUTPUT"], "w", encoding="utf-8") as out:\n'
        '    out.write(\'{"a": 1}\\n\')\n'
        'for _ in range(6000):\n'
        '    print("x" * 200)\n'
    )
    result = python_runtime.run_code(code, [{'row': 1}], timeout=30)
    assert result['rows'] == [{'a': 1}]
    runs = os.path.join(python_runtime.workspace(), 'runs')
    assert os.listdir(runs) == [], 'a finished run left its temp files behind'


def test_stop_kills_the_script_instead_of_waiting_out_its_timeout(monkeypatch):
    import threading
    import time

    from ai.errors import AIError
    from core.config import Config

    from services import python_runtime

    monkeypatch.setattr(Config, 'CLOUD_MODE', False)
    monkeypatch.setattr(python_runtime, 'get_setting', lambda key: True if key == 'ai_allow_python' else '')
    cancel = threading.Event()
    timer = threading.Timer(0.3, cancel.set)
    timer.start()
    try:
        started = time.monotonic()
        with pytest.raises(AIError) as refusal:
            python_runtime.run_code('import time\ntime.sleep(30)\n', [], timeout=25, cancel_event=cancel)
    finally:
        timer.cancel()
    assert refusal.value.key == 'ai.cancelled'
    assert time.monotonic() - started < 10, '停止 waited for the script instead of killing it'


def test_max_rows_is_reported_not_silently_applied(monkeypatch):
    from core.config import Config

    from services import python_runtime

    monkeypatch.setattr(Config, 'CLOUD_MODE', False)
    monkeypatch.setattr(python_runtime, 'get_setting', lambda key: True if key == 'ai_allow_python' else '')
    code = (
        'import os\n'
        'with open(os.environ["CIXI_OUTPUT"], "w", encoding="utf-8") as out:\n'
        '    for i in range(5):\n'
        '        out.write(\'{"a": %d}\\n\' % i)\n'
    )
    result = python_runtime.run_code(code, [], max_rows=2)
    assert [row['a'] for row in result['rows']] == [0, 1]
    assert result['truncated'] is True and result['max_rows'] == 2
    assert result['wrote_output'] is True


def test_a_script_that_writes_no_output_is_named_not_an_empty_table(monkeypatch):
    from nodes.executors import python_node

    from services import python_runtime, python_scripts

    monkeypatch.setattr(python_scripts, 'find_script', lambda ref: {'id': ref, 'name': 'demo', 'code': 'pass'})
    monkeypatch.setattr(
        python_runtime,
        'run_script',
        lambda *args, **kwargs: {
            'rows': [],
            'stdout': '',
            'stderr': '',
            'duration_ms': 1,
            'interpreter': '3.11',
            'wrote_output': False,
            'truncated': False,
            'max_rows': 100,
        },
    )
    node = {'id': 'n1', 'type': 'python', 'params': {'script_id': 'demo'}}
    with pytest.raises(RuntimeError) as refusal:
        python_node.run(node, _call())
    assert 'CIXI_OUTPUT' in str(refusal.value)


def test_the_node_prints_a_truncated_output(monkeypatch):
    from nodes.executors import python_node

    from services import python_runtime, python_scripts

    logs = []
    monkeypatch.setattr(python_node, 'add_log', lambda msg, **kwargs: logs.append(msg))
    monkeypatch.setattr(python_scripts, 'find_script', lambda ref: {'id': ref, 'name': 'demo', 'code': 'pass'})
    monkeypatch.setattr(
        python_runtime,
        'run_script',
        lambda *args, **kwargs: {
            'rows': [{'a': 1}],
            'stdout': '',
            'stderr': '',
            'duration_ms': 1,
            'interpreter': '3.11',
            'wrote_output': True,
            'truncated': True,
            'max_rows': 1,
        },
    )
    node = {'id': 'n1', 'type': 'python', 'params': {'script_id': 'demo'}}
    assert python_node.run(node, _call()) == [{'a': 1}]
    assert len(logs) == 2, logs
    assert '1' in logs[1]


def test_python_candidates_are_read_for_the_target_os(tmp_path, monkeypatch):
    from core import machine

    (tmp_path / 'python3').write_bytes(b'')
    monkeypatch.chdir(tmp_path)
    # The PATH is split with the TARGET's separator and joined with its shape; `.` keeps the path
    # free of a drive colon (which a POSIX list would read as a separator).
    found = machine.python_candidates(env={'PATH': '.'}, system='linux')
    assert any(path.replace('\\', '/').endswith('python3') for path in found), found
    # The python.org launcher's default install puts only `py` on PATH; it must be probed.
    win = machine.python_candidates(env={'PATH': ''}, system='win32')
    assert 'py' in [name.lower() for name in win]


def test_dataset_peek_sends_a_few_capped_rows_not_the_table(monkeypatch):
    import pandas as pd
    from ai import tools

    frame = pd.DataFrame([{'正文': 'x' * 500, '平台': '知乎'} for _ in range(100)])
    monkeypatch.setattr(tools, '_dataset_frame', lambda dataset_id: frame)
    result = tools.tool_dataset_peek({'dataset_id': 'd1', 'rows': 3}, {})
    assert result['total_rows'] == 100
    assert result['shown_rows'] == 3
    assert result['rows'][0]['正文'].endswith('…')
    assert len(result['rows'][0]['正文']) <= 121
    assert [item['name'] for item in result['columns']] == ['正文', '平台']


def test_dataset_page_is_bounded_and_reports_more(monkeypatch):
    import pandas as pd
    from ai import tools

    frame = pd.DataFrame([{'a': index} for index in range(100)])
    monkeypatch.setattr(tools, '_dataset_frame', lambda dataset_id: frame)
    page = tools.tool_dataset_page({'dataset_id': 'd1', 'offset': 90, 'limit': 5}, {})
    assert [row['a'] for row in page['rows']] == [90, 91, 92, 93, 94]
    assert page['has_more'] is True
    assert page['next_offset'] == 95


def test_dataset_sample_honours_columns_and_offset_and_caps_cells(monkeypatch):
    import pandas as pd
    from ai import tools

    frame = pd.DataFrame([{'正文': 'x' * 500, 'b': index} for index in range(20)])
    monkeypatch.setattr(tools, '_dataset_frame', lambda dataset_id: frame)
    page = tools.tool_dataset_sample(
        {'dataset_id': 'd1', 'limit': '5 rows', 'offset': '2', 'columns': ['正文', 'b']}, {}
    )
    assert page['offset'] == 2
    assert [row['b'] for row in page['rows']] == [2, 3, 4, 5, 6]
    assert len(page['rows'][0]['正文']) <= 201, 'a whole post reached the model'
    assert page['columns'] == ['正文', 'b']
