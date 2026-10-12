"""Unit tests for the 水军/bot-likelihood analyzer (analyzers/bot.py).

The analyzer's job is a per-AUTHOR signal over the whole table, so these pin the three things that
make it honest: a near-duplicate shared across DIFFERENT accounts is flagged, the SAME account
repeating itself is not (that is not astroturfing, it is one person), and every required column is
refused by name. Timing is left coarse — the burst signal is relative to the corpus and is exercised
indirectly; the deterministic, falsifiable claims are the cross-account duplicate and the refusals.
"""

import pandas as pd
import pytest

from analyzers.bot import BotLikelihoodAnalyzer

pytestmark = pytest.mark.unit


class TestBotLikelihood:
    def _frame(self, text, author, time):
        return pd.DataFrame({'正文': text, '评论者': author, '评论时间': time})

    def test_near_duplicate_across_accounts_is_flagged(self):
        frame = self._frame(
            ['假货骗子大家快来买', '假货骗子大家快来买', '完全无关的一段话内容'],
            ['A', 'B', 'C'],
            ['2024-05-01 10:00', '2024-05-01 10:01', '2024-05-01 10:02'],
        )
        out = BotLikelihoodAnalyzer().analyze_dataframe(frame)
        assert list(out.columns)[-3:] == ['bot_score', 'bot_level', 'bot_evidence']
        assert len(out) == 3
        assert out['bot_level'][0] != 'none', 'A copied to B across accounts → suspect'
        assert out['bot_level'][1] != 'none'
        assert out['bot_level'][2] == 'none', 'an unrelated single post is clean'

    def test_the_same_author_repeating_itself_is_not_cross_account(self):
        frame = self._frame(
            ['假货骗子大家快来买', '假货骗子大家快来买'],
            ['A', 'A'],
            ['2024-05-01 10:00', '2024-05-01 10:01'],
        )
        out = BotLikelihoodAnalyzer().analyze_dataframe(frame)
        assert (out['bot_level'] == 'none').all(), 'one author repeating is not coordination'

    def test_missing_required_column_is_refused_by_name(self):
        no_author = pd.DataFrame({'正文': ['x'], '评论时间': ['2024-05-01 10:00']})
        with pytest.raises(ValueError, match='评论者'):
            BotLikelihoodAnalyzer().analyze_dataframe(no_author)
        no_time = pd.DataFrame({'正文': ['x'], '评论者': ['A']})
        with pytest.raises(ValueError, match='评论时间'):
            BotLikelihoodAnalyzer().analyze_dataframe(no_time)
        no_text = pd.DataFrame({'评论者': ['A'], '评论时间': ['2024-05-01 10:00']})
        with pytest.raises(ValueError, match='正文'):
            BotLikelihoodAnalyzer().analyze_dataframe(no_text)

    def test_clean_spread_table_is_all_none_and_order_preserved(self):
        frame = self._frame(
            ['内容甲完全不同', '内容乙也各写各的', '内容丙又是一回事'],
            ['A', 'B', 'C'],
            ['2024-05-01 09:00', '2024-05-01 10:00', '2024-05-01 11:00'],
        )
        out = BotLikelihoodAnalyzer().analyze_dataframe(frame)
        assert len(out) == 3
        assert list(out['评论者']) == ['A', 'B', 'C'], 'the table must not be reordered'
        assert (out['bot_level'] == 'none').all()
