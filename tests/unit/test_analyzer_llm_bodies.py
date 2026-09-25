"""Tests for the three LLM-backed analyzers: cleaner.py, emotion.py, tendency.py.

These modules were imported by *no* test at all, so none of their answer-parsing
ever ran. The parts worth pinning are the ones a run silently depends on and no
device tier can see:

- what a model answer has to look like before it counts (the parsers are the
  only place a free-form reply becomes a table cell),
- what a rejected answer becomes (``skip_value`` / ``fail_value`` — an
  unparseable row is *reported as Neutral*, not left blank, so the gap never
  shows up as a hole in the table),
- the ML fallback's neutral default and who it writes it into,
- the exact result-column names the browser's result table addresses.

Everything is a fixed tiny input against an in-memory fake: no browser, no
Ollama daemon, no sleep, and OpenRouter is never reached (``chat`` is
overridden, and the fast tier additionally runs under ``--disable-socket``).
"""

import logging
import re

import pandas as pd
import pytest

import analyzers.cleaner as cleaner_module
import analyzers.emotion as emotion_module
import analyzers.tendency as tendency_module
from analyzers.cleaner import ContentCleaner
from analyzers.clustering import TextCluster
from analyzers.emotion import EmotionAnalyzer
from analyzers.keyword import KeywordExtractor
from analyzers.llm_client import LLMClient, LLMError
from analyzers.tendency import TendencyAnalyzer
from i18n import t

pytestmark = pytest.mark.unit

# A row every analyzer agrees is long enough to ask about.
LONG = '三亚的海非常蓝，适合冬天去度假潜水，珊瑚很多'  # 22 chars
# Long enough for the scorers (min_len 10), too short for the cleaner (min_len 20),
# which is the measured divergence between them.
MID = '三亚的海非常蓝，适合冬天度假潜水'  # 16 chars


# ─── The scripted transport ─────────────────────────────────────────────


class ScriptedClient(LLMClient):
    """A real ``LLMClient`` whose transport is a script.

    Subclassing keeps ``truncate()`` and the cache-scope fields (provider, model,
    host, max_chars) the production ones, while ``chat()`` answers from memory:
    neither the local daemon nor OpenRouter is ever contacted. Replies are keyed
    by the *prompt*, because that is the only thing a row loop can hand back.
    """

    def __init__(self, replies=None, default='Emotion: Joy, Confidence: 0.9', **kw):
        super().__init__(provider='openrouter', model='scripted', api_key='test-key', **kw)
        self.replies = dict(replies or {})
        self.default = default
        self.prompts = []

    def chat(self, prompt, max_retries=2):
        self.prompts.append(prompt)
        return self.replies.get(prompt, self.default)


def one_row_frame(text=LONG):
    return pd.DataFrame({'正文': [text]})


@pytest.fixture
def cleaner():
    return ContentCleaner()


@pytest.fixture
def emotion():
    return EmotionAnalyzer()


@pytest.fixture
def tendency():
    return TendencyAnalyzer()


# ─── cleaner.py: KEEP / DELETE parsing ──────────────────────────────────


