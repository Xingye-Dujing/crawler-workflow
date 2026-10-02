"""Tests for the cleaning/transform toolbox in services/data_analysis.py.

This is the code behind the "Analysis" node's step list, and the pipeline
report is what the console shows the user after a run, so the tests concentrate
on the two things a workflow author cannot debug by eye:

- *missing configuration must not destroy data*: a step that names no column, or a
  column this table does not have, is refused by that name before it runs (see
  :class:`TestTheStepGateRefusesWhatItCannotDo`), and a step whose blank means
  "every column" is inert rather than a filter, and
- *what the report claims must be what happened* (rows_before / rows_after /
  rows_removed for every step, in order).

A second half grew here: the operator vocabulary itself. The browser's dropdowns,
this module's own list and the service's ``if/elif`` chains were three unlinked
copies, and every filter operator but eight had never been swept on a real numeric
column, on a text column or on a column that is not there.
"""

import ast
import re
from pathlib import Path

import pandas as pd
import pytest

import services.data_analysis as _data_analysis_module
from services.data_analysis import DataAnalysisService as D
from services.data_analysis import UnknownOperationError

pytestmark = pytest.mark.unit


OPERATIONS = [
    'drop_null',
    'fill_null',
    'drop_duplicates',
    'dedupe_similar',
    'filter_rows',
    'select_columns',
    'rename_columns',
    'strip_whitespace',
    'convert_type',
    'sort_rows',
    'sample_rows',
    'groupby_agg',
    'join_tables',
    'column_calc',
    'bin_column',
    'extract_time',
    'bin_time',
    'topic_model',
    'sentiment_evolution',
]

# ─── reading the names out of the real sources ─────────────────────────
#
# The operator vocabulary existed in three unlinked places: this module's
# ``OPERATIONS`` literal, the ``if op == …`` chains inside the service, and three
# ``var … = […]`` arrays the browser builds its dropdowns from. Nothing connected
# them, so adding an operator to the service left the panel silent about it — and
# adding one to the panel made a node raise. These helpers read the *sources* so
# the assertions below compare names without becoming a fourth copy of them.

DATA_ANALYSIS_PY = Path(_data_analysis_module.__file__)
WORKFLOW_JS = Path(__file__).resolve().parents[2] / 'backend' / 'static' / 'js' / 'workflow.js'


def _source_walk(node):
    """Pre-order (i.e. source order) walk — ``ast.walk`` is breadth-first, which
    would reorder an ``elif`` chain whose branches nest ever deeper."""
    yield node
    for child in ast.iter_child_nodes(node):
        yield from _source_walk(child)


def _compared_literals(function_name: str, subject: str) -> list:
    """Every string literal ``function_name`` compares ``subject`` against, in source order.

    This is how the module names the filter operators and the convertible types
    without hand-listing them again: the ``if/elif`` chain in the service *is* the
    registry the browser has to agree with.
    """
    tree = ast.parse(DATA_ANALYSIS_PY.read_text(encoding='utf-8'))
    function = next(
        (node for node in _source_walk(tree) if isinstance(node, ast.FunctionDef) and node.name == function_name),
        None,
    )
    assert function is not None, f'{function_name} is gone from data_analysis.py'
    names = []
    for node in _source_walk(function):
        if not isinstance(node, ast.Compare) or not isinstance(node.left, ast.Name):
            continue
        if node.left.id != subject or not all(isinstance(op, (ast.Eq, ast.In)) for op in node.ops):
            continue
        for comparator in node.comparators:
            values = comparator.elts if isinstance(comparator, ast.Tuple) else [comparator]
            names.extend(
                value.value for value in values if isinstance(value, ast.Constant) and isinstance(value.value, str)
            )
    return names


def _js_array(name: str) -> list:
    """The string literals of workflow.js's ``var NAME = […];`` dropdown source."""
    match = re.search(rf'var {name} = \[([^\]]*)\];', WORKFLOW_JS.read_text(encoding='utf-8'))
    assert match, f'{name} is no longer a flat literal array in workflow.js'
    return re.findall(r"'([^']*)'", match.group(1))


