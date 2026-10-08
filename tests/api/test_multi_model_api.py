"""The multi-model BERT comparison at the executor seam.

The feature lets an emotion/tendency/sentiment node tick several registered models at once
and return ONE tidy table (one row per text × model) that the comparison charts read. These
tests pin the two halves that are pure-Python (no torch):

* ``bert_model_list`` — the comma-list parsing, de-dup, SORT (so click order cannot change the
  fingerprint), full-width comma, and the fallback to the single ``bert_model``;
* ``_run_bert_compare`` / the ``_execute_process_node`` routing — ≥2 models switches to the long
  table tagged by 模型 and aligned by 原行, while a single model keeps the old in-place shape.

The transformers path itself is stubbed by replacing the analyzer class, so this stays a fast
test — the analyzer's own refusal (missing stack / unknown label) is covered in its test file.
"""

import pandas as pd
import pytest

pytestmark = pytest.mark.api


def _fake_analyzer(label_col, score_col, verdict):
    class FakeAnalyzer:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def analyze_dataframe(self, df, text_column='', ctx=None):
            df[label_col] = verdict
            df[score_col] = 0.9
            return df

    return FakeAnalyzer


class TestBertModelList:
    def test_dedupes_and_sorts(self, app_module):
        assert app_module.bert_model_list({'bert_models': 'm2, m1 , m1'}) == ['m1', 'm2']

    def test_full_width_comma_splits_like_the_backend(self, app_module):
        assert app_module.bert_model_list({'bert_models': 'm1，，m2'}) == ['m1', 'm2']

    def test_single_entry_is_not_reordered_into_a_list_of_two(self, app_module):
        assert app_module.bert_model_list({'bert_models': 'solo'}) == ['solo']

    def test_empty_list_falls_back_to_the_single_field(self, app_module):
        assert app_module.bert_model_list({'bert_model': 'only'}) == ['only']

    def test_the_list_wins_over_the_single_field(self, app_module):
        assert app_module.bert_model_list({'bert_model': 'ignored', 'bert_models': 'b,a'}) == ['a', 'b']

    def test_nothing_set_is_empty(self, app_module):
        assert app_module.bert_model_list({}) == []


class TestRegistryName:
    def test_known_path_returns_its_friendly_name(self, app_module, monkeypatch):
        monkeypatch.setattr(app_module, '_model_registry', lambda: [{'name': '网暴模型', 'path': 'a/m'}])
        assert app_module._registry_name('a/m') == '网暴模型'

    def test_unknown_path_falls_back_to_its_folder_name(self, app_module, monkeypatch):
        monkeypatch.setattr(app_module, '_model_registry', lambda: [])
        assert app_module._registry_name('x/y/z') == 'z'


class TestRunBertCompare:
    def test_two_models_widen_to_a_tidy_table(self, app_module, monkeypatch):
        monkeypatch.setattr(
            app_module,
            '_model_registry',
            lambda: [{'name': 'M1', 'path': 'a/m1'}, {'name': 'M2', 'path': 'a/m2'}],
        )
        monkeypatch.setattr(app_module, 'EmotionAnalyzer', _fake_analyzer('emotion', 'confidence', 'Joy'))
        df = pd.DataFrame({'正文': ['x', 'y']})
        records = app_module._run_bert_compare(
            'emotion', {'bert_models': 'a/m2,a/m1', 'mode': 'bert', 'batch_size': 4}, df, '正文', None
        )
        assert len(records) == 4, '2 rows × 2 models'
        assert {r['模型'] for r in records} == {'M1', 'M2'}
        assert 'emotion' in records[0] and 'confidence' in records[0] and '原行' in records[0]
        # 原行 aligns the same text across models: each model covers both row ids.
        for name in ('M1', 'M2'):
            assert sorted(r['原行'] for r in records if r['模型'] == name) == [0, 1]

    def test_a_single_model_is_refused_not_silently_long(self, app_module, monkeypatch):
        # _run_bert_compare is only ever reached with ≥2; if called with one it must refuse, not
        # hand back a tidy table the caller did not ask for.
        monkeypatch.setattr(app_module, 'EmotionAnalyzer', _fake_analyzer('emotion', 'confidence', 'Joy'))
        df = pd.DataFrame({'正文': ['x']})
        with pytest.raises(ValueError, match='emotion'):  # needle is the op, not a pasted sentence (language-neutral)
            app_module._run_bert_compare('emotion', {'bert_models': 'a/m1', 'mode': 'bert'}, df, '正文', None)


class TestProcessNodeRouting:
    def test_emotion_two_models_routes_to_tidy(self, app_module, monkeypatch):
        monkeypatch.setattr(
            app_module, '_model_registry', lambda: [{'name': 'M1', 'path': 'a/m1'}, {'name': 'M2', 'path': 'a/m2'}]
        )
        monkeypatch.setattr(app_module, 'EmotionAnalyzer', _fake_analyzer('emotion', 'confidence', 'Joy'))
        node = {'operation': 'emotion', 'params': {'mode': 'bert', 'bert_models': 'a/m1,a/m2', 'batch_size': 4}}
        out = app_module._execute_process_node(node, [{'正文': 'x'}, {'正文': 'y'}])
        assert any('模型' in row for row in out), 'the multi-model branch added the 模型 column'
        assert len(out) == 4

    def test_sentiment_single_model_keeps_the_in_place_shape(self, app_module, monkeypatch):
        # One model via the single bert_model field must NOT go long: no 模型/原行, just the op's
        # own columns — every canvas written before multi-model keeps its exact output shape.
        monkeypatch.setattr(app_module, 'SentimentAnalyzer', _fake_analyzer('sentiment', 'score', '正面'))
        node = {'operation': 'sentiment', 'params': {'mode': 'bert', 'bert_model': 'a/m1', 'batch_size': 4}}
        out = app_module._execute_process_node(node, [{'正文': 'x'}, {'正文': 'y'}])
        assert len(out) == 2
        assert all('模型' not in row and '原行' not in row for row in out), 'single model stayed wide'

    def test_tendency_two_models_routes_to_tidy(self, app_module, monkeypatch):
        monkeypatch.setattr(
            app_module, '_model_registry', lambda: [{'name': 'T1', 'path': 'a/t1'}, {'name': 'T2', 'path': 'a/t2'}]
        )
        monkeypatch.setattr(app_module, 'TendencyAnalyzer', _fake_analyzer('tendency', 'tendency_confidence', 'Praise'))
        node = {'operation': 'tendency', 'params': {'mode': 'bert', 'bert_models': 'a/t1,a/t2', 'batch_size': 4}}
        out = app_module._execute_process_node(node, [{'正文': 'x'}])
        assert len(out) == 2 and all('模型' in row for row in out)
