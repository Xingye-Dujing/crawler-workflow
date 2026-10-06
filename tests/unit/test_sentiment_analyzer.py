"""``analyzers/sentiment.py`` — the polarity operation, four ways.

The two operations beside this one answer 「哪种情绪」 and 「什么传播倾向」. SnowNLP and a
Chinese sentiment BERT answer one simpler question — is this text positive — so they got
their own operation and their own three-value column instead of being squeezed into a five
or six label set they cannot produce. What is pinned here is exactly that risk: a mode
guessed into another algorithm, a probability decided into the wrong label, and a missing
backend quietly replaced by a model nobody asked for.

Nothing here reaches a network or a GPU: the LLM path is pinned at the routing seam, and
the transformer path runs against a stub ``transformers`` in ``sys.modules`` — which is
enough to pin the batching, the label signing and the refusals, and is stated as such in
the README rather than pretended to be a real inference.
"""

import os

import pandas as pd
import pytest

import analyzers.sentiment as sentiment_module
from analyzers.sentiment import BERT_BATCH, SentimentAnalyzer, bert_backend
from i18n import set_lang

pytestmark = pytest.mark.unit


@pytest.fixture
def exec_():
    """The application module, imported inside the test and never at module scope.

    ``tests/unit/test_test_tiers.py`` refuses a module-level ``import app``: collection
    imports every file before any fixture runs, so the app would be built while
    ``Config.DATA_DIR`` still pointed at the repository, and its singleton services would
    go on writing into the user's real ``data/`` for the rest of the session.
    """
    import app

    return app


TEXTS = ['今天玩得非常开心', '这服务太差了令人失望', '会议将于周三举行', '']


def frame() -> pd.DataFrame:
    return pd.DataFrame([{'正文': t} for t in TEXTS])


@pytest.fixture(autouse=True)
def _chinese():
    """Console wording is asserted in zh; the refusals are the same sentences in en."""
    set_lang('zh')


class TestDeclaredModes:
    """The select-shaped parameter of the node, refused by name like every other one."""

    def test_the_four_modes_are_what_the_matrix_declares(self, exec_):
        default, allowed = exec_.PROCESS_ENUMS['sentiment']['mode']
        assert allowed == ('llm', 'ml', 'snownlp', 'bert')
        # SnowNLP needs no model, no download and no GPU, so an untouched node costs
        # nothing and answers a real question.
        assert default == 'snownlp'

    def test_a_blank_mode_is_the_declared_default(self, exec_):
        assert exec_.enum_param('sentiment', {'mode': ''}, 'mode') == 'snownlp'
        assert exec_.enum_param('sentiment', {}, 'mode') == 'snownlp'

    @pytest.mark.parametrize('stored', ['LLM', 'SnowNLP', 'BERT', 'senti', 'senta', 'llm-mode', 'ML'])
    def test_a_spelling_the_operation_does_not_know_is_refused_by_name(self, exec_, stored):
        # ``mode='ML'`` once paid for the row-by-row LLM pass the user had declined,
        # because the code tested for one value and treated everything else as the other.
        message = str(pytest.raises(ValueError, exec_.enum_param, 'sentiment', {'mode': stored}, 'mode').value)
        assert 'sentiment' in message and 'mode' in message and stored in message, message

    @pytest.mark.parametrize('stored', [' bert ', 'llm\n', '  snownlp'])
    def test_a_padded_but_real_mode_is_read_as_what_it_names(self, exec_, stored):
        # Padding is not a different algorithm; refusing it would fail a node whose value
        # came out of a textarea. Case, however, IS: 'LLM' is refused above.
        assert exec_.enum_param('sentiment', {'mode': stored}, 'mode') == stored.strip()

    def test_an_unknown_mode_reaches_the_analyzer_as_a_refusal_not_a_fallback(self):
        # enum_param is the gate; this is the same rule held at the second door, because
        # a caller that constructs the analyzer directly exists too (/api/analysis/run).
        with pytest.raises(ValueError, match='未知'):
            SentimentAnalyzer(mode='Bert').analyze_dataframe(frame(), '正文')