class TestCleanerParsing:
    """``parse_model_output`` turns one plain string into (action, cleaned_text).

    The action vocabulary is the *localized* pair 保留/删除, not KEEP/DELETE — the
    downstream filter node and the exported table both read those two strings, so
    a parser that "modernised" them to 'keep' would silently un-select every row.
    """

    def test_a_good_answer_keeps_the_cleaned_text(self, cleaner):
        assert cleaner.parse_model_output('KEEP: 三亚的海很蓝') == ('保留', '三亚的海很蓝')

    def test_the_cleaned_text_is_multi_line(self, cleaner):
        # ``KEEP:`` is matched with DOTALL: an opinion the model wrapped over
        # several lines is still one kept row, not a truncation at the newline.
        assert cleaner.parse_model_output('KEEP: 第一行\n第二行') == ('保留', '第一行\n第二行')

    def test_an_explicit_delete_carries_no_text(self, cleaner):
        assert cleaner.parse_model_output('DELETE: null') == ('删除', None)

    def test_an_empty_keep_is_a_delete(self, cleaner):
        """'KEEP:' with nothing after it is the model having cleaned the row to
        nothing, which the prompt's own rule calls a deletion — not a kept empty
        cell, which an export would ship as a blank row."""
        assert cleaner.parse_model_output('KEEP:') == ('删除', None)
        assert cleaner.parse_model_output('KEEP:      ') == ('删除', None)

    def test_an_unparseable_answer_is_two_nones(self, cleaner):
        # Not ('删除', None): a refusal to decide must stay distinguishable from a
        # decision to delete, because the row runner counts the first as a
        # failure and the second as a result.
        assert cleaner.parse_model_output('这条评论看起来没问题') == (None, None)

    def test_a_prose_wrapped_answer_is_found_by_the_first_fallback(self, cleaner):
        """Models prefix the answer with reasoning despite the instructions. The
        fallback *searches* for 'KEEP:' instead of matching it at position zero —
        and it is greedy to the end of the string, so the fenced tail comes back
        inside the cleaned text (measured, pinned here as the current contract)."""
        assert cleaner.parse_model_output('分析如下：\nKEEP: 海很蓝\n```') == ('保留', '海很蓝\n```')

    def test_a_keep_mention_before_a_delete_is_still_a_keep(self, cleaner):
        """The two fallback searches are ordered KEEP first. An answer that
        contains both markers is therefore kept, with the text cut at 'DELETE:' —
        the precedence, not the wording, is the behaviour being pinned."""
        assert cleaner.parse_model_output('noise KEEP: 保留这句 DELETE: null') == ('保留', '保留这句')

    def test_the_delete_fallback_only_needs_the_marker_somewhere(self, cleaner):
        assert cleaner.parse_model_output('这是广告推广。\nDELETE: null') == ('删除', None)

    def test_an_empty_keep_with_nothing_after_it_falls_through_to_delete(self, cleaner):
        # The fallback keep branch returns only when the captured text is non-empty,
        # so an empty KEEP followed by a real DELETE is a deletion, not a hole.
        assert cleaner.parse_model_output('noise KEEP:   \nDELETE: null') == ('删除', None)

    def test_a_blank_answer_is_unparseable(self, cleaner):
        assert cleaner.parse_model_output('   ') == (None, None)


# ─── emotion.py: label + confidence parsing ─────────────────────────────