@pytest.fixture
def df():
    return pd.DataFrame(
        {
            '名称': ['  三亚攻略  ', '海口美食', '三亚潜水', None],
            '点赞': ['12', '30', None, '3'],
            '作者': ['甲', '乙', '甲', '乙'],
        }
    )


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

    @pytest.mark.parametrize(
        'op, params',
        [
            ('drop_null', {}),
            ('fill_null', {'value': 'x'}),
            ('drop_duplicates', {}),
            ('dedupe_similar', {'column': '作者'}),
            ('filter_rows', {'column': '作者', 'op': 'eq', 'value': '甲'}),
            ('select_columns', {'columns': ['作者']}),
            ('rename_columns', {'mapping': {'作者': 'who'}}),
            ('strip_whitespace', {}),
            ('convert_type', {'column': '点赞', 'dtype': 'str'}),
            ('sort_rows', {'column': '点赞'}),
            ('sample_rows', {'n': 2}),
            ('groupby_agg', {'group_col': '作者', 'agg_col': '点赞', 'agg_func': 'count'}),
            (
                'join_tables',
                {
                    'other_df': pd.DataFrame({'作者': ['甲'], '城市': ['海口']}),
                    'left_on': '作者',
                    'right_on': '作者',
                    'how': 'left',
                },
            ),
            ('column_calc', {'new_col': 'twice', 'expr': '点赞 * 2'}),
            ('bin_column', {'column': '点赞', 'bins': [0, 5, 10]}),
            ('extract_time', {'column': '时间', 'new_col': '日期', 'part': 'date'}),
            (
                'bin_time',
                {'column': '时间', 'new_col': '阶段', 'edges': ['2024-05-01', '2024-05-08'], 'labels': ['前']},
            ),
            ('topic_model', {'column': '正文', 'n_topics': 2, 'topn': 3}),
            ('sentiment_evolution', {'column': '作者'}),
        ],
    )
    def test_every_registered_operation_is_reachable_from_the_pipeline(self, op, params):
        # Carries a timestamp and a text column as well as the numeric/categorical pair the
        # original steps needed: an op that cannot be reached with real inputs would pass a
        # registry check and fail on the canvas.
        frame = pd.DataFrame(
            {
                '点赞': [1, 2, 3],
                '作者': ['甲', '甲', '乙'],
                '时间': ['2024-05-02 10:00', '2024-05-03 11:00', '2024-05-09 12:00'],
                '正文': ['服务太差了', '服务太差了', '今天天气不错'],
            }
        )
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

    @pytest.mark.parametrize(
        'column, op, value, expected',
        [
            ('作者', 'eq', '甲', ['甲', '甲']),
            ('作者', 'ne', '甲', ['乙', '乙']),
            ('名称', 'contains', '三亚', ['甲', '甲']),
            ('名称', 'not_contains', '三亚', ['乙', '乙']),
            ('名称', 'is_null', None, ['乙']),
            ('名称', 'not_null', None, ['甲', '乙', '甲']),
        ],
    )
    def test_filter_text_operators(self, column, op, value, expected):
        frame = pd.DataFrame({'名称': ['三亚攻略', '海口', None, '三亚潜水'], '作者': ['甲', '乙', '乙', '甲']})
        assert D.filter_rows(frame, column, op, value)['作者'].tolist() == expected

    @pytest.mark.parametrize(
        'op, bound, expected',
        [
            ('gt', '5', ['12', '30']),
            ('gte', '12', ['12', '30']),
            ('lt', '5', ['3']),
            ('lte', '3', ['3']),
        ],
    )
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
        """A column whose rows were written by different hands must convert, and must not lecture.

        Two things are pinned here. The first is the shape a 转换类型 datetime actually meets: a
        scraped/cleaned table carries a full timestamp in one row and a bare date in the next, so there is
        **no single format** for pandas to apply — it infers one, fails, and then parses element by
        element anyway while warning that it did. That fallback is the behaviour, so it is now declared
        (``format='mixed'``) instead of discovered by accident, and the warning the user cannot act on is
        gone. The second is the junk row: an unparseable value becomes missing, never a raised node.
        """
        import warnings

        frame = pd.DataFrame({'d': ['2024-01-01', '2024-01-02 03:04:05', 'nonsense']})
        with warnings.catch_warnings():
            warnings.simplefilter('error', UserWarning)
            out = D.convert_type(frame, 'd', 'datetime')
        assert out['d'].iloc[0].year == 2024 and out['d'].iloc[0].day == 1
        assert out['d'].iloc[1].day == 2 and out['d'].iloc[1].hour == 3
        assert pd.isna(out['d'].iloc[1]) is False, 'a real timestamp must not be coerced away'
        assert pd.isna(out['d'].iloc[2])

    @pytest.mark.parametrize(
        'raw, expected',
        [
            ('False', False),
            ('0', False),
            ('', False),
            ('否', False),
            ('True', True),
            ('1', True),
        ],
    )
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

    @pytest.mark.parametrize(
        'other, left_on, right_on',
        [
            (None, 'k', 'k'),
            (pd.DataFrame(columns=['k']), 'k', 'k'),
        ],
    )
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

    def test_column_calc_refuses_an_expression_it_cannot_run(self):
        """Was `test_column_calc_swallows_a_bad_expression`, and the change is the point.

        Swallowing it settled the node DONE with the named column missing and one line in
        ``logs/`` as the only trace; the failure then surfaced two nodes later as an empty
        chart, on a run that had already paid for its crawl. Every other step in this
        service refuses a column it cannot find, and this one can only be checked by
        running it — so its failure IS the refusal.
        """
        frame = pd.DataFrame({'a': [1, 2]})
        with pytest.raises(UnknownOperationError) as err:
            D.column_calc(frame, 'c', 'ghost + 1')
        message = str(err.value)
        assert 'c' in message and 'ghost + 1' in message, message

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

    @pytest.mark.parametrize(
        'bins, labels',
        [
            ('oops', None),  # not a bin definition at all
            ([10, 5, 0], None),  # edges in the wrong order
            ([0, 5, 10], ['a']),  # one bucket short of edges
        ],
    )
    def test_bin_column_refuses_a_bin_definition_it_cannot_apply(self, bins, labels):
        """Was `test_bin_column_swallows_a_bad_bin_definition`, and the change is the point:
        the node used to settle DONE with no new column and a line in ``logs/`` as the only
        trace, so the user's next sight of the problem was a chart grouped on a column that
        does not exist.
        """
        frame = pd.DataFrame({'v': range(5)})
        with pytest.raises(UnknownOperationError) as err:
            D.bin_column(frame, 'v', bins=bins, labels=labels)
        assert 'v' in str(err.value), str(err.value)

    def test_bin_column_on_a_missing_column_changes_nothing(self, df):
        assert D.bin_column(df, 'nope', bins=[0, 1]) is df


# ─── the operator vocabulary shared with the browser ───────────────────


class TestOperatorNameLists:
    """ONE place where the browser's operator names meet Python's registry.

    The 分析 node's dropdowns are three flat literal arrays in
    ``backend/static/js/workflow.js`` (``ANALYSIS_OPS`` / ``FILTER_OPS`` /
    ``CONVERT_TYPES``); Python keeps its own answers — ``_operations()`` for the
    steps, the ``if op == …`` chain inside ``filter_rows`` for the comparisons,
    the ``if dtype == …`` chain inside ``convert_type`` for the types. They were
    never compared, so the two halves drifted in both directions: an operator the
    service gained stayed invisible to the user, and an operator the panel offered
    for a service that had none made the node die on ``Unknown filter operator``.

    The parity is asserted against the *sources* (the AST chain, the JS text), so
    this module's own ``OPERATIONS`` literal cannot quietly become the truth.
    """

    def test_the_panel_and_python_name_the_same_operations(self):
        registry = set(D._operations())
        assert registry == set(OPERATIONS), 'this module must not hold its own opinion'
        assert set(_js_array('ANALYSIS_OPS')) == registry, (
            'the 步骤 dropdown and DataAnalysisService._operations drifted apart'
        )

        # ``filter_rows`` answers a name it does not compare with a refusal, so a
        # panel-only operator is a runtime error rather than a missing feature.
        assert _compared_literals('filter_rows', 'op') == _js_array('FILTER_OPS'), (
            'the 比较方式 dropdown and filter_rows drifted apart'
        )

        # ``convert_type`` compares four names and *falls through* to str for
        # anything else, so 'str' is in the dropdown but never compared; a name in
        # the dropdown that the chain does not compare would silently stringify.
        compared = set(_compared_literals('convert_type', 'dtype'))
        offered = set(_js_array('CONVERT_TYPES'))
        assert offered == compared | {'str'}, 'a dtype the service does not compare is offered anyway'
        assert 'str' not in compared

    def test_no_further_copy_of_the_operation_names_exists(self):
        """A fourth list is how this contract broke before: whoever added an
        operator edited the two copies they could see. Only the panel and this
        module may name the whole set, and both are pinned above.
        """
        root = Path(__file__).resolve().parents[2]
        candidates = (
            list((root / 'backend').rglob('*.py'))
            + list((root / 'backend' / 'static').rglob('*.js'))
            + list((root / 'tests').rglob('*.py'))
        )
        bracketed = re.compile(r'[\[(][^\[\]()]*[\])]', re.DOTALL)
        names = set(OPERATIONS)
        offenders = {}
        for path in candidates:
            if '__pycache__' in path.parts:
                continue
            text = path.read_text(encoding='utf-8', errors='replace')
            for match in bracketed.finditer(text):
                found = {op for op in names if f"'{op}'" in match.group(0) or f'"{op}"' in match.group(0)}
                if len(found) >= 4:
                    offenders.setdefault(path.relative_to(root).as_posix(), set()).update(found)
        assert set(offenders) == {'backend/static/js/workflow.js', 'tests/unit/test_data_analysis.py'}, (
            f'an unlinked copy of the operation names appeared in {sorted(offenders)}'
        )


