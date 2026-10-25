"""The ONNX half of the bert path, tested without torch, transformers, or a real graph.

The packaged Windows app has no torch (multi-gigabyte, excluded from the runtime requirements), so
``bert`` nodes answer through ``onnxruntime`` + ``tokenizers`` there. These cases install both as
stubs in ``sys.modules`` — the same seam ``test_sentiment_analyzer._install_bert_stub`` uses for the
torch pipeline — and drive the real loader, because the parts worth proving are the numbers this
module computes itself: the position ids and the additive mask handed to the graph, the label
vocabulary read from the model folder, and the fact that a graph in a shape we did not ask for is
refused rather than answered wrongly.
"""

import json
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import analyzers.sentiment as sentiment_module
from analyzers.sentiment import BertClassifier, _importable, bert_classifier, bert_runtime

pytestmark = pytest.mark.unit

LABELS = {'0': 'negative', '1': 'positive'}


def _pack(tmp_path: Path, *, sidecar=None, name: str = 'pack') -> Path:
    """A model folder shaped like what ``ml_train/scripts/export_onnx_bert.py`` writes."""
    folder = tmp_path / name
    folder.mkdir(parents=True)
    (folder / 'model.onnx').write_bytes(b'protobuf-ish')
    (folder / 'tokenizer.json').write_text('{"model":{}}', encoding='utf-8')
    holder = sidecar if isinstance(sidecar, dict) else {'precision': 'int8', 'id2label': LABELS, 'max_length': 128}
    (folder / 'cixi_bert.json').write_text(json.dumps(holder, ensure_ascii=False), encoding='utf-8')
    return folder


class _Encoding:
    """The three lists the loader reads, named the way the ``tokenizers`` crate names them."""

    def __init__(self, ids, mask, type_ids):
        self.ids = ids
        self.attention_mask = mask
        self.type_ids = type_ids


class _Tokenizer:
    """Two rows of different length, padded to the batch max: row 0 has one pad cell."""

    instances = []

    def __init__(self, _path):
        self.truncation = None
        self.padded = False
        _Tokenizer.instances.append(self)

    @classmethod
    def from_file(cls, path):
        return cls(path)

    def enable_truncation(self, length):
        self.truncation = length

    def enable_padding(self, *args, **kwargs):
        self.padded = True

    def encode_batch(self, texts):
        return [_Encoding([101, 100 + index, 102, 0], [1, 1, 1, 0], [0, 0, 0, 0]) for index, _ in enumerate(texts)]


class _Input:
    def __init__(self, name):
        self.name = name


class _Session:
    """Records the feed and answers with fixed logits: row 0 negative, row 1 positive."""

    created = []
    logits = [[2.0, 0.0], [0.0, 3.0]]
    inputs = list(sentiment_module.ONNX_GRAPH_INPUTS)
    #: Declared, not conjured inside ``run``: the cases below read it, and an attribute that only
    #: exists after a call is something a checker (and a reader) cannot see.
    feed: dict = {}

    def __init__(self, path, providers=None):
        type(self).created.append((path, providers))

    def get_inputs(self):
        return [_Input(name) for name in type(self).inputs]

    def run(self, _names, feed):
        type(self).feed = feed
        return [np.asarray(type(self).logits, dtype=np.float32)]


@pytest.fixture(autouse=True)
def _stub_onnx_stack(monkeypatch):
    """Fake ``onnxruntime`` + ``tokenizers`` and no torch, exactly like the packaged app."""
    ort = types.ModuleType('onnxruntime')
    ort.InferenceSession = _Session
    tokenizers = types.ModuleType('tokenizers')
    tokenizers.Tokenizer = _Tokenizer
    monkeypatch.setitem(sys.modules, 'onnxruntime', ort)
    monkeypatch.setitem(sys.modules, 'tokenizers', tokenizers)
    monkeypatch.setitem(sys.modules, 'torch', None)
    monkeypatch.setitem(sys.modules, 'transformers', None)
    _Session.created = []
    _Session.feed = None
    _Session.logits = [[2.0, 0.0], [0.0, 3.0]]
    _Session.inputs = list(sentiment_module.ONNX_GRAPH_INPUTS)
    _Tokenizer.instances = []
    monkeypatch.setattr(
        sentiment_module,
        '_importable',
        lambda name: name in ('onnxruntime', 'tokenizers'),
    )
    yield


