"""A scheduled canvas that carries an LLM ANALYSIS step must be refused like a process one.

``workflow_needs_llm`` used to inspect only ``process`` nodes, so a canvas whose ``analysis`` node
carried ``topic_label``/``cluster_label``/``cluster_review`` passed the save-time and fire-time
verdict, crawled everything, and then failed at the analysis node. The verdict is ONE rule asked
twice (panel save and clock fire), both through ``scheduled_canvas``.
"""

import pytest

from engine import run_schedule
from engine.plan import workflow_needs_llm
from i18n import t
from services.workflows.manager import WorkflowManager

pytestmark = pytest.mark.unit

NAME_NODE = {'id': 'n1', 'type': 'name', 'params': {'workflow_name': '日常'}}


def _analysis(op):
    return {'id': 'n2', 'type': 'analysis', 'params': {'steps': [{'op': op}]}}


class TestWorkflowNeedsLlm:
    def test_an_analysis_node_with_an_llm_step_needs_a_model(self):
        for op in ('topic_label', 'cluster_label', 'cluster_review'):
            assert workflow_needs_llm({'nodes': [_analysis(op)]}) is True, op

    def test_an_analysis_node_with_a_non_llm_step_does_not(self):
        assert workflow_needs_llm({'nodes': [_analysis('topic_map')]}) is False

    def test_a_flat_llm_operation_on_an_analysis_node_needs_a_model(self):
        node = {'id': 'n2', 'type': 'analysis', 'params': {'operation': 'topic_label'}}
        assert workflow_needs_llm({'nodes': [node]}) is True

    def test_a_disabled_analysis_node_is_not_on_the_canvas(self):
        node = _analysis('topic_label')
        node['params']['enabled'] = False
        assert workflow_needs_llm({'nodes': [node]}) is False


class TestScheduledCanvasVerdict:
    def test_a_canvas_with_an_llm_analysis_step_is_refused(self, tmp_path, monkeypatch):
        manager = WorkflowManager(str(tmp_path / 'workflows'))
        monkeypatch.setattr(run_schedule, 'get_workflow_manager', lambda: manager)
        name = '要模型的画布'
        manager.save(name, {'nodes': [NAME_NODE, _analysis('topic_label')], 'connections': []})

        answer = run_schedule.scheduled_canvas(name)

        assert answer['workflow'] is None
        assert answer['error'] == t('sched.canvasNeedsModel', name=name)

    def test_a_canvas_with_a_non_llm_analysis_step_is_runnable(self, tmp_path, monkeypatch):
        manager = WorkflowManager(str(tmp_path / 'workflows'))
        monkeypatch.setattr(run_schedule, 'get_workflow_manager', lambda: manager)
        name = '纯采集画布'
        manager.save(name, {'nodes': [NAME_NODE, _analysis('topic_map')], 'connections': []})

        answer = run_schedule.scheduled_canvas(name)

        assert answer['error'] == ''
        assert answer['workflow'] is not None