# ─── every filter operator, on every column shape ──────────────────────

# The sweep frame is deliberately awkward: a real integer column (so a text bound
# cannot match it), text that contains regex metacharacters, an empty cell, and
# Chinese labels the panel's 值 box would carry.
SWEEP = pd.DataFrame(
    {
        'n': [3, 5, 1],
        't': ['甲.', '乙(1)', ''],
        'city': ['北京', '上海', '北京'],
    }
)

# Six rows is enough for all twelve comparison names to be told apart by one
# probe each; three rows only have eight subsets to hand out.
SIGN = pd.DataFrame(
    {
        'n': [3, 5, 1, 3, 9, 7],
        't': ['甲.', '乙(1)', '', '甲', 'x', '3'],
        'city': ['北京', '上海', '北京', None, '广州', '广州'],
    }
)
SIGNATURES = [
    ('eq', 'city', '北京', [3, 1]),
    ('ne', 'city', '北京', [5, 3, 9, 7]),
    ('gt', 'n', '3', [5, 9, 7]),
    ('gte', 'n', '3', [3, 5, 3, 9, 7]),
    ('lt', 'n', '3', [1]),
    ('lte', 'n', '3', [3, 1, 3]),
    ('contains', 't', '甲', [3, 3]),
    ('not_contains', 't', 'x', [3, 5, 1, 3, 7]),
    ('in', 'city', '北京,上海', [3, 5, 1]),
    ('not_in', 't', '3', [3, 5, 1, 3, 9]),
    ('is_null', 'city', None, [3]),
    ('not_null', 'city', None, [3, 5, 1, 9, 7]),
]


class TestEveryFilterOperator:
    """All twelve comparison names the panel offers, none of them untested.

    A node-level case existed for eight of them; ``not_in``, ``gt``, ``lt`` and
    ``lte`` had never been sent by a test that reached the operator through the
    pipeline at all. Each row below is the *measured* answer, including the
    surprises: an integer column never equals the text typed in the 值 box, while
    ``contains`` reads that same text.
    """

    @pytest.mark.parametrize('op', _compared_literals('filter_rows', 'op'))
    def test_a_column_that_is_not_there_is_a_no_op_for_every_operator(self, op):
        """Even an unusable bound is not reached: the column check comes first, so
        a filter on a renamed-away column keeps every row rather than refusing.
        """
        assert D.filter_rows(SWEEP, 'nope', op, 'not-a-number') is SWEEP

    @pytest.mark.parametrize(
        ('op, bound, expected'),
        [
            ('eq', '3', []),
            ('ne', '3', [3, 5, 1]),
            ('gt', '3', [5]),
            ('gte', '3', [3, 5]),
            ('lt', '3', [1]),
            ('lte', '3', [3, 1]),
            ('contains', '3', [3]),
            ('not_contains', '3', [5, 1]),
            ('in', '3, 5', []),
            ('not_in', '3', [3, 5, 1]),
            ('is_null', None, []),
            ('not_null', None, [3, 5, 1]),
        ],
    )
    def test_a_real_integer_column_answers_the_measured_row_set(self, op, bound, expected):
        """The trap this pins: ``gt``/``lt`` coerce the bound to a number and the
        column too, but ``eq`` and ``in`` compare the *text* against integers, so
        序号 等于 3 finds nothing while 序号 大于 3 finds rows. Only ``contains``
        stringifies the column.
        """
        assert D.filter_rows(SWEEP, 'n', op, bound)['n'].tolist() == expected

    @pytest.mark.parametrize(
        ('op, bound, expected'),
        [
            ('eq', '北京', [3, 1]),
            ('ne', '北京', [5]),
            ('gt', '3', []),
            ('gte', '3', []),
            ('lt', '3', []),
            ('lte', '3', []),
            ('contains', '京', [3, 1]),
            ('not_contains', '京', [5]),
            ('in', '北京,上海', [3, 5, 1]),
            ('not_in', '北京', [5]),
            ('is_null', None, []),
            ('not_null', None, [3, 5, 1]),
        ],
    )
    def test_a_text_column_answers_the_measured_row_set(self, op, bound, expected):
        """The four numeric comparisons coerce the *column* with
        ``to_numeric(errors='coerce')``, so on a text column they match nothing
        instead of complaining — the bound is what has to parse.
        """
        assert D.filter_rows(SWEEP, 'city', op, bound)['n'].tolist() == expected

    @pytest.mark.parametrize('op', ['gt', 'gte', 'lt', 'lte'])
    @pytest.mark.parametrize('bound', ['', '   ', 'abc', None, '3, 5', [], {}])
    def test_a_comparison_without_a_number_refuses_by_naming_the_bound(self, op, bound):
        """The refusal is the point: an unparseable bound used to die inside
        ``float()`` with a bare ValueError, and a pipeline that answers "no rows"
        for a typo is indistinguishable from data that really was empty.
        """
        with pytest.raises(UnknownOperationError) as excinfo:
            D.filter_rows(SWEEP, 'n', op, bound)
        assert f'"{op}" needs a numeric value' in str(excinfo.value)

    def test_each_operator_has_an_answer_no_other_operator_gives(self):
        """``in``/``not_in`` and ``is_null``/``not_null`` differ only by a leading
        ``~``, so a copy-paste could make two names answer the same thing and no
        single-op test would notice. Each name here gets one probe, and the twelve
        answers are pairwise different.
        """
        answers = []
        for op, column, bound, expected in SIGNATURES:
            got = D.filter_rows(SIGN, column, op, bound)['n'].tolist()
            assert got == expected, (op, column, bound, got)
            answers.append(tuple(got))
        assert len(set(answers)) == len(SIGNATURES) == len(_compared_literals('filter_rows', 'op'))
        assert {row[0] for row in SIGNATURES} == set(_compared_literals('filter_rows', 'op'))