class TestWhichRuntime:
    def test_a_machine_with_only_the_onnx_stack_answers_onnx(self):
        assert bert_runtime() == 'onnx'

    def test_a_machine_with_torch_still_answers_torch(self, monkeypatch):
        monkeypatch.setattr(sentiment_module, '_importable', lambda name: name in ('torch', 'transformers'))
        assert bert_runtime() == 'torch'

    def test_a_machine_with_neither_refuses(self, monkeypatch):
        monkeypatch.setattr(sentiment_module, '_importable', lambda name: False)
        assert bert_runtime() == ''
        # and the refusal names what is missing instead of inventing a model.
        assert sentiment_module.bert_backend()

    def test_importable_answers_for_a_module_already_loaded(self):
        """``sys.modules`` is the answer; ``find_spec`` is only the lookup for the rest."""
        assert _importable('pandas') is True
        assert _importable('definitely_not_a_real_package_here') is False


class TestTheGraphFeed:
    def test_positions_and_mask_are_built_from_the_padding_mask(self, tmp_path, monkeypatch):
        folder = _pack(tmp_path)
        classifier = BertClassifier(str(folder), runtime='onnx')
        classifier.predict(['第一条', '第二条'])
        feed = _Session.feed
        # Row 0 of the stub encoding is [1,1,1,0]: positions 0,1,2 and pad position 0 (never -1).
        assert feed['position_ids'].tolist() == [[0, 1, 2, 0], [0, 1, 2, 0]]
        assert feed['attention_mask_4d'].shape == (2, 1, 1, 4)
        assert feed['attention_mask_4d'][0][0][0].tolist() == [0.0, 0.0, 0.0, sentiment_module.ONNX_MASK_VALUE]
        assert feed['input_ids'].dtype == np.int64
        assert feed['attention_mask_4d'].dtype == np.float32

    def test_answers_carry_the_model_s_own_label_names(self, tmp_path):
        classifier = BertClassifier(str(_pack(tmp_path)), runtime='onnx')
        answers = classifier.predict(['第一条', '第二条'])
        assert [item['label'] for item in answers] == ['negative', 'positive']
        # logits [2,0] -> P(negative) = 0.8808; [0,3] -> P(positive) = 0.9526. These are the numbers
        # the polarity thresholds are applied to, so they are the pipeline's own shape and value.
        assert answers[0]['score'] == pytest.approx(0.880797, abs=1e-4)
        assert answers[1]['score'] == pytest.approx(0.952574, abs=1e-4)

    def test_a_graph_that_is_not_the_shape_we_export_is_refused_by_name(self, tmp_path, monkeypatch):
        _Session.inputs = ['input_ids', 'attention_mask']
        with pytest.raises(ValueError) as raised:
            BertClassifier(str(_pack(tmp_path)), runtime='onnx')
        assert 'input_ids' in str(raised.value) and 'attention_mask' in str(raised.value)

    def test_a_folder_without_a_graph_names_the_folder(self, tmp_path):
        empty = tmp_path / 'bare'
        empty.mkdir()
        with pytest.raises(ValueError) as raised:
            BertClassifier(str(empty), runtime='onnx')
        assert 'bare' in str(raised.value)

    def test_a_folder_that_cannot_translate_an_output_is_refused(self, tmp_path):
        folder = _pack(tmp_path, sidecar={'precision': 'fp32', 'max_length': 128})
        with pytest.raises(ValueError) as raised:
            BertClassifier(str(folder), runtime='onnx')
        assert 'id2label' in str(raised.value)

    def test_the_tokenizer_is_truncated_to_the_configured_length(self, tmp_path):
        classifier = BertClassifier(str(_pack(tmp_path)), runtime='onnx', max_length=128)
        assert classifier._tokenizer.truncation == 128
        assert classifier._tokenizer.padded is True, 'rows of one batch must be the same length'


