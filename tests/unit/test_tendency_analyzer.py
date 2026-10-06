"""``analyzers/tendency.py`` — the six-class stance operation, and its bert path.

tendency has no public corpus, so the model behind its ``bert`` mode was distilled from the
node's own ``llm`` path (ml_train/distill_tendency.py) and fine-tuned (train_bert_tendency.py).
What is pinned here mirrors the emotion bert tests, at the seam that matters: the missing
backend / unnamed model refuse BY NAME, a model answer that is not one of the six stances
stays blank instead of defaulting to ``Objective Statement``, the column goes through in
batches, and a requested bert mode never secretly runs the LLM or sklearn path.
"""

import sys
import types

import pandas as pd
import pytest

import analyzers.tendency as tendency_module
from analyzers.sentiment import BERT_BATCH
from analyzers.tendency import TendencyAnalyzer
from i18n import set_lang

pytestmark = pytest.mark.unit


@pytest.fixture
def exec_():
    """The application module, imported inside the test and never at module scope."""
    import app

    return app


TEXTS = ['这项新政策真的很好，支持！', '这种敷衍了事的作风该批评', '会议定于下周三举行', '']


def frame() -> pd.DataFrame:
    return pd.DataFrame([{'正文': t} for t in TEXTS])


@pytest.fixture(autouse=True)
def _chinese():
    set_lang('zh')


def _install_bert_stub(monkeypatch, answer_for, batches=None):
    """A fake ``transformers`` in ``sys.modules`` that answers per BATCH.

    tendency binds ``bert_backend`` by value, so the probe is patched on ``tendency_module``.
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
    monkeypatch.setattr(tendency_module, 'bert_backend', lambda: '')
    return calls


class TestLabelSet:
    def test_the_six_stance_labels_are_declared(self):
        labels = TendencyAnalyzer().valid_labels
        assert len(labels) == 6
        assert 'Objective Statement' in labels and 'Satire/Mockery' in labels

    def test_the_tendency_modes_are_what_the_matrix_declares(self, exec_):
        default, allowed = exec_.PROCESS_ENUMS['tendency']['mode']
        assert default == 'llm'
        assert allowed == ('llm', 'ml', 'bert')


class TestBertMode:
    def test_a_machine_without_the_backend_is_told_which_piece_is_missing(self, monkeypatch):
        monkeypatch.setattr(tendency_module, 'bert_backend', lambda: 'torch')
        with pytest.raises(ValueError, match='torch') as err:
            TendencyAnalyzer(mode='bert', bert_model='m').analyze_dataframe(frame(), '正文')
        assert '代替' in str(err.value), str(err.value)

    def test_a_backend_that_exists_with_no_model_named_still_refuses(self, monkeypatch):
        monkeypatch.setattr(tendency_module, 'bert_backend', lambda: '')
        with pytest.raises(ValueError, match='模型'):
            TendencyAnalyzer(mode='bert', bert_model='  ').analyze_dataframe(frame(), '正文')

    def test_a_pipeline_label_lands_in_the_tendency_and_confidence_columns(self, monkeypatch):
        calls = _install_bert_stub(monkeypatch, lambda t: {'label': 'Praise/Affirmation', 'score': 0.88})
        rows = (
            TendencyAnalyzer(mode='bert', bert_model='some/model').analyze_dataframe(frame(), '正文').to_dict('records')
        )
        assert calls[0]['task'] == 'text-classification' and calls[0]['model'] == 'some/model'
        assert rows[0]['tendency'] == 'Praise/Affirmation' and rows[0]['tendency_confidence'] == pytest.approx(0.88)

    def test_the_column_goes_through_in_batches_not_one_row_at_a_time(self, monkeypatch):
        batches = []
        _install_bert_stub(monkeypatch, lambda t: {'label': 'Objective Statement', 'score': 0.9}, batches=batches)
        TendencyAnalyzer(mode='bert', bert_model='m', batch_size=4).analyze_dataframe(frame(), '正文')
        assert batches == [TEXTS[:3]]

    def test_a_small_batch_size_splits_the_column(self, monkeypatch):
        batches = []
        _install_bert_stub(monkeypatch, lambda t: {'label': 'Objective Statement', 'score': 0.9}, batches=batches)
        TendencyAnalyzer(mode='bert', bert_model='m', batch_size=2).analyze_dataframe(frame(), '正文')
        assert [len(b) for b in batches] == [2, 1]

    def test_an_unknown_label_leaves_the_row_blank_rather_than_defaulting_objective(self, monkeypatch):
        """A model answer outside the six is a question about the MODEL, not a stance: the
        row stays blank rather than being stamped ``Objective Statement`` (tendency's own
        near-neutral default), which would be a claim about the text nothing established.
        """
        _install_bert_stub(
            monkeypatch,
            lambda t: (
                {'label': 'Disgust', 'score': 0.6} if '敷衍' in t else {'label': 'Praise/Affirmation', 'score': 0.9}
            ),
        )
        rows = TendencyAnalyzer(mode='bert', bert_model='m', batch_size=1).analyze_dataframe(frame(), '正文')
        rows = rows.to_dict('records')
        assert rows[0]['tendency'] == 'Praise/Affirmation'
        assert rows[1]['tendency'] == '' and rows[1]['tendency_confidence'] is None
        assert rows[1]['tendency'] != 'Objective Statement', 'an unmapped label must not be stamped Objective Statement'

    def test_a_failing_batch_blanks_its_own_rows_and_leaves_the_others(self, monkeypatch):
        def answer_for(text):
            if '敷衍' in text:
                raise RuntimeError('CUDA out of memory')
            return {'label': 'Praise/Affirmation', 'score': 0.9}

        _install_bert_stub(monkeypatch, answer_for)
        rows = TendencyAnalyzer(mode='bert', bert_model='m', batch_size=1).analyze_dataframe(frame(), '正文')
        rows = rows.to_dict('records')
        assert rows[0]['tendency'] == 'Praise/Affirmation'
        assert rows[1]['tendency'] == '' and rows[1]['tendency_confidence'] is None

    def test_bert_mode_never_falls_back_to_the_llm_or_sklearn_paths(self, monkeypatch):
        _install_bert_stub(monkeypatch, lambda t: {'label': 'Criticism/Questioning', 'score': 0.7})
        reached = []
        monkeypatch.setattr(tendency_module, 'run_llm_dataframe', lambda *a, **k: reached.append('llm'))
        monkeypatch.setattr(TendencyAnalyzer, '_analyze_ml', lambda self, df, tc: reached.append('ml'))
        TendencyAnalyzer(mode='bert', bert_model='m').analyze_dataframe(frame(), '正文')
        assert reached == [], f'bert mode reached another algorithm: {reached}'

    def test_a_batch_size_that_is_not_a_count_cannot_become_a_zero_step_loop(self):
        assert TendencyAnalyzer(mode='bert', batch_size=0).batch_size == BERT_BATCH
        assert TendencyAnalyzer(mode='bert', batch_size=-5).batch_size == 1

    def test_the_gpu_is_handed_to_the_pipeline_when_there_is_one(self, monkeypatch):
        calls = _install_bert_stub(monkeypatch, lambda t: {'label': 'Satire/Mockery', 'score': 0.6})
        monkeypatch.setattr(tendency_module, 'bert_device', lambda: 0)
        TendencyAnalyzer(mode='bert', bert_model='m').analyze_dataframe(frame(), '正文')
        assert calls[0]['device'] == 0, 'a card the machine has must not be left idle'