class TestEmotionParsing:
    """``parse_emotion_response`` returns (label, score) or the pair of Nones.

    ``tests/integration/test_llm_rows.py`` once carried a hand-written copy of
    this function that claimed the real contract while returning ``(None, 0.0)``
    and accepting ``pos``/``neg`` — neither of which the whitelist has ever
    contained. These are the measurements that copy should have been made from.
    """

    def test_a_good_answer(self, emotion):
        assert emotion.parse_emotion_response('Emotion: Joy, Confidence: 0.85') == ('Joy', 0.85)

    def test_the_answer_may_wear_prose_and_code_fences(self, emotion):
        # Both fields are *searched*, so a chatty model is still parsed, and the
        # two markers may come in either order.
        assert emotion.parse_emotion_response('Sure!\n```Emotion: Fear, Confidence: 0.4```') == ('Fear', 0.4)
        assert emotion.parse_emotion_response('Confidence: 0.9, Emotion: Sadness') == ('Sadness', 0.9)

    def test_an_out_of_whitelist_label_is_unparseable(self, emotion):
        assert emotion.parse_emotion_response('Emotion: Excitement, Confidence: 0.9') == (None, None)

    def test_the_whitelist_is_case_sensitive(self, emotion):
        """'joy' is a parse failure, not a near miss — the five categories are
        matched exactly as the prompt spells them, so a lowercase answer costs the
        row its result and lands the Neutral failure default instead."""
        assert emotion.parse_emotion_response('Emotion: joy, Confidence: 0.5') == (None, None)

    def test_a_label_handing_over_two_categories_keeps_the_first_word(self, emotion):
        # The prompt itself suggests 'Fear/Sadness' for rhetoric; the letters-only
        # capture reads 'Fear'. Pinned because the row is scored, not refused.
        assert emotion.parse_emotion_response('Emotion: Fear/Sadness, Confidence: 0.7') == ('Fear', 0.7)

    def test_a_confidence_above_one_is_clamped_not_passed_through(self, emotion):
        assert emotion.parse_emotion_response('Emotion: Joy, Confidence: 1.8') == ('Joy', 1.0)
        assert emotion.parse_emotion_response('Emotion: Joy, Confidence: 42') == ('Joy', 1.0)

    def test_a_confidence_inside_the_range_is_left_alone(self, emotion):
        # The clamp must not round: 0.85 is the model's number, and a chart that
        # averaged clamped-but-untouched scores would hide a rewrite.
        assert emotion.parse_emotion_response('Emotion: Joy, Confidence: 0.0') == ('Joy', 0.0)
        assert emotion.parse_emotion_response('Emotion: Joy, Confidence: 0.85') == ('Joy', 0.85)

    def test_a_negative_confidence_is_not_a_number_the_parser_can_see(self, emotion):
        """The digit class excludes '-', so a negative score never reaches the
        clamp — it is an unparseable answer. Reverting the clamp to a plain
        ``float`` would turn this into (label, -0.5), which is why both are here."""
        assert emotion.parse_emotion_response('Emotion: Joy, Confidence: -0.5') == (None, None)

    def test_a_malformed_number_is_a_failure_not_a_crash(self, emotion):
        # '0.9.9' is matched by [0-9.]+ and rejected by float(); the except that
        # swallows it is the only reason one bad row cannot kill the node.
        assert emotion.parse_emotion_response('Emotion: Joy, Confidence: 0.9.9') == (None, None)

    def test_a_missing_confidence_is_unparseable(self, emotion):
        assert emotion.parse_emotion_response('Emotion: Neutral.') == (None, None)

    def test_garbage_is_two_nones(self, emotion):
        assert emotion.parse_emotion_response('这句话没有明确情绪') == (None, None)


# ─── tendency.py: the label matcher ─────────────────────────────────────


class TestTendencyParsing:
    def test_a_good_answer(self, tendency):
        assert tendency.parse_tendency_response('Tendency: Satire/Mockery, Confidence: 0.7') == (
            'Satire/Mockery',
            0.7,
        )

    def test_the_answer_may_wear_prose_and_code_fences(self, tendency):
        assert tendency.parse_tendency_response('```json\nTendency: Praise/Affirmation\nConfidence: 0.7\n```') == (
            'Praise/Affirmation',
            0.7,
        )

    def test_an_out_of_whitelist_label_is_unparseable(self, tendency):
        assert tendency.parse_tendency_response('Tendency: Positive Vibes, Confidence: 0.5') == (None, None)

    def test_a_missing_confidence_is_unparseable(self, tendency):
        assert tendency.parse_tendency_response('Tendency: Satire/Mockery') == (None, None)

    def test_a_confidence_above_one_is_clamped(self, tendency):
        # Unlike emotion.py this path has no in-range branch at all: every score
        # goes through max/min, so the two endpoints are the only reachable cap.
        assert tendency.parse_tendency_response('Tendency: Advocacy/Call-to-action, Confidence: 1.4') == (
            'Advocacy/Call-to-action',
            1.0,
        )
        assert tendency.parse_tendency_response('Tendency: Satire/Mockery, Confidence: 0.9.9') == (None, None)


