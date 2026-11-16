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