class TestThresholds:
    def test_the_defaults_are_a_band_around_the_middle(self, exec_):
        assert exec_.sentiment_thresholds({}) == (0.6, 0.4)

    def test_a_band_is_read_as_typed(self, exec_):
        assert exec_.sentiment_thresholds({'pos_threshold': '0.8', 'neg_threshold': '0.2'}) == (0.8, 0.2)

    def test_an_inverted_band_is_refused_not_swapped(self, exec_):
        """pos=0.3, neg=0.7 makes every row positive AND negative at once. Guessing which
        number the user meant would print a confident column out of an unanswerable ask."""
        with pytest.raises(exec_.UnknownOperationError, match='0.3'):
            exec_.sentiment_thresholds({'pos_threshold': 0.3, 'neg_threshold': 0.7})

    def test_touching_bounds_are_allowed_because_they_are_not_contradictory(self, exec_):
        assert exec_.sentiment_thresholds({'pos_threshold': 0.5, 'neg_threshold': 0.5}) == (0.5, 0.5)

    @pytest.mark.parametrize(
        'score,expected', [(1.0, 'positive'), (0.6, 'positive'), (0.5, 'neutral'), (0.4, 'negative'), (0.0, 'negative')]
    )
    def test_the_boundaries_belong_to_the_strong_answer(self, score, expected):
        # `score == pos_threshold` is the strongest reading the user's own figure still
        # accepts; answering 中性 there would look like the threshold had been ignored.
        assert SentimentAnalyzer(pos_threshold=0.6, neg_threshold=0.4).label_for_score(score) == expected

    def test_a_widened_band_makes_a_real_neutral_row(self):
        analyzer = SentimentAnalyzer(pos_threshold=0.9, neg_threshold=0.1)
        assert analyzer.label_for_score(0.5) == 'neutral'


class _FakeSnowNLP:
    """Stands in for the bundled model with a fixed table of polarities.

    SnowNLP is trained on shopping reviews and leans positive on objective text, so the
    fake answers are the interesting shapes (a strong positive, a strong negative, a
    mid-band neutral) rather than whatever the real weights say on a given day.
    """

    TABLE = {
        '今天玩得非常开心': 0.94,
        '这服务太差了令人失望': 0.03,
        '会议将于周三举行': 0.5,
    }

    def __init__(self, text):
        self._value = self.TABLE.get(text, 0.5)

    @property
    def sentiments(self):
        return self._value


@pytest.fixture
def fake_snownlp(monkeypatch):
    import snownlp

    monkeypatch.setattr(snownlp, 'SnowNLP', _FakeSnowNLP)
    return _FakeSnowNLP