class TestTendencyLabelMatching:
    """``_match_label`` replaced a truncating regex; this is the measurement that
    forced the change plus the ordering rule it introduced.
    """

    def test_a_comma_less_answer_no_longer_eats_the_rest_of_the_line(self, tendency):
        """The prompt asks for 'Tendency: {label}, Confidence: {score}' and models
        drop the comma. The old ``Tendency:\\s*(.+?)(?=,|$)`` then had no comma to
        stop at, so ``.+?`` expanded to end-of-string and the captured blob was
        compared against the whitelist — the row was counted as a parse failure
        for an answer that named a real category.
        """
        reply = 'Tendency: Criticism/Questioning Confidence: 0.8'
        stale_capture = re.search(r'Tendency:\s*(.+?)(?=,|$)', reply).group(1)
        assert stale_capture not in tendency.valid_labels  # what the removed regex compared
        assert tendency._match_label(reply) == 'Criticism/Questioning'
        assert tendency.parse_tendency_response(reply) == ('Criticism/Questioning', 0.8)

    def test_a_label_mentioned_out_of_the_answer_slot_is_not_an_answer(self, tendency):
        """Matching is anchored to ``Tendency:`` — otherwise a model that merely
        discusses a category ('this is not Satire/Mockery') would be scored as
        one. Relaxing the anchor to a bare ``re.search(label)`` fails here."""
        assert tendency._match_label('不是 Satire/Mockery。Tendency: 说不好, Confidence: 0.5') is None

    def test_the_longest_label_wins_when_one_labels_the_other(self, tendency):
        """The sort by descending length is what keeps 'Joy' from labelling
        'Joy/Hope'. No *current* pair is prefix-related, so the guard is only
        observable once a label is added — which is exactly when it would
        otherwise start mis-scoring real rows in production."""
        scoped = TendencyAnalyzer()
        scoped.valid_labels = ['Joy', 'Joy/Hope']
        assert scoped._match_label('Tendency: Joy/Hope, Confidence: 0.8') == 'Joy/Hope'
        assert scoped._match_label('Tendency: Joy, Confidence: 0.8') == 'Joy'

    def test_no_shipped_label_is_a_prefix_of_another(self, tendency):
        """The companion fact: if this ever fails, the rule above stops being
        defensive and starts deciding real answers."""
        labels = tendency.valid_labels
        assert [
            (short, long_) for short in labels for long_ in labels if short is not long_ and long_.startswith(short)
        ] == []

    def test_unmatched_content_returns_none_rather_than_the_closest_label(self, tendency):
        assert tendency._match_label('Tendency: Neutral-ish, Confidence: 0.5') is None


# ─── emotion.py / tendency.py: the ML fallback ──────────────────────────


