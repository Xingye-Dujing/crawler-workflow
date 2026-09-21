"""Tests for analyzers/ml_base.py — the scikit-learn fallback classifier.

This is the "no LLM available" path, and it is the only analyzer that touches
disk: a trained pipeline is saved so a later run can predict without Ollama.
Two properties are worth pinning:

- a *missing* model must degrade to a neutral answer, never break a run,
- the training guards have to fire before sklearn does, because the API layer
  turns ``ValueError`` into a 400 the user can act on.

``MODEL_DIR`` is derived from ``__file__`` at import time, so each test
monkeypatches it into its own tmp directory (the harness deliberately does not
own this path).
"""
import os
import re

import pandas as pd
import pytest
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

import analyzers.ml_base as ml_base
from analyzers.ml_base import MLClassifier, build_tfidf_pipeline, build_training_data, get_classifier

pytestmark = pytest.mark.unit

TEXTS = [
    '三亚的海非常蓝，适合冬天度假', '海南粉的汤底非常鲜美', '海口骑楼老街很漂亮', '三亚潜水体验很好',
    '糟糕的体验，非常差劲', '垃圾产品，不推荐购买', '服务太差，不会再来', '难用死了，太失望',
]
LABELS = ['pos', 'pos', 'pos', 'pos', 'neg', 'neg', 'neg', 'neg']


@pytest.fixture
def model_dir(tmp_path, monkeypatch):
    """Keep every pkl of this suite out of the real ``data/models``.

    The real directory is created by the module at import time, so the stand-in
    has to exist before ``fit`` can write into it.
    """
    target = tmp_path / 'models'
    target.mkdir()
    monkeypatch.setattr(ml_base, 'MODEL_DIR', str(target))
    return str(target)


def _unique_name(node_name):
    return re.sub(r'\W+', '_', node_name)


def _picklable_pipeline():
    """The same TF-IDF + logistic shape, without the unpicklable lambda.

    ``build_tfidf_pipeline`` installs ``tokenizer=lambda ...``, which joblib
    cannot serialise; supplying a pipeline is the only way ``fit`` can persist
    today (see the xfail below).
    """
    return Pipeline([
        ('tfidf', TfidfVectorizer(token_pattern=r'\S+', ngram_range=(1, 2), max_features=5000)),
        ('clf', LogisticRegression(max_iter=1000)),
    ])


# ─── graceful degradation ──────────────────────────────────────────────


class TestFallback:
    def test_an_untrained_model_answers_neutral(self, model_dir):
        classifier = MLClassifier(model_name=_unique_name('untrained'))
        assert classifier.predict(['随便一句话', '另一句']) == [('Neutral', 0.5), ('Neutral', 0.5)]

    def test_no_text_means_no_answers(self, model_dir):
        assert MLClassifier(model_name=_unique_name('empty')).predict([]) == []

    def test_a_saved_model_is_picked_up_by_a_fresh_instance(self, model_dir, request):
        name = _unique_name(request.node.name)
        MLClassifier(model_name=name, pipeline=_picklable_pipeline()).fit(TEXTS, LABELS)
        assert os.path.exists(os.path.join(model_dir, f'{name}.pkl'))
        predictions = MLClassifier(model_name=name).predict(['非常差的体验', '风景很漂亮'])
        assert [label for label, _ in predictions] == ['neg', 'pos']


# ─── training guards ───────────────────────────────────────────────────


class TestTrainingGuards:
    def test_no_rows_at_all_is_refused(self, model_dir):
        with pytest.raises(ValueError) as excinfo:
            MLClassifier(model_name=_unique_name('norows')).fit([], [])
        assert str(excinfo.value)

    def test_a_single_label_cannot_be_learned(self, model_dir):
        classifier = MLClassifier(model_name=_unique_name('onelabel'))
        with pytest.raises(ValueError, match='pos'):
            classifier.fit(['好', '也不错'], ['pos', 'pos'])

    def test_training_stops_before_any_file_is_written(self, model_dir):
        classifier = MLClassifier(model_name=_unique_name('nowrite'))
        with pytest.raises(ValueError):
            classifier.fit(['文本'], ['pos'])
        assert not os.path.exists(os.path.join(model_dir, 'nowrite.pkl'))

    def test_the_default_pipeline_can_be_saved(self, model_dir):
        classifier = MLClassifier(model_name=_unique_name('default-pipeline'))
        classifier.fit(TEXTS, LABELS)
        assert os.path.exists(os.path.join(model_dir, f"{_unique_name('default-pipeline')}.pkl"))
        assert classifier.predict(['很好'])[0][0] in ('pos', 'neg')


