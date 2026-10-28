"""The ONNX loader driven against the REAL ``tokenizers`` crate, with only the session faked.

``tests/unit/ml/test_bert_onnx_runner.py`` stubs both libraries, and that stubbing hid a defect: the
crate's ``Encoding`` exposes ``type_ids``, and the fake invented ``token_type_ids``. Every stubbed
case stayed green while the packaged app — the one place this path runs — would have died on the
first bert node. This file keeps the only part that must be real (the tokenizer, and therefore the
attribute names and the padding it applies) and fakes just the inference session, which is the
piece a unit test cannot ship.

``tokenizers`` is a declared dependency (``requirements.txt``, ``desktop/requirements-runtime.txt``),
so nothing here skips: a machine without the crate fails, which is the answer, not a green.
"""

import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest
from tokenizers import Tokenizer, models, pre_tokenizers

from analyzers.sentiment import ONNX_GRAPH_INPUTS, BertClassifier

pytestmark = pytest.mark.unit

#: ids chosen so one row pads: '好 差' → [2, 3], '好' → [2, PAD].
VOCAB = {'[PAD]': 0, '[UNK]': 1, '好': 2, '差': 3}


class _Session:
    """The exported graph's contract: these four inputs, these logits back."""

    inputs = list(ONNX_GRAPH_INPUTS)
    #: Every session the launcher built, oldest first. The test reads its feed from here rather than
    #: through `BertClassifier._session`, whose static type is the real onnxruntime class — which
    #: has no `feed` member, and the checker is right that this attribute belongs to the stub.
    instances = []

    def __init__(self, path, providers=None):
        self.path = path
        self.providers = providers
        self.feed = None
        type(self).instances.append(self)

    def get_inputs(self):
        return [types.SimpleNamespace(name=name) for name in type(self).inputs]

    def run(self, _wanted, feed):
        self.feed = feed
        # row 0 -> 差 (index 1) wins, row 1 -> 好 (index 0) wins.
        return [np.asarray([[0.0, 2.0], [1.5, -1.0]], dtype=np.float32)]


@pytest.fixture
def pack(tmp_path, monkeypatch):
    """A model folder a real tokenizer can be read out of, and a fake onnxruntime to match."""
    holder = tmp_path / 'tokenizer.json'
    tokenizer = Tokenizer(models.WordLevel(VOCAB, unk_token='[UNK]'))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer.enable_padding(pad_id=0, pad_token='[PAD]')
    tokenizer.enable_truncation(128)
    tokenizer.save(str(holder))
    (tmp_path / 'model.onnx').write_bytes(b'graph')
    (tmp_path / 'cixi_bert.json').write_text(
        json.dumps({'precision': 'int8', 'id2label': {'0': '好', '1': '差'}}, ensure_ascii=False), encoding='utf-8'
    )
    ort = types.ModuleType('onnxruntime')
    ort.InferenceSession = _Session
    monkeypatch.setitem(sys.modules, 'onnxruntime', ort)
    assert 'type_ids' in dir(Tokenizer.from_file(str(holder)).encode_batch(['好'])[0]), 'the crate renamed its fields'
    return tmp_path


class TestTheRealCrateFeedsTheGraph:
    def test_the_padded_row_is_masked_and_positioned_as_the_export_builds_it(self, pack):
        classifier = BertClassifier(str(pack), runtime='onnx', max_length=128)
        answers = classifier.predict(['好 差', '好'])
        feed = _Session.instances[-1].feed

        assert feed['input_ids'].tolist() == [[2, 3], [2, 0]], 'the real tokenizer produced these ids'
        # Row 1 is padded: its second key column carries the mask value, row 0 (no padding) does not.
        assert feed['attention_mask_4d'][0][0][0].tolist() == [0.0, 0.0]
        assert feed['attention_mask_4d'][1][0][0].tolist() == [0.0, -1e9]
        assert feed['position_ids'].tolist() == [[0, 1], [0, 0]]
        assert feed['token_type_ids'].tolist() == [[0, 0], [0, 0]]
        assert [item['label'] for item in answers] == ['差', '好'], 'the feed above is what produced these'

    def test_answers_are_the_model_s_own_labels_with_pipeline_shaped_scores(self, pack):
        classifier = BertClassifier(str(pack), runtime='onnx')
        answers = classifier.predict(['好 差', '好'])
        assert [item['label'] for item in answers] == ['差', '好']
        assert answers[0]['score'] == pytest.approx(float(np.exp(2) / (1 + np.exp(2))), abs=1e-6)
        assert answers[1]['score'] == pytest.approx(float(np.exp(2.5) / (1 + np.exp(2.5))), abs=1e-6)

    def test_the_padding_and_truncation_the_crate_was_saved_with_are_kept(self, pack):
        classifier = BertClassifier(str(pack), runtime='onnx', max_length=128)
        # ``padding``/``truncation`` answer as dicts on this crate version — read them as the
        # library exposes them rather than as the shape a stub would invent.
        assert classifier._tokenizer.padding['length'] is None, 'pad to this batch, not to 128'
        assert classifier._tokenizer.truncation['max_length'] == 128

    def test_the_export_script_and_the_loader_agree_on_the_graph_shape(self):
        """Two halves of one contract, written by different files (and ml_train is gitignored)."""
        assert ONNX_GRAPH_INPUTS == ('input_ids', 'position_ids', 'attention_mask_4d', 'token_type_ids')

        holder = Path(__file__).resolve().parents[3] / 'ml_train' / 'scripts' / 'export_onnx_bert.py'
        if not holder.is_file():
            pytest.skip('ml_train is not in this checkout; the pack shipped with the app is the other half')
        source = holder.read_text(encoding='utf-8')
        assert "GRAPH_INPUTS = ('input_ids', 'position_ids', 'attention_mask_4d', 'token_type_ids')" in source