class TestFilterValueTraps:
    """Three behaviours a panel user cannot predict from the label alone.

    Each is the *current* behaviour, pinned on purpose so a change is a decision
    rather than a surprise (see the controller notes: two of them are bugs).
    """

    def test_contains_reads_the_value_as_a_regular_expression_not_as_text(self):
        """``str.contains`` defaults to ``regex=True``, so a 值 of ``.`` matches
        every row and ``(`` is refused as a broken pattern by the arrow engine.
        The panel's label says 包含 — the user types what they see in the cell.
        """
        assert D.filter_rows(SWEEP, 't', 'contains', '.')['n'].tolist() == [3, 5]
        with pytest.raises(ValueError) as excinfo:
            D.filter_rows(SWEEP, 't', 'contains', '(')
        assert 'regular expression' in str(excinfo.value)

    def test_a_blank_value_under_not_contains_is_an_empty_table(self):
        """Every cell contains the empty string, so the negation keeps nothing:
        choosing 不包含 and leaving 值 empty destroys the whole run rather than
        meaning "no rows excluded".
        """
        assert D.filter_rows(SWEEP, 't', 'not_contains', '')['n'].tolist() == []
        assert D.filter_rows(SWEEP, 't', 'contains', '')['n'].tolist() == [3, 5, 1]

    def test_is_null_treats_an_empty_cell_as_missing_but_a_none_bound_is_not_a_value(self):
        assert D.filter_rows(SWEEP, 't', 'is_null', None)['n'].tolist() == [1]
        assert D.filter_rows(SWEEP, 't', 'not_null', None)['n'].tolist() == [3, 5]
        # The bound is ignored by both, so junk next to it changes nothing.
        assert D.filter_rows(SWEEP, 't', 'is_null', 'anything')['n'].tolist() == [1]

    @pytest.mark.parametrize('bound', ['北京,上海', '北京, 上海', ('北京', '上海'), ['北京', '上海'], {'北京', '上海'}])
    def test_membership_accepts_the_comma_string_the_panel_sends(self, bound):
        """The panel's 值 box can only ever send text — and the service splits it on
        the comma, which is what makes 属于 usable from a form. A list/tuple/set is
        what a JSON caller sends, and both spellings have to agree.
        """
        assert D.filter_rows(SWEEP, 'city', 'in', bound)['n'].tolist() == [3, 5, 1]
        assert D.filter_rows(SWEEP, 'city', 'not_in', bound)['n'].tolist() == []

    @pytest.mark.parametrize('junk', ['', '   ', 'abc', 'regex:*', None, 0, 1e400, [], {}])
    def test_an_operator_name_that_is_not_a_name_is_refused_by_name(self, junk):
        """``filter_rows`` refuses instead of defaulting to ``eq``: the normalizer
        supplies 'eq' when the key is *absent*, so a present-but-wrong value is a
        different mistake and must not quietly become a different comparison.
        """
        with pytest.raises(UnknownOperationError) as excinfo:
            D.filter_rows(SWEEP, 'city', junk, '北京')
        assert 'Unknown filter operator' in str(excinfo.value)


# ─── pipeline order ────────────────────────────────────────────────────


class TestPipelineOrder:
    """``run_pipeline`` is the only code that decides what "then" means.

    A workflow file is a list, so the user's step order is the answer; nothing
    sorts, groups or deduplicates it. These tests pin that a reordering is a
    different pipeline, because a runner that keyed its work by operation name
    would pass every single-step test in this file and still be wrong.
    """

    STEPS = [
        {'op': 'rename_columns', 'params': {'mapping': {'city': '城市'}}},
        {'op': 'filter_rows', 'params': {'column': '城市', 'op': 'contains', 'value': '京'}},
        {'op': 'drop_duplicates', 'params': {'columns': ['n']}},
    ]

    def test_the_report_follows_the_list_in_order_and_keeps_repeated_steps(self):
        steps = self.STEPS + [self.STEPS[1], self.STEPS[1]]
        result, report = D.run_pipeline(SWEEP.copy(), steps)
        assert [step['op'] for step in report] == [step['op'] for step in steps]
        assert [step['params'] for step in report] == [step['params'] for step in steps]
        # The report is per *entry*, not per name: two identical filter steps are
        # two lines, so the console shows what actually ran.
        assert len(report) == 5
        assert list(result.columns) == ['n', 't', '城市']

    def test_the_steps_run_in_list_order_not_in_an_order_of_their_own(self):
        """Renaming first is what lets the following filter see the column.

        The list order decides, so the answer is a fact about the file and not about
        how the runner happens to group its work. Run the other way round, the filter
        asks for a 城市 that is not there yet — and that is now an error rather than
        every row kept, because a pipeline that reports the filter's answer while
        handing back the unfiltered table is the lie this file exists to prevent.
        """
        renamed_then_filtered, _ = D.run_pipeline(SWEEP.copy(), self.STEPS[:2])
        assert renamed_then_filtered['n'].tolist() == [3, 1], 'only the 北京 rows hold 京'
        with pytest.raises(UnknownOperationError) as excinfo:
            D.run_pipeline(SWEEP.copy(), self.STEPS[1::-1])
        assert '城市' in str(excinfo.value), excinfo.value

    def test_a_refused_step_leaves_the_frame_where_it_was(self):
        """Nothing is applied "partially then fixed": the refusal happens before the
        step runs, so the rows a valid prefix produced are what comes back — and an
        exception means the caller must not be shown a table at all.
        """
        steps = self.STEPS[:2] + [{'op': 'sort_rows', 'params': {'column': '不存在', 'ascending': True}}]
        with pytest.raises(UnknownOperationError):
            D.run_pipeline(SWEEP.copy(), steps)

    def test_row_math_is_reported_for_every_step_of_a_shrinking_chain(self):
        steps = [
            {'op': 'filter_rows', 'params': {'column': 'city', 'op': 'eq', 'value': '北京'}},
            {'op': 'sample_rows', 'params': {'n': 1, 'seed': 0}},
        ]
        result, report = D.run_pipeline(SWEEP.copy(), steps)
        assert [(r['rows_before'], r['rows_after'], r['rows_removed']) for r in report] == [(3, 2, 1), (2, 1, 1)]
        assert len(result) == 1

    def test_a_step_that_raises_leaves_the_pipeline_at_that_step(self):
        """Nothing downstream of a refusal runs, and the refusal is the service's
        own message rather than a partially-transformed frame. The *bound* is what
        fails here: a column that is not there is a no-op (pinned above) and would
        let the chain finish on a wrong answer.
        """
        steps = [
            {'op': 'select_columns', 'params': {'columns': ['n', 'city']}},
            {'op': 'filter_rows', 'params': {'column': 'n', 'op': 'gt', 'value': '很多'}},
            {'op': 'sort_rows', 'params': {'column': 'n', 'ascending': False}},
        ]
        with pytest.raises(UnknownOperationError, match='needs a numeric value'):
            D.run_pipeline(SWEEP.copy(), steps)


