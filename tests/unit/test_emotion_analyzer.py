"""``analyzers/emotion.py`` — the six-class emotion operation, and its bert path.

The emotion label set was realigned to the SMP2020-EWECT scheme (Anger / Fear / Joy /
Neutral / Sadness / **Surprise**) when a fine-tuned transformer was added beside the LLM and
sklearn modes. What is pinned here is exactly that risk surface: the missing ``Surprise``
class, a mode guessed into another algorithm, a missing backend quietly replaced by a model
nobody asked for, and a model answer that is not one of the six left as a value instead of a
blank. Nothing here reaches a GPU: the transformer path runs against a stub ``transformers``
in ``sys.modules``, which pins the batching, the label mapping and the refusals.
"""

import sys
import types

import pandas as pd
import pytest

import analyzers.emotion as emotion_module
from analyzers.emotion import EmotionAnalyzer
from analyzers.sentiment import BERT_BATCH
from i18n import set_lang

pytestmark = pytest.mark.unit


@pytest.fixture
def exec_():
    """The application module, imported inside the test and never at module scope.

    ``tests/unit/test_test_tiers.py`` refuses a module-level ``import app``: collection
    imports every file before any fixture runs, so the app would be built while
    ``Config.DATA_DIR`` still pointed at the repository.
    """
    import app

    return app


TEXTS = ['今天玩得非常开心', '这人真的太可恶了', '会议将于周三举行', '']


def frame() -> pd.DataFrame:
    return pd.DataFrame([{'正文': t} for t in TEXTS])


@pytest.fixture(autouse=True)
def _chinese():
    """Refusals are asserted in zh; the same sentences exist in en (parity is tested elsewhere)."""
    set_lang('zh')


def _install_bert_stub(monkeypatch, answer_for, batches=None):
    """A fake ``transformers`` in ``sys.modules`` that answers per BATCH.

    emotion binds ``bert_backend`` by value (``from ... import``), so the probe is patched on
    ``emotion_module`` — patching the sentiment original would not be seen here. The returned
    list receives one record per ``pipeline()`` call; ``batches`` receives the texts of every
    call so a test can assert the column went through in chunks.
    """
    stub = types.ModuleType('transformers')
    calls = []

    def fake_pipeline(task, model=None, device=-1):
        calls.append({'task': task, 'model': model, 'device': device})

        def run(texts, **kwargs):
            if isinstance(texts, str):
                raise AssertionError('the node must hand the pipeline a whole batch, not one row')
            if batches is not None:
                batches.append(list(texts))
            return [answer_for(t) for t in texts]

        return run

    stub.pipeline = fake_pipeline
    monkeypatch.setitem(sys.modules, 'transformers', stub)
    monkeypatch.setattr(emotion_module, 'bert_backend', lambda: '')
    return calls


class TestLabelSet:
    """The six categories, with Surprise present, and the node's declared modes."""

    def test_surprise_is_a_valid_label(self):
        assert EmotionAnalyzer().valid_labels == ['Anger', 'Joy', 'Sadness', 'Fear', 'Surprise', 'Neutral']
        assert 'Surprise' in EmotionAnalyzer().valid_labels

    def test_the_emotion_modes_are_what_the_matrix_declares(self, exec_):
        default, allowed = exec_.PROCESS_ENUMS['emotion']['mode']
        # bert was added as an opt-in; the default stays llm so an untouched node does not
        # suddenly require a GPU and a model path.
        assert default == 'llm'
        assert allowed == ('llm', 'ml', 'bert')


