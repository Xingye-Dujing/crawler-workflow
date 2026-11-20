"""The ai_trace_tier setting gates which model calls open an AI-workspace conversation.

A tier includes every higher tier. The registry in trace_tier is shared by the backend gate and the
browser's live-confirm gate, so the two cannot disagree about which node should raise the dock.
"""

import pytest

from services.analysis import trace_tier as tt

pytestmark = pytest.mark.unit


def _node(op, **params):
    return {'id': 'n1', 'type': 'process', 'params': {'operation': op, **params}}


def test_tier_order_and_unknown_reads_as_off():
    assert tt.tier_rank('off') < tt.tier_rank('traditional') < tt.tier_rank('llm') < tt.tier_rank('api')
    assert tt.tier_rank('') == 0
    assert tt.tier_rank('nonsense') == 0


@pytest.mark.parametrize(
    'node,op,provider,expected',
    [
        (_node('sentiment', mode='bert'), 'sentiment', 'ollama', 'traditional'),
        (_node('sentiment', mode='snownlp'), 'sentiment', 'ollama', 'traditional'),
        (_node('sentiment', mode='llm'), 'sentiment', 'ollama', 'llm'),
        (_node('sentiment', mode='llm'), 'sentiment', 'deepseek', 'api'),
        (_node('zero_shot'), 'zero_shot', 'ollama', 'traditional'),
        (_node('semantic_dedupe'), 'semantic_dedupe', 'ollama', 'traditional'),
        (_node('qualitative_code'), 'qualitative_code', 'ollama', 'llm'),
        (_node('content_analysis', mode='dual'), 'content_analysis', 'ollama', 'llm'),
        (_node('content_analysis', mode='report'), 'content_analysis', 'ollama', 'off'),
        (_node('keyword'), 'keyword', 'ollama', 'off'),
    ],
)
def test_node_tier(node, op, provider, expected):
    assert tt.node_tier(node, op, provider) == expected


def test_threshold_includes_higher_tiers_only():
    bert = _node('sentiment', mode='bert')
    llm = _node('sentiment', mode='llm')
    # off traces nothing
    assert not tt.should_trace(bert, 'sentiment', 'ollama', 'off')
    # traditional traces everything with a model
    assert tt.should_trace(bert, 'sentiment', 'ollama', 'traditional')
    assert tt.should_trace(llm, 'sentiment', 'ollama', 'traditional')
    # llm excludes traditional
    assert not tt.should_trace(bert, 'sentiment', 'ollama', 'llm')
    assert tt.should_trace(llm, 'sentiment', 'ollama', 'llm')
    # api traces only cloud calls
    assert not tt.should_trace(llm, 'sentiment', 'ollama', 'api')
    assert tt.should_trace(llm, 'sentiment', 'deepseek', 'api')


def test_traditional_identity_names_the_local_model():
    prov, name = tt.resolve_model_identity(_node('zero_shot'), 'zero_shot', 'ollama')
    assert 'NLI' in name or 'mDeBERTa' in name or prov == 'local model'
    prov2, name2 = tt.resolve_model_identity(_node('semantic_dedupe'), 'semantic_dedupe', 'ollama')
    assert 'bge' in name2
    assert prov2 == 'local model'