# ─── deduplication: exact, normalised, and near ────────────────────────


class TestDropDuplicatesModes:
    """Two different questions the same node can ask: "same string" and "same comment".

    A paid comment farm never reposts the *same string* — it adds a tracking link, one
    more emoji code, or re-pastes the forward chain — so exact equality answers only half
    the user's question. What is pinned here is that asking for one mode never silently
    runs the other, and that the normalisation is a comparison key rather than a rewrite.
    """

    FARM = [
        {'正文': '这服务太差了'},
        {'正文': '这服务太差了 https://t.cn/A6xyz'},
        {'正文': '[泪]这服务太差了'},
        {'正文': '完全不同的评论'},
    ]

    def test_exact_matching_sees_four_distinct_rows(self):
        out = D.drop_duplicates(pd.DataFrame(self.FARM), columns=['正文'], mode='exact')
        assert len(out) == 4

    def test_normalised_matching_collapses_a_farms_variations(self):
        out = D.drop_duplicates(pd.DataFrame(self.FARM), columns=['正文'], mode='normalized')
        assert len(out) == 2, 'the three spellings of one comment are one comment'
        assert out.iloc[0]['正文'] == '这服务太差了', 'the first occurrence is what survives'

    def test_the_comparison_key_never_reaches_the_table(self):
        out = D.drop_duplicates(pd.DataFrame(self.FARM), columns=['正文'], mode='normalized')
        assert list(out.columns) == ['正文'], 'a key column downstream would be a leaked implementation detail'

    def test_the_original_text_is_what_survives_not_the_normalised_form(self):
        # The key is lossy by design; the row it identifies must not be.
        frame = pd.DataFrame([{'正文': '这服务太差了 https://t.cn/A6xyz'}])
        out = D.drop_duplicates(frame, columns=['正文'], mode='normalized')
        assert out.iloc[0]['正文'] == '这服务太差了 https://t.cn/A6xyz'

    @pytest.mark.parametrize('mode', ['Exact', 'NORMALIZED', 'fuzzy', 'near'])
    def test_a_mode_the_step_does_not_know_is_refused_by_name(self, mode):
        with pytest.raises(UnknownOperationError) as err:
            D.drop_duplicates(pd.DataFrame(self.FARM), columns=['正文'], mode=mode)
        assert 'drop_duplicates' in str(err.value) and mode in str(err.value)

    def test_a_blank_column_list_still_means_every_column(self):
        out = D.drop_duplicates(pd.DataFrame(self.FARM), mode='normalized')
        assert len(out) == 2, '留空=全部 is a rule of this step, not of one mode'