class TestEmotionMlMode:
    """``_analyze_ml`` is the "no LLM available" path.

    Its contract is that every row is *answered*: a row the classifier could not
    reach still gets the neutral default rather than a hole, because the result
    table is what the user sees.
    """

    def test_a_missing_column_still_grows_two_result_columns(self, emotion):
        """Measured asymmetry: emotion.py assigns 'emotion'/'confidence' *before*
        checking the text column, so a misconfigured node comes back with two
        blank columns — the opposite of tendency.py, which returns the frame
        untouched. Pinned because the two files disagree today.
        """
        frame = pd.DataFrame({'标题': ['a', 'b']})
        result = emotion._analyze_ml(frame, '正文')
        assert result is frame
        assert list(result.columns) == ['标题', 'emotion', 'confidence']
        assert result['emotion'].tolist() == ['', '']
        assert result['confidence'].isna().all()

    def test_a_missing_column_names_the_column_it_wanted(self, emotion, caplog):
        with caplog.at_level(logging.ERROR, logger='analyzers.emotion'):
            emotion._analyze_ml(pd.DataFrame({'标题': ['a']}), '不存在')
        assert t('ml.missing_col', col='不存在') in caplog.text

    def test_blank_rows_are_answered_with_the_blank_not_a_label(self, emotion):
        # Nothing to predict, so nothing is claimed: the columns exist and every
        # cell is empty, and the run logs "nothing to process".
        frame = pd.DataFrame({'正文': ['', '   ', None]})
        result = emotion._analyze_ml(frame, '正文')
        assert result['emotion'].tolist() == ['', '', '']
        assert result['confidence'].isna().all()

    def test_a_failing_prediction_falls_back_to_neutral_half_confidence(self, emotion, monkeypatch, caplog):
        """The real default is ('Neutral', 0.5) — read off the ``fail_value``
        branch, not guessed: 0.5 is below the skip default of 0.6, so a fallen-back
        row is visibly less certain than a row that was simply too short."""

        def boom(texts):
            raise RuntimeError('no model trained')

        monkeypatch.setattr(emotion, '_ml_predict', boom)
        frame = pd.DataFrame({'正文': ['三亚的海非常蓝', '海口的海南粉很鲜美', '   ', '博鳌小镇很安静']})
        result = emotion._analyze_ml(frame, '正文')
        assert result['emotion'].tolist() == ['Neutral', 'Neutral', '', 'Neutral']
        assert result['confidence'].tolist() == [0.5, 0.5, None, 0.5]
        assert t('ml.emotion_failed', err='no model trained') in caplog.text

    def test_predictions_land_on_the_non_blank_rows_in_index_order(self, emotion, monkeypatch):
        seen = {}

        def fake_predict(texts):
            seen['texts'] = texts
            return [('Joy', 0.9), ('Anger', 0.3)]

        monkeypatch.setattr(emotion, '_ml_predict', fake_predict)
        frame = pd.DataFrame({'正文': ['  三亚的海非常蓝  ', '   ', '海口的海南粉很鲜美']})
        result = emotion._analyze_ml(frame, '正文')
        assert seen['texts'] == ['三亚的海非常蓝', '海口的海南粉很鲜美']  # stripped, blanks dropped
        assert result['emotion'].tolist() == ['Joy', '', 'Anger']
        assert result['confidence'].tolist() == [0.9, None, 0.3]

    def test_a_short_answer_list_leaves_the_tail_blank(self, emotion, monkeypatch):
        # ``zip(..., strict=False)`` means a classifier that answers fewer rows
        # than it was given is not an error — the gap survives as an empty cell.
        monkeypatch.setattr(emotion, '_ml_predict', lambda texts: [('Joy', 0.9)])
        result = emotion._analyze_ml(pd.DataFrame({'正文': ['aaa bbb ccc', 'ddd eee fff']}), '正文')
        assert result['emotion'].tolist() == ['Joy', '']

    def test_ml_mode_writes_into_the_caller_frame(self, emotion, monkeypatch):
        """The ML path mutates the DataFrame it was handed and returns the same
        object; unlike clustering.py / keyword.py it does not copy first. Pinned
        as the contract, flagged as the asymmetry.
        """
        monkeypatch.setattr(emotion, '_ml_predict', lambda texts: [('Joy', 0.9)])
        frame = one_row_frame()
        before = frame.copy()
        assert emotion._analyze_ml(frame, '正文') is frame
        assert list(frame.columns) == ['正文', 'emotion', 'confidence']
        pd.testing.assert_series_equal(frame['正文'], before['正文'])

    def test_mode_ml_never_consults_a_transport(self, monkeypatch):
        # The node's mode select is the only thing separating a sklearn call from
        # a per-row LLM crawl, so a reverted branch would pay for every row again.
        analyzer = EmotionAnalyzer(mode='ml')
        client = ScriptedClient()
        monkeypatch.setattr(analyzer, '_ml_predict', lambda texts: [('Joy', 0.9)])
        analyzer.analyze_dataframe(one_row_frame(), '正文', ctx={'client': client})
        assert client.prompts == []


