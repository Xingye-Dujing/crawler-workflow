"""Tests for the cleaning/transform toolbox in services/data_analysis.py.

This is the code behind the "Analysis" node's step list, and the pipeline
report is what the console shows the user after a run, so the tests concentrate
on the two things a workflow author cannot debug by eye:

- *missing configuration must not destroy data*: an op whose column or bound is
  absent returns the frame untouched (or raises a named error), never silently
  drops rows, and
- *what the report claims must be what happened* (rows_before / rows_after /
  rows_removed for every step, in order).
"""
import pandas as pd
import pytest

from services.data_analysis import DataAnalysisService as D
from services.data_analysis import UnknownOperationError

pytestmark = pytest.mark.unit


OPERATIONS = [
    'drop_null', 'fill_null', 'drop_duplicates', 'filter_rows', 'select_columns', 'rename_columns',
    'strip_whitespace', 'convert_type', 'sort_rows', 'sample_rows', 'groupby_agg', 'join_tables',
    'column_calc', 'bin_column',
]


@pytest.fixture
def df():
    return pd.DataFrame({
        '名称': ['  三亚攻略  ', '海口美食', '三亚潜水', None],
        '点赞': ['12', '30', None, '3'],
        '作者': ['甲', '乙', '甲', '乙'],
    })


# ─── registry / pipeline ───────────────────────────────────────────────


class TestRegistry:
    def test_registry_exposes_exactly_the_documented_operations(self):
        assert sorted(D._operations()) == sorted(OPERATIONS)

    def test_registry_entries_take_the_frame_first(self):
        import inspect

        for name, func in D._operations().items():
            params = list(inspect.signature(func).parameters)
            assert params[0] == 'df', name
            assert callable(func), name

    @pytest.mark.parametrize('op, params', [
        ('drop_null', {}),
        ('fill_null', {'value': 'x'}),
        ('drop_duplicates', {}),
        ('filter_rows', {'column': '作者', 'op': 'eq', 'value': '甲'}),
        ('select_columns', {'columns': ['作者']}),
        ('rename_columns', {'mapping': {'作者': 'who'}}),
        ('strip_whitespace', {}),
        ('convert_type', {'column': '点赞', 'dtype': 'str'}),
        ('sort_rows', {'column': '点赞'}),
        ('sample_rows', {'n': 2}),
        ('groupby_agg', {'group_col': '作者', 'agg_col': '点赞', 'agg_func': 'count'}),
        ('join_tables', {'other_df': pd.DataFrame({'作者': ['甲'], '城市': ['海口']}),
                         'left_on': '作者', 'right_on': '作者', 'how': 'left'}),
        ('column_calc', {'new_col': 'twice', 'expr': '点赞 * 2'}),
        ('bin_column', {'column': '点赞', 'bins': [0, 5, 10]}),
    ])
    def test_every_registered_operation_is_reachable_from_the_pipeline(self, op, params):
        frame = pd.DataFrame({'点赞': [1, 2, 3], '作者': ['甲', '甲', '乙']})
        result, report = D.run_pipeline(frame, [{'op': op, 'params': params}])
        assert isinstance(result, pd.DataFrame)
        assert report[0]['op'] == op
        assert report[0]['rows_before'] == 3

    def test_pipeline_chains_steps_in_order(self, df):
        steps = [
            {'op': 'drop_null', 'params': {'columns': ['名称']}},
            {'op': 'strip_whitespace', 'params': {}},
            {'op': 'filter_rows', 'params': {'column': '名称', 'op': 'contains', 'value': '三亚'}},
        ]
        result, report = D.run_pipeline(df, steps)
        assert result['名称'].tolist() == ['三亚攻略', '三亚潜水']
        assert [r['rows_before'] for r in report] == [4, 3, 3]
        assert [r['rows_after'] for r in report] == [3, 3, 2]
        assert [r['rows_removed'] for r in report] == [1, 0, 1]
        assert all(r['params'] == steps[i]['params'] for i, r in enumerate(report))

    def test_unknown_operation_is_refused_by_name(self, df):
        with pytest.raises(UnknownOperationError, match='Unknown analysis operation: tidy'):
            D.run_pipeline(df, [{'op': 'tidy', 'params': {}}])

    def test_no_steps_is_a_no_op(self, df):
        result, report = D.run_pipeline(df, [])
        assert result is df
        assert report == []
        assert D.run_pipeline(df, None)[1] == []


