"""Tests for analyzers/anomaly.py — Isolation Forest row scoring.

The node is decorative when it works and confusing when it lies, so the tests
concentrate on the two failure modes that would mislead a user:

- a table too small (or with no numbers at all, or with only the columns the
  user named ruled out) must RAISE: an added column of 0.0 scores reads as "the
  table was checked and is clean", which is a conclusion the node did not earn,
- the same input must give the same answer, because the result is stored as a
  checkpoint and re-read after a resume.
"""

import io

import pandas as pd
import pytest

from analyzers.anomaly import AnomalyDetector

pytestmark = pytest.mark.unit

VALUES = [10, 12, 11, 13, 12, 11, 10, 12, 13, 11, 12, 10, 11, 13, 12, 11, 10, 12, 13, 500]


@pytest.fixture
def df():
    return pd.DataFrame({'点赞': VALUES, '阅读': [v * 2 for v in VALUES], '标题': ['文'] * len(VALUES)})


class TestOutputContract:
    def test_two_columns_are_appended_and_rows_are_kept(self, df):
        result = AnomalyDetector.analyze_dataframe(df)
        assert list(result.columns) == ['点赞', '阅读', '标题', 'anomaly_score', 'is_anomaly']
        assert len(result) == len(df)
        assert result['is_anomaly'].dtype.kind == 'i'
        assert result['anomaly_score'].dtype.kind == 'f'

    def test_scores_and_flags_agree(self, df):
        result = AnomalyDetector.analyze_dataframe(df)
        flagged = result[result['is_anomaly'] == 1]
        assert not flagged.empty
        assert flagged['anomaly_score'].min() > result[result['is_anomaly'] == 0]['anomaly_score'].max()

    def test_the_input_frame_is_not_mutated(self, df):
        AnomalyDetector.analyze_dataframe(df)
        assert list(df.columns) == ['点赞', '阅读', '标题']


class TestGuards:
    """Each of these used to answer with a full table of 0.0 scores — a clean
    bill of health from a node that computed nothing."""

    @pytest.mark.parametrize('rows', [0, 1, 3, 4])
    def test_a_table_too_small_to_score_is_refused(self, rows):
        frame = pd.DataFrame({'v': [9999] * rows})
        with pytest.raises(ValueError) as caught:
            AnomalyDetector.analyze_dataframe(frame)
        assert str(rows) in str(caught.value), 'the message must say how few rows there were'
        assert str(AnomalyDetector.MIN_ROWS) in str(caught.value)

    def test_a_table_without_numbers_is_refused(self):
        frame = pd.DataFrame({'标题': ['甲'] * 10, '正文': ['乙'] * 10})
        with pytest.raises(ValueError):
            AnomalyDetector.analyze_dataframe(frame)

    def test_naming_only_text_columns_is_refused_by_name(self, df):
        """A wrong setting has to be told apart from an empty result set — and it
        has to name the column the user should fix."""
        with pytest.raises(ValueError) as caught:
            AnomalyDetector.analyze_dataframe(df, columns=['标题'])
        assert '标题' in str(caught.value)

    def test_a_mixed_selection_scores_the_usable_part_and_says_what_it_dropped(self, df, caplog):
        with caplog.at_level('WARNING'):
            result = AnomalyDetector.analyze_dataframe(df, columns=['点赞', '标题'])
        assert len(result) == len(df)
        assert result.loc[result['is_anomaly'] == 1, '点赞'].tolist() == [500], 'the numeric column still scored'
        assert '标题' in caplog.text, 'the dropped column must be named, not silently discarded'

    def test_missing_values_are_treated_as_zero_not_as_errors(self):
        frame = pd.DataFrame({'v': [1.0, 2.0, None, 3.0, 2.0, 1.0, 2.0, None]})
        result = AnomalyDetector.analyze_dataframe(frame)
        assert len(result) == 8
        assert result['is_anomaly'].isin([0, 1]).all()


class TestDetection:
    def test_the_obvious_outlier_is_the_one_flagged(self, df):
        result = AnomalyDetector.analyze_dataframe(df)
        assert result.loc[result['is_anomaly'] == 1, '点赞'].tolist() == [500]

    @pytest.mark.parametrize('contamination, minimum, maximum', [(0.05, 0, 2), (0.1, 1, 4), (0.4, 3, 10)])
    def test_contamination_moves_the_flag_count(self, df, contamination, minimum, maximum):
        flagged = int(AnomalyDetector.analyze_dataframe(df, contamination=contamination)['is_anomaly'].sum())
        assert minimum <= flagged <= maximum

    def test_selecting_one_column_ignores_the_others(self, df):
        subset = AnomalyDetector.analyze_dataframe(df, columns=['点赞'])
        alone = AnomalyDetector.analyze_dataframe(df[['点赞']])
        assert subset['is_anomaly'].tolist() == alone['is_anomaly'].tolist()

    def test_constant_columns_produce_no_anomalies(self):
        frame = pd.DataFrame({'v': [7] * 20})
        assert set(AnomalyDetector.analyze_dataframe(frame)['is_anomaly']) == {0}


class TestDeterminism:
    def test_the_same_frame_scores_identically_twice(self, df):
        first = AnomalyDetector.analyze_dataframe(df, random_state=42)
        second = AnomalyDetector.analyze_dataframe(df, random_state=42)
        pd.testing.assert_frame_equal(first, second)

    def test_a_resumed_run_sees_the_same_table(self, df):
        original = AnomalyDetector.analyze_dataframe(df)
        # A checkpoint is stored as JSON rows, so the flags must survive that.
        reloaded = pd.read_json(io.StringIO(original.to_json(orient='records')), dtype=False)
        assert reloaded['is_anomaly'].astype(int).tolist() == original['is_anomaly'].tolist()