class TestTendencyMlMode:
    def test_a_missing_column_returns_the_frame_untouched(self, tendency):
        frame = pd.DataFrame({'标题': ['a']})
        result = tendency._analyze_ml(frame, '正文')
        assert result is frame
        assert list(result.columns) == ['标题']  # emotion.py would have grown two here

    def test_a_failing_prediction_falls_back_to_objective_statement(self, tendency, monkeypatch):
        def boom(texts):
            raise RuntimeError('no model trained')

        monkeypatch.setattr(tendency, '_ml_predict', boom)
        frame = pd.DataFrame({'正文': ['三亚的海非常蓝', '   ', '海口的海南粉很鲜美']})
        result = tendency._analyze_ml(frame, '正文')
        assert result['tendency'].tolist() == ['Objective Statement', '', 'Objective Statement']
        assert result['tendency_confidence'].tolist() == [0.5, None, 0.5]

    def test_the_confidence_column_is_named_after_the_operation(self, tendency, monkeypatch):
        """'tendency_confidence', not 'confidence' — a tendency node and an
        emotion node can sit in one chain, and the second would overwrite the
        first's score if both used the bare name."""
        monkeypatch.setattr(tendency, '_ml_predict', lambda texts: [('Praise/Affirmation', 0.8)])
        result = tendency._analyze_ml(one_row_frame(), '正文')
        assert list(result.columns) == ['正文', 'tendency', 'tendency_confidence']


# ─── analyze_dataframe over the shared row runner ───────────────────────


class TestRunnerDeclaration:
    """What each analyzer hands ``run_llm_dataframe``, captured at the call.

    The column names, the skip/fail triples and the "not worth asking" length live
    only in those three call sites, and the browser's result table addresses the
    columns by name — so a renamed result column or a swapped default is a
    user-visible break no row-level test would notice.
    """

    @staticmethod
    def capture(monkeypatch, module):
        seen = {}

        def fake_run(df, text_column, **kwargs):
            seen['text_column'] = text_column
            seen.update(kwargs)
            return df

        monkeypatch.setattr(module, 'run_llm_dataframe', fake_run, raising=True)
        return seen

    def test_cleaner_declares_its_columns_defaults_and_topic_scope(self, monkeypatch, cleaner):
        seen = self.capture(monkeypatch, cleaner_module)
        cleaner.clean_dataframe(one_row_frame(), '正文', topic='三亚旅游', ctx={'client': ScriptedClient()})
        assert seen['text_column'] == '正文'
        assert seen['op'] == 'clean'
        assert seen['result_columns'] == ['action', 'cleaned_text']
        assert seen['blank'] == ['', None]
        # A short row and a failed row are both deleted, so a cleaning node that
        # cannot reach a model never leaves an undecided row downstream.
        assert seen['skip_value'] == ('删除', None)
        assert seen['fail_value'] == ('删除', None)
        assert seen['min_len'] == 20
        assert seen['label'] == t('label.clean')
        # The topic is the cleaner's own cache scope: the prompt builder is a
        # closure whose body cannot see it, so only this string separates two
        # topics' answers.
        assert seen['extra_key'] == '三亚旅游'
        prompt = seen['build_prompt']('这句话很重要')
        assert '三亚旅游' in prompt and '这句话很重要' in prompt
        assert seen['parse']('KEEP: 好') == ('保留', '好')

    def test_an_absent_topic_is_an_empty_scope_not_a_default_string(self, monkeypatch, cleaner):
        seen = self.capture(monkeypatch, cleaner_module)
        cleaner.clean_dataframe(one_row_frame(), '正文', ctx={'client': ScriptedClient()})
        assert seen['extra_key'] == ''
        assert 'the specific topic' in seen['build_prompt']('正文内容')

    def test_emotion_declares_its_columns_and_defaults(self, monkeypatch, emotion):
        seen = self.capture(monkeypatch, emotion_module)
        emotion.analyze_dataframe(one_row_frame(), '正文', ctx={'client': ScriptedClient()})
        assert seen['op'] == 'emotion'
        assert seen['result_columns'] == ['emotion', 'confidence']
        assert seen['blank'] == ['', None]
        assert seen['skip_value'] == ('Neutral', 0.6)
        assert seen['fail_value'] == ('Neutral', 0.5)
        assert seen['min_len'] == 10
        assert seen['label'] == t('label.emotion')
        assert seen.get('extra_key', '') == ''  # nothing widens an emotion scope
        assert seen['parse']('Emotion: Joy, Confidence: 0.9') == ('Joy', 0.9)

    def test_tendency_declares_its_columns_and_defaults(self, monkeypatch, tendency):
        seen = self.capture(monkeypatch, tendency_module)
        tendency.analyze_dataframe(one_row_frame(), '正文', ctx={'client': ScriptedClient()})
        assert seen['op'] == 'tendency'
        assert seen['result_columns'] == ['tendency', 'tendency_confidence']
        assert seen['skip_value'] == ('Objective Statement', 0.6)
        assert seen['fail_value'] == ('Objective Statement', 0.5)
        assert seen['label'] == t('label.tendency')