class TestInspect:
    def test_reports_shape_nulls_and_duplicates(self):
        frame = pd.DataFrame({'a': ['x', 'x', None], 'b': [1, 2, 3]})
        report = D.inspect(frame)
        assert report['rows'] == 3
        assert report['columns'] == ['a', 'b']
        assert report['null_counts'] == {'a': 1, 'b': 0}
        assert report['duplicate_rows'] == 0
        assert set(report['dtypes']) == {'a', 'b'}

    def test_empty_frame_still_describes_itself(self):
        report = D.inspect(pd.DataFrame(columns=['a']))
        assert report['rows'] == 0
        assert report['columns'] == ['a']
        assert report['duplicate_rows'] == 0


# ─── row-level operations ──────────────────────────────────────────────


class TestRows:
    def test_drop_null_treats_empty_text_as_missing(self):
        frame = pd.DataFrame({'a': ['x', '', 'z']})
        assert D.drop_null(frame)['a'].tolist() == ['x', 'z']

    def test_drop_null_how_all_only_removes_fully_empty_rows(self):
        frame = pd.DataFrame({'a': ['x', None, None], 'b': ['1', '2', None]})
        assert D.drop_null(frame, how='all').shape[0] == 2

    def test_drop_null_ignores_unknown_columns(self):
        frame = pd.DataFrame({'a': ['x', 'y'], 'b': [None, 'z']})
        assert D.drop_null(frame, columns=['nope']).shape[0] == 1
        assert D.drop_null(frame, columns=['a']).shape[0] == 2

    def test_fill_null_with_a_value(self):
        frame = pd.DataFrame({'a': ['x', '', None]})
        assert D.fill_null(frame, columns=['a'], value='-')['a'].tolist() == ['x', '-', '-']

    @pytest.mark.parametrize('method, expected', [('ffill', ['x', 'x', 'z']), ('bfill', ['x', 'z', 'z'])])
    def test_fill_null_with_a_direction(self, method, expected):
        frame = pd.DataFrame({'a': ['x', None, 'z']})
        assert D.fill_null(frame, columns=['a'], method=method)['a'].tolist() == expected

    @pytest.mark.parametrize('method, expected', [('pad', ['x', 'x', 'z']), ('backfill', ['x', 'z', 'z'])])
    def test_fill_null_accepts_pandas_aliases(self, method, expected):
        frame = pd.DataFrame({'a': ['x', None, 'z']})
        assert D.fill_null(frame, columns=['a'], method=method)['a'].tolist() == expected

    def test_fill_null_covers_every_column_by_default(self):
        frame = pd.DataFrame({'a': [None], 'b': [None]})
        filled = D.fill_null(frame, value=0)
        assert filled['a'].tolist() == [0] and filled['b'].tolist() == [0]

    def test_drop_duplicates_keeps_first_by_default(self):
        frame = pd.DataFrame({'a': ['x', 'x', 'y']})
        assert D.drop_duplicates(frame)['a'].tolist() == ['x', 'y']

    def test_drop_duplicates_keep_last_and_subset(self):
        frame = pd.DataFrame({'a': ['x', 'x', 'y'], 'b': [1, 2, 3]})
        assert D.drop_duplicates(frame, columns=['a'], keep='last')['b'].tolist() == [2, 3]

    @pytest.mark.parametrize('column, op, value, expected', [
        ('作者', 'eq', '甲', ['甲', '甲']),
        ('作者', 'ne', '甲', ['乙', '乙']),
        ('名称', 'contains', '三亚', ['甲', '甲']),
        ('名称', 'not_contains', '三亚', ['乙', '乙']),
        ('名称', 'is_null', None, ['乙']),
        ('名称', 'not_null', None, ['甲', '乙', '甲']),
    ])
    def test_filter_text_operators(self, column, op, value, expected):
        frame = pd.DataFrame({'名称': ['三亚攻略', '海口', None, '三亚潜水'], '作者': ['甲', '乙', '乙', '甲']})
        assert D.filter_rows(frame, column, op, value)['作者'].tolist() == expected

    @pytest.mark.parametrize('op, bound, expected', [
        ('gt', '5', ['12', '30']),
        ('gte', '12', ['12', '30']),
        ('lt', '5', ['3']),
        ('lte', '3', ['3']),
    ])
    def test_filter_numeric_operators_compare_as_numbers(self, op, bound, expected, df):
        assert D.filter_rows(df, '点赞', op, bound)['点赞'].tolist() == expected

    def test_filter_membership_operators_accept_a_comma_string(self):
        frame = pd.DataFrame({'t': ['a', 'b', 'c']})
        assert D.filter_rows(frame, 't', 'in', 'a, b')['t'].tolist() == ['a', 'b']
        assert D.filter_rows(frame, 't', 'not_in', ['a'])['t'].tolist() == ['b', 'c']

    def test_filter_on_a_missing_column_changes_nothing(self, df):
        assert D.filter_rows(df, 'nope', 'eq', 'x') is df

    def test_filter_with_a_non_numeric_bound_raises(self, df):
        with pytest.raises(UnknownOperationError, match='needs a numeric value'):
            D.filter_rows(df, '点赞', 'gt', '很多')

    def test_filter_with_an_unknown_operator_raises(self, df):
        with pytest.raises(UnknownOperationError, match='Unknown filter operator: regexp'):
            D.filter_rows(df, '名称', 'regexp', '三亚')

    def test_filter_resets_the_index(self, df):
        out = D.filter_rows(df, '作者', 'eq', '乙')
        assert out.index.tolist() == [0, 1]


