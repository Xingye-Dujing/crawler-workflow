"""Tests for analyzers/significance.py — one numeric column compared across a group column.

The result is a single tidy row a preview/chart reads by column name, so the shape has to
hold. The refusals are the load-bearing part: an empty table would settle the node DONE and
hide "this comparison could not be made" behind a green run, so every unanswerable input
must raise by name. The Welch-vs-Student case is pinned explicitly — calling a Welch result
a plain "t-test" without saying so is exactly the silent model-swap this project bans.
"""

import pandas as pd
import pytest
from scipy import stats

from analyzers.significance import SignificanceAnalyzer

pytestmark = pytest.mark.unit

COLUMNS = [
    'method',
    'group_column',
    'value_column',
    'statistic',
    'p_value',
    'n_groups',
    'group_sizes',
    'significant_005',
]


@pytest.fixture
def two_groups():
    # Unequal n and unequal spread, so Welch's t and Student's t genuinely differ.
    return pd.DataFrame({'phase': ['发酵期'] * 3 + ['爆发期'] * 5, 'score': [1, 2, 3, 10, 20, 30, 40, 51]})


@pytest.fixture
def three_groups():
    return pd.DataFrame(
        {
            'phase': ['A'] * 3 + ['B'] * 3 + ['C'] * 4,
            'score': [1, 2, 3, 9, 10, 11, 20, 21, 22, 23],
        }
    )


def _row(result):
    assert list(result.columns) == COLUMNS, 'the result table columns are a downstream contract'
    assert len(result) == 1, 'one comparison yields exactly one row'
    return result.iloc[0].to_dict()


class TestShape:
    def test_one_row_with_the_contract_columns(self, two_groups):
        row = _row(SignificanceAnalyzer.analyze_dataframe(two_groups, 'phase', 'score', 'ttest'))
        assert row['method'] == 'ttest'
        assert row['group_column'] == 'phase'
        assert row['value_column'] == 'score'

    def test_the_input_frame_is_not_mutated(self, two_groups):
        before = two_groups.copy()
        SignificanceAnalyzer.analyze_dataframe(two_groups, 'phase', 'score', 'ttest')
        pd.testing.assert_frame_equal(two_groups, before)


class TestTests:
    def test_ttest_is_welch_not_student(self, two_groups):
        a = two_groups.loc[two_groups['phase'] == '发酵期', 'score'].to_numpy(float)
        b = two_groups.loc[two_groups['phase'] == '爆发期', 'score'].to_numpy(float)
        welch = stats.ttest_ind(a, b, equal_var=False)
        student = stats.ttest_ind(a, b, equal_var=True)
        row = _row(SignificanceAnalyzer.analyze_dataframe(two_groups, 'phase', 'score', 'ttest'))
        assert row['statistic'] == round(float(welch.statistic), 4)
        # The guard against a silent swap: on this unequal-variance data the two differ, so
        # matching Welch and NOT matching Student proves the panel label "Welch's t" is honest.
        assert round(float(welch.statistic), 4) != round(float(student.statistic), 4)
        assert row['statistic'] != round(float(student.statistic), 4)

    def test_anova_matches_scipy(self, three_groups):
        groups = [g['score'].to_numpy(float) for _, g in three_groups.groupby('phase')]
        expected = stats.f_oneway(*groups)
        row = _row(SignificanceAnalyzer.analyze_dataframe(three_groups, 'phase', 'score', 'anova'))
        assert row['n_groups'] == 3
        assert row['statistic'] == round(float(expected.statistic), 4)
        assert row['p_value'] == pytest.approx(float(expected.pvalue))

    def test_mannwhitney_matches_scipy(self, two_groups):
        a = two_groups.loc[two_groups['phase'] == '发酵期', 'score'].to_numpy(float)
        b = two_groups.loc[two_groups['phase'] == '爆发期', 'score'].to_numpy(float)
        expected = stats.mannwhitneyu(a, b, alternative='two-sided')
        row = _row(SignificanceAnalyzer.analyze_dataframe(two_groups, 'phase', 'score', 'mannwhitney'))
        assert row['statistic'] == round(float(expected.statistic), 4)

    def test_kruskal_matches_scipy(self, three_groups):
        groups = [g['score'].to_numpy(float) for _, g in three_groups.groupby('phase')]
        expected = stats.kruskal(*groups)
        row = _row(SignificanceAnalyzer.analyze_dataframe(three_groups, 'phase', 'score', 'kruskal'))
        assert row['statistic'] == round(float(expected.statistic), 4)

    def test_significant_flag_tracks_the_p_value(self, two_groups):
        row = _row(SignificanceAnalyzer.analyze_dataframe(two_groups, 'phase', 'score', 'ttest'))
        assert row['significant_005'] is (row['p_value'] < 0.05)

    def test_overlapping_groups_are_not_significant(self):
        frame = pd.DataFrame({'g': ['x'] * 4 + ['y'] * 4, 'score': [1, 2, 3, 4, 2, 3, 4, 5]})
        row = _row(SignificanceAnalyzer.analyze_dataframe(frame, 'g', 'score', 'ttest'))
        assert row['p_value'] > 0.05
        assert row['significant_005'] is False

    def test_group_sizes_reports_what_it_measured(self, two_groups, three_groups):
        two = _row(SignificanceAnalyzer.analyze_dataframe(two_groups, 'phase', 'score', 'ttest'))
        assert two['group_sizes'] == '3, 5'
        three = _row(SignificanceAnalyzer.analyze_dataframe(three_groups, 'phase', 'score', 'anova'))
        assert three['group_sizes'] == '3, 3, 4'

    def test_nan_and_blank_rows_are_dropped_and_counted(self, two_groups):
        frame = two_groups.copy()
        frame.loc[7, 'score'] = float('nan')  # one usable row removed from the 爆发期 group
        row = _row(SignificanceAnalyzer.analyze_dataframe(frame, 'phase', 'score', 'ttest'))
        assert row['group_sizes'] == '3, 4', 'the dropped NaN row must not be counted as measured'