class TestSnowNLPMode:
    def test_a_column_of_text_becomes_two_columns(self, fake_snownlp):
        out = SentimentAnalyzer(mode='snownlp').analyze_dataframe(frame(), '正文').to_dict('records')
        assert [r['sentiment'] for r in out[:3]] == ['positive', 'negative', 'neutral']
        assert out[0]['score'] == pytest.approx(0.94)

    def test_the_thresholds_choose_the_label_and_the_score_survives(self, fake_snownlp):
        """The row for a factual meeting is neutral at 0.5/0.6 but negative at 0.5/0.2 —
        and both must report the same 0.5, because the raw figure is the data and the
        label is the reading."""
        strict = SentimentAnalyzer(mode='snownlp', pos_threshold=0.9, neg_threshold=0.6)
        rows = strict.analyze_dataframe(frame(), '正文').to_dict('records')
        assert rows[2]['sentiment'] == 'negative'
        assert rows[2]['score'] == pytest.approx(0.5)

    def test_a_blank_row_stays_blank_rather_than_becoming_neutral(self, fake_snownlp):
        rows = SentimentAnalyzer(mode='snownlp').analyze_dataframe(frame(), '正文').to_dict('records')
        assert rows[3]['sentiment'] == '' and rows[3]['score'] is None, (
            '「没判断」 and 「判断为中性」 are different claims about the text'
        )

    def test_one_failing_row_does_not_end_the_column(self, monkeypatch):
        import snownlp

        class _Boom:
            def __init__(self, text):
                if text == '这服务太差了令人失望':
                    raise RuntimeError('权重读取失败')

            @property
            def sentiments(self):
                return 0.8

        monkeypatch.setattr(snownlp, 'SnowNLP', _Boom)
        rows = SentimentAnalyzer(mode='snownlp').analyze_dataframe(frame(), '正文').to_dict('records')
        assert rows[0]['sentiment'] == 'positive', 'the rows that read must still be answered'
        assert rows[1]['sentiment'] == '' and rows[1]['score'] is None, 'the row that failed must not be guessed'

    def test_a_missing_column_is_reported_not_a_crash(self, fake_snownlp):
        out = SentimentAnalyzer(mode='snownlp').analyze_dataframe(pd.DataFrame([{'别的': 'x'}]), '正文')
        assert list(out.columns) == ['别的', 'sentiment', 'score']


class TestMlMode:
    def test_an_untrained_model_answers_this_operations_neutral_not_emotions(self, tmp_path, monkeypatch):
        """``MLClassifier`` answers a model that was never fitted with the CALLER's neutral
        word: a leaked 'Neutral' from the emotion label set would be a class these charts
        have never seen, and a column of it reads as a finding."""
        from analyzers import ml_base

        monkeypatch.setattr(ml_base, 'MODEL_DIR', str(tmp_path))
        rows = SentimentAnalyzer(mode='ml').analyze_dataframe(frame(), '正文').to_dict('records')
        assert {r['sentiment'] for r in rows[:3]} == {'neutral'}
        assert 'Neutral' not in [r['sentiment'] for r in rows], 'the emotion label set leaked into the polarity column'

    def test_a_trained_model_separates_the_classes(self, tmp_path, monkeypatch):
        """Trained on the very sentences it is then asked about.

        A TF-IDF + logistic model on a dozen hand-written Chinese sentences has no honest
        claim to generalise to new ones, and an assertion that it did would be a number
        chosen for the test rather than one the data supports. What IS claimed here is the
        wiring: fit reaches the classifier, predict answers inside this operation's own
        three-word vocabulary, and three different classes come out as three labels.
        """
        from analyzers import ml_base

        monkeypatch.setattr(ml_base, 'MODEL_DIR', str(tmp_path))
        labeled = [
            ('今天玩得非常开心', 'positive'),
            ('这服务太差了令人失望', 'negative'),
            ('会议将于周三举行', 'neutral'),
        ]
        train = pd.DataFrame([{'正文': text, 'sentiment': label} for text, label in labeled for _ in range(4)])
        analyzer = SentimentAnalyzer(mode='ml')
        analyzer.fit_training(train, text_column='正文', label_column='sentiment')
        # Asked in the same order it was taught, so the expectation is one line per class.
        probe = pd.DataFrame([{'正文': text} for text, _ in labeled])
        rows = analyzer.analyze_dataframe(probe, '正文').to_dict('records')
        assert [r['sentiment'] for r in rows] == ['positive', 'negative', 'neutral']
        assert all(0.0 <= r['score'] <= 1.0 for r in rows), 'a confidence the charts group on must stay a probability'


