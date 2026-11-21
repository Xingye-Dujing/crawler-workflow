"""The bulk-LLM tag setting routes only row-at-a-time short-answer nodes.

A small local model is enough to rewrite a row or pick a short label; topic naming and
qualitative coding still need the run's main model. The resolved tag is printed, so a run
can never claim it used the global model while the cache holds answers from the small one.
"""

import pytest
from runtime.state import execution_state

from services.analysis.process import is_bulk_llm_op

pytestmark = pytest.mark.unit


@pytest.fixture
def llm_run(monkeypatch):
    """A run whose settings answer the bulk tag and disable the AI trace seam."""
    import runtime.settings as runtime_settings

    from services.analysis import llm as llm_module

    monkeypatch.setitem(execution_state, 'run_id', 'run-tier')
    monkeypatch.setitem(
        execution_state,
        'llm',
        {'provider': 'ollama', 'model': 'qwen3.5:9b', 'ollama_host': 'http://localhost:11434'},
    )
    values = {'llm_bulk_model': 'qwen3.5:4b', 'ai_trace_tier': 'off'}
    # build_llm_run_ctx imports get_setting at CALL time so settings patches are honoured.
    monkeypatch.setattr(runtime_settings, 'get_setting', lambda key, default=None: values.get(key, default))
    logs = []
    monkeypatch.setattr(llm_module, 'add_log', logs.append)
    return llm_module, logs, values


def _node(op='clean', **params):
    return {'id': 'n1', 'params': {'operation': op, **params}}


class TestBulkOpRegistry:
    def test_row_short_answer_modes_are_bulk(self):
        assert is_bulk_llm_op('clean', {'mode': 'llm'})
        assert is_bulk_llm_op('sentiment', {'mode': 'llm'})
        assert is_bulk_llm_op('ner', {'mode': 'llm'})

    def test_traditional_modes_and_deep_ops_are_not_bulk(self):
        assert not is_bulk_llm_op('sentiment', {'mode': 'bert'})
        assert not is_bulk_llm_op('ner', {})  # the declared default is regex
        assert not is_bulk_llm_op('qualitative_code')
        assert not is_bulk_llm_op('topic_label')


class TestBulkModelResolution:
    def test_a_bulk_node_uses_the_small_tag_and_names_it(self, llm_run):
        module, logs, _values = llm_run
        ctx = module.build_llm_run_ctx(_node('clean', mode='llm'), 'clean')
        assert ctx['client'].model == 'qwen3.5:4b'
        assert any('qwen3.5:4b' in line for line in logs)

    def test_a_deep_node_keeps_the_run_model(self, llm_run):
        module, logs, _values = llm_run
        ctx = module.build_llm_run_ctx(_node('qualitative_code'), 'qualitative_code')
        assert ctx['client'].model == 'qwen3.5:9b'
        assert not logs

    def test_an_explicit_node_tag_beats_the_bulk_setting(self, llm_run):
        module, _logs, _values = llm_run
        ctx = module.build_llm_run_ctx(_node('clean', mode='llm', model='qwen3.5:2b'), 'clean')
        assert ctx['client'].model == 'qwen3.5:2b'

    def test_a_blank_bulk_setting_follows_the_global_model(self, llm_run):
        module, logs, values = llm_run
        values['llm_bulk_model'] = ''
        ctx = module.build_llm_run_ctx(_node('clean', mode='llm'), 'clean')
        assert ctx['client'].model == 'qwen3.5:9b'
        assert not logs

    def test_a_cloud_provider_never_receives_a_daemon_tag(self, llm_run, monkeypatch):
        module, _logs, _values = llm_run
        monkeypatch.setitem(execution_state, 'llm', {**execution_state['llm'], 'provider': 'deepseek'})
        ctx = module.build_llm_run_ctx(_node('clean', mode='llm'), 'clean')
        assert ctx['client'].model == 'qwen3.5:9b'