class TestFittedBehaviour:
    def test_predict_returns_a_label_and_a_confidence(self, model_dir):
        classifier = MLClassifier(model_name=_unique_name('fitted'), pipeline=_picklable_pipeline())
        classifier.fit(TEXTS, LABELS)
        results = classifier.predict(['服务很差', '很漂亮'])
        assert len(results) == 2
        for label, confidence in results:
            assert label in ('pos', 'neg')
            assert 0.5 <= confidence <= 1.0

    def test_labels_are_mapped_from_the_sorted_label_set(self, model_dir):
        classifier = MLClassifier(model_name=_unique_name('labelmap'), pipeline=_picklable_pipeline())
        classifier.fit(TEXTS, LABELS)
        assert classifier._label_map == {'neg': 0, 'pos': 1}

    def test_fit_returns_self_for_chaining(self, model_dir):
        classifier = MLClassifier(model_name=_unique_name('chain'), pipeline=_picklable_pipeline())
        assert classifier.fit(TEXTS, LABELS) is classifier
        assert classifier._fitted is True

    def test_the_input_frame_is_not_mutated(self, model_dir):
        texts = list(TEXTS)
        labels = list(LABELS)
        MLClassifier(model_name=_unique_name('nomutate'), pipeline=_picklable_pipeline()).fit(texts, labels)
        assert texts == TEXTS and labels == LABELS


# ─── pipeline builder and helpers ──────────────────────────────────────


class TestPipelineBuilder:
    def test_default_pipeline_is_tfidf_then_classifier(self):
        steps = dict(build_tfidf_pipeline().steps)
        assert list(steps) == ['tfidf', 'clf']
        assert isinstance(steps['tfidf'], TfidfVectorizer)
        assert isinstance(steps['clf'], LogisticRegression)

    def test_a_custom_classifier_and_feature_cap_are_honoured(self):
        custom = LogisticRegression(C=0.1, max_iter=5)
        pipeline = build_tfidf_pipeline(classifier=custom, max_features=10)
        assert pipeline.steps[1][1] is custom
        assert pipeline.steps[0][1].max_features == 10

    def test_the_vectorizer_trusts_pre_tokenised_text(self):
        # The pipeline is fed text jieba already split, so the vectorizer must
        # not re-tokenise it with its own word regex.
        vectorizer = build_tfidf_pipeline().steps[0][1]
        assert vectorizer.token_pattern is None
        assert vectorizer.tokenizer('三亚 的 海') == ['三亚', '的', '海']


class TestTrainingData:
    def test_blank_rows_are_dropped(self):
        texts = ['好文本', '', '  ', None, '差文本']
        labels = ['pos', 'neg', 'neg', 'neg', 'neg']
        frame = pd.DataFrame({'正文': texts, '情感': labels})
        got_texts, got_labels = build_training_data(frame, '正文', '情感')
        assert got_texts == ['好文本', '差文本']
        assert got_labels == ['pos', 'neg']

    def test_rows_without_a_label_are_dropped(self):
        frame = pd.DataFrame({'正文': ['文本'], '情感': [None]})
        assert build_training_data(frame, '正文', '情感') == ([], [])

    def test_labels_are_stringified(self):
        frame = pd.DataFrame({'t': ['a'], 'n': [1]})
        assert build_training_data(frame, 't', 'n') == (['a'], ['1'])


class TestSharedClassifiers:
    def test_the_same_name_shares_one_instance(self):
        assert get_classifier('emotion') is get_classifier('emotion')

    def test_different_names_do_not_collide(self):
        assert get_classifier('emotion') is not get_classifier('tendency')
        assert get_classifier('tendency').model_name == 'tendency'

    def test_the_cache_starts_empty_for_each_test(self):
        # The harness resets process globals; without that a model trained by
        # one test would answer for the next one.
        assert get_classifier('emotion')._fitted is False