class TestDedupeSimilar:
    """SimHash near-duplicates, which is the half exact matching cannot reach.

    Every number here is a MEASUREMENT, not a choice, and it is the reason the default is
    not the tightest distance that could be defended: on hand-written Weibo comments a
    one-word rewrite lands 5–18 bits away while two unrelated comments land 26–28. A
    tighter default (3, the narrowest the banding could prove when this was written) finds
    essentially nothing the normalised-exact key had not already found.
    """

    # Measured distance 4: one character swapped for a near-synonym.
    NEAR = [
        {'正文': '这家店的服务态度真的很差，再也不会来了'},
        {'正文': '这家店的服务态度真的很差，再也不会去了'},
        {'正文': '今天天气不错适合出去玩'},
    ]

    def test_a_one_word_edit_is_the_same_comment(self):
        out = D.dedupe_similar(pd.DataFrame(self.NEAR), column='正文')
        assert len(out) == 2
        assert out.iloc[0]['正文'] == '这家店的服务态度真的很差，再也不会来了', 'the first of a group is kept'

    def test_a_distance_that_only_just_reaches_the_pair_still_finds_it(self):
        # The same pair at the narrowest distance that can see it (measured 4), which is
        # what makes the case above a real one rather than an artefact of a loose default.
        out = D.dedupe_similar(pd.DataFrame(self.NEAR), column='正文', max_distance=4)
        assert len(out) == 2

    def test_a_distance_below_the_measured_gap_leaves_the_pair_alone(self):
        # ... and at 3 it does not, which is the measurement this default was chosen from.
        out = D.dedupe_similar(pd.DataFrame(self.NEAR), column='正文', max_distance=3)
        assert len(out) == 3

    def test_unrelated_comments_are_not_collapsed(self):
        frame = pd.DataFrame([{'正文': '今天天气不错'}, {'正文': '这只猫太可爱了'}])
        assert len(D.dedupe_similar(frame, column='正文')) == 2

    def test_a_loose_default_does_not_swallow_unrelated_long_comments(self):
        """The default has to sit BELOW the unrelated band (measured 26–28), or it would
        merge comments on the strength of both being Chinese sentences of similar length.
        """
        frame = pd.DataFrame(
            [
                {'正文': '这家店的服务态度真的很差，我再也不会来了'},
                {'正文': '今天天气不错，适合出去走走看看风景'},
                {'正文': '这个价格买到这样的质量算是很划算了'},
            ]
        )
        assert len(D.dedupe_similar(frame, column='正文')) == 3

    def test_blank_and_artifact_only_rows_are_never_grouped(self):
        """Every comment with no fingerprint of its own hashes to the same value. Treating
        that as a duplicate would delete unrelated empty rows — they are empty, not equal.
        """
        frame = pd.DataFrame([{'正文': '   '}, {'正文': None}, {'正文': '//@张三:'}])
        assert len(D.dedupe_similar(frame, column='正文')) == 3

    def test_a_distance_the_banded_index_cannot_prove_is_refused_by_name(self):
        from services.text_dedupe import MAX_BANDED_DISTANCE

        too_far = MAX_BANDED_DISTANCE + 1
        with pytest.raises(UnknownOperationError) as err:
            D.dedupe_similar(pd.DataFrame(self.NEAR), column='正文', max_distance=too_far)
        assert str(too_far) in str(err.value), str(err.value)

    def test_the_widest_distance_the_index_can_prove_is_accepted(self):
        from services.text_dedupe import MAX_BANDED_DISTANCE

        out = D.dedupe_similar(pd.DataFrame(self.NEAR), column='正文', max_distance=MAX_BANDED_DISTANCE)
        assert len(out) == 2

    def test_a_negative_distance_is_refused_too(self):
        with pytest.raises(UnknownOperationError):
            D.dedupe_similar(pd.DataFrame(self.NEAR), column='正文', max_distance=-1)

    def test_a_column_that_is_not_there_is_a_no_op_like_every_other_step(self):
        frame = pd.DataFrame([{'别的': 'a'}, {'别的': 'b'}])
        out = D.dedupe_similar(frame, column='正文')
        assert list(out.columns) == ['别的'] and len(out) == 2

    def test_the_pipeline_reports_the_rows_it_removed(self):
        steps = [{'op': 'dedupe_similar', 'params': {'column': '正文'}}]
        result, report = D.run_pipeline(pd.DataFrame(self.NEAR), steps)
        assert len(result) == 2
        assert report[0]['rows_removed'] == 1, 'a shrinking step must say how much it shrank'

    def test_the_outcome_is_reproducible_across_runs(self):
        """The fingerprint may not depend on Python's salted ``hash()``: a dedupe that
        grouped differently on every run would make a resumed run disagree with itself.
        """
        frame = pd.DataFrame(self.NEAR)
        first = D.dedupe_similar(frame, column='正文')
        second = D.dedupe_similar(frame, column='正文')
        assert list(first['正文']) == list(second['正文'])


# ─── the event study: when, which subjects, which way the crowd leaned ───


class TestExtractTime:
    """One calendar part out of a timestamp — the floor everything else stands on."""

    def test_the_format_our_own_weibo_crawler_writes_is_read(self):
        """``weibo.py`` keeps the search page's Chinese display stamp for most rows —
        '2022年01月27日 00:59' — and ``pd.to_datetime`` answers every one of them with NaT.
        Measured on a real export: 4000 of 4000 sampled rows are this shape. A time operator
        that cannot read the project's own column is not a time operator, and the failure was
        silent: an empty 日期 column and a green node.
        """
        frame = pd.DataFrame({'发布时间': ['2022年01月27日 00:59', '2022年02月03日 23:59']})
        out = D.extract_time(frame, '发布时间')
        assert list(out['日期']) == ['2022-01-27', '2022-02-03']

    def test_a_column_holding_both_shapes_parses_whole(self):
        """An export where some rows took the absolute path and some did not: folding the
        CJK form first and parsing once keeps every row, where the old single call lost the
        Chinese half."""
        frame = pd.DataFrame({'发布时间': ['2022-01-27 00:59', '2022年01月27日 00:59']})
        out = D.extract_time(frame, '发布时间')
        assert list(out['日期']) == ['2022-01-27', '2022-01-27']

    def test_the_chinese_form_parses_through_convert_type_too(self):
        # The second door onto the same column: a 发布时间 that extract_time reads while
        # convert_type answers NaT for it is the same defect wearing a different control.
        frame = pd.DataFrame({'发布时间': ['2022年01月27日 00:59']})
        out = D.convert_type(frame, '发布时间', 'datetime')
        assert not pd.isna(out.at[0, '发布时间'])

    def test_an_iso_timestamp_becomes_a_day(self):
        frame = pd.DataFrame({'评论时间': ['2024-05-02 13:45', '2024-05-02 23:59', '2024-05-03 00:01']})
        out = D.extract_time(frame, '评论时间')
        assert list(out['日期']) == ['2024-05-02', '2024-05-02', '2024-05-03']

    def test_days_sort_chronologically_as_text(self):
        """The value is text on purpose: it is grouped, exported and charted, and an ISO
        date's lexical order IS its chronological order — so a line chart drawn from it
        runs left to right in time without a separate datetime column."""
        days = ['2024-05-02', '2024-05-19', '2024-05-08']
        assert sorted(days) == ['2024-05-02', '2024-05-08', '2024-05-19']

    def test_a_relative_label_the_site_gave_is_not_guessed_into_a_year(self):
        """Weibo shows "09月26日 21:00" when it has no year. Inventing this year for it
        would move rows between phases, which is the one thing an event study cannot
        survive — so the cell stays empty and the console says how many did."""
        frame = pd.DataFrame({'评论时间': ['2024-05-02 13:45', '09月26日 21:00']})
        out = D.extract_time(frame, '评论时间')
        assert out.at[0, '日期'] == '2024-05-02'
        assert pd.isna(out.at[1, '日期']), 'an unparseable stamp is not a day'

    def test_other_parts_answer_with_numbers(self):
        frame = pd.DataFrame({'时间': ['2024-05-02 13:45']})
        assert D.extract_time(frame, '时间', new_col='月份', part='month').at[0, '月份'] == 5
        assert D.extract_time(frame, '时间', new_col='小时', part='hour').at[0, '小时'] == 13

    def test_a_missing_column_is_a_no_op_like_every_other_step(self):
        frame = pd.DataFrame({'别的': ['a']})
        assert list(D.extract_time(frame, '时间').columns) == ['别的']


