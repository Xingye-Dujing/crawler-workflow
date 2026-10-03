"""``analyzers/aggression.py`` — 网络暴力言论识别, and what a word list may and may not claim.

The study's object is violent speech, not negative speech, and nothing in this project measured
it before: the sentiment curve answered "how cold" where the question was "how abusive". A
lexical detector can rank a corpus by explicit violence; it cannot see a euphemism, and a test
suite that let it look like a classifier would be how an unstated recall rate starts being
cited as a finding. So the assertions below are of three kinds — the levels a stated pattern
produces, the weights that make doxxing outrank a slur, and the false positives this device
DELIBERATELY takes (a correction that mentions 造谣 is not violence) — plus the LLM boundary,
which is exercised against an injected client and never against a real model.
"""

import pandas as pd
import pytest

import analyzers.aggression as aggression_module
from analyzers.aggression import AggressionAnalyzer
from i18n import set_lang

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _chinese():
    set_lang('zh')


def level(text: str) -> str:
    return AggressionAnalyzer.score_text(text)[0]


class TestLevels:
    """What each feature family turns into, and the difference between mild and severe."""

    @pytest.mark.parametrize(
        ('text', 'expected'),
        [
            ('这件事还需要更多证据', 'none'),
            ('警方已经通报调查结果', 'none'),
            ('你也配叫受害者', 'mild'),
            ('听说内部人士说家属拿了钱', 'mild'),
            ('傻逼滚开，废物一个', 'severe'),
            ('他的手机号是13812345678，人肉出来了', 'severe'),
        ],
    )
    def test_a_comment_comes_back_with_one_of_three_levels(self, text, expected):
        assert level(text) == expected

    def test_an_empty_or_blank_row_is_judged_clean_rather_than_unmeasured(self):
        # ``none`` means "judged, and nothing fired". A blank is judged the same way, and the
        # distinction lives in the hit list, not in a fourth level the export would have to guess.
        assert AggressionAnalyzer.score_text('   ') == ('none', 0.0, [])
        assert AggressionAnalyzer.score_text(None) == ('none', 0.0, [])

    def test_repeating_one_family_does_not_reach_severe_on_its_own(self):
        """One insult restated five ways is ONE act of abuse. Summing hits would rank a
        repetitive comment above a comment that both doxxes and slanders, which is the opposite
        of what the study's escalation claim is about."""
        once = AggressionAnalyzer.score_text('你也配叫受害者')[1]
        repeated = AggressionAnalyzer.score_text('你也配，你父母也不配，你全家都不配，这也不配，那也不配')[1]
        assert repeated > once, 'more distinct attacks do count for something'
        assert repeated - once <= 0.2 + 1e-9, 'and the cap is what keeps restatement from deciding'

    def test_a_doxxing_comment_outranks_a_slur(self):
        # The escalation step is weighted as the escalation step: 人肉 turns online abuse into
        # real-world harm, and a ranking that scored it equal to an insult would flatten exactly
        # the difference the paper's governance section is built on.
        assert level('13812345678，家庭住址在3号楼，人肉搜索') == 'severe'
        assert AggressionAnalyzer.score_text('13812345678')[1] >= 0.6
        assert AggressionAnalyzer.score_text('你真恶心')[1] < 0.3

    def test_a_debunking_comment_is_not_counted_as_rumour(self):
        """The false positive this device deliberately refuses: 造谣/辟谣 appear far more often in
        comments ACCUSING someone of rumour-mongering than in comments spreading one, so reading
        「别听他造谣，警方已经辟谣了」 as violence would put a correction on the rumour curve."""
        assert level('别听他造谣，警方已经辟谣了') == 'none'

    def test_a_miss_is_silent_and_says_so(self):
        # There is no way for a word list to notice an attack phrased outside it. Pinning the
        # miss keeps the limitation a fact of this module rather than a surprise to a reader.
        assert level('阁下的智力水平令人担忧') == 'none'


class TestHits:
    """The evidence column, which is what makes a verdict checkable."""

    def test_hits_name_the_family_and_the_words_that_fired(self):
        _level, _score, hits = AggressionAnalyzer.score_text('傻逼滚开，人肉他的手机号13812345678')
        joined = '；'.join(hits)
        assert 'abuse:' in joined and 'privacy:' in joined
        assert '傻逼' in joined and '13812345678' in joined

    def test_the_clean_rows_carry_no_hits(self):
        assert AggressionAnalyzer.score_text('今天天气不错')[2] == []