class TestAnalyzerRows:
    """The three analyzers end to end against one scripted transport."""

    def test_emotion_scores_a_row_asks_once_and_names_its_columns(self, emotion):
        client = ScriptedClient(default='Emotion: Joy, Confidence: 0.9')
        result = emotion.analyze_dataframe(one_row_frame(), '正文', ctx={'client': client})
        assert list(result.columns) == ['正文', 'emotion', 'confidence']
        assert (result.loc[0, 'emotion'], result.loc[0, 'confidence']) == ('Joy', 0.9)
        assert len(client.prompts) == 1
        # The real template went out, with the row's own text inside it.
        assert 'Fine-Grained Sentiment Analysis Expert' in client.prompts[0]
        assert LONG in client.prompts[0]

    def test_tendency_scores_a_row_asks_once_and_names_its_columns(self, tendency):
        client = ScriptedClient(default='Tendency: Criticism/Questioning, Confidence: 0.8')
        result = tendency.analyze_dataframe(one_row_frame(), '正文', ctx={'client': client})
        assert list(result.columns) == ['正文', 'tendency', 'tendency_confidence']
        assert (result.loc[0, 'tendency'], result.loc[0, 'tendency_confidence']) == (
            'Criticism/Questioning',
            0.8,
        )
        assert len(client.prompts) == 1
        assert 'Media Content Analysis Expert' in client.prompts[0]

    def test_an_unparseable_answer_becomes_the_neutral_failure_default(self, emotion):
        """The row runner counts (None, None) as a failure and then fills the gap
        with ``fail_value`` — so a bad answer is reported as Neutral 0.5 rather
        than as a blank, which is why a chart can never tell the two apart."""
        client = ScriptedClient(default='这段话情绪不明显')
        result = emotion.analyze_dataframe(one_row_frame(), '正文', ctx={'client': client})
        assert (result.loc[0, 'emotion'], result.loc[0, 'confidence']) == ('Neutral', 0.5)
        assert len(client.prompts) == 1

    def test_tendency_falls_back_to_objective_statement_the_same_way(self, tendency):
        client = ScriptedClient(default='无法判断')
        result = tendency.analyze_dataframe(one_row_frame(), '正文', ctx={'client': client})
        assert (result.loc[0, 'tendency'], result.loc[0, 'tendency_confidence']) == (
            'Objective Statement',
            0.5,
        )

    def test_a_cleaner_receives_its_verdict_and_its_cleaned_text(self, cleaner):
        client = ScriptedClient(default='KEEP: 三亚的海非常蓝')
        result = cleaner.clean_dataframe(one_row_frame(), '正文', topic='三亚旅游', ctx={'client': client})
        assert list(result.columns) == ['正文', 'action', 'cleaned_text']
        assert (result.loc[0, 'action'], result.loc[0, 'cleaned_text']) == ('保留', '三亚的海非常蓝')
        assert len(client.prompts) == 1

    def test_an_unparseable_cleaning_answer_deletes_the_row(self, cleaner):
        # fail_value is ('删除', None): the model's silence is a deletion, so a
        # transport hiccup shrinks the table instead of leaving it undecided.
        client = ScriptedClient(default='我不确定')
        result = cleaner.clean_dataframe(one_row_frame(), '正文', ctx={'client': client})
        assert (result.loc[0, 'action'], result.loc[0, 'cleaned_text']) == ('删除', None)

    def test_an_empty_row_is_never_asked_about(self, emotion):
        client = ScriptedClient()
        result = emotion.analyze_dataframe(pd.DataFrame({'正文': [LONG, '']}), '正文', ctx={'client': client})
        assert len(client.prompts) == 1
        assert result.loc[1, 'emotion'] == ''
        assert pd.isna(result.loc[1, 'confidence'])

    def test_the_two_scorers_and_the_cleaner_disagree_about_a_short_row(self, cleaner, emotion):
        """min_len is per-analyzer. A 16-character comment is answered by the
        emotion node and deleted unseen by the cleaning node — the row never
        reaches the model there, so no transport change can make it appear."""
        short_client = ScriptedClient(default='KEEP: 三亚的海')
        clean = cleaner.clean_dataframe(one_row_frame(MID), '正文', ctx={'client': short_client})
        assert (clean.loc[0, 'action'], clean.loc[0, 'cleaned_text']) == ('删除', None)
        assert short_client.prompts == []

        emotion_client = ScriptedClient(default='Emotion: Joy, Confidence: 0.7')
        scored = EmotionAnalyzer().analyze_dataframe(one_row_frame(MID), '正文', ctx={'client': emotion_client})
        assert (scored.loc[0, 'emotion'], scored.loc[0, 'confidence']) == ('Joy', 0.7)
        assert len(emotion_client.prompts) == 1

    def test_a_row_too_short_for_the_scorers_takes_the_skip_default(self, emotion):
        client = ScriptedClient()
        result = emotion.analyze_dataframe(one_row_frame('太短'), '正文', ctx={'client': client})
        assert (result.loc[0, 'emotion'], result.loc[0, 'confidence']) == ('Neutral', 0.6)
        assert client.prompts == []

    def test_a_missing_column_raises_in_llm_mode(self, emotion):
        """The LLM and ML paths answer the same misconfiguration differently, by
        design on the LLM side: a blank table there would settle the node DONE, so
        the runner refuses instead (the ML frame is covered in TestEmotionMlMode).
        """
        client = ScriptedClient()
        with pytest.raises(LLMError) as err:
            emotion.analyze_dataframe(pd.DataFrame({'标题': ['a']}), '正文', ctx={'client': client})
        assert err.value.kind == 'error'
        assert '正文' in str(err.value)
        assert client.prompts == []