# ─── column-level operations ───────────────────────────────────────────


class TestColumns:
    def test_select_columns_keeps_the_requested_order(self):
        frame = pd.DataFrame({'a': [1], 'b': [2], 'c': [3]})
        assert list(D.select_columns(frame, ['c', 'a']).columns) == ['c', 'a']

    def test_select_columns_drops_names_that_do_not_exist(self):
        frame = pd.DataFrame({'a': [1], 'b': [2]})
        assert list(D.select_columns(frame, ['b', 'zz']).columns) == ['b']

    def test_select_columns_with_nothing_selectable_returns_the_frame(self, df):
        assert D.select_columns(df, ['nope']) is df

    def test_rename_columns(self, df):
        assert list(D.rename_columns(df, {'作者': 'who'}).columns) == ['名称', '点赞', 'who']

    def test_strip_whitespace_leaves_missing_values_alone(self):
        frame = pd.DataFrame({'a': ['  x  ', None, '  y'], 'b': [1, 2, 3]})
        out = D.strip_whitespace(frame)
        assert out['a'].tolist()[0] == 'x' and out['a'].tolist()[2] == 'y'
        assert pd.isna(out['a'].tolist()[1])
        assert out['b'].tolist() == [1, 2, 3]

    def test_strip_whitespace_can_target_one_column(self):
        frame = pd.DataFrame({'a': [' x '], 'b': [' y ']})
        out = D.strip_whitespace(frame, columns=['a'])
        assert out['a'].tolist() == ['x'] and out['b'].tolist() == [' y ']

    def test_convert_type_int_coerces_junk_to_missing(self, df):
        out = D.convert_type(df, '点赞', 'int')
        assert out['点赞'].tolist()[:2] == [12, 30]
        assert pd.isna(out['点赞'].tolist()[2])

    def test_convert_type_datetime(self):
        frame = pd.DataFrame({'d': ['2024-01-01', 'nonsense']})
        out = D.convert_type(frame, 'd', 'datetime')
        assert out['d'].iloc[0].year == 2024
        assert pd.isna(out['d'].iloc[1])

    @pytest.mark.parametrize('raw, expected', [
        ('False', False), ('0', False), ('', False), ('否', False), ('True', True), ('1', True),
    ])
    def test_convert_type_bool_uses_text_semantics(self, raw, expected):
        frame = pd.DataFrame({'v': [raw]}, dtype=object)
        assert D.convert_type(frame, 'v', 'bool')['v'].tolist() == [expected]

    def test_convert_type_bool_handles_real_values(self):
        frame = pd.DataFrame({'v': [True, 0, 1, None]}, dtype=object)
        assert D.convert_type(frame, 'v', 'bool')['v'].tolist() == [True, False, True, False]

    def test_convert_type_falls_back_to_string(self):
        frame = pd.DataFrame({'v': [1, 2]})
        assert D.convert_type(frame, 'v', 'str')['v'].tolist() == ['1', '2']

    def test_convert_type_on_a_missing_column_changes_nothing(self, df):
        assert D.convert_type(df, 'nope', 'int') is df

    def test_convert_type_of_unparseable_text_does_not_raise(self):
        frame = pd.DataFrame({'v': ['abc']})
        out = D.convert_type(frame, 'v', 'int')
        assert pd.isna(out['v'].iloc[0])