class TestBertMode:
    """The mode is offered, and it refuses by name. Nothing here ever runs a transformer."""

    def test_a_machine_without_the_backend_is_told_which_piece_is_missing(self, monkeypatch):
        monkeypatch.setattr(emotion_module, 'bert_backend', lambda: 'torch')
        with pytest.raises(ValueError, match='torch') as err:
            EmotionAnalyzer(mode='bert', bert_model='m').analyze_dataframe(frame(), '正文')
        assert '代替' in str(err.value), str(err.value)

    def test_a_backend_that_exists_with_no_model_named_still_refuses(self, monkeypatch):
        monkeypatch.setattr(emotion_module, 'bert_backend', lambda: '')
        with pytest.raises(ValueError, match='模型'):
            EmotionAnalyzer(mode='bert', bert_model='  ').analyze_dataframe(frame(), '正文')

    def test_a_pipeline_label_lands_in_the_emotion_and_confidence_columns(self, monkeypatch):
        calls = _install_bert_stub(monkeypatch, lambda t: {'label': 'Anger', 'score': 0.82})
        analyzer = EmotionAnalyzer(mode='bert', bert_model='some/model')
        rows = analyzer.analyze_dataframe(frame(), '正文').to_dict('records')
        assert calls[0]['task'] == 'text-classification' and calls[0]['model'] == 'some/model'
        assert rows[0]['emotion'] == 'Anger' and rows[0]['confidence'] == pytest.approx(0.82)

    def test_the_column_goes_through_in_batches_not_one_row_at_a_time(self, monkeypatch):
        batches = []
        _install_bert_stub(monkeypatch, lambda t: {'label': 'Joy', 'score': 0.9}, batches=batches)
        EmotionAnalyzer(mode='bert', bert_model='m', batch_size=4).analyze_dataframe(frame(), '正文')
        # Three readable rows at batch size 4 are one call; the blank row is not in it.
        assert batches == [['今天玩得非常开心', '这人真的太可恶了', '会议将于周三举行']]

    def test_a_small_batch_size_splits_the_column(self, monkeypatch):
        batches = []
        _install_bert_stub(monkeypatch, lambda t: {'label': 'Joy', 'score': 0.9}, batches=batches)
        EmotionAnalyzer(mode='bert', bert_model='m', batch_size=2).analyze_dataframe(frame(), '正文')
        assert [len(b) for b in batches] == [2, 1]

    def test_an_unknown_label_leaves_the_row_blank_rather_than_inventing_neutral(self, monkeypatch):
        """A model answer that is not one of the six is a question about the MODEL, not a
        verdict: the row stays blank instead of being guessed into Neutral, which is a claim
        about the text that nothing in fact established.
        """
        _install_bert_stub(
            monkeypatch,
            lambda t: {'label': 'Disgust', 'score': 0.6} if '可恶' in t else {'label': 'Joy', 'score': 0.9},
        )
        rows = EmotionAnalyzer(mode='bert', bert_model='m', batch_size=1).analyze_dataframe(frame(), '正文')
        rows = rows.to_dict('records')
        assert rows[0]['emotion'] == 'Joy'
        assert rows[1]['emotion'] == '' and rows[1]['confidence'] is None
        assert rows[1]['emotion'] != 'Neutral', 'an unmapped label must not be stamped Neutral'

    def test_a_failing_batch_blanks_its_own_rows_and_leaves_the_others(self, monkeypatch):
        def answer_for(text):
            if '可恶' in text:
                raise RuntimeError('CUDA out of memory')
            return {'label': 'Joy', 'score': 0.9}

        _install_bert_stub(monkeypatch, answer_for)
        rows = EmotionAnalyzer(mode='bert', bert_model='m', batch_size=1).analyze_dataframe(frame(), '正文')
        rows = rows.to_dict('records')
        assert rows[0]['emotion'] == 'Joy', 'a batch that answered must still be kept'
        assert rows[1]['emotion'] == '' and rows[1]['confidence'] is None

    def test_bert_mode_never_falls_back_to_the_llm_or_sklearn_paths(self, monkeypatch):
        """The one-failure-one-line rule made concrete: with bert requested, neither the
        row-by-row LLM nor the sklearn classifier may run behind a column this node said a
        transformer produced — even when the transformer refuses.
        """
        _install_bert_stub(monkeypatch, lambda t: {'label': 'Fear', 'score': 0.7})
        reached = []
        monkeypatch.setattr(emotion_module, 'run_llm_dataframe', lambda *a, **k: reached.append('llm'))
        monkeypatch.setattr(EmotionAnalyzer, '_analyze_ml', lambda self, df, tc: reached.append('ml'))
        EmotionAnalyzer(mode='bert', bert_model='m').analyze_dataframe(frame(), '正文')
        assert reached == [], f'bert mode reached another algorithm: {reached}'

    def test_a_batch_size_that_is_not_a_count_cannot_become_a_zero_step_loop(self):
        assert EmotionAnalyzer(mode='bert', batch_size=0).batch_size == BERT_BATCH
        assert EmotionAnalyzer(mode='bert', batch_size=-5).batch_size == 1

    def test_the_gpu_is_handed_to_the_pipeline_when_there_is_one(self, monkeypatch):
        calls = _install_bert_stub(monkeypatch, lambda t: {'label': 'Surprise', 'score': 0.6})
        monkeypatch.setattr(emotion_module, 'bert_device', lambda: 0)
        EmotionAnalyzer(mode='bert', bert_model='m').analyze_dataframe(frame(), '正文')
        assert calls[0]['device'] == 0, 'a card the machine has must not be left idle'