class TestBinTime:
    """The lifecycle split. The boundary rules are the whole test."""

    #: The paper's own phases for the 胖猫 event, as (start, end-inclusive) pairs.
    EDGES = ['2024-04-11', '2024-05-02', '2024-05-08', '2024-05-19', '2024-05-26', '2024-07-11']
    LABELS = ['发酵期', '爆发期', '波动期', '二次爆发期', '消退期']

    def _phase_of(self, stamp):
        frame = pd.DataFrame({'评论时间': [stamp]})
        return D.bin_time(frame, '评论时间', edges=self.EDGES, labels=self.LABELS).at[0, '阶段']

    def test_the_five_phases_come_out_of_six_boundaries(self):
        out = D.bin_time(
            pd.DataFrame({'评论时间': ['2024-04-11 00:00', '2024-05-02 08:00', '2024-07-10 23:00']}),
            '评论时间',
            edges=self.EDGES,
            labels=self.LABELS,
        )
        assert list(out['阶段']) == ['发酵期', '爆发期', '消退期']

    def test_the_last_minute_before_a_boundary_stays_in_the_earlier_phase(self):
        """The comparison runs on the calendar DAY, so 5月7日 23:59 is still 爆发期 — the
        paper's phase is "5月2日-5月7日", and a timestamp comparison would have moved that
        row into 波动期 by one minute. Those boundary days are what the study is about."""
        assert self._phase_of('2024-05-07 23:59') == '爆发期'
        assert self._phase_of('2024-05-08 00:00') == '波动期'

    def test_a_row_outside_every_window_is_left_empty(self):
        assert pd.isna(self._phase_of('2024-01-01 00:00'))

    def test_a_label_count_that_does_not_match_the_boundaries_is_refused(self):
        # Five phases need six boundaries; four names against six boundaries would silently
        # leave one window unnamed, and pd.cut would report it as its own error. Asserted on
        # the two counts rather than on the wording, which is translated.
        with pytest.raises(UnknownOperationError) as err:
            D.bin_time(pd.DataFrame({'时间': ['2024-05-02']}), '时间', edges=self.EDGES, labels=['甲', '乙'])
        assert '6' in str(err.value) and '2' in str(err.value), str(err.value)

    def test_boundaries_that_are_not_dates_are_refused_by_name(self):
        frame = pd.DataFrame({'时间': ['2024-05-02']})
        with pytest.raises(UnknownOperationError, match='2024-13-99'):
            D.bin_time(frame, '时间', edges=['2024-13-99', '2024-05-08'], labels=['甲'])

    def test_boundaries_out_of_order_are_refused(self):
        # pd.cut raises on unsorted bins with pandas' own wording; naming the parameter is
        # what lets the user find the box that holds it.
        frame = pd.DataFrame({'时间': ['2024-05-02']})
        with pytest.raises(UnknownOperationError):
            D.bin_time(frame, '时间', edges=['2024-05-08', '2024-05-01'], labels=['甲'])


class TestTopicModel:
    """LDA. Pinned for shape and for reproducibility, not for a topic's words."""

    CORPUS = [
        '外卖 空包 商家 道歉 品牌',
        '外卖 空包 门店 公关 危机',
        '外卖 骑手 配送 订单 迟到',
        '警方 通报 调查 结果 真相',
        '警方 通报 立案 谣言 处置',
        '官方 通报 调查 结果 公布',
    ]

    def test_one_row_per_topic_and_keyword(self):
        out = D.topic_model(pd.DataFrame({'正文': self.CORPUS}), '正文', n_topics=2, topn=3)
        assert list(out.columns) == ['topic', 'rank', 'keyword', 'weight']
        assert len(out) == 2 * 3, 'two topics, three words each'
        assert sorted(set(out['topic'])) == ['Topic-1', 'Topic-2']

    def test_ranks_run_from_the_heaviest_word_down(self):
        out = D.topic_model(pd.DataFrame({'正文': self.CORPUS}), '正文', n_topics=2, topn=3)
        for _topic, group in out.groupby('topic'):
            assert list(group['rank']) == [1, 2, 3]
            assert list(group['weight']) == sorted(group['weight'], reverse=True)

    def test_the_answer_repeats_because_the_seed_is_fixed(self):
        """A topic model with a random init answers differently every run, and a resumed
        run that produced a different table than the one it recorded is not a resume."""
        frame = pd.DataFrame({'正文': self.CORPUS})
        first = D.topic_model(frame, '正文', n_topics=2, topn=3)
        second = D.topic_model(frame, '正文', n_topics=2, topn=3)
        assert list(first['keyword']) == list(second['keyword'])

    def test_one_topic_is_refused_because_it_models_nothing(self):
        with pytest.raises(UnknownOperationError, match='1'):
            D.topic_model(pd.DataFrame({'正文': self.CORPUS}), '正文', n_topics=1)

    def test_more_topics_than_texts_is_refused_with_both_numbers(self):
        with pytest.raises(UnknownOperationError) as err:
            D.topic_model(pd.DataFrame({'正文': ['只有一句话']}), '正文', n_topics=5)
        assert '5' in str(err.value) and '1' in str(err.value)

    def test_a_corpus_with_no_words_is_refused_rather_than_answered_empty(self):
        # Every row punctuation: no vocabulary, so there is no model to fit. Returning an
        # empty table would settle the node DONE over nothing.
        with pytest.raises(UnknownOperationError):
            D.topic_model(pd.DataFrame({'正文': ['。。。', '！！！']}), '正文', n_topics=2)