class TestLlmMode:
    def test_the_llm_mode_routes_to_the_row_runner_and_nothing_else(self, monkeypatch):
        """The seam that matters: the other three modes must not be reachable from here,
        and the LLM must receive this operation's own prompt and parser."""
        seen = {}

        def fake_run(df, text_column, **kwargs):
            seen['op'] = kwargs['op']
            seen['columns'] = kwargs['result_columns']
            seen['prompt'] = kwargs['build_prompt']('x')
            seen['parsed'] = kwargs['parse']('Sentiment: positive, Score: 0.9')
            out = df.copy()
            out['sentiment'] = 'positive'
            out['score'] = 0.9
            return out

        monkeypatch.setattr(sentiment_module, 'run_llm_dataframe', fake_run)
        rows = SentimentAnalyzer(mode='llm').analyze_dataframe(frame(), '正文').to_dict('records')
        assert seen['op'] == 'sentiment'
        assert seen['columns'] == ['sentiment', 'score']
        assert 'POSITIVE' in seen['prompt']
        assert seen['parsed'] == ('positive', 0.9)
        assert rows[0]['sentiment'] == 'positive'

    @pytest.mark.parametrize(
        'answer,expected',
        [
            ('Sentiment: positive, Score: 0.91', ('positive', 0.91)),
            ('Sentiment: NEGATIVE, Score: 0.12', ('negative', 0.12)),
            ('Sentiment: neutral, Score: 1.7', ('neutral', 1.0)),
            ('Here you go:\n```Sentiment: positive, Score: 0.6```', ('positive', 0.6)),
            ('Sentiment: joy, Score: 0.5', (None, None)),
            ('no answer at all', (None, None)),
            ('', (None, None)),
            ('Sentiment: positive', ('positive', None)),
        ],
    )
    def test_the_parser_only_answers_its_own_three_labels(self, answer, expected):
        assert SentimentAnalyzer().parse_sentiment_response(answer) == expected

    def test_a_score_that_cannot_be_read_is_no_score_not_zero(self):
        assert SentimentAnalyzer().parse_sentiment_response('Sentiment: negative, Score: abc') == ('negative', None)


def _install_bert_stub(monkeypatch, answer_for, batches=None):
    """A fake ``transformers`` in ``sys.modules`` that answers per BATCH.

    The real package is never imported here: this machine has no torch, and importing it
    would print its own verdict about that to stderr — a fact about the dependency no
    test in this file is making. ``answer_for(text)`` is called for every text in the
    batch the product hands over, so a test can prove the column went through in chunks;
    letting it raise is how a test reproduces a failing batch.

    ``batches`` receives the list of texts of every call, which is the measurement the
    batching tests assert on. The returned list receives one record per ``pipeline()``
    call.
    """
    import sys
    import types

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
    # The probe is what decides whether the mode refuses, and this machine genuinely has
    # neither package; without this the stub above would never be reached.
    monkeypatch.setattr(sentiment_module, 'bert_backend', lambda: '')
    return calls


