"""Tests for analyzers/correlation.py — pairwise numeric correlation table.

The result is a *tidy long table* a chart node reads by column name, so the
shape has to hold even when nothing can be computed (fewer than two numeric
columns). Ordering is part of the contract too: the UI shows the top pairs
first, so absolute strength must be descending.
"""

import pandas as pd
import pytest

from analyzers.correlation import CorrelationAnalyzer

pytestmark = pytest.mark.unit

COLUMNS = ['col1', 'col2', 'method', 'correlation', 'abs_correlation']


@pytest.fixture
def df():
    return pd.DataFrame(
        {
            '点赞': [1, 2, 3, 4, 5, 6, 7, 8],
            '收藏': [2, 4, 6, 8, 10, 12, 14, 16],
            '差评': [8, 7, 6, 5, 4, 3, 2, 1],
            '评论': [5, 3, 8, 1, 9, 2, 7, 4],
            '标题': ['文'] * 8,
        }
    )


class TestShape:
    def test_every_unordered_pair_appears_once(self, df):
        result = CorrelationAnalyzer.analyze_dataframe(df)
        assert list(result.columns) == COLUMNS
        assert len(result) == 6  # C(4, 2)
        assert not (result['col1'] == result['col2']).any()
        pairs = {frozenset(row) for row in result[['col1', 'col2']].values.tolist()}
        assert len(pairs) == 6

    def test_abs_correlation_mirrors_the_signed_value(self, df):
        result = CorrelationAnalyzer.analyze_dataframe(df)
        assert (result['abs_correlation'] == result['correlation'].abs()).all()

    def test_rows_are_sorted_by_absolute_strength(self, df):
        values = CorrelationAnalyzer.analyze_dataframe(df)['abs_correlation'].tolist()
        assert values == sorted(values, reverse=True)

    @pytest.mark.parametrize(
        'frame',
        [
            pd.DataFrame({'a': [1, 2, 3]}),
            pd.DataFrame({'t': ['x', 'y']}),
            pd.DataFrame({'a': [1], 'b': ['x']}),
            pd.DataFrame(columns=['a', 'b']),
        ],
    )
    def test_without_two_numeric_columns_the_table_is_empty_but_well_shaped(self, frame):
        result = CorrelationAnalyzer.analyze_dataframe(frame)
        assert list(result.columns) == COLUMNS
        assert result.empty

    def test_the_input_frame_is_not_mutated(self, df):
        before = df.copy()
        CorrelationAnalyzer.analyze_dataframe(df)
        pd.testing.assert_frame_equal(df, before)


class TestDetection:
    def test_an_obvious_positive_pair_is_first(self, df):
        result = CorrelationAnalyzer.analyze_dataframe(df)
        top = result.iloc[0]
        assert {'点赞', '收藏'} == {top['col1'], top['col2']}
        assert top['correlation'] == 1.0

    def test_an_obvious_negative_pair_is_detected(self, df):
        result = CorrelationAnalyzer.analyze_dataframe(df)
        pair = result[result.apply(lambda r: {r['col1'], r['col2']} == {'点赞', '差评'}, axis=1)]
        assert pair['correlation'].iloc[0] == -1.0
        assert pair['abs_correlation'].iloc[0] == 1.0

    def test_a_weak_pair_is_kept_only_when_the_floor_allows_it(self, df):
        strict = CorrelationAnalyzer.analyze_dataframe(df, min_abs=0.99)
        assert set(strict['col1']) | set(strict['col2']) == {'点赞', '收藏', '差评'}
        assert '评论' not in set(strict['col1']) | set(strict['col2'])
        assert len(strict) < len(CorrelationAnalyzer.analyze_dataframe(df))

    def test_a_floor_above_one_filters_everything_out(self, df):
        assert CorrelationAnalyzer.analyze_dataframe(df, min_abs=1.5).empty

    @pytest.mark.parametrize('method', ['pearson', 'spearman', 'kendall'])
    def test_rank_methods_keep_the_monotonic_pairs_perfect(self, df, method):
        result = CorrelationAnalyzer.analyze_dataframe(df, method=method)
        assert set(result['method']) == {method}
        perfect = result[result['abs_correlation'] == 1.0]
        assert {frozenset(row) for row in perfect[['col1', 'col2']].values.tolist()} >= {
            frozenset(('点赞', '收藏')),
            frozenset(('点赞', '差评')),
        }

    def test_an_unknown_method_is_pandas_business(self, df):
        with pytest.raises(ValueError):
            CorrelationAnalyzer.analyze_dataframe(df, method='not-a-method')


class TestColumnSelection:
    def test_only_the_requested_numeric_columns_are_compared(self, df):
        result = CorrelationAnalyzer.analyze_dataframe(df, columns=['点赞', '收藏'])
        assert result[['col1', 'col2']].values.tolist() == [['点赞', '收藏']]

    def test_non_numeric_names_in_the_selection_are_dropped(self, df):
        assert CorrelationAnalyzer.analyze_dataframe(df, columns=['点赞', '标题']).empty

    def test_selecting_one_of_two_columns_leaves_nothing_to_compare(self, df):
        assert CorrelationAnalyzer.analyze_dataframe(df, columns=['点赞']).empty

    def test_a_constant_column_produces_no_pairs(self):
        frame = pd.DataFrame({'a': [1, 2, 3, 4], 'b': [7, 7, 7, 7], 'c': [4, 3, 2, 1]})
        result = CorrelationAnalyzer.analyze_dataframe(frame)
        assert set(result['col1']) | set(result['col2']) == {'a', 'c'}
