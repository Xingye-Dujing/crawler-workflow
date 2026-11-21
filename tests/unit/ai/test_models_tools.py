"""The local-model tools are read-only and bounded: a wrong id refuses, a big table is sampled."""

import types

import pytest
from ai import skills, tools
from ai.errors import AIError

pytestmark = pytest.mark.unit


@pytest.fixture
def runnable_model(monkeypatch):
    """Bypass the per-machine availability gate: these tests pin the tool's own contract.

    Whether torch/transformers are installed decides if the REAL model can run, and CI omits them.
    The unknown-id test below deliberately keeps the real gate; these tests are about columns and
    row bounds, so they name a deterministic stand-in instead of depending on the developer's box.
    """
    from services.models import catalog

    fake = types.SimpleNamespace(
        id='sentiment_weibosenti_bin',
        name='Weibo sentiment',
        family='text_classification',
        task='sentiment',
        path='/models/weibo',
    )
    monkeypatch.setattr(catalog, 'runnable_or_refuse', lambda model_id: fake)
    return fake


def test_catalog_tool_lists_models_and_filters_by_task():
    answer = tools.tool_models_catalog({}, {})
    assert answer['count'] >= 4
    assert any(row['id'] == 'sentiment_weibosenti_bin' for row in answer['models'])
    assert 'cuda' in answer['runtime']
    narrow = tools.tool_models_catalog({'task': 'embedding'}, {})
    assert narrow['count'] >= 0
    assert all(row['family'] == 'embedding' or row['task'] == 'embedding' for row in narrow['models'])


def test_infer_refuses_an_unknown_model_by_name():
    with pytest.raises(AIError) as caught:
        tools.tool_model_infer({'model_id': 'no-such-model', 'column': '正文'}, {})
    assert 'no-such-model' in str(caught.value)


def test_infer_refuses_a_missing_column(runnable_model):
    with pytest.raises(AIError, match='column'):
        tools.tool_model_infer(
            {
                'model_id': 'sentiment_weibosenti_bin',
                'column': 'does-not-exist',
                'rows': [{'text': '好'}],
            },
            {},
        )


def test_infer_is_bounded_and_reports_truncation(monkeypatch, runnable_model):
    seen = {}

    def fake(manifest, texts, args):
        seen['n'] = len(texts)
        return {'distribution': {'positive': len(texts)}, 'labels': [], 'sample': []}

    monkeypatch.setattr(tools, '_infer_text_classifier', fake)
    rows = [{'正文': str(index)} for index in range(250)]
    answer = tools.tool_model_infer(
        {'model_id': 'sentiment_weibosenti_bin', 'column': '正文', 'rows': rows, 'limit': 200}, {}
    )
    assert seen['n'] == 200, 'the hard cap is 200 rows, never the whole dataset'
    assert answer['total_rows'] == 250 and answer['truncated'] is True
    assert answer['model'] and answer['rows'] == 200


def test_rerank_tool_is_bounded_and_uses_the_small_cross_encoder(monkeypatch):
    seen = {}

    def fake(query, candidates, model_name, top_k):
        seen['n'] = len(candidates)
        seen['model'] = model_name
        return [{'rank': 1, 'text': candidates[0], 'score': 0.9}]

    monkeypatch.setattr('analyzers.backends.reranker.rerank', fake)
    answer = tools.tool_model_rerank(
        {'query': '正面评价', 'candidates': [f'候选{i}' for i in range(60)], 'model': 'BAAI/bge-reranker-base'}, {}
    )
    assert seen['n'] == 50, 'the hard cap is 50 candidates'
    assert seen['model'] == 'BAAI/bge-reranker-base'
    assert answer['count'] == 1


def test_new_skills_are_builtin_local_and_name_registered_tools():
    for skill_id in ('models', 'model_tuning'):
        skill = skills.BUILTIN[skill_id]
        assert skill.local_only is True
        assert skill.name_key.startswith('ai.skill.')
        assert skill.tools
        for tool in skill.tools:
            assert tool in tools.TOOLS, f'{skill_id} names an unregistered tool {tool}'


def test_prompt_block_names_the_registered_models():
    from ai import vocabulary

    block = vocabulary.prompt_block()
    assert '本地模型' in block
    assert 'sentiment_weibosenti_bin' in block
