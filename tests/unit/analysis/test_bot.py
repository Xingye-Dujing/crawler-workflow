"""Unit tests for the 水军/bot-likelihood analyzer (analyzers/bot.py).

The analyzer's job is a per-AUTHOR signal over the whole table, so these pin the three things that
make it honest: a near-duplicate shared across DIFFERENT accounts is flagged, the SAME account
repeating itself is not (that is not astroturfing, it is one person), and every required column is
refused by name. Timing is left coarse — the burst signal is relative to the corpus and is exercised
indirectly; the deterministic, falsifiable claims are the cross-account duplicate and the refusals.
"""

import threading

import pandas as pd
import pytest

from analyzers.bot import BotLikelihoodAnalyzer
from crawlers.core.faults import CrawlerStopped

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

    def test_a_blank_author_cell_is_empty_not_a_pseudo_author_named_nan(self):
        """``float('nan')`` is truthy, so ``str(v or '')`` produced the author ``'nan'``: every
        deleted-account row pooled into one account (duplicate checks skipped between them, one
        burst window, and an author count that named a person who does not exist)."""
        from analyzers.bot import _author_cell

        assert _author_cell(None) == ''
        assert _author_cell(float('nan')) == ''
        assert _author_cell(pd.NA) == ''
        assert _author_cell(' A ') == 'A'

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


class _FlipEvent:
    """A stand-in cancel event that reports itself stopped after N checks.

    Used to prove the scan consults the event INSIDE the row loop: a check moved
    back out to just-before-the-loop would be consumed once and never again, so the
    raise would never land and ``calls`` would stay at 1.
    """

    def __init__(self, flips_after: int):
        self.calls = 0
        self.flips_after = flips_after

    def is_set(self) -> bool:
        self.calls += 1
        return self.calls > self.flips_after


class TestBotCancellation:
    def _wide(self, n):
        return pd.DataFrame(
            {
                '正文': [f'水军文案内容编号{i}' for i in range(n)],
                '评论者': [f'账号{i}' for i in range(n)],
                '评论时间': ['2024-05-01 10:00'] * n,
            }
        )

    def test_a_stop_already_set_refuses_before_scanning(self):
        stopped = threading.Event()
        stopped.set()
        with pytest.raises(CrawlerStopped):
            BotLikelihoodAnalyzer().analyze_dataframe(self._wide(6), cancel_event=stopped)

    def test_a_never_set_event_scores_the_whole_table(self):
        # The signature gained cancel_event; the default and a fresh (unset) event must
        # not change any previous behaviour — the table still lands, no exception.
        out = BotLikelihoodAnalyzer().analyze_dataframe(self._wide(6), cancel_event=threading.Event())
        assert len(out) == 6
        assert list(out.columns)[-3:] == ['bot_score', 'bot_level', 'bot_evidence']

    def test_a_stop_mid_scan_lands_within_a_bounded_number_of_rows(self):
        # The O(n²) loop must notice the Stop and bail; flipping it after two checks means
        # three outer rows ran, then the raise — not all six, and not zero of them.
        flip = _FlipEvent(flips_after=2)
        with pytest.raises(CrawlerStopped):
            BotLikelihoodAnalyzer().analyze_dataframe(self._wide(6), cancel_event=flip)
        assert 1 < flip.calls < 6, 'the check must run per row inside the loop, not once before it'


class TestBandedScanEquivalence:
    """The pair scan is banded (the dedupe step's pigeonhole index), not all-pairs. The
    banding is an EXACT filter, not a heuristic — any pair farther than DUP_BITS is never
    compared, any pair within it must share a band — so the per-row dup verdict has to
    match the brute-force reference bit for bit, on a table big enough that a silently
    approximate index would disagree."""

    def test_the_banded_verdict_matches_the_all_pairs_reference(self):
        import random

        from services.datasets.dedupe import hamming, normalize_text, simhash64

        rng = random.Random(42)
        seeds = [
            '假货骗子大家快来买假一赔十',
            '这个主播讲得真好学到了很多',
            '今天的天气适合出门散步逛街',
            '新品上市全场折扣优惠力度很大',
            '转发这条锦鲤好运连连发大财',
        ]
        texts, authors = [], []
        for i in range(150):
            seed = seeds[i % len(seeds)]
            variant = seed if rng.random() < 0.3 else seed + rng.choice(['！！', '转发', '真的假的', '，说的对'])
            texts.append(f'{variant}{i}')
            authors.append(f'账号{i}')
        # Plant cross-account farms: the same wording, accounts that differ.
        for farm in range(6):
            base = seeds[farm % len(seeds)]
            for member in range(4):
                texts.append(base + ('！' * (farm + 1)))
                authors.append(f'水军{farm}-{member}')

        frame = pd.DataFrame(
            {
                '正文': texts,
                '评论者': authors,
                '评论时间': ['2024-05-01 10:00'] * len(texts),
            }
        )
        out = BotLikelihoodAnalyzer().analyze_dataframe(frame)

        hashes = [simhash64(normalize_text(str(t))) if normalize_text(str(t)) else None for t in texts]
        names = [str(a or '').strip() for a in authors]
        reference = [False] * len(texts)
        for i, left in enumerate(hashes):
            if left is None or not names[i]:
                continue
            for j, right in enumerate(hashes):
                if i == j or right is None or names[i] == names[j] or not names[j]:
                    continue
                if hamming(left, right) <= 3:
                    reference[i] = True
                    break
        # Every row shares one timestamp, so the burst component is 0 for the whole table
        # and bot_score > 0 is EXACTLY the dup signal — the thing the reference computes.
        scored = [bool(value > 0) for value in out['bot_score']]
        assert scored == reference, 'the banded scan disagreed with the all-pairs reference'
