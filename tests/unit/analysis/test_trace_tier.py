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
        (_node('topic_model', method='embedding'), 'topic_model', 'ollama', 'traditional'),
        (_node('topic_model', method='lda'), 'topic_model', 'ollama', 'off'),
        (_node('topic_map', method='lda'), 'topic_map', 'ollama', 'off'),
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


def test_bert_degrade_is_reflected_in_the_trace_identity(monkeypatch):
    import nodes.executors.process as process

    # The executor degrades an unrunnable BERT to SnowNLP; the chip must follow, not keep claiming
    # a BERT model that never answered.
    monkeypatch.setattr(process, '_bert_runnable', lambda _path: (False, 'no torch'))
    prov, name = tt.resolve_model_identity(_node('sentiment', mode='bert'), 'sentiment', 'ollama')
    assert prov == 'SnowNLP'
    assert name == ''


def test_non_bert_mode_never_claims_a_stale_bert_model():
    prov, name = tt.resolve_model_identity(
        _node('sentiment', mode='snownlp', bert_model='/models/rbt3'), 'sentiment', 'ollama'
    )
    assert prov == 'SnowNLP'
    assert name == '', 'a stale bert_model field must not be named for a SnowNLP run'


def test_embedding_topic_identity_names_the_encoder(monkeypatch):
    import services.analysis.topic_kernels as kernels

    monkeypatch.setattr(kernels, '_resolve_topic_method', lambda _method: 'embedding')
    node = _node('topic_model', method='embedding')
    assert tt.should_trace(node, 'topic_model', 'ollama', 'traditional')
    prov, name = tt.resolve_model_identity(node, 'topic_model', 'ollama')
    assert prov == 'local model'
    assert 'bge' in name.lower()


def test_cloud_provider_uses_the_run_model_not_a_node_model():
    prov, name = tt.resolve_model_identity(
        _node('sentiment', mode='llm', model='qwen:stale'), 'sentiment', 'deepseek', run_model='deepseek-chat'
    )
    assert prov == 'DeepSeek'
    assert name == 'deepseek-chat'
    ollama_prov, ollama_name = tt.resolve_model_identity(
        _node('sentiment', mode='llm', model='qwen:node'), 'sentiment', 'ollama', run_model='qwen:global'
    )
    assert ollama_prov == 'Ollama'
    assert ollama_name == 'qwen:node'