class TestSentimentEvolution:
    """The paper's evolution curve — checked against the paper's published numbers.

    表 2 of the 胖猫 study reports, for each phase, the counts of 积极/中性/消极 and their
    percentages. If this step implements the same index the paper plotted, then feeding it
    those counts must reproduce the paper's own daily values. That is what makes this a
    verification rather than a shape check.
    """

    @staticmethod
    def _frame(periods: dict) -> pd.DataFrame:
        rows = []
        for period, (positive, neutral, negative) in periods.items():
            rows += [{'period': period, 'sentiment': 'positive'}] * positive
            rows += [{'period': period, 'sentiment': 'neutral'}] * neutral
            rows += [{'period': period, 'sentiment': 'negative'}] * negative
        return pd.DataFrame(rows)

    def test_the_papers_phase_shares_come_back_out(self):
        # 发酵期: 17 积极 / 252 中性 / 80 消极 out of 349 (表 2).
        out = D.sentiment_evolution(self._frame({'发酵期': (17, 252, 80)}), 'period')
        assert out.at[0, 'positive_n'] == 17
        assert out.at[0, 'neutral_n'] == 252
        assert out.at[0, 'negative_n'] == 80
        assert out.at[0, 'total'] == 349
        assert out.at[0, 'positive_pct'] == pytest.approx(4.87, abs=0.01)
        assert out.at[0, 'neutral_pct'] == pytest.approx(72.21, abs=0.01)
        assert out.at[0, 'negative_pct'] == pytest.approx(22.92, abs=0.01)

    def test_the_index_is_positive_minus_negative_over_total(self):
        # The paper's own worked examples: 发酵期 (17 − 80) / 349 = −0.1805, and the phase
        # the paper calls the most negative, 二次爆发期 (1887 − 6030) / 8029 = −0.516.
        # Looked up BY NAME, not by position: the row order of a phase table is the step
        # below this one's business, and asserting on the arithmetic here keeps the two
        # questions from failing each other.
        out = D.sentiment_evolution(self._frame({'发酵期': (17, 252, 80), '二次爆发期': (1887, 112, 6030)}), 'period')
        index = out.set_index('period')['sentiment_index']
        assert index['发酵期'] == pytest.approx(-0.1805, abs=0.0001)
        assert index['二次爆发期'] == pytest.approx(-0.5160, abs=0.0001)

    def test_a_neutral_majority_reads_as_moderate_even_when_opinions_are_extreme(self):
        """The distinction the whole curve rests on: 76% negative in 爆发期 is a phase
        index of only −0.56, because the crowd leaned negative without being unanimous.
        A mean over rows would have answered a different question."""
        phase = {'爆发期': (1553, 260, 5811)}
        out = D.sentiment_evolution(self._frame(phase), 'period')
        assert out.at[0, 'negative_pct'] == pytest.approx(76.22, abs=0.01)
        assert out.at[0, 'sentiment_index'] == pytest.approx(-0.5584, abs=0.0001)

    def test_a_row_the_model_could_not_judge_is_not_a_neutral_opinion(self):
        """A blank polarity is "not judged", not "judged neutral". Counting it as neutral
        would report a finding the data does not contain, so it lands in ``other_n`` and
        in the denominator only — which is also what makes the two visible side by side.
        """
        frame = self._frame({'发酵期': (1, 1, 1)})
        frame.loc[len(frame)] = {'period': '发酵期', 'sentiment': ''}
        out = D.sentiment_evolution(frame, 'period')
        assert out.at[0, 'neutral_n'] == 1, 'the blank must not be counted as neutral'
        assert out.at[0, 'other_n'] == 1
        assert out.at[0, 'total'] == 4, 'but it IS part of what that period was'
        assert out.at[0, 'sentiment_index'] == pytest.approx(0.0)

    def test_a_positive_period_reads_positive(self):
        # 衰退期 (547 − 503) / 2286 = +0.0192 — the only phase of the paper's where the two
        # sides nearly cancel, which is why the study describes the whole event as negative.
        out = D.sentiment_evolution(self._frame({'衰退期': (547, 1236, 503)}), 'period')
        assert out.at[0, 'sentiment_index'] == pytest.approx(0.0192, abs=0.0001)

    def test_phases_labeled_in_chinese_still_come_back_in_lifecycle_order(self):
        """The one ordering trap. Chinese phase names have no chronological sort order —
        '二次爆发期' sorts BEFORE '发酵期' by code point — so sorting the result would put
        the paper's table 2 out of order. ``bin_time`` builds an ORDERED categorical, and
        grouping by it keeps the order the user declared in the phase names.
        """
        frame = self._frame({'发酵期': (1, 0, 1), '爆发期': (1, 0, 1), '二次爆发期': (1, 0, 1), '消退期': (1, 0, 1)})
        # Give the rows a timestamp inside each phase, then let the pipeline tag them.
        stamps = {'发酵期': '2024-04-20', '爆发期': '2024-05-03', '二次爆发期': '2024-05-20', '消退期': '2024-06-01'}
        dated = []
        for record in frame.to_dict('records'):
            dated.append({**record, '评论时间': stamps[record['period']]})
        tagged = D.bin_time(
            pd.DataFrame(dated),
            '评论时间',
            edges=['2024-04-11', '2024-05-02', '2024-05-08', '2024-05-19', '2024-05-26', '2024-07-11'],
            labels=['发酵期', '爆发期', '波动期', '二次爆发期', '消退期'],
        )
        out = D.sentiment_evolution(tagged, '阶段')
        assert list(out['period']) == ['发酵期', '爆发期', '二次爆发期', '消退期'], (
            'the declared lifecycle order, not the code-point order of the names'
        )

    def test_the_periods_come_back_in_time_order(self):
        """A line chart draws in row order, so the step sorts rather than making the user
        add a sort and get it wrong."""
        frame = self._frame({'2024-05-19': (1, 0, 1), '2024-04-11': (1, 0, 1), '2024-05-02': (1, 0, 1)})
        out = D.sentiment_evolution(frame, 'period')
        assert list(out['period']) == ['2024-04-11', '2024-05-02', '2024-05-19']

    def test_other_label_spellings_can_be_named(self):
        # The emotion node writes Anger/Joy/Sadness; a 积极/中性/消极 column is what a
        # replicated study usually holds. The three names are parameters for that reason.
        frame = pd.DataFrame([{'日期': '2024-05-02', 'labels': '积极'}, {'日期': '2024-05-02', 'labels': '消极'}])
        out = D.sentiment_evolution(frame, '日期', label_col='labels', positive='积极', neutral='中性', negative='消极')
        assert out.at[0, 'positive_n'] == 1 and out.at[0, 'negative_n'] == 1
        assert out.at[0, 'sentiment_index'] == pytest.approx(0.0)

    def test_a_missing_label_column_is_a_no_op(self):
        frame = pd.DataFrame({'日期': ['2024-05-02']})
        assert list(D.sentiment_evolution(frame, '日期').columns) == ['日期']
