"""The run loop's after-run data check: one console line per finding, and nothing else.

``_postcheck_node`` is the wiring between a capability's optional ``postcheck`` hook and the
console. The node's rows are already produced and stored when it runs, so a finding is advisory —
it prints a line and never touches the status. A broken hook is its own named line, never an
exception into the run loop.
"""

from types import SimpleNamespace

import pytest

from engine import run as run_module

pytestmark = pytest.mark.unit


def _manifest(postcheck='fake.postcheck:check'):
    return SimpleNamespace(postcheck=postcheck)


class TestTheConsoleLine:
    def test_one_line_per_finding(self, monkeypatch):
        monkeypatch.setattr('capabilities_kernel.registry.manifest_for_node', lambda _type: _manifest())
        monkeypatch.setattr(
            'services.validation.engine.postcheck_problems',
            lambda *_args: [{'message_key': 'engine.empty_output', 'context': {'rows': 2, 'op': 'topic_map'}}],
        )
        lines = []
        monkeypatch.setattr(run_module, 'add_log', lambda line, **_kwargs: lines.append(line))
        run_module._postcheck_node({'id': 'a', 'type': 'analysis'}, [], [{'x': 1}, {'x': 2}], '分析 #a', 0)
        assert len(lines) == 1
        assert '分析 #a' in lines[0]
        assert 'topic_map' in lines[0]

    def test_a_manifest_without_a_hook_logs_nothing(self, monkeypatch):
        monkeypatch.setattr('capabilities_kernel.registry.manifest_for_node', lambda _type: _manifest(''))
        lines = []
        monkeypatch.setattr(run_module, 'add_log', lambda line, **_kwargs: lines.append(line))
        run_module._postcheck_node({'id': 'a', 'type': 'analysis'}, [], [], '分析 #a', 0)
        assert lines == []

    def test_an_unknown_type_is_not_a_crash(self, monkeypatch):
        monkeypatch.setattr('capabilities_kernel.registry.manifest_for_node', lambda _type: None)
        run_module._postcheck_node({'id': 'x', 'type': 'moonbase'}, [], [], 'x', 0)

    def test_a_non_list_result_is_treated_as_no_rows(self, monkeypatch):
        """A chart/compile node answers a dict; the hook gets an empty row list, not the dict."""
        seen = {}

        def problems(manifest, _node, rows, inputs):
            seen['rows'] = rows
            return []

        monkeypatch.setattr('capabilities_kernel.registry.manifest_for_node', lambda _type: _manifest())
        monkeypatch.setattr('services.validation.engine.postcheck_problems', problems)
        run_module._postcheck_node({'id': 'v', 'type': 'visualize'}, {'latex': 'x'}, [{'x': 1}], '图表 #v', 0)
        assert seen['rows'] == []