class TestBertMode:
    """The mode is offered, and it refuses by name. Nothing here ever runs a transformer."""

    def test_a_machine_without_the_backend_is_told_which_piece_is_missing(self, monkeypatch):
        monkeypatch.setattr(sentiment_module, 'bert_backend', lambda: 'torch')
        with pytest.raises(ValueError, match='torch') as err:
            SentimentAnalyzer(mode='bert', bert_model='m').analyze_dataframe(frame(), '正文')
        # The refusal must not be a shrug: silently using SnowNLP would put one model's
        # verdict in a column the node said another model produced.
        assert '代替' in str(err.value), str(err.value)

    def test_a_backend_that_exists_with_no_model_named_still_refuses(self, monkeypatch):
        monkeypatch.setattr(sentiment_module, 'bert_backend', lambda: '')
        with pytest.raises(ValueError, match='模型'):
            SentimentAnalyzer(mode='bert', bert_model='  ').analyze_dataframe(frame(), '正文')

    def test_the_probe_answers_the_packages_it_is_asked_about(self):
        # Whatever this machine has, the answer is a comma-joined subset of the two names.
        answer = bert_backend()
        assert set(str(answer).replace(' ', '').split(',')) <= {'torch', 'transformers', ''}

    def test_a_pipeline_answer_is_signed_into_a_polarity(self, monkeypatch):
        """The mapping from a model's own label to a probability the thresholds mean.

        ``transformers`` is put in ``sys.modules`` rather than imported: this machine has
        no torch, and importing the real package prints its own verdict about that onto
        stderr — a fact about the dependency that no test here is making. The product's
        ``from transformers import pipeline`` then resolves to the stub, which is the
        seam the method actually calls.
        """
        calls = _install_bert_stub(monkeypatch, lambda t: {'label': '负面' if '差' in t else '正面', 'score': 0.93})
        analyzer = SentimentAnalyzer(mode='bert', pos_threshold=0.6, neg_threshold=0.4, bert_model='some/model')
        rows = analyzer.analyze_dataframe(frame(), '正文').to_dict('records')
        assert calls[0]['task'] == 'sentiment-analysis' and calls[0]['model'] == 'some/model'
        assert rows[0]['sentiment'] == 'positive' and rows[0]['score'] == pytest.approx(0.93)
        assert rows[1]['sentiment'] == 'negative' and rows[1]['score'] == pytest.approx(0.07)

    def test_the_column_goes_through_in_batches_not_one_row_at_a_time(self, monkeypatch):
        """The whole reason this mode is usable on a real table: the round trips through
        Python are per BATCH. Three readable rows at a batch size of 4 are one call, and
        the blank row is not in it — nothing is asked about a text that is not there."""
        batches = []
        _install_bert_stub(monkeypatch, lambda t: {'label': '正面', 'score': 0.9}, batches=batches)
        analyzer = SentimentAnalyzer(mode='bert', bert_model='m', batch_size=4)
        analyzer.analyze_dataframe(frame(), '正文')
        assert batches == [['今天玩得非常开心', '这服务太差了令人失望', '会议将于周三举行']]

    def test_a_small_batch_size_splits_the_column(self, monkeypatch):
        batches = []
        _install_bert_stub(monkeypatch, lambda t: {'label': '正面', 'score': 0.9}, batches=batches)
        SentimentAnalyzer(mode='bert', bert_model='m', batch_size=2).analyze_dataframe(frame(), '正文')
        assert [len(b) for b in batches] == [2, 1]

    def test_a_failing_batch_blanks_its_own_rows_and_leaves_the_others(self, monkeypatch):
        """A batch that raises answers every row of THAT batch with the same reason. The
        per-row contract of this operation survives batching: what read is answered, what
        did not stays blank rather than being guessed at."""

        def answer_for(text):
            if '差' in text:
                raise RuntimeError('CUDA out of memory')
            return {'label': '正面', 'score': 0.9}

        _install_bert_stub(monkeypatch, answer_for)
        rows = SentimentAnalyzer(mode='bert', bert_model='m', batch_size=1).analyze_dataframe(frame(), '正文')
        rows = rows.to_dict('records')
        assert rows[0]['sentiment'] == 'positive', 'a batch that answered must still be kept'
        assert rows[1]['sentiment'] == '' and rows[1]['score'] is None, 'the failed row must not be guessed'
        assert rows[2]['sentiment'] == 'positive'

    def test_a_batch_size_that_is_not_a_count_cannot_become_a_zero_step_loop(self):
        """The chunking loop steps by this number, so a 0 reaching it would score nothing
        and report success over a table of blanks. 0 is read the way every other blank in
        this project is — not stated, so the declared default — and a negative count is
        floored at one row rather than trusted."""
        assert SentimentAnalyzer(mode='bert', batch_size=0).batch_size == BERT_BATCH
        assert SentimentAnalyzer(mode='bert', batch_size=-5).batch_size == 1

    def test_the_gpu_is_handed_to_the_pipeline_when_there_is_one(self, monkeypatch):
        calls = _install_bert_stub(monkeypatch, lambda t: {'label': '正面', 'score': 0.9})
        monkeypatch.setattr(sentiment_module, 'bert_device', lambda: 0)
        SentimentAnalyzer(mode='bert', bert_model='m').analyze_dataframe(frame(), '正文')
        assert calls[0]['device'] == 0, 'a card the machine has must not be left idle'

    def test_the_device_probe_always_answers_something_a_pipeline_accepts(self):
        # -1 is the pipeline's own CPU default, so the no-torch case needs no branch.
        # Asserted as a member rather than as -1: whether this machine has torch is a
        # fact about the machine, not about the code under test.
        assert sentiment_module.bert_device() in (-1, 0)

    def test_a_label_the_mapping_does_not_know_refuses_rather_than_guessing(self, monkeypatch):
        _install_bert_stub(monkeypatch, lambda t: {'label': 'SURPRISE', 'score': 0.5})
        analyzer = SentimentAnalyzer(mode='bert', bert_model='m')
        with pytest.raises(ValueError, match='SURPRISE'):
            analyzer.analyze_dataframe(frame(), '正文')