# ─── keyword.py vs clustering.py: an unknown method ─────────────────────


class TestUnknownMethodDispatch:
    """Two nodes take a method name the panel can fill in; only one of them
    refuses a typo. Pinned as it is, because it is not obvious from either
    module which behaviour a new analyzer should copy.
    """

    @pytest.fixture
    def frame(self):
        return pd.DataFrame(
            {
                '正文': [
                    '三亚的海非常蓝，适合冬天度假',
                    '海南粉的汤底非常鲜美，很好吃',
                    '潜水体验很好，珊瑚很多',
                ]
            }
        )

    def test_keyword_falls_back_to_textrank_and_stamps_the_requested_name(self, frame):
        result = KeywordExtractor().analyze_dataframe(frame, method='yake', topk=3, merge=False)
        # Not textrank's own name: the column reports what the node asked for, so
        # a filter on method='yake' still matches rows TextRank produced.
        assert set(result['method']) == {'yake'}
        assert set(result['row']) <= set(frame.index)
        hits = ['keyword', 'weight', 'row']
        textrank = KeywordExtractor().analyze_dataframe(frame, method='textrank', topk=3, merge=False)
        tfidf = KeywordExtractor().analyze_dataframe(frame, method='tfidf', topk=3, merge=False)
        # The fixture must keep telling the two algorithms apart, or the next
        # assertion proves nothing.
        assert not textrank[hits].equals(tfidf[hits]), 'the fixture no longer separates tfidf from textrank'
        assert result[hits].equals(textrank[hits])

    def test_clustering_refuses_the_same_typo_by_name(self, frame):
        with pytest.raises(ValueError, match='Unknown clustering method: yake'):
            TextCluster().analyze_dataframe(frame, method='yake')