class TestReshaping:
    def test_sort_rows_both_directions(self):
        frame = pd.DataFrame({'a': [3, 1, 2]})
        assert D.sort_rows(frame, 'a')['a'].tolist() == [1, 2, 3]
        assert D.sort_rows(frame, 'a', ascending=False)['a'].tolist() == [3, 2, 1]

    def test_sort_rows_on_a_missing_column_changes_nothing(self, df):
        assert D.sort_rows(df, 'nope') is df

    def test_sample_without_a_bound_keeps_everything(self, df):
        assert D.sample_rows(df) is df
        assert D.sample_rows(df, n=None, frac=None) is df

    def test_sample_prefers_n_over_frac(self):
        frame = pd.DataFrame({'a': range(10)})
        assert len(D.sample_rows(frame, n=2, frac=0.9)) == 2

    def test_sample_n_at_or_above_the_frame_size_is_a_no_op(self):
        frame = pd.DataFrame({'a': range(4)})
        assert len(D.sample_rows(frame, n=4)) == 4
        assert len(D.sample_rows(frame, n=99)) == 4
        assert len(D.sample_rows(frame, n=0)) == 0

    @pytest.mark.parametrize('frac, expected', [(1.5, 4), (1.0, 4), (0.5, 2), (0.0, 0), (-2, 0)])
    def test_sample_frac_is_clamped_to_the_unit_interval(self, frac, expected):
        frame = pd.DataFrame({'a': range(4)})
        assert len(D.sample_rows(frame, frac=frac, seed=1)) == expected

    def test_sample_is_reproducible_with_a_seed(self):
        frame = pd.DataFrame({'a': range(20)})
        first = D.sample_rows(frame, n=6, seed=42)['a'].tolist()
        second = D.sample_rows(frame, n=6, seed=42)['a'].tolist()
        assert first == second
        assert len(set(first)) == 6

    def test_groupby_agg_summarises(self):
        frame = pd.DataFrame({'g': ['a', 'b', 'a'], 'v': [1, 2, 3]})
        out = D.groupby_agg(frame, 'g', 'v', 'sum')
        assert dict(zip(out['g'], out['v'], strict=True)) == {'a': 4, 'b': 2}

    def test_groupby_agg_with_a_missing_column_changes_nothing(self, df):
        assert D.groupby_agg(df, 'nope', '点赞') is df
        assert D.groupby_agg(df, '作者', 'nope') is df

    def test_groupby_agg_renames_failure_as_unknown_operation(self):
        frame = pd.DataFrame({'g': ['a', 'b'], 't': ['x', 'y']})
        with pytest.raises(UnknownOperationError, match='groupby_agg\\(mean\\) failed on "t"'):
            D.groupby_agg(frame, 'g', 't', 'mean')

    def test_groupby_agg_sum_over_text_concatenates(self):
        # pandas 3 keeps ``sum`` meaningful for strings (concatenation), so the
        # guard in the source only fires for aggregates the dtype truly rejects.
        frame = pd.DataFrame({'g': ['a', 'a', 'b'], 't': ['x', 'y', 'z']})
        out = D.groupby_agg(frame, 'g', 't', 'sum')
        assert sorted(out['t'].tolist()) == ['xy', 'z']

    def test_join_tables_appends_the_right_frame(self):
        left = pd.DataFrame({'k': [1, 2], 'a': ['x', 'y']})
        right = pd.DataFrame({'k': [1, 2], 'b': ['p', 'q']})
        out = D.join_tables(left, right, left_on='k', right_on='k')
        assert out['b'].tolist() == ['p', 'q']

    def test_join_tables_left_keeps_unmatched_rows(self):
        left = pd.DataFrame({'k': [1, 9]})
        right = pd.DataFrame({'k': [1], 'b': ['p']})
        out = D.join_tables(left, right, how='left', left_on='k', right_on='k')
        assert len(out) == 2 and pd.isna(out['b'].iloc[1])

    @pytest.mark.parametrize('other, left_on, right_on', [
        (None, 'k', 'k'),
        (pd.DataFrame(columns=['k']), 'k', 'k'),
    ])
    def test_join_tables_without_a_right_table_raises(self, other, left_on, right_on):
        with pytest.raises(UnknownOperationError):
            D.join_tables(pd.DataFrame({'k': [1]}), other, left_on=left_on, right_on=right_on)

    def test_join_tables_without_keys_raises(self):
        with pytest.raises(UnknownOperationError):
            D.join_tables(pd.DataFrame({'k': [1]}), pd.DataFrame({'k': [1]}))

    def test_join_tables_names_the_missing_columns(self):
        left = pd.DataFrame({'k': [1]})
        right = pd.DataFrame({'other': [1]})
        with pytest.raises(UnknownOperationError) as excinfo:
            D.join_tables(left, right, left_on='ghost', right_on='nope')
        message = str(excinfo.value)
        assert 'ghost (left)' in message and 'nope (right)' in message

    def test_column_calc_adds_the_derived_column(self):
        frame = pd.DataFrame({'a': [1, 2], 'b': [3, 4]})
        assert D.column_calc(frame, 'c', 'a + b')['c'].tolist() == [4, 6]

    def test_column_calc_swallows_a_bad_expression(self):
        frame = pd.DataFrame({'a': [1, 2]})
        out = D.column_calc(frame, 'c', 'ghost + 1')
        assert list(out.columns) == ['a']

    @pytest.mark.parametrize('new_col, expr', [('', 'a + 1'), ('c', ''), ('', '')])
    def test_column_calc_needs_both_names(self, new_col, expr):
        frame = pd.DataFrame({'a': [1]})
        assert list(D.column_calc(frame, new_col, expr).columns) == ['a']

    def test_column_calc_does_not_mutate_the_input(self):
        frame = pd.DataFrame({'a': [1]})
        D.column_calc(frame, 'c', 'a + 1')
        assert list(frame.columns) == ['a']

    def test_bin_column_labels_the_intervals(self):
        frame = pd.DataFrame({'v': [1, 6, 9]})
        out = D.bin_column(frame, 'v', bins=[0, 5, 10], labels=['lo', 'hi'])
        assert out['v_bin'].tolist() == ['lo', 'hi', 'hi']

    def test_bin_column_intervals_are_right_closed(self):
        frame = pd.DataFrame({'v': [0, 5, 10]})
        out = D.bin_column(frame, 'v', bins=[0, 5, 10], labels=['lo', 'hi'])
        assert pd.isna(out['v_bin'].iloc[0])  # 0 is outside the (0, 5] interval
        assert out['v_bin'].tolist()[1:] == ['lo', 'hi']

    def test_bin_column_uses_a_custom_name_and_default_bins(self):
        frame = pd.DataFrame({'v': range(8)})
        assert 'bucket' in D.bin_column(frame, 'v', new_col='bucket').columns
        assert 'v_bin' in D.bin_column(frame, 'v').columns

    def test_bin_column_swallows_a_bad_bin_definition(self):
        frame = pd.DataFrame({'v': range(5)})
        out = D.bin_column(frame, 'v', bins='oops')
        assert list(out.columns) == ['v']

    def test_bin_column_on_a_missing_column_changes_nothing(self, df):
        assert D.bin_column(df, 'nope', bins=[0, 1]) is df