class TestOperationContract:
    def test_the_operation_is_declared_where_the_node_is_read(self, exec_):
        """Every place the executor decides something about an op knows it from one of
        these tables; a sentiment node missing from one of them is a node that silently
        does the wrong thing rather than one that fails loudly."""
        assert 'sentiment' in exec_.PROCESS_ENUMS
        assert 'sentiment' in exec_._TEXT_COLUMN_OPS

    def test_the_column_names_are_the_ones_the_frontend_and_charts_read(self, fake_snownlp):
        out = SentimentAnalyzer(mode='snownlp').analyze_dataframe(frame(), '正文')
        assert {'sentiment', 'score'} <= set(out.columns)
        # 'neutral' must be spelled exactly as the label set declares, or a distribution
        # chart groups it beside its own capitalised twin.
        assert set(out['sentiment'].unique()) <= {'', 'positive', 'negative', 'neutral'}


class TestBertModelPathResolution:
    """A workflow stores a model reference, but the model folder is gitignored and lives at a
    machine-specific path. Resolution must let a RELATIVE path travel across machines while
    still accepting an absolute path, a bare folder name, and a hub id.
    """

    def test_relative_path_resolves_under_the_project_root(self, tmp_path, monkeypatch):
        # Use a name that cannot exist under the real cwd, so the test exercises the
        # project-root join and not the "already-cwd-relative-and-real" short-circuit.
        target = tmp_path / 'somewhere' / 'bert_portable'
        target.mkdir(parents=True)
        monkeypatch.setattr(sentiment_module, 'BASE_DIR', str(tmp_path))
        assert sentiment_module.resolve_bert_model('somewhere/bert_portable') == str(target)

    def test_bare_folder_name_is_found_under_ml_train(self, tmp_path, monkeypatch):
        (tmp_path / 'ml_train' / 'bert_tendency_model').mkdir(parents=True)
        monkeypatch.setattr(sentiment_module, 'BASE_DIR', str(tmp_path))
        resolved = sentiment_module.resolve_bert_model('bert_tendency_model')
        assert resolved == os.path.join(str(tmp_path), 'ml_train', 'bert_tendency_model')

    def test_an_existing_absolute_path_is_left_untouched(self, tmp_path):
        model = tmp_path / 'bert_sentiment_model'
        model.mkdir()
        assert sentiment_module.resolve_bert_model(str(model)) == str(model)

    def test_an_unmatched_name_passes_through_as_a_hub_id(self):
        # Not a local folder: hand it to transformers unchanged rather than guess a path,
        # so a genuinely-remote model still loads and a wrong id refuses by name downstream.
        assert sentiment_module.resolve_bert_model('someone/just-a-hub-id') == 'someone/just-a-hub-id'

    def test_blank_resolves_to_blank_so_the_refusal_still_fires(self):
        assert sentiment_module.resolve_bert_model('   ') == ''
