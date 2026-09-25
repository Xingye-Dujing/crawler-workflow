"""Tests for the cleaning/transform toolbox in services/data_analysis.py.

This is the code behind the "Analysis" node's step list, and the pipeline
report is what the console shows the user after a run, so the tests concentrate
on the two things a workflow author cannot debug by eye:

- *missing configuration must not destroy data*: an op whose column or bound is
  absent returns the frame untouched (or raises a named error), never silently
  drops rows, and
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
        ],
    )
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
        frame = pd.DataFrame({'d': ['2024-01-01', 'nonsense']})
        out = D.convert_type(frame, 'd', 'datetime')
        assert out['d'].iloc[0].year == 2024
        assert pd.isna(out['d'].iloc[1])

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
        """Renaming first is what lets the following filter see the column; run the
        other way round, the filter looks for a 城市 that is not there yet and keeps
        every row. The list order decides, so the answer is a fact about the file
        and not about how the runner happens to group its work.
        """
        renamed_then_filtered, _ = D.run_pipeline(SWEEP.copy(), self.STEPS[:2])
        filtered_then_renamed, _ = D.run_pipeline(SWEEP.copy(), self.STEPS[1::-1])
        assert renamed_then_filtered['n'].tolist() == [3, 1], 'only the 北京 rows hold 京'
        assert filtered_then_renamed['n'].tolist() == [3, 5, 1]
        # Both orders end with the rename applied, which is why the surviving rows —
        # the only visible difference — have to be what is asserted.
        assert list(filtered_then_renamed.columns) == ['n', 't', '城市']

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
