"""The bot-likelihood signal, and the difference between "same content" and "no content".

A missing 正文 cell used to become the string ``'nan'`` (``str(float('nan'))`` is truthy), so
every row whose body was never collected shared one SimHash and unrelated authors were accused
of coordinated duplicate posting — the same fold the 评论者 column already had.
"""

import pandas as pd

from analyzers.bot import BotLikelihoodAnalyzer


def _frame(bodies, authors):
    return pd.DataFrame(
        {
            '评论者': authors,
            '正文': bodies,
            '评论时间': ['2022年01月27日 00:59'] * len(bodies),
        }
    )


def test_two_missing_bodies_are_not_the_same_content():
    out = BotLikelihoodAnalyzer().analyze_dataframe(
        _frame([None, float('nan'), '不同的正文一', '不同的正文二'], ['甲', '乙', '丙', '丁'])
    )
    assert list(out['bot_score']) == [0.0, 0.0, 0.0, 0.0]
    assert list(out['bot_level']) == ['none'] * 4
    assert not any(out['bot_evidence']), list(out['bot_evidence'])


def test_the_same_body_still_reads_as_duplicate():
    """Positive control: the empty-cell fold must not silence the signal it exists for."""
    out = BotLikelihoodAnalyzer().analyze_dataframe(_frame(['同一句话', '同一句话'], ['甲', '乙']))
    assert out['bot_score'].max() > 0
    assert any(out['bot_evidence'])