class TestTheSessionCache:
    def test_the_same_model_and_task_reuse_one_session(self, tmp_path):
        folder = str(_pack(tmp_path))
        first = bert_classifier(folder, task='text-classification')
        second = bert_classifier(folder, task='text-classification')
        assert first is second
        assert len(_Session.created) == 1, 'a reloaded model per batch is the bug this cache kills'

    def test_a_different_task_is_a_different_answer(self, tmp_path):
        folder = str(_pack(tmp_path))
        sentiment = bert_classifier(folder, task='sentiment-analysis')
        emotion = bert_classifier(folder, task='text-classification')
        assert sentiment is not emotion

    def test_a_different_truncation_length_is_a_different_session(self, tmp_path):
        """The length is baked into the tokenizer at load, so sharing a session across two nodes that
        configured 截断长度 differently would silently truncate one of them wrong."""
        folder = str(_pack(tmp_path))
        short = bert_classifier(folder, task='text-classification', max_length=128)
        long = bert_classifier(folder, task='text-classification', max_length=512)
        assert short is not long
        assert short._tokenizer.truncation == 128 and long._tokenizer.truncation == 512

    def test_a_third_model_drops_the_oldest_and_says_so(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sentiment_module, 'SESSION_LIMIT', 2)
        held = []
        for index in range(3):
            held.append(bert_classifier(str(_pack(tmp_path, name=f'pack{index}')), task='text-classification'))
        assert len(sentiment_module._SESSIONS) == 2
        assert held[0] not in sentiment_module._SESSIONS.values(), 'the oldest session must be released'
        assert sentiment_module._SESSION_ORDER[0] != sentiment_module._SESSION_ORDER[-1]

    def test_the_cache_is_cleared_between_cases(self):
        """A session surviving a case would answer the next one with another case's dead fakes."""
        assert sentiment_module._SESSIONS == {} and sentiment_module._SESSION_ORDER == []


class TestAnalyzersReachTheOnnxRunner:
    def _frame(self):
        return pd.DataFrame({'正文': ['第一条文本', '第二条文本']})

    def test_the_sentiment_column_is_answered_by_the_graph_not_by_snownlp(self, tmp_path):
        folder = str(_pack(tmp_path))
        result = sentiment_module.SentimentAnalyzer(mode='bert', bert_model=folder).analyze_dataframe(
            self._frame(), '正文'
        )
        # logits say row 0 negative (P 0.881) and row 1 positive (P 0.953); the polarity column is
        # signed by the label, which is the existing _signed_polarity contract, not a second one.
        assert result['sentiment'].tolist() == ['negative', 'positive']
        assert float(result['score'].iloc[0]) == pytest.approx(1 - 0.880797, abs=1e-4)
        assert float(result['score'].iloc[1]) == pytest.approx(0.952574, abs=1e-4)

    def test_emotion_reads_the_labels_the_checkpoint_declares(self, tmp_path):
        from analyzers.emotion import EmotionAnalyzer

        # The label vocabulary is the checkpoint's own id2label; the analyzer only checks that the
        # answer is one of the classes this operation knows (``self.valid_labels``).
        folder = _pack(tmp_path, sidecar={'precision': 'int8', 'id2label': {'0': 'Joy', '1': 'Sadness'}})
        _Session.logits = [[0.0, 4.0], [5.0, 0.0]]
        result = EmotionAnalyzer(mode='bert', bert_model=str(folder)).analyze_dataframe(self._frame(), '正文')
        assert result['emotion'].tolist() == ['Sadness', 'Joy']

    def test_an_unknown_label_still_refuses_rather_than_guessing(self, tmp_path):
        from analyzers.sentiment import PolarityError

        folder = _pack(tmp_path, sidecar={'precision': 'int8', 'id2label': {'0': 'maybe', '1': 'perhaps'}})
        with pytest.raises((PolarityError, ValueError)):
            sentiment_module.SentimentAnalyzer(mode='bert', bert_model=str(folder)).analyze_dataframe(
                self._frame(), '正文'
            )