class TestRefusals:
    def test_no_group_column(self, two_groups):
        with pytest.raises(ValueError):
            SignificanceAnalyzer.analyze_dataframe(two_groups, '', 'score', 'ttest')

    def test_no_value_column(self, two_groups):
        with pytest.raises(ValueError):
            SignificanceAnalyzer.analyze_dataframe(two_groups, 'phase', '', 'ttest')

    def test_missing_group_column_names_the_column(self, two_groups):
        with pytest.raises(ValueError) as caught:
            SignificanceAnalyzer.analyze_dataframe(two_groups, 'nope', 'score', 'ttest')
        assert 'nope' in str(caught.value)

    def test_missing_value_column_names_the_column(self, two_groups):
        with pytest.raises(ValueError) as caught:
            SignificanceAnalyzer.analyze_dataframe(two_groups, 'phase', 'nada', 'ttest')
        assert 'nada' in str(caught.value)

    def test_a_non_numeric_value_column_refuses_by_name(self):
        frame = pd.DataFrame({'phase': ['A', 'A', 'B', 'B'], 'text': ['你好', '世界', 'foo', 'bar']})
        with pytest.raises(ValueError) as caught:
            SignificanceAnalyzer.analyze_dataframe(frame, 'phase', 'text', 'ttest')
        assert 'text' in str(caught.value)

    def test_two_group_method_with_three_groups_refuses_and_points_to_anova(self, three_groups):
        with pytest.raises(ValueError) as caught:
            SignificanceAnalyzer.analyze_dataframe(three_groups, 'phase', 'score', 'ttest')
        assert 'ttest' in str(caught.value)

    def test_single_group_refuses_every_method(self):
        frame = pd.DataFrame({'phase': ['only'] * 4, 'score': [1, 2, 3, 4]})
        for method in ('ttest', 'anova', 'mannwhitney', 'kruskal'):
            with pytest.raises(ValueError):
                SignificanceAnalyzer.analyze_dataframe(frame, 'phase', 'score', method)

    def test_all_blank_group_labels_refuses_instead_of_empty_table(self, two_groups):
        frame = two_groups.copy()
        frame['phase'] = ''
        with pytest.raises(ValueError) as caught:
            SignificanceAnalyzer.analyze_dataframe(frame, 'phase', 'score', 'ttest')
        # The refusal names the group column it could not build any buckets from.
        assert 'phase' in str(caught.value)