class TestDataframe:
    def test_the_three_columns_are_added_and_the_input_is_untouched(self):
        frame = pd.DataFrame({'正文': ['傻逼滚开', '这件事还需要更多证据'], '点赞': [3, 5]})
        out = AggressionAnalyzer().analyze_dataframe(frame, '正文')
        assert list(out.columns) == ['正文', '点赞', 'aggression', 'aggression_score', 'aggression_hits']
        assert list(out['aggression']) == ['severe', 'none']
        assert len(out) == 2, 'a detector adds columns, it does not filter rows'

    def test_a_text_column_that_is_not_there_is_refused_not_answered_with_blanks(self):
        # Settling DONE over a table of ``none`` is how a mis-typed column becomes a finding:
        # "this corpus contains no abusive speech".
        with pytest.raises(ValueError, match='没有这列'):
            AggressionAnalyzer().analyze_dataframe(pd.DataFrame({'正文': ['甲']}), '没有这列')

    def test_the_lexicon_mode_never_builds_a_model(self):
        """The default has to be free and repeatable, so it must not reach the LLM machinery even
        when a run context is handed to it — a workflow that stored a model name would otherwise
        pay for a pass the user did not ask for."""
        calls = []
        frame = pd.DataFrame({'正文': ['傻逼滚开']})
        monkey_client = {'client': object(), 'node_id': 'n1', 'publish': lambda df: calls.append(df)}
        out = AggressionAnalyzer(mode='lexicon').analyze_dataframe(frame, '正文', ctx=monkey_client)
        assert calls == []
        assert list(out['aggression']) == ['severe']

    def test_two_runs_of_one_table_answer_with_one_table(self):
        frame = pd.DataFrame({'正文': ['傻逼滚开', '你也配', '13812345678 人肉', '天气不错']})
        first = AggressionAnalyzer().analyze_dataframe(frame, '正文')
        second = AggressionAnalyzer().analyze_dataframe(frame, '正文')
        assert first.equals(second)


class TestAnswerParsing:
    """The LLM boundary, read as text — no model is called in this file."""

    @pytest.mark.parametrize(
        ('raw', 'expected'),
        [
            ('severe|abuse', ('severe', 'abuse')),
            ('严重|人身攻击', ('severe', '人身攻击')),
            ('mild|rumour', ('mild', 'rumour')),
            ('轻微|谩骂', ('mild', '谩骂')),
            ('none|无', ('none', '')),
            ('无', ('none', '')),
        ],
    )
    def test_a_level_word_in_either_language_lands_on_the_right_level(self, raw, expected):
        assert AggressionAnalyzer.parse_answer(raw) == expected

    def test_an_unrecognisable_answer_is_reported_not_invented(self):
        # A local model that answers with prose is not a licence to guess. The raw phrase is kept
        # in the hits column so the reader can see the parser did not understand it.
        level, hits = AggressionAnalyzer.parse_answer('这条评论包含攻击性语言，建议删除')
        assert level == 'none'
        assert hits, 'the words the model said are not thrown away'

    def test_nothing_at_all_is_no_verdict(self):
        assert AggressionAnalyzer.parse_answer('') == ('none', '')
        assert AggressionAnalyzer.parse_answer(None) == ('none', '')


class TestPrompt:
    def test_the_prompt_asks_for_one_line_and_names_the_allowed_labels(self):
        prompt = AggressionAnalyzer().build_prompt('傻逼滚开')
        assert '傻逼滚开' in prompt
        for word in ('none', 'mild', 'severe', 'abuse', 'attack', 'privacy', 'rumour'):
            assert word in prompt, f'the model cannot return {word} if it was never offered'
        assert '只输出一行' in prompt

    def test_the_lexicon_and_the_prompt_agree_on_the_family_names(self):
        """Two vocabularies in one module is how a hit list stops matching a prompt: the
        dataframe's ``aggression_hits`` says ``privacy`` and the model is asked for 隐私披露, and
        a downstream group-by then joins nothing to nothing."""
        families = set(aggression_module.PATTERNS)
        prompt = AggressionAnalyzer().build_prompt('x')
        assert families == {'abuse', 'attack', 'privacy', 'rumour'}
        for name in families:
            assert name in prompt
