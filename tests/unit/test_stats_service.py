"""Tests for services/stats.py — the tiny distribution helpers.

The charts and the execution-history series plot *counts*, and they address
labels positionally (labels[i] with values[i]), so both properties matter: the
pairing must hold, and a row the LLM answered nothing for must not invent a
bucket.
"""
import pytest

from services.stats import StatsService as S

pytestmark = pytest.mark.unit


LABELLED_ROWS = [
    {'emotion': 'Joy', 'tendency': 'Positive'},
    {'emotion': 'Sadness', 'tendency': 'Negative'},
    {'emotion': 'Joy', 'tendency': 'Neutral'},
    {'emotion': 'Neutral', 'tendency': 'Positive'},
    {'emotion': 'Joy'},
]


class TestEmotionDistribution:
    def test_counts_follow_first_seen_label_order(self):
        dist = S.emotion_distribution(LABELLED_ROWS)
        assert dist['labels'] == ['Joy', 'Sadness', 'Neutral']
        assert dist['values'] == [3, 1, 1]

    def test_labels_and_values_stay_positionally_paired(self):
        dist = S.emotion_distribution(LABELLED_ROWS)
        assert dict(zip(dist['labels'], dist['values'], strict=True)) == {'Joy': 3, 'Sadness': 1, 'Neutral': 1}

    @pytest.mark.parametrize('rows', [
        [],
        [{'emotion': ''}],
        [{'emotion': None}],
        [{'emotion': 0}],
        [{'标题': 'no emotion column'}],
    ])
    def test_rows_without_an_answer_are_ignored(self, rows):
        assert S.emotion_distribution(rows) == {'labels': [], 'values': []}

    def test_single_label_still_produces_one_bucket(self):
        assert S.emotion_distribution([{'emotion': 'Anger'}] * 2) == {'labels': ['Anger'], 'values': [2]}

    def test_the_input_is_not_consumed_or_reordered(self):
        rows = [dict(r) for r in LABELLED_ROWS]
        S.emotion_distribution(rows)
        assert [r['emotion'] for r in rows] == ['Joy', 'Sadness', 'Joy', 'Neutral', 'Joy']


class TestTendencyDistribution:
    def test_counts_follow_first_seen_label_order(self):
        dist = S.tendency_distribution(LABELLED_ROWS)
        assert dist['labels'] == ['Positive', 'Negative', 'Neutral']
        assert dist['values'] == [2, 1, 1]

    def test_missing_tendency_keys_are_skipped(self):
        rows = [{'tendency': 'Positive'}, {'emotion': 'Joy'}, {'tendency': ''}]
        assert S.tendency_distribution(rows) == {'labels': ['Positive'], 'values': [1]}

    def test_empty_input(self):
        assert S.tendency_distribution([]) == {'labels': [], 'values': []}

    def test_both_distributions_share_a_shape(self):
        assert set(S.emotion_distribution(LABELLED_ROWS)) == set(S.tendency_distribution(LABELLED_ROWS)) == {
            'labels', 'values'}
