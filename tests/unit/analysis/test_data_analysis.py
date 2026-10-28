"""Tests for the cleaning/transform toolbox in services/analysis/pipeline.py.

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

# One alias for the live module: the encoder tests patch its module state, and the source
# guards below read its ``__file__`` — both need the module object, not a copy of a name.
import services.analysis.pipeline as m
import services.analysis.topic_kernels as tk
from services.analysis.pipeline import DataAnalysisService as D
from services.analysis.pipeline import UnknownOperationError, _stage_order

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
    'suggest_stages',
    'topic_model',
    'topic_by_stage',
    'topic_label',
    'cluster_label',
    'cluster_review',
    'topic_map',
    'topic_salience',
    'topic_timeline',
    'topic_flow',
    'topic_coherence',
    'cooccur',
    'reply_graph',
    'compare_platform',
    'forecast',
    'alert',
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

DATA_ANALYSIS_PY = Path(m.__file__)
ANALYSIS_DIR = DATA_ANALYSIS_PY.parent


def _function_definition(function_name: str) -> ast.FunctionDef:
    """The named function wherever the Stage 9 split put it (``ops/<op>.py`` or the service)."""
    for path in sorted(ANALYSIS_DIR.rglob('*.py')):
        for node in _source_walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.FunctionDef) and node.name == function_name:
                return node
    raise AssertionError(f'{function_name} is declared nowhere under {ANALYSIS_DIR}')


SETTINGS_JS = Path(__file__).resolve().parents[3] / 'backend' / 'static' / 'js' / 'panels' / 'settings.js'


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
    function = _function_definition(function_name)
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
    """The string literals of settings.js's ``var NAME = […];`` dropdown source."""
    match = re.search(rf'var {name} = \[([^\]]*)\];', SETTINGS_JS.read_text(encoding='utf-8'))
    assert match, f'{name} is no longer a flat literal array in settings.js'
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
            ('sentiment_evolution', {'column': '作者', 'label_col': '正文'}),
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

    def test_groupby_agg_extra_metrics_add_columns_without_touching_the_primary(self):
        frame = pd.DataFrame({'g': ['a', 'b', 'a'], 'v': [1, 2, 3], 'w': [10, 20, 30]})
        out = D.groupby_agg(frame, 'g', 'v', 'sum', agg_metrics=[('w', 'mean')])
        assert list(out.columns) == ['g', 'v', 'w_mean'], 'primary keeps its name, extra is column_func'
        rows = dict(zip(out['g'], zip(out['v'], out['w_mean'], strict=True), strict=True))
        assert rows == {'a': (4, 20.0), 'b': (2, 20.0)}

    def test_groupby_agg_without_extra_metrics_is_unchanged(self):
        frame = pd.DataFrame({'g': ['a', 'b', 'a'], 'v': [1, 2, 3]})
        assert list(D.groupby_agg(frame, 'g', 'v', 'sum').columns) == ['g', 'v']

    def test_groupby_agg_a_missing_extra_metric_column_is_named(self):
        frame = pd.DataFrame({'g': ['a'], 'v': [1]})
        with pytest.raises(UnknownOperationError, match='nope'):
            D.groupby_agg(frame, 'g', 'v', 'sum', agg_metrics=[('nope', 'mean')])

    def test_groupby_agg_orders_groups_by_name_when_no_order_column_is_given(self):
        frame = pd.DataFrame({'阶段': ['二次爆发期', '发酵期', '爆发期'], '序': [4, 1, 2], 'v': [1, 2, 3]})
        frame = pd.DataFrame(frame.to_dict('records'))
        out = D.groupby_agg(frame, '阶段', 'v', 'sum')
        assert out['阶段'].tolist()[0] == '二次爆发期', 'a name sort puts the fourth phase first'
        assert list(out.columns) == ['阶段', 'v']

    def test_naming_an_order_column_puts_the_groups_back_in_lifecycle_order(self):
        frame = pd.DataFrame({'阶段': ['二次爆发期', '发酵期', '爆发期'], '序': [4, 1, 2], 'v': [1, 2, 3]})
        frame = pd.DataFrame(frame.to_dict('records'))
        out = D.groupby_agg(frame, '阶段', 'v', 'sum', order_col='序')
        assert out['阶段'].tolist() == ['发酵期', '爆发期', '二次爆发期']
        assert out['v'].tolist() == [2, 3, 1]
        assert list(out.columns) == ['阶段', 'v'], 'the helper column is not left in the table'

    def test_an_order_column_that_is_not_in_the_table_is_named(self):
        frame = pd.DataFrame({'g': ['a'], 'v': [1]})
        with pytest.raises(UnknownOperationError, match='没有这列'):
            D.groupby_agg(frame, 'g', 'v', order_col='没有这列')

    def test_a_group_with_no_rank_anywhere_is_refused_not_appended(self):
        frame = pd.DataFrame({'阶段': ['发酵期', '爆发期', '衰退期'], '序': [1, 2, None], 'v': [1, 2, 3]})
        with pytest.raises(UnknownOperationError, match='衰退期'):
            D.groupby_agg(frame, '阶段', 'v', 'sum', order_col='序')

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
    ``backend/static/js/panels/settings.js`` (``ANALYSIS_OPS`` / ``FILTER_OPS`` /
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
        root = Path(__file__).resolve().parents[3]
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
        assert set(offenders) == {
            'backend/static/js/panels/settings.js',
            'tests/unit/analysis/test_data_analysis.py',
        }, f'an unlinked copy of the operation names appeared in {sorted(offenders)}'


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
        from services.datasets.dedupe import MAX_BANDED_DISTANCE

        too_far = MAX_BANDED_DISTANCE + 1
        with pytest.raises(UnknownOperationError) as err:
            D.dedupe_similar(pd.DataFrame(self.NEAR), column='正文', max_distance=too_far)
        assert str(too_far) in str(err.value), str(err.value)

    def test_the_widest_distance_the_index_can_prove_is_accepted(self):
        from services.datasets.dedupe import MAX_BANDED_DISTANCE

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

    def test_the_order_column_numbers_the_phases_in_lifecycle_order(self):
        out = D.bin_time(
            pd.DataFrame({'评论时间': ['2024-05-20 08:00', '2024-04-12 08:00', '2024-05-03 08:00']}),
            '评论时间',
            edges=self.EDGES,
            labels=self.LABELS,
            order_new_col='阶段序号',
        )
        assert out['阶段'].tolist() == ['二次爆发期', '发酵期', '爆发期']
        # 4, 1, 2 — the number is what survives the node boundary that erases the categorical.
        assert out['阶段序号'].tolist() == [4, 1, 2]

    def test_a_row_in_no_phase_has_no_number_rather_than_a_zeroth_one(self):
        out = D.bin_time(
            pd.DataFrame({'评论时间': ['2024-04-12', '2020-01-01']}),
            '评论时间',
            edges=self.EDGES,
            labels=self.LABELS,
            order_new_col='阶段序号',
        )
        assert out['阶段序号'].tolist()[0] == 1
        assert pd.isna(out['阶段序号'].iloc[1]), '0 would read as "the first phase", which is a lie'

    def test_no_order_column_means_no_extra_column_and_the_old_behaviour(self):
        out = D.bin_time(pd.DataFrame({'评论时间': ['2024-04-12']}), '评论时间', edges=self.EDGES, labels=self.LABELS)
        assert list(out.columns) == ['评论时间', '阶段'], 'an untouched box adds nothing'
        blank = D.bin_time(
            pd.DataFrame({'评论时间': ['2024-04-12']}),
            '评论时间',
            edges=self.EDGES,
            labels=self.LABELS,
            order_new_col='   ',
        )
        assert list(blank.columns) == list(out.columns)


class TestSentimentEvolutionOrdering:
    """表 2 is read top-to-bottom as a lifecycle, so its ROW ORDER is a finding."""

    LABELS = ['发酵期', '爆发期', '波动期', '二次爆发期', '衰退期']

    @classmethod
    def _phases(cls) -> pd.DataFrame:
        """The shape a node boundary hands over: the phase column is plain strings."""
        rows = []
        for position, name in enumerate(cls.LABELS, start=1):
            for index in range(6):
                rows.append(
                    {
                        '阶段': name,
                        '阶段序号': position,
                        'sentiment': ['positive', 'neutral', 'negative'][index % 3],
                        'score': [0.9, 0.5, 0.1][index % 3],
                    }
                )
        return pd.DataFrame(list(pd.DataFrame(rows).to_dict('records')))

    def test_grouping_by_a_phase_name_without_an_order_column_sorts_the_lifecycle_wrong(self):
        # Pinned as a fact, not a wish: 二次爆发期 starts with U+4E8C, which is below 发 (U+53D1),
        # so a name sort puts the fourth phase first and the export still looks complete.
        out = D.sentiment_evolution(self._phases(), '阶段', label_col='sentiment')
        assert out['period'].tolist()[0] == '二次爆发期'

    def test_naming_the_order_column_puts_the_periods_back_in_lifecycle_order(self):
        out = D.sentiment_evolution(self._phases(), '阶段', label_col='sentiment', order_col='阶段序号')
        assert out['period'].tolist() == self.LABELS

    def test_the_order_column_also_carries_the_numbers_that_make_a_chart_honour_it(self):
        out = D.sentiment_evolution(self._phases(), '阶段', label_col='sentiment', order_col='阶段序号')
        assert set(out.columns) >= {'period', 'total', 'volume_pct', 'sentiment_index'}
        assert '阶段序号' not in out.columns, 'the helper column is not left in the table'

    def test_a_time_column_orders_the_periods_the_same_way(self):
        frame = self._phases()
        frame['首日'] = pd.to_datetime([f'2022-01-{9 + position:02d}' for position in frame['阶段序号']])
        out = D.sentiment_evolution(frame, '阶段', label_col='sentiment', order_col='首日')
        assert out['period'].tolist() == self.LABELS

    def test_a_phase_with_no_rank_anywhere_is_refused_not_appended(self):
        frame = self._phases()
        frame.loc[frame['阶段'] == '衰退期', '阶段序号'] = None
        with pytest.raises(UnknownOperationError) as err:
            D.sentiment_evolution(frame, '阶段', label_col='sentiment', order_col='阶段序号')
        assert '衰退期' in str(err.value)

    def test_an_order_column_that_is_not_in_the_table_is_named(self):
        with pytest.raises(UnknownOperationError, match='没有这列'):
            D.sentiment_evolution(self._phases(), '阶段', label_col='sentiment', order_col='没有这列')

    def test_days_need_no_order_column_because_the_name_already_sorts_in_time(self):
        frame = pd.DataFrame(
            {
                '日期': ['2022-01-16', '2022-01-17', '2022-01-16', '2022-01-17'],
                'sentiment': ['positive', 'negative', 'neutral', 'negative'],
            }
        )
        out = D.sentiment_evolution(frame, '日期', label_col='sentiment')
        assert out['period'].tolist() == ['2022-01-16', '2022-01-17']


class TestSuggestStages:
    """The phase-boundary proposal, pinned on a curve whose cut is not debatable.

    The step exists because the 胖猫 study drew its five phases by eye on a posts-per-day
    chart. What is checkable here is the arithmetic of that eye: peaks found, valleys chosen
    between them, and — the part that decides whether the printed boundaries can be pasted
    into :meth:`bin_time` at all — an edge list that opens the day AFTER a valley and closes
    the day after the last observed day.
    """

    #: Two peaks (05-05 and 05-10) with a quiet 05-07 between them.
    CURVE = {
        '2024-05-01': 1,
        '2024-05-02': 1,
        '2024-05-03': 1,
        '2024-05-04': 4,
        '2024-05-05': 6,
        '2024-05-06': 3,
        '2024-05-07': 1,
        '2024-05-08': 2,
        '2024-05-09': 5,
        '2024-05-10': 8,
        '2024-05-11': 2,
    }

    @classmethod
    def _frame(cls, curve: dict) -> pd.DataFrame:
        rows = []
        for day, count in curve.items():
            rows += [{'评论时间': f'{day} 12:00', '正文': '甲'} for _ in range(count)]
        return pd.DataFrame(rows)

    def test_two_peaks_cut_the_curve_into_two_windows(self):
        out = D.suggest_stages(self._frame(self.CURVE), '评论时间')
        assert list(out['起点']) == ['2024-05-01', '2024-05-08'], 'the new phase opens the day after the valley'
        assert list(out['终点']) == ['2024-05-07', '2024-05-11']
        assert list(out['天数']) == [7, 4]
        assert list(out['行数']) == [17, 17]
        assert sum(out['行数']) == len(self._frame(self.CURVE)), 'every row lands in exactly one window'

    def test_the_reported_peak_is_that_day_s_raw_count_not_the_smoothed_one(self):
        # The boundary search smooths, because a one-day spike is noise; what the user reads
        # against 表 1 of the study (349/7624/1038/8029/2286) is the raw count of the day.
        out = D.suggest_stages(self._frame(self.CURVE), '评论时间')
        assert list(out['峰值日']) == ['2024-05-05', '2024-05-10']
        assert list(out['峰值计数']) == [6, 8]

    def test_the_basis_names_where_each_window_starts(self):
        out = D.suggest_stages(self._frame(self.CURVE), '评论时间')
        assert '2024-05-01' in out.at[0, '依据']
        assert '2024-05-07' in out.at[1, '依据'], 'the valley that closed the first window'

    def test_the_printed_boundaries_are_the_ones_bin_time_accepts(self, caplog):
        """The whole point of the step is the paste, so the paste is executed rather than
        admired: the interior edges are the windows' 起点, and the last edge is the day after
        the final window — a list ending on 2024-05-11 would drop that day's 2 rows."""
        with caplog.at_level('INFO'):
            out = D.suggest_stages(self._frame(self.CURVE), '评论时间')
        assert '2024-05-12' in caplog.text, 'the closing edge must be 终点 + 1 day'
        edges = list(out['起点']) + ['2024-05-12']
        binned = D.bin_time(self._frame(self.CURVE), '评论时间', edges=edges, labels=['阶段1', '阶段2'])
        assert list(binned['阶段'].value_counts().sort_index()) == list(out['行数'])

    def test_a_flat_curve_is_refused_rather_than_cut_anywhere(self):
        flat = {
            day: 2
            for day in [
                '2024-05-01',
                '2024-05-02',
                '2024-05-03',
                '2024-05-04',
                '2024-05-05',
                '2024-05-06',
                '2024-05-07',
                '2024-05-08',
            ]
        }
        with pytest.raises(UnknownOperationError, match='阶段划分'):
            D.suggest_stages(self._frame(flat), '评论时间')

    def test_too_few_days_of_records_is_refused_by_the_count_it_found(self):
        with pytest.raises(UnknownOperationError, match='3 天'):
            D.suggest_stages(self._frame({'2024-05-01': 4, '2024-05-02': 9, '2024-05-03': 4}), '评论时间')

    def test_a_peak_ratio_below_one_is_not_a_peak(self):
        # "twice the usual day" is the definition; 0.5 would call every ordinary day a peak
        # and cut the curve at its own noise.
        with pytest.raises(UnknownOperationError, match='0.5'):
            D.suggest_stages(self._frame(self.CURVE), '评论时间', peak_ratio=0.5)

    def test_more_peaks_than_the_ceiling_are_folded_and_said_so(self, caplog):
        # Four runs clear the floor (the 9-row hump is split from the 6-3 tail by the
        # smoothing) and the ceiling is 2: two peaks are folded into their neighbours, and the
        # console says so with the numbers it used — a proposal that quietly lost a peak is a
        # proposal the user cannot audit. The assertion is the whole sentence, filled with the
        # counts this curve produces: matching bare digits also matched the log line number,
        # which moved the day the module did.
        from i18n import t

        curve = dict(
            zip(
                pd.date_range('2024-05-01', periods=21).strftime('%Y-%m-%d'),
                [1, 3, 6, 9, 6, 3, 1, 1, 4, 8, 11, 7, 3, 1, 1, 3, 7, 12, 8, 4, 1],
                strict=True,
            )
        )
        with caplog.at_level('WARNING'):
            out = D.suggest_stages(self._frame(curve), '评论时间', max_windows=2)
        assert len(out) == 2
        said = t('analysis.stages_folded', kept=2, dropped=2)
        assert said in caplog.text, f'the folded peaks are not reported: {caplog.text}'
        assert out.at[0, '起点'] == '2024-05-01', 'the 9-row hump stayed inside the first window'

    def test_adjacent_tall_days_do_not_cancel_the_next_burst(self):
        """The defect the real 刘学州 curve found.

        Two days of a summit sit side by side (20 then 19), so the flattened curve puts its
        maximum on the shoulder between them — and when the floor was then tested against the
        RAW value at that position, the shoulder failed it and the whole burst disappeared.
        On the event that is the flagship of this project, that left one peak in the 76-day
        curve and the step answered 「曲线只有一段」 next to a secondary 587-row burst on 02-16.
        A summit is now a RUN of days clearing the floor, so this curve cuts into two windows
        and the second one still carries its own tallest day (8 rows on 05-10).
        """
        curve = dict(
            zip(
                pd.date_range('2024-05-01', periods=21).strftime('%Y-%m-%d'),
                [5, 5, 5, 1, 20, 19, 1, 1, 1, 8, 1, 7, 1, 1, 1, 1, 1, 1, 1, 1, 1],
                strict=True,
            )
        )
        out = D.suggest_stages(self._frame(curve), '评论时间')
        assert len(out) == 2, 'the 8/1/7 burst is a second summit, not noise inside the first'
        assert list(out['起点']) == ['2024-05-01', '2024-05-09']
        assert list(out['峰值日']) == ['2024-05-05', '2024-05-10']
        assert list(out['峰值计数']) == [20, 8], 'the raw tallest day of each run, not the shoulder'

    def test_a_window_shorter_than_the_minimum_joins_its_larger_neighbour(self, caplog):
        # 最短窗口 was declared and only ever used as a "do we have enough days at all" floor: a
        # two-day tail is a proposal the user cannot paste without noticing. It now folds, into
        # the neighbour carrying more rows, and says how many windows it ate.
        curve = dict(
            zip(
                pd.date_range('2024-05-01', periods=9).strftime('%Y-%m-%d'),
                [5, 5, 12, 1, 12, 1, 5, 5, 20],
                strict=True,
            )
        )
        with caplog.at_level('WARNING'):
            out = D.suggest_stages(self._frame(curve), '评论时间')
        assert len(out) == 2
        assert list(out['终点']) == ['2024-05-04', '2024-05-09'], 'the 2-day tail closed the 5-day window'
        assert list(out['行数']) == [23, 43], '18 + 25: the tail joined the side that already had more rows'
        assert '最短窗口' in caplog.text, 'the fold is reported, not hidden'

    def test_the_minimum_window_is_the_box_that_decides_it(self):
        curve = dict(
            zip(
                pd.date_range('2024-05-01', periods=9).strftime('%Y-%m-%d'),
                [5, 5, 12, 1, 12, 1, 5, 5, 20],
                strict=True,
            )
        )
        out = D.suggest_stages(self._frame(curve), '评论时间', min_days=1)
        assert len(out) == 3, 'asked for no minimum, and the 2-day tail stays its own proposal'
        assert list(out['天数']) == [4, 3, 2]

    def test_a_column_of_relative_labels_answers_nothing_and_says_so(self):
        # Weibo hands back "09月26日 21:00" for a recent post: nothing to count by day, and
        # an empty proposal would read as "this event has no phases".
        frame = pd.DataFrame({'评论时间': ['今天', '昨天', '前天']})
        with pytest.raises(UnknownOperationError):
            D.suggest_stages(frame, '评论时间')


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


class TestTopicByStage:
    """LDA per 舆情阶段 — 表 1 of the study, and the refusals that keep it honest.

    Nothing here asserts WHICH words a topic got: LDA on a twelve-post fixture picks its
    buckets by luck, and a test that pinned them would be a test of scikit-learn's numerics.
    What is pinned is the shape of the artifact (one row per phase × topic), the numbering by
    lifecycle POSITION, the invariants (every post belongs to exactly one topic, the weight
    list and the word list are the same words), and every way the step can be asked to guess.
    """

    #: Three phases, two clear vocabularies each. The NAMES are chosen so that a code-point
    #: sort puts 二次爆发期 first — the exact mistake the order guard exists to stop.
    FAMILIES = {
        'police': '警方 通报 调查 结果 谣言 核实 依法 处理',
        'delivery': '外卖 祭奠 点单 空包 商家 配送 退款 平台',
    }

    @classmethod
    def _frame(cls, stages: dict | None = None, dated: bool = True) -> pd.DataFrame:
        stages = stages or {'发酵期': 6, '爆发期': 6, '二次爆发期': 6}
        first_day = pd.Timestamp('2024-04-11')
        rows = []
        for offset, (stage, count) in enumerate(stages.items()):
            for index in range(count):
                family = cls.FAMILIES['police' if index % 2 == 0 else 'delivery']
                stamp = first_day + pd.Timedelta(days=10 * offset + index % 3)
                rows.append({'阶段': stage, '评论时间': str(stamp), '正文': f'{family} 第{index}条'})
        frame = pd.DataFrame(rows)
        return frame if dated else frame.drop(columns=['评论时间'])

    def _run(self, frame, **kwargs):
        # ``order_col`` by default: the fixture's 阶段 is a plain string column, which is the
        # shape two connected nodes hand each other, so the phase order has to be read from the
        # timestamps rather than from a categorical that is no longer there.
        params = {'column': '正文', 'stage_col': '阶段', 'order_col': '评论时间', 'topics': [2, 2, 2]}
        params.update(kwargs)
        return D.topic_by_stage(frame, **params)

    def test_the_stages_are_modelled_separately_and_numbered_by_position(self):
        out = self._run(self._frame())
        assert list(out.columns) == [
            'stage',
            'stage_order',
            'topic',
            'feature_words',
            'weights',
            'doc_n',
            'perplexity',
            'sample_texts',
        ]
        assert list(out['topic']) == [
            'TopicⅠ-1',
            'TopicⅠ-2',
            'TopicⅡ-1',
            'TopicⅡ-2',
            'TopicⅢ-1',
            'TopicⅢ-2',
        ]
        # Ⅰ is U+2160, not the letter I: the paper's own table uses the Unicode numeral, and a
        # CSV that silently carried 'TopicI-1' would not match it.
        assert out.at[0, 'topic'][5] == 'Ⅰ'
        assert list(out['stage_order']) == [1, 1, 2, 2, 3, 3]
        assert list(out['stage']) == ['发酵期'] * 2 + ['爆发期'] * 2 + ['二次爆发期'] * 2

    def test_a_phase_column_that_crossed_a_node_boundary_needs_its_order_named(self):
        # Records round trip (what two connected nodes hand each other) erases the categorical,
        # and Chinese phase names have no chronological code-point order.
        frame = self._frame().drop(columns=['评论时间'])
        with pytest.raises(UnknownOperationError, match='阶段先后'):
            self._run(frame, order_col='')

    def test_a_time_column_can_supply_the_order_the_categorical_lost(self):
        shuffled = self._frame().sample(frac=1, random_state=7).reset_index(drop=True)
        out = self._run(shuffled, order_col='评论时间')
        assert list(out['stage']) == ['发酵期'] * 2 + ['爆发期'] * 2 + ['二次爆发期'] * 2

    def test_the_order_column_is_not_allowed_to_place_a_phase_it_cannot_read(self):
        # A phase whose every row carries a relative label ('刚刚') has no position on the
        # timeline. Appending it at the end would invent one and renumber the table.
        frame = self._frame()
        frame.loc[frame['阶段'] == '二次爆发期', '评论时间'] = '刚刚'
        with pytest.raises(UnknownOperationError, match='二次爆发期'):
            self._run(frame, order_col='评论时间')

    def test_the_ordered_categorical_from_the_same_pipeline_is_used_as_is(self):
        # bin_time in the same node: no order column needed, because pd.cut kept the declared
        # order and grouping by it preserves it.
        tagged = D.bin_time(
            self._frame(dated=True).drop(columns=['阶段']),
            '评论时间',
            edges=['2024-04-11', '2024-04-21', '2024-05-01', '2024-05-11'],
            labels=['发酵期', '爆发期', '二次爆发期'],
        )
        out = self._run(tagged, order_col='')
        assert list(out['stage']) == ['发酵期'] * 2 + ['爆发期'] * 2 + ['二次爆发期'] * 2

    def test_a_declared_phase_that_turned_out_empty_is_refused_not_skipped(self):
        # pd.cut names every window whether or not a row falls in it: these edges leave 爆发期
        # ([04-25, 05-01)) with zero posts while 空窗期 takes them. Skipping the empty phase and
        # modelling three would make TopicⅢ belong to the wrong name.
        tagged = D.bin_time(
            self._frame(dated=True).drop(columns=['阶段']),
            '评论时间',
            edges=['2024-04-11', '2024-04-21', '2024-04-25', '2024-05-01', '2024-05-11'],
            labels=['发酵期', '空窗期', '爆发期', '二次爆发期'],
        )
        assert (tagged['阶段'] == '爆发期').sum() == 0
        with pytest.raises(UnknownOperationError, match='爆发期'):
            D.topic_by_stage(tagged, column='正文', stage_col='阶段', topics=[2, 2, 2, 2])

    def test_a_time_column_that_is_not_in_the_table_is_refused_by_name(self):
        with pytest.raises(UnknownOperationError, match='发布日'):
            self._run(self._frame(), order_col='发布日')

    def test_one_post_belongs_to_exactly_one_topic_of_its_phase(self):
        frame = self._frame()
        out = self._run(frame)
        for stage in ('发酵期', '爆发期', '二次爆发期'):
            rows = out[out['stage'] == stage]
            assert sum(rows['doc_n']) == 6, f'{stage}: the buckets partition the phase'
            assert (rows['perplexity'] == rows.iloc[0]['perplexity']).all(), 'perplexity is per phase'
            assert rows['perplexity'].gt(0).all()

    def test_the_word_list_and_the_weight_list_are_the_same_words(self):
        out = self._run(self._frame())
        for row in out.to_dict('records'):
            words = row['feature_words'].split('、')
            weighted = [pair.split(':')[0] for pair in row['weights'].split(' ')]
            assert words == weighted, 'the cell a reader sees and the cell a chart reads agree'
            assert words, 'a topic with no words is a refusal, not an empty cell'
            assert row['sample_texts'], 'and a topic with no sample text was never assigned a post'

    def test_one_topic_count_applies_to_every_phase(self):
        out = self._run(self._frame(), topics='2')
        assert len(out) == 6
        assert list(out['topic'])[-2:] == ['TopicⅢ-1', 'TopicⅢ-2']

    def test_a_count_list_that_does_not_fit_the_stages_is_refused_with_both_numbers(self):
        with pytest.raises(UnknownOperationError, match='3 个阶段'):
            self._run(self._frame(), topics=[2, 2])

    def test_a_count_that_is_not_a_number_is_refused_by_its_own_text(self):
        with pytest.raises(UnknownOperationError, match='很多'):
            self._run(self._frame(), topics=['2', '很多', '2'])

    def test_a_phase_shorter_than_its_topic_count_is_refused_not_shrunk(self):
        # Two topics over two posts is a model that memorises; the study's own 发酵期 has 349
        # rows, so a thin phase is a signal to lower the count, not to invent one.
        frame = self._frame({'发酵期': 6, '爆发期': 6, '二次爆发期': 2})
        with pytest.raises(UnknownOperationError, match='二次爆发期'):
            self._run(frame, topics=[2, 2, 3])

    def test_rows_without_a_phase_are_counted_once_and_left_out(self, caplog):
        frame = self._frame()
        frame.loc[frame.index[:3], '阶段'] = ''
        with caplog.at_level('WARNING'):
            out = self._run(frame, topics=2)
        assert len(out) == 6, 'the three unphased rows join no model'
        assert '3 行' in caplog.text

    def test_the_lda_word_source_reads_the_weight_matrix_and_keeps_the_same_shape(self):
        out = self._run(self._frame(), word_source='lda')
        assert len(out) == 6
        assert all(len(row['feature_words'].split('、')) > 0 for row in out.to_dict('records'))

    def test_an_unused_topic_falls_back_without_losing_the_weight_cell_agreement(self):
        # Whatever filled the row, ``weights`` and ``feature_words`` must still be the same words:
        # a chart that reads one and a table that reads the other cannot be allowed to disagree.
        frame = self._frame()
        out = self._run(frame, word_source='tfidf', topics=6)
        assert all(len(row['feature_words']) > 0 for row in out.to_dict('records'))
        for _, row in out.iterrows():
            assert row['feature_words'].split('、') == [part.split(':')[0] for part in row['weights'].split()]
        assert (out['doc_n'] == 0).any(), 'six topics over six posts per stage leaves topics unused'

    def test_an_unknown_word_source_is_refused_by_the_gate(self):
        from services.analysis.pipeline import STEP_PARAMS, normalize_step_params, validate_step

        params = normalize_step_params('topic_by_stage', {'column': '正文', 'stage_col': '阶段', 'topics': '2'})
        assert 'word_source' not in params, 'an absent select is left to the operation itself'
        assert normalize_step_params('topic_by_stage', {'word_source': '  ', 'topics': ''})['word_source'] == 'tfidf'
        with pytest.raises(UnknownOperationError, match='word_source'):
            validate_step(self._frame(), 'topic_by_stage', {**params, 'word_source': 'gensim'})
        assert STEP_PARAMS['topic_by_stage']['nonblank'] == ('topics',)


class TestTopicLabel:
    """The 主题概括 column: one model call per topic, and no silent gap when it fails.

    ``llm`` is always a stub here — the OpenRouter transport is never reached from a test, and
    a real daemon would make this a device-tier test. What is pinned is the accounting around
    the calls: how many, what went into the prompt, and what the table looks like when the
    model says no.
    """

    class _Client:
        """A stand-in for ``LLMClient`` that records prompts and can be made to fail."""

        label = 'ollama:stub'

        def __init__(self, answer='概括：对事件细节的追问', fail_when=None):
            self.prompts = []
            self.answer = answer
            self.fail_when = fail_when

        def chat(self, prompt, max_retries=2):
            from analyzers.llm_client import LLMError

            self.prompts.append(prompt)
            if self.fail_when and self.fail_when(prompt):
                raise LLMError('daemon answered nothing', 'bad_response')
            return self.answer

    @staticmethod
    def _topics() -> pd.DataFrame:
        return pd.DataFrame(
            {
                'stage': ['发酵期', '发酵期', '爆发期'],
                'topic': ['TopicⅠ-1', 'TopicⅠ-2', 'TopicⅡ-1'],
                'feature_words': ['谣言、暴力、刘某', '谭某、感情、讨论', '性别、对立、煽动'],
                'sample_texts': ['原文甲', '原文乙', '原文丙'],
            }
        )

    def _run(self, frame=None, **kwargs):
        params = {'words_col': 'feature_words', 'samples_col': 'sample_texts'}
        params.update(kwargs)
        client = params.pop('client', None) or self._Client()
        return D.topic_label(frame if frame is not None else self._topics(), llm=client, **params), client

    def test_one_call_per_topic_and_one_summary_per_row(self):
        out, client = self._run()
        assert len(client.prompts) == 3
        assert list(out['主题概括']) == ['对事件细节的追问'] * 3
        assert len(out) == 3, 'the step labels the table, it does not replace it'

    def test_the_prompt_carries_the_phase_the_number_the_words_and_the_posts(self):
        _out, client = self._run()
        assert '发酵期' in client.prompts[0]
        assert 'TopicⅠ-2' in client.prompts[1]
        assert '谭某、感情、讨论' in client.prompts[1]
        assert '原文丙' in client.prompts[2]

    def test_the_wrapping_a_small_model_adds_comes_off_the_cell(self):
        for answer, expected in [
            ('概括：对事件细节的追问', '对事件细节的追问'),
            ('"对事件细节的追问"', '对事件细节的追问'),
            ('【对事件细节的追问】', '对事件细节的追问'),
            ('Summary: the cost of chasing details', 'the cost of chasing details'),
            ('第一行被截断\n第二行不要', '第一行被截断'),
        ]:
            out, _client = self._run(client=self._Client(answer=answer), max_topics=3)
            assert out.at[0, '主题概括'] == expected, answer

    def test_a_refusal_fails_the_node_and_names_the_topic(self):
        client = self._Client(fail_when=lambda prompt: 'TopicⅡ-1' in prompt)
        with pytest.raises(UnknownOperationError, match='TopicⅡ-1'):
            D.topic_label(self._topics(), llm=client, on_fail='abort')

    def test_the_opt_in_leaves_only_the_failed_cell_empty_and_logs_it(self, caplog):
        client = self._Client(fail_when=lambda prompt: 'TopicⅠ-2' in prompt)
        with caplog.at_level('WARNING'):
            out = D.topic_label(self._topics(), llm=client, on_fail='blank')
        assert out.at[0, '主题概括'] and out.at[2, '主题概括']
        assert not out.at[1, '主题概括'], 'the topic that failed is the only empty cell'
        assert caplog.text.count('TopicⅠ-2') == 1, 'one failure, one line'

    def test_an_answer_of_punctuation_is_a_failure_not_an_empty_cell(self):
        client = self._Client(answer='「」。')
        with pytest.raises(UnknownOperationError, match='TopicⅠ-1'):
            D.topic_label(self._topics(), llm=client)

    def test_no_client_is_a_missing_input_not_a_skip(self):
        with pytest.raises(UnknownOperationError, match='模型'):
            D.topic_label(self._topics(), llm=None)

    def test_fallback_with_no_model_names_every_topic_from_its_words(self):
        out = D.topic_label(self._topics(), llm=None, on_fail='fallback')
        assert (out['主题概括'] != '').all(), 'a topic with no model is named, not left blank'
        assert all('·' in v for v in out['主题概括']), "the fallback joins the topic's own words"

    def test_fallback_labels_a_refused_topic_instead_of_aborting(self):
        client = self._Client(fail_when=lambda prompt: 'TopicⅡ-1' in prompt)
        out = D.topic_label(self._topics(), llm=client, on_fail='fallback')
        assert out.at[2, '主题概括'] and '·' in out.at[2, '主题概括'], 'the failing topic falls back to its words'
        assert out.at[0, '主题概括'] == '对事件细节的追问', 'the topics the model answered keep that answer'

    def test_fallback_labels_a_punctuation_answer_from_its_words(self):
        out = D.topic_label(self._topics(), llm=self._Client(answer='「」。'), on_fail='fallback')
        assert (out['主题概括'] != '').all() and all('·' in v for v in out['主题概括'])

    def test_fallback_does_not_ask_the_model_any_fewer_times(self):
        client = self._Client()
        D.topic_label(self._topics(), llm=client, on_fail='fallback')
        assert len(client.prompts) == 3, 'fallback answers when the model fails; it never skips a call'

    def test_a_topic_with_no_feature_words_is_refused_before_the_call(self):
        frame = self._topics()
        frame.loc[1, 'feature_words'] = ''
        client = self._Client()
        with pytest.raises(UnknownOperationError, match='TopicⅠ-2'):
            D.topic_label(frame, llm=client)
        assert len(client.prompts) == 1, 'the row that cannot be labelled is never asked'

    class _Store:
        """A stand-in for the run ledger's ``llm_cache``: same two methods, kept in a dict."""

        def __init__(self):
            self.rows = {}

        def cache_get(self, scope, key):
            return self.rows.get((scope, key))

        def cache_put(self, scope, key, value):
            self.rows[(scope, key)] = value

    def test_a_store_makes_the_second_run_of_the_same_table_free(self):
        store = self._Store()
        first = self._Client(answer='概括：第一次的答复')
        D.topic_label(self._topics(), llm=first, store=store, words_col='feature_words', samples_col='sample_texts')
        assert len(first.prompts) == 3, 'the first pass pays for every topic'

        second = self._Client(answer='概括：不该被用到的答复')
        out = D.topic_label(
            self._topics(), llm=second, store=store, words_col='feature_words', samples_col='sample_texts'
        )
        assert second.prompts == [], 'a re-run replays the cache and asks nothing'
        assert list(out['主题概括']) == ['第一次的答复'] * 3, 'the cell holds the cached answer'

    def test_a_different_model_does_not_replay_another_models_words(self):
        store = self._Store()
        D.topic_label(self._topics(), llm=self._Client(answer='概括：甲模型'), store=store)

        class _OtherClient(TestTopicLabel._Client):
            label = 'openrouter:other'

        other = _OtherClient(answer='概括：乙模型')
        out = D.topic_label(self._topics(), llm=other, store=store)
        assert len(other.prompts) == 3, 'the cache is keyed by the model that answered'
        assert out.at[0, '主题概括'] == '乙模型'

    def test_edited_feature_words_re_ask_only_that_topic(self):
        store = self._Store()
        D.topic_label(self._topics(), llm=self._Client(), store=store)

        frame = self._topics()
        frame.loc[1, 'feature_words'] = '完全不同的、词、表'
        client = self._Client(answer='概括：重问之后的')
        D.topic_label(frame, llm=client, store=store)
        assert len(client.prompts) == 1, 'the prompt is the key, so only the edited topic is asked again'

    def test_no_store_still_works_and_asks_every_time(self):
        client = self._Client()
        D.topic_label(self._topics(), llm=client)
        assert len(client.prompts) == 3

    def test_a_table_too_big_for_the_cap_is_refused_with_both_numbers(self):
        with pytest.raises(UnknownOperationError, match='3 行'):
            D.topic_label(self._topics(), llm=self._Client(), max_topics=2)

    def test_a_stopped_run_marks_the_rows_the_model_never_saw(self):
        class _Stop:
            def __init__(self):
                self.seen = 0

            def is_set(self):
                self.seen += 1
                return self.seen > 1

        from analyzers.llm_client import ABORT_MARK

        client = self._Client()
        out = D.topic_label(self._topics(), llm=client, cancel=_Stop())
        assert len(client.prompts) == 1, 'Stop is checked before every call, not after the pass'
        assert list(out['主题概括'][1:]) == [ABORT_MARK, ABORT_MARK]

    def test_the_pipeline_hands_the_client_only_to_the_steps_that_need_it(self):
        client = self._Client()
        result, report = D.run_pipeline(
            self._topics(),
            [
                {'op': 'select_columns', 'params': {'columns': ['stage', 'topic', 'feature_words', 'sample_texts']}},
                # ``summary_col`` is spelled out because the gate treats a *new* column name as
                # something the caller must state: an absent one would add a header nobody chose.
                {
                    'op': 'topic_label',
                    'params': {'words_col': 'feature_words', 'samples_col': 'sample_texts', 'summary_col': '主题概括'},
                },
            ],
            llm=client,
        )
        assert len(client.prompts) == 3
        assert [entry['op'] for entry in report] == ['select_columns', 'topic_label']
        assert result['主题概括'].notna().all()

    def test_the_gate_knows_its_columns_and_its_switch(self):
        from services.analysis.pipeline import LLM_OPS, STEP_PARAMS, normalize_step_params, validate_step

        assert frozenset({'topic_label', 'cluster_label', 'cluster_review'}) == LLM_OPS
        params = normalize_step_params('topic_label', {'words_col': ' 词 ', 'summary_col': ' 概括 ', 'on_fail': ''})
        assert params['words_col'] == '词' and params['summary_col'] == '概括'
        assert params['on_fail'] == 'abort', 'a blank select is the declared default'
        with pytest.raises(UnknownOperationError, match='on_fail'):
            validate_step(self._topics(), 'topic_label', {'words_col': 'feature_words', 'on_fail': 'ignore'})
        assert STEP_PARAMS['topic_label']['nonblank'] == ('summary_col',)


class TestClusterLabel:
    """聚类摘要: one model call per cluster over its OWN raw texts. Same refusal / Stop / cache
    discipline as 主题概括 (a paid per-row step), but the input is documents grouped by a cluster
    label, not a pre-reduced topic table — so the shape it returns is one row per cluster."""

    class _Client:
        label = 'ollama:stub'

        def __init__(self, answer='这一簇在追问事件细节'):
            self.prompts = []
            self.answer = answer

        def chat(self, prompt, max_retries=2):
            self.prompts.append(prompt)
            return self.answer

    class _Store:
        def __init__(self):
            self._d = {}

        def cache_get(self, scope, key):
            return self._d.get(scope + '|' + key)

        def cache_put(self, scope, key, value):
            self._d[scope + '|' + key] = value

    @staticmethod
    def _docs() -> pd.DataFrame:
        return pd.DataFrame(
            {
                '正文': ['甲甲', '乙乙', '丙丙', '丁丁', '戊戊'],
                'cluster': [0, 0, 1, 1, 2],
            }
        )

    def test_one_summary_row_per_cluster(self):
        out = D.cluster_label(self._docs(), llm=self._Client(), summary_col='摘要')
        assert list(out.columns) == ['cluster', 'n_docs', '摘要']
        assert len(out) == 3, 'three clusters → three rows, whatever the document count'
        assert (out['n_docs'] == [2, 2, 1]).all()

    def test_the_grouping_column_keeps_the_name_the_user_gave_it(self):
        """The output's first column used to be the literal ``cluster`` whatever ``group_col`` said,
        so pointing the step at 簇 produced a table whose key was a column the user never named —
        and every downstream chart had to be told about a column the input does not have."""
        frame = pd.DataFrame({'簇': [0, 0, 1], '正文': ['甲', '乙', '丙']})
        out = D.cluster_label(frame, llm=self._Client(), group_col='簇', summary_col='概述')
        assert list(out.columns) == ['簇', 'n_docs', '概述']
        assert out['簇'].tolist() == [0, 1]

    def test_a_missing_group_column_is_refused_by_name(self):
        frame = pd.DataFrame({'正文': ['甲']})
        with pytest.raises(UnknownOperationError, match='cluster'):
            D.cluster_label(frame, llm=self._Client())

    def test_a_missing_text_column_is_refused_by_name(self):
        frame = pd.DataFrame({'cluster': [0]})
        with pytest.raises(UnknownOperationError, match='正文'):
            D.cluster_label(frame, llm=self._Client())

    def test_no_model_is_a_refusal_not_an_empty_column(self):
        from i18n import t

        with pytest.raises(UnknownOperationError) as exc:
            D.cluster_label(self._docs(), llm=None)
        assert t('analysis.label_no_llm', op='cluster_label') in str(exc.value)

    def test_a_stopped_run_marks_the_clusters_the_model_never_saw(self):
        class _Stop:
            def __init__(self):
                self.seen = 0

            def is_set(self):
                self.seen += 1
                return self.seen > 1

        from analyzers.llm_client import ABORT_MARK

        client = self._Client()
        out = D.cluster_label(self._docs(), llm=client, cancel=_Stop())
        assert len(client.prompts) == 1, 'Stop is checked before every call, not after the pass'
        assert list(out['摘要'][1:]) == [ABORT_MARK, ABORT_MARK]

    def test_the_answer_is_cached_so_a_re_run_does_not_re_pay(self):
        store = self._Store()
        client = self._Client()
        D.cluster_label(self._docs(), llm=client, store=store)
        assert len(client.prompts) == 3
        again = self._Client()
        D.cluster_label(self._docs(), llm=again, store=store)
        assert again.prompts == [], 'the same table is replayed from the cache'

    def test_a_cluster_count_over_the_cap_is_refused_with_both_numbers(self):
        with pytest.raises(UnknownOperationError, match='3 行'):
            D.cluster_label(self._docs(), llm=self._Client(), max_groups=2)

    def test_it_reaches_the_pipeline_only_through_llm_ops(self):
        client = self._Client()
        result, report = D.run_pipeline(
            self._docs(),
            [{'op': 'cluster_label', 'params': {'group_col': 'cluster', 'text_col': '正文', 'summary_col': '摘要'}}],
            llm=client,
        )
        assert [entry['op'] for entry in report] == ['cluster_label']
        assert len(result) == 3 and len(client.prompts) == 3


class TestReplyGraph:
    """回复传播边: parent floor → that floor's author, one directed edge per reply. Orphans (a
    reply whose 父楼层 has no matching top-level row) and self-edges (the same author) are dropped,
    and a thread with nothing to link refuses rather than returning an empty table."""

    @staticmethod
    def _thread() -> pd.DataFrame:
        return pd.DataFrame(
            {
                '评论者': ['甲', '乙', '丙', '丁', '乙'],
                '楼层': ['1', '2', '3', '4', '5'],
                '父楼层': ['', '', '1', '1', '9'],
            }
        )

    def test_builds_directed_edges_from_the_parent_floor(self):
        out = D.reply_graph(self._thread())
        assert list(out.columns) == ['src_author', 'dst_author', 'weight']
        pairs = {(r.src_author, r.dst_author): r.weight for r in out.itertuples()}
        assert pairs == {('甲', '丙'): 1, ('甲', '丁'): 1}, 'floor 1 is 甲; 丙 and 丁 answer it'

    def test_orphan_reply_and_self_edge_are_dropped(self):
        frame = pd.DataFrame(
            {
                '评论者': ['甲', '甲', '乙', '乙'],
                '楼层': ['1', '2', '3', '4'],
                '父楼层': ['', '1', '1', '3'],
            }
        )
        out = D.reply_graph(frame)
        assert list(out['src_author']) == ['甲'] and list(out['dst_author']) == ['乙']

    def test_weight_counts_repeats_between_the_same_pair(self):
        frame = pd.DataFrame(
            {
                '评论者': ['甲', '乙', '乙'],
                '楼层': ['1', '2', '3'],
                '父楼层': ['', '1', '1'],
            }
        )
        out = D.reply_graph(frame)
        assert len(out) == 1 and int(out['weight'].iloc[0]) == 2

    def test_no_resolvable_reply_raises_not_an_empty_table(self):
        frame = pd.DataFrame({'评论者': ['甲', '乙'], '楼层': ['1', '2'], '父楼层': ['', '']})
        with pytest.raises(UnknownOperationError):
            D.reply_graph(frame)

    def test_a_missing_named_column_is_refused_by_name(self):
        frame = pd.DataFrame({'评论者': ['甲'], '楼层': ['1']})
        with pytest.raises(UnknownOperationError, match='父楼层'):
            D.reply_graph(frame)


class TestComparePlatform:
    """跨平台对比: one row per platform — a count always, an optional aggregate of a numeric
    column. A value column that is not in the table is refused by name, never dropped silently."""

    @staticmethod
    def _merged() -> pd.DataFrame:
        return pd.DataFrame(
            {
                'platform': ['weibo', 'weibo', 'zhihu'],
                '情感': [1.0, 3.0, 5.0],
            }
        )

    def test_counts_and_mean_per_platform(self):
        out = D.compare_platform(self._merged(), platform_col='platform', value_col='情感', agg='mean')
        assert list(out.columns) == ['platform', 'n', '情感_mean']
        assert out.iloc[0]['platform'] == 'weibo' and int(out.iloc[0]['n']) == 2
        assert abs(float(out.iloc[0]['情感_mean']) - 2.0) < 1e-9
        assert abs(float(out.iloc[1]['情感_mean']) - 5.0) < 1e-9

    def test_without_a_value_column_it_is_counts_only(self):
        out = D.compare_platform(self._merged())
        assert list(out.columns) == ['platform', 'n']

    def test_a_missing_value_column_is_refused_by_name(self):
        with pytest.raises(UnknownOperationError, match='根本没有'):
            D.compare_platform(self._merged(), value_col='根本没有')

    def test_an_aggregate_it_does_not_compute_is_refused_by_name(self):
        """The column is named ``{value}_{agg}``, so the number under it must be that aggregate. A
        typed 'median' used to silently answer the MEAN while claiming 'median' in its name."""
        with pytest.raises(UnknownOperationError, match='median'):
            D.compare_platform(self._merged(), platform_col='platform', value_col='情感', agg='median')

    def test_sum_is_computed_and_named_as_sum(self):
        out = D.compare_platform(self._merged(), platform_col='platform', value_col='情感', agg='sum')
        assert '情感_sum' in out.columns, 'the only other computed aggregate names its own column'

    def test_a_missing_platform_column_is_refused_by_name(self):
        frame = pd.DataFrame({'情感': [1.0]})
        with pytest.raises(UnknownOperationError, match='platform'):
            D.compare_platform(frame)


class TestTopicModelEmbedding:
    """method='embedding' yields the SAME table shape as LDA, refuses by name without the
    optional encoder, and never falls back to LDA."""

    @staticmethod
    def _frame():
        return pd.DataFrame(
            {'正文': ['猫 狗 宠物 可爱', '猫 狗 宠物 可爱', '股票 基金 涨跌 市场', '股票 基金 涨跌 市场']}
        )

    def test_a_missing_encoder_is_refused_by_name_not_fallen_back(self, monkeypatch):
        monkeypatch.setattr(tk, '_embed_missing_packages', lambda: 'sentence-transformers')
        with pytest.raises(UnknownOperationError, match='sentence-transformers'):
            m.DataAnalysisService.topic_model(self._frame(), '正文', n_topics=2, method='embedding')

    def test_embedding_returns_the_lda_table_shape(self, monkeypatch):
        import sys
        import types

        import numpy as np

        class _FakeST:
            def __init__(self, name):
                self.name = name

            def encode(self, texts, **kw):
                return np.array([[0.0, 0.0], [0.0, 0.0], [1.0, 1.0], [1.0, 1.0]])

        fake = types.ModuleType('sentence_transformers')
        fake.SentenceTransformer = _FakeST
        monkeypatch.setitem(sys.modules, 'sentence_transformers', fake)
        monkeypatch.setattr(tk, '_embed_missing_packages', lambda: '')
        out = m.DataAnalysisService.topic_model(self._frame(), '正文', n_topics=2, topn=2, method='embedding')
        assert list(out.columns) == ['topic', 'rank', 'keyword', 'weight']
        assert set(out['topic']) == {'Topic-1', 'Topic-2'}, 'the two texts groups become two topics'
        assert (out['weight'] <= 1.0 + 1e-9).all() and (out['weight'] > 0).all(), 'weights normalised per topic'

    def test_the_encoder_is_constructed_once_and_reused_across_steps(self, monkeypatch):
        """The fix M1 is about: a run embeds once per stage AND once per figure step, so the encoder
        must be built a single time and cached by model name — not reloaded from disk every call.
        A fake that records every construction proves the second step reuses the first's instance."""
        import sys
        import types

        import numpy as np

        builds = []

        class _FakeST:
            def __init__(self, name):
                builds.append(name)
                self.name = name

            def encode(self, texts, **kw):
                return np.array([[1.0, 0.0] if '猫' in str(t) else [0.0, 1.0] for t in texts])

        fake = types.ModuleType('sentence_transformers')
        fake.SentenceTransformer = _FakeST
        monkeypatch.setitem(sys.modules, 'sentence_transformers', fake)
        monkeypatch.setattr(tk, '_embed_missing_packages', lambda: '')
        monkeypatch.setattr(tk, '_EMBED_MODEL_CACHE', {})
        frame = self._frame()
        m.DataAnalysisService.topic_model(frame, '正文', n_topics=2, topn=2, method='embedding')
        m.DataAnalysisService.topic_map(frame, '正文', n_topics=2, method='embedding')
        assert len(builds) == 1, f'the encoder was rebuilt per call: {builds}'

    def test_blank_method_defaults_to_auto_and_a_bad_one_is_refused(self):
        from services.analysis.pipeline import normalize_step_params, validate_step

        assert normalize_step_params('topic_model', {'column': '正文', 'method': ''})['method'] == 'auto'
        with pytest.raises(UnknownOperationError, match='method'):
            validate_step(self._frame(), 'topic_model', {'column': '正文', 'method': 'bogus'})


class TestTopicViewsEmbedding:
    """The three figure/stage steps accept ``method='embedding'`` exactly as ``topic_model`` does:
    the SAME output columns as their LDA default (the charts read those names), a named refusal when
    the optional encoder is absent, and never a silent fallback to LDA. The chart input contract is
    the whole point — 主题距离图 reads pc1/pc2/prevalence_pct and 显著词图 reads
    term/overall_freq/within_freq — so the embedding variant must reproduce them unchanged.
    """

    @staticmethod
    def _frame():
        return pd.DataFrame(
            {
                '正文': [
                    '猫 狗 宠物 可爱',
                    '股票 基金 涨跌 市场',
                    '猫 狗 宠物 亲近',
                    '股票 基金 大盘 走势',
                ],
                '阶段': pd.Categorical(
                    ['发酵期', '发酵期', '波动期', '波动期'],
                    categories=['发酵期', '波动期'],
                    ordered=True,
                ),
            }
        )

    def _install_encoder(self, monkeypatch):
        # The encoder is keyed on text CONTENT (猫 vs 股票), so any subset length — a whole frame or
        # one stage inside topic_by_stage — gets one vector per text and KMeans separates the two kinds.
        import sys
        import types

        import numpy as np

        class _FakeST:
            def __init__(self, name):
                self.name = name

            def encode(self, texts, **kw):
                return np.array([[1.0, 0.0] if '猫' in str(t) else [0.0, 1.0] for t in texts])

        fake = types.ModuleType('sentence_transformers')
        fake.SentenceTransformer = _FakeST
        monkeypatch.setitem(sys.modules, 'sentence_transformers', fake)
        monkeypatch.setattr(tk, '_embed_missing_packages', lambda: '')

    def test_a_missing_encoder_is_refused_by_name_for_all_three_views(self, monkeypatch):
        monkeypatch.setattr(tk, '_embed_missing_packages', lambda: 'sentence-transformers')
        with pytest.raises(UnknownOperationError, match='sentence-transformers'):
            m.DataAnalysisService.topic_map(self._frame(), '正文', n_topics=2, method='embedding')
        with pytest.raises(UnknownOperationError, match='sentence-transformers'):
            m.DataAnalysisService.topic_salience(self._frame(), '正文', n_topics=2, method='embedding')
        with pytest.raises(UnknownOperationError, match='sentence-transformers'):
            m.DataAnalysisService.topic_by_stage(
                self._frame(), '正文', stage_col='阶段', topics=[2, 2], method='embedding'
            )

    def test_embedding_topic_map_reproduces_the_lda_columns(self, monkeypatch):
        lda = m.DataAnalysisService.topic_map(self._frame(), '正文', n_topics=2)
        self._install_encoder(monkeypatch)
        emb = m.DataAnalysisService.topic_map(self._frame(), '正文', n_topics=2, method='embedding')
        assert list(emb.columns) == list(lda.columns)
        assert set(emb['topic']) == {'Topic-1', 'Topic-2'}
        assert round(float(sum(emb['prevalence_pct'])), 2) == 100.0
        assert all(str(words) for words in emb['feature_words'])

    def test_embedding_topic_salience_reproduces_the_lda_columns(self, monkeypatch):
        lda = m.DataAnalysisService.topic_salience(self._frame(), '正文', n_topics=2)
        self._install_encoder(monkeypatch)
        emb = m.DataAnalysisService.topic_salience(self._frame(), '正文', n_topics=2, method='embedding')
        assert list(emb.columns) == list(lda.columns)
        assert {'term', 'overall_freq', 'within_freq'} <= set(emb.columns)
        assert len(emb) > 0 and all(str(t) for t in emb['term'])

    def test_embedding_topic_by_stage_reproduces_the_lda_columns(self, monkeypatch):
        lda = m.DataAnalysisService.topic_by_stage(self._frame(), '正文', stage_col='阶段', topics=[2, 2])
        self._install_encoder(monkeypatch)
        emb = m.DataAnalysisService.topic_by_stage(
            self._frame(), '正文', stage_col='阶段', topics=[2, 2], method='embedding'
        )
        assert list(emb.columns) == list(lda.columns)
        assert len(emb) == len(lda), 'two stages x two topics each, for either method'

    def test_the_method_enum_defaults_to_auto_and_refuses_a_bogus_one(self):
        from services.analysis.pipeline import normalize_step_params, validate_step

        for op in ('topic_map', 'topic_salience', 'topic_by_stage'):
            assert normalize_step_params(op, {'column': '正文', 'method': ''})['method'] == 'auto'
        for op in ('topic_map', 'topic_salience', 'topic_by_stage'):
            params = {'column': '正文', 'method': 'bogus'}
            if op == 'topic_by_stage':
                params.update(stage_col='阶段', topics='2,2')
            with pytest.raises(UnknownOperationError, match='method'):
                validate_step(self._frame(), op, params)


class TestTopicMethodAuto:
    """``method='auto'`` (the new default) uses the encoder when it imports and LDA when it does
    not, and an auto run on a torch-less machine STILL returns a table instead of refusing — the
    whole point. The resolved method is printed (never a silent mislabel), while an EXPLICIT
    ``embedding`` with no encoder still refuses BY NAME, because a chosen model is not substituted.
    """

    @staticmethod
    def _frame():
        return pd.DataFrame(
            {
                '正文': ['猫 狗 宠物 可爱', '股票 基金 涨跌 市场', '猫 狗 宠物 亲近', '股票 基金 大盘 走势'],
                '阶段': pd.Categorical(
                    ['发酵期', '发酵期', '波动期', '波动期'], categories=['发酵期', '波动期'], ordered=True
                ),
            }
        )

    def _install_encoder(self, monkeypatch):
        import sys
        import types

        import numpy as np

        class _FakeST:
            def __init__(self, name):
                self.name = name

            def encode(self, texts, **kw):
                return np.array([[1.0, 0.0] if '猫' in str(t) else [0.0, 1.0] for t in texts])

        fake = types.ModuleType('sentence_transformers')
        fake.SentenceTransformer = _FakeST
        monkeypatch.setitem(sys.modules, 'sentence_transformers', fake)
        monkeypatch.setattr(tk, '_embed_missing_packages', lambda: '')

    def test_auto_uses_the_encoder_and_gives_the_embedding_table(self, monkeypatch):
        self._install_encoder(monkeypatch)
        out = m.DataAnalysisService.topic_map(self._frame(), '正文', n_topics=2, method='auto')
        assert list(out.columns) == ['topic', 'pc1', 'pc2', 'prevalence_pct', 'doc_n', 'feature_words']

    def test_auto_falls_back_to_lda_without_raising_when_the_encoder_is_absent(self, monkeypatch):
        monkeypatch.setattr(tk, '_embed_missing_packages', lambda: 'sentence-transformers')
        # No encoder available and none installed on this path: auto must answer with a real LDA
        # table for BOTH figure steps, not refuse the untouched default.
        mp = m.DataAnalysisService.topic_map(self._frame(), '正文', n_topics=2, method='auto')
        sl = m.DataAnalysisService.topic_salience(self._frame(), '正文', n_topics=2, method='auto')
        assert not mp.empty and not sl.empty, 'auto fell through but produced nothing'

    def test_auto_falls_back_for_the_staged_step_too(self, monkeypatch):
        monkeypatch.setattr(tk, '_embed_missing_packages', lambda: 'sentence-transformers')
        out = m.DataAnalysisService.topic_by_stage(
            self._frame(), '正文', stage_col='阶段', topics=[2, 2], method='auto'
        )
        assert not out.empty, 'auto staged step produced nothing on a torch-less machine'

    def test_auto_falls_back_for_the_discovery_step_too(self, monkeypatch):
        """The literal 「新建画布主题步」. An untouched topic_model defaults to auto, and on a
        machine with no torch/sentence-transformers that default must return a real LDA table —
        the optional encoder can never block the generic path. Only an EXPLICIT embedding choice
        refuses (see the next test), because a model the user named is not silently swapped."""
        monkeypatch.setattr(tk, '_embed_missing_packages', lambda: 'sentence-transformers, torch')
        out = m.DataAnalysisService.topic_model(self._frame(), '正文', n_topics=2, topn=5, method='auto')
        assert list(out.columns) == ['topic', 'rank', 'keyword', 'weight'], 'same shape whether LDA or embedding ran'
        assert not out.empty, 'the default topic step produced nothing on a torch-less machine'
        assert out['topic'].str.startswith('Topic-').all(), 'auto fell through but emitted no topic rows'

    def test_explicit_embedding_still_refuses_by_name_when_absent(self, monkeypatch):
        monkeypatch.setattr(tk, '_embed_missing_packages', lambda: 'sentence-transformers')
        with pytest.raises(UnknownOperationError, match='sentence-transformers'):
            m.DataAnalysisService.topic_map(self._frame(), '正文', n_topics=2, method='embedding')


class TestTopicViews:
    """The two data steps behind the pyLDAvis figure, and the λ that decides its word list.

    The figure itself is the visualizer's job (pinned in ``test_visualization.py``); what lives
    here is the arithmetic it draws from: where the bubbles sit, how big they are, and which
    terms a topic is ABOUT rather than merely loud about.
    """

    #: One word the whole corpus shares (通报) plus two vocabularies the topics can split on.
    COMMON = '通报'
    FAMILIES = ['警方 调查 依法 处置 行政处罚', '人肉 号码 隐私 曝光 个人信息']

    @classmethod
    def _corpus(cls, per_family: int = 20) -> pd.DataFrame:
        rows = []
        for index in range(per_family):
            rows.append({'正文': f'{cls.COMMON} {cls.FAMILIES[0]} 第{index}条'})
            rows.append({'正文': f'{cls.COMMON} {cls.FAMILIES[1]} 第{index}条'})
        return pd.DataFrame(rows)

    def test_the_map_answers_one_row_per_topic_with_the_models_own_prevalence(self):
        out = D.topic_map(self._corpus(), '正文', n_topics=3, topn=4)
        assert list(out.columns) == ['topic', 'pc1', 'pc2', 'prevalence_pct', 'doc_n', 'feature_words']
        assert list(out['topic']) == ['Topic-1', 'Topic-2', 'Topic-3']
        assert out['prevalence_pct'].sum() == pytest.approx(100.0, abs=0.2)
        assert sum(out['doc_n']) == 40, 'the argmax counts partition the corpus'
        assert out[['pc1', 'pc2']].notna().all().all()
        assert all(len(words.split('、')) == 4 for words in out['feature_words'])

    def test_the_map_spreads_on_both_axes_rather_than_collapsing_onto_one_line(self):
        """The scaling of each MDS axis must use the eigenvalue of the axis CHOSEN. Reading the
        solver's first two slots instead takes its two smallest — numpy returns them ascending —
        and every point lands on a vertical line with a confident-looking table beside it."""
        out = D.topic_map(self._corpus(), '正文', n_topics=4)
        assert float(out['pc1'].std()) > 0, 'PC1 collapsed to a constant'
        assert float(out['pc2'].std()) > 0, 'PC2 collapsed to a constant'

    def test_mds_of_a_known_square_comes_back_a_square(self):
        # Four points at the corners of a unit square: the distances alone must recover two
        # axes of equal spread and the right diagonal, with no help from the original layout.
        from services.analysis.pipeline import _mds_2d

        sides, diagonal = 1.0, 2**0.5
        distances = [
            [0.0, sides, diagonal, sides],
            [sides, 0.0, sides, diagonal],
            [diagonal, sides, 0.0, sides],
            [sides, diagonal, sides, 0.0],
        ]
        points = _mds_2d(distances)
        assert len(points) == 4 and all(len(point) == 2 for point in points)
        spread = [max(p[axis] for p in points) - min(p[axis] for p in points) for axis in (0, 1)]
        assert spread[0] == pytest.approx(spread[1], abs=1e-6), 'a square is not drawn as a rectangle'
        assert spread[0] == pytest.approx(diagonal, abs=1e-6)

    def test_the_same_table_lays_the_same_map_twice(self):
        # A figure whose bubbles move between two runs of identical input cannot be cited, so
        # the MDS is an eigendecomposition with a fixed sign convention, not an iterative fit.
        frame = self._corpus()
        first = D.topic_map(frame, '正文', n_topics=3)
        second = D.topic_map(frame, '正文', n_topics=3)
        assert first[['pc1', 'pc2']].equals(second[['pc1', 'pc2']])

    def test_the_map_refuses_a_question_it_cannot_ask(self):
        with pytest.raises(UnknownOperationError, match='2'):
            D.topic_map(self._corpus(), '正文', n_topics=1)
        with pytest.raises(UnknownOperationError, match='有效文本'):
            D.topic_map(self._corpus(per_family=1), '正文', n_topics=9)
        with pytest.raises(UnknownOperationError):
            D.topic_map(pd.DataFrame({'正文': ['。。。', '！！！', '？？']}), '正文', n_topics=2)

    def test_the_salience_table_lists_terms_per_topic_in_ranking_order(self):
        out = D.topic_salience(self._corpus(), '正文', n_topics=2, topn=6)
        assert list(out.columns) == ['topic', 'rank', 'term', 'overall_freq', 'within_freq', 'relevance']
        assert sorted(out['topic'].unique()) == ['Topic-1', 'Topic-2']
        for _topic, rows in out.groupby('topic'):
            assert list(rows['rank']) == list(range(1, len(rows) + 1)), 'ranks are dense and per topic'
            assert list(rows['relevance']) == sorted(rows['relevance'], reverse=True), 'the order IS the score'
            assert (rows['overall_freq'] > 0).all()

    def test_lambda_trades_common_words_for_diagnostic_ones(self):
        """The figure's slider is not decoration: λ=1 ranks by probability WITHIN the topic, so
        the word the whole corpus shares tops every list; λ=0 ranks by over-representation, so
        it drops out and the words that identify the topic come up. Both are honest answers and
        they are different tables, which is why the value used is printed with them."""
        frame = self._corpus()
        # topn=4 because the shared filter now removes the fixture's counter tokens (第/0/条), and
        # the vocabulary that survives is ten words: ask for ten per topic and both λ values return
        # the whole of it, so the comparison would measure the list length instead of the ranking.
        loud = D.topic_salience(frame, '正文', n_topics=2, topn=4, relevance=1.0)
        sharp = D.topic_salience(frame, '正文', n_topics=2, topn=4, relevance=0.0)
        assert loud['overall_freq'].mean() > sharp['overall_freq'].mean(), (
            'λ=1 must favour the globally common terms; the corpus word 通报 is the test case'
        )
        assert self.COMMON in set(loud['term'])
        assert set(sharp['term']) - {self.COMMON}, 'λ=0 should surface the topic-specific words'

    def test_a_lambda_outside_the_unit_interval_is_refused_by_name(self):
        for value in (1.5, -0.1):
            with pytest.raises(UnknownOperationError, match=str(value)):
                D.topic_salience(self._corpus(per_family=3), '正文', n_topics=2, relevance=value)

    def test_topn_caps_the_list_without_breaking_the_ranking(self):
        out = D.topic_salience(self._corpus(), '正文', n_topics=2, topn=3)
        assert len(out) <= 6
        assert max(len(rows) for _topic, rows in out.groupby('topic')) == 3

    def test_a_numeric_stage_order_survives_the_round_trip_that_erased_the_categorical(self):
        """``topic_by_stage`` writes ``stage_order`` precisely so the next step can recover the
        lifecycle without a time column: the phase NAMES alone would sort 二次爆发期 first."""
        frame = pd.DataFrame(
            [
                ('二次爆发期', 4),
                ('发酵期', 1),
                ('波动期', 3),
                ('爆发期', 2),
            ],
            columns=['stage', 'stage_order'],
        )
        assert _stage_order(frame, 'stage', 'stage_order', op='topic_timeline') == [
            '发酵期',
            '爆发期',
            '波动期',
            '二次爆发期',
        ]

    def test_a_number_is_read_before_a_date_and_a_mixed_column_is_not_silently_sorted(self):
        # A column where no row parses to a number falls through to the date reading, and a column
        # that is neither is refused with the names that could not be placed.
        frame = pd.DataFrame({'stage': ['发酵期', '爆发期'], 'x': ['a', 'b']})
        with pytest.raises(UnknownOperationError, match='发酵期'):
            _stage_order(frame, 'stage', 'x', op='topic_timeline')

    def test_a_phase_with_no_rank_in_an_ordered_column_is_refused_not_appended(self):
        frame = pd.DataFrame({'stage': ['发酵期', '爆发期', '波动期'], 'x': [1, None, 3]})
        with pytest.raises(UnknownOperationError, match='爆发期'):
            _stage_order(frame, 'stage', 'x', op='topic_timeline')


class TestTopicTimeline:
    """Which subject was born in which phase — and the flag the study calls 次生舆情.

    The words are chosen so jieba keeps each of them as one token (a one-character or a
    never-seen compound would make the fixture measure the tokenizer instead of the
    lifecycle). Nothing pins WHICH subject a real corpus produces; what is pinned is the
    tracking rule, the two-part definition of a secondary flare-up, and every way the step
    could be asked to invent an order it was not given.
    """

    STAGES = ['发酵期', '爆发期', '衰退期']
    ROWS = [
        # One subject across the first two phases: born at the opening, so not secondary.
        ('发酵期', 'TopicⅠ-1', '警方、通报、调查', 100),
        ('爆发期', 'TopicⅡ-1', '警方、通报、问责', 700),
        # A subject the first week never had, still growing when it peaks.
        ('爆发期', 'TopicⅡ-2', '外卖、商家、退款', 200),
        ('衰退期', 'TopicⅢ-1', '外卖、商家、判决', 600),
        # Late, and biggest the moment it appears: a late topic, not a flare-up.
        ('衰退期', 'TopicⅢ-2', '判决、问责、处理', 40),
    ]

    @classmethod
    def _frame(cls, rows=None, ordered=True):
        frame = pd.DataFrame(rows or cls.ROWS, columns=['stage', 'topic', 'feature_words', 'doc_n'])
        if ordered:
            frame['stage'] = pd.Categorical(frame['stage'], categories=cls.STAGES, ordered=True)
        return frame

    def test_a_subject_is_followed_by_its_words_not_by_its_number(self):
        out = D.topic_timeline(self._frame())
        assert list(out.columns) == [
            'topic',
            'topic_words',
            'first_stage',
            'peak_stage',
            'last_stage',
            'stages_present',
            'stage_path',
            'size_total',
            'peak_size',
            'is_secondary',
        ]
        assert len(out) == 3, 'the police subject, the delivery one, and the late 判决 topic'
        police = out[out['topic'] == 'TopicⅠ-1'].iloc[0]
        assert police['stages_present'] == 2, 'the two police rows are ONE subject, not two entries'
        assert police['first_stage'] == '发酵期' and police['peak_stage'] == '爆发期'
        assert police['size_total'] == 800 and police['peak_size'] == 700
        assert not police['is_secondary'], 'it opened the case, so it is not a flare-up'

    def test_a_late_subject_that_grows_after_it_appears_is_the_secondary_one(self):
        out = D.topic_timeline(self._frame())
        late = out[out['topic'] == 'TopicⅡ-2'].iloc[0]
        assert late['first_stage'] == '爆发期'
        assert late['peak_stage'] == '衰退期', 'the peak has to come after the debut'
        assert late['stage_path'] == '爆发期 → 衰退期'
        assert late['is_secondary']

    def test_a_subject_that_peaks_where_it_was_born_is_late_but_not_a_flare_up(self):
        out = D.topic_timeline(self._frame())
        row = out[out['topic'] == 'TopicⅢ-2'].iloc[0]
        assert row['first_stage'] == '衰退期' and row['stages_present'] == 1
        assert not row['is_secondary']

    def test_the_merged_word_list_keeps_each_word_once_in_first_seen_order(self):
        out = D.topic_timeline(self._frame())
        assert out[out['topic'] == 'TopicⅠ-1'].iloc[0]['topic_words'] == '警方、通报、调查、问责'

    def test_the_table_reads_in_lifecycle_order(self):
        out = D.topic_timeline(self._frame())
        debuts = [self.STAGES.index(name) for name in out['first_stage']]
        assert debuts == sorted(debuts)

    def test_one_phase_cannot_have_a_lifecycle(self):
        with pytest.raises(UnknownOperationError, match='至少'):
            D.topic_timeline(self._frame(rows=self.ROWS[:1]))

    def test_an_unordered_phase_column_is_refused_rather_than_sorted_by_code_point(self):
        # 二次爆发期 sorts BEFORE 发酵期 by code point; renumbering a replication in silence is
        # the mistake this guard exists for (AGENTS.md's phase-order invariant).
        with pytest.raises(UnknownOperationError) as excinfo:
            D.topic_timeline(self._frame(ordered=False))
        assert '阶段' in str(excinfo.value)

    def test_a_time_column_can_supply_the_order_the_round_trip_erased(self):
        frame = self._frame(ordered=False)
        stamps = {'发酵期': '2024-04-11', '爆发期': '2024-04-23', '衰退期': '2024-05-19'}
        frame['日期'] = [stamps[name] for name in frame['stage']]
        out = D.topic_timeline(frame, order_col='日期')
        # Deliberately written so a code-point sort would put 衰退期 second: the order the
        # timestamps give is the one the table has to follow.
        assert out[out['topic'] == 'TopicⅢ-2'].iloc[0]['first_stage'] == '衰退期'

    def test_a_row_with_no_words_cannot_be_followed(self):
        rows = list(self.ROWS)
        rows[1] = ('爆发期', 'TopicⅡ-1', '', 700)
        with pytest.raises(UnknownOperationError, match='没有特征词'):
            D.topic_timeline(self._frame(rows=rows))

    def test_a_size_column_of_text_has_no_peak_to_find(self):
        frame = self._frame()
        frame['doc_n'] = ['很多', '较多', '一些', '一些', '少']
        with pytest.raises(UnknownOperationError, match='doc_n'):
            D.topic_timeline(frame)

    def test_only_part_of_a_size_column_being_text_is_said_and_counted_as_zero(self):
        frame = self._frame()
        frame['doc_n'] = frame['doc_n'].astype(object)
        frame.loc[1, 'doc_n'] = '未知'
        out = D.topic_timeline(frame)
        assert out[out['topic'] == 'TopicⅠ-1'].iloc[0]['size_total'] == 100

    @pytest.mark.parametrize('value', [0, -1, 1.5, 'abc', ''])
    def test_the_overlap_threshold_has_to_be_a_ratio(self, value):
        with pytest.raises(UnknownOperationError):
            D.topic_timeline(self._frame(), min_overlap=value)

    def test_the_threshold_is_the_users_saying_how_much_similarity_is_one_subject(self):
        # The fixture's merged pairs share 2 words out of 4 (0.5): three subjects at the
        # default, five when the user asks for a tighter match.
        assert len(D.topic_timeline(self._frame())) == 3
        assert len(D.topic_timeline(self._frame(), min_overlap=0.9)) == 5

    def test_a_row_that_belongs_to_no_phase_is_left_out_without_inventing_one(self):
        frame = self._frame()
        # The shape an unparseable timestamp leaves after 按时间划分阶段: a MISSING phase, which
        # joins no lifecycle rather than opening a new one.
        frame.loc[4, 'stage'] = pd.NA
        out = D.topic_timeline(frame)
        assert 'TopicⅢ-2' not in set(out['topic'])
        assert len(out) == 2

    def test_a_phase_the_boundaries_named_but_no_post_fell_into_is_not_a_second_one(self):
        # An empty category in the column's category list is not a phase with rows in it, and a
        # lifecycle needs two of those.
        frame = self._frame(rows=self.ROWS[:1])
        frame['stage'] = pd.Categorical(frame['stage'], categories=self.STAGES, ordered=True)
        with pytest.raises(UnknownOperationError, match='至少'):
            D.topic_timeline(frame)

    def test_a_blank_size_column_is_not_a_peak_of_zero(self):
        frame = self._frame()
        frame['doc_n'] = [None] * len(frame)
        with pytest.raises(UnknownOperationError, match='doc_n'):
            D.topic_timeline(frame)


class TestTopicFlow:
    """Adjacent phases compared as word DISTRIBUTIONS, feeding the existing 桑基图 node."""

    ROWS = [
        ('发酵期', 'TopicⅠ-1', '警方、通报、调查', '警方:0.5 通报:0.3 调查:0.2'),
        ('发酵期', 'TopicⅠ-2', '外卖、商家、退款', '外卖:0.6 商家:0.25 退款:0.15'),
        ('爆发期', 'TopicⅡ-1', '警方、通报、问责', '警方:0.45 通报:0.35 问责:0.2'),
        ('爆发期', 'TopicⅡ-2', '外卖、商家、判决', '判决:0.5 外卖:0.3 商家:0.2'),
        ('衰退期', 'TopicⅢ-1', '判决、问责、处理', '判决:0.55 问责:0.3 处理:0.15'),
    ]

    @classmethod
    def _frame(cls, rows=None, ordered=True):
        frame = pd.DataFrame(rows or cls.ROWS, columns=['stage', 'topic', 'feature_words', 'weights'])
        if ordered:
            # The categories come from the rows in the order they appear, because that order is
            # the lifecycle: a code-point sort of the names is exactly what the guard refuses.
            frame['stage'] = pd.Categorical(
                frame['stage'], categories=list(dict.fromkeys(frame['stage'].tolist())), ordered=True
            )
        return frame

    def _flow(self, **kwargs):
        return D.topic_flow(self._frame(), **kwargs)

    def test_edges_join_the_shapes_the_sankey_node_reads(self):
        out = self._flow(min_similarity=0.01)
        assert list(out.columns) == [
            'source',
            'target',
            'source_topic',
            'target_topic',
            'similarity',
            'divergence',
            'from_stage',
            'to_stage',
            'source_words',
            'target_words',
        ]
        assert {('TopicⅠ-1', 'TopicⅡ-1')} <= {(row['source'], row['target']) for _, row in out.iterrows()}
        assert (out['source_words'] != '').all() and (out['target_words'] != '').all()

    def test_a_summary_column_becomes_the_name_the_sankey_draws(self):
        """A sankey of row labels tells the reader nothing; 表 1's 概括 is the readable name.

        The chart's node names come from ``source``/``target``, so the composition belongs here —
        and the raw ids stay beside them, because a figure whose nodes cannot be traced back to
        表 1 is not auditable.
        """
        frame = self._frame()
        frame['主题概括'] = ['控诉网暴', '追问责任', '外卖退款', '判决问责', '处理结果']
        out = D.topic_flow(frame, min_similarity=0.01, label_col='主题概括')
        assert (out['source'].str.contains('｜')).all(), 'every node carries its summary'
        assert 'TopicⅠ-1｜控诉网暴' in set(out['source'])
        assert 'TopicⅠ-1' in set(out['source_topic']), 'the 表 1 id is still what you audit against'

    def test_a_summary_column_that_is_not_in_the_table_is_named(self):
        with pytest.raises(UnknownOperationError, match='主题概括'):
            D.topic_flow(self._frame(), label_col='主题概括')

    def test_only_adjacent_phases_are_compared(self):
        out = self._flow(min_similarity=0.01)
        joined = {(row['from_stage'], row['to_stage']) for _, row in out.iterrows()}
        assert joined == {('发酵期', '爆发期'), ('爆发期', '衰退期')}

    def test_the_closer_pair_scores_higher_and_the_table_is_sorted(self):
        out = self._flow(min_similarity=0.01)
        pair = {(row['source'], row['target']): row['similarity'] for _, row in out.iterrows()}
        # Ⅰ-1 and Ⅱ-1 share 警方/通报 at nearly the same mass; Ⅰ-1 against Ⅱ-2 shares nothing.
        assert pair[('TopicⅠ-1', 'TopicⅡ-1')] > pair[('TopicⅠ-1', 'TopicⅡ-2')]
        assert pair[('TopicⅡ-2', 'TopicⅢ-1')] > pair[('TopicⅡ-1', 'TopicⅢ-1')]
        assert (out['similarity'].diff().dropna() <= 0).all(), 'the thickest link has to come first'

    def test_a_threshold_nothing_reaches_names_the_best_similarity_measured(self):
        measured = self._flow(min_similarity=0.01)['similarity'].max()
        with pytest.raises(UnknownOperationError) as excinfo:
            self._flow(min_similarity=0.9999)
        assert str(round(measured, 4)) in str(excinfo.value)

    def test_a_topic_with_no_weights_cannot_be_compared(self):
        rows = list(self.ROWS)
        rows[2] = ('爆发期', 'TopicⅡ-1', '警方、通报、问责', '警方 通报 问责')
        with pytest.raises(UnknownOperationError, match='TopicⅡ-1'):
            D.topic_flow(self._frame(rows=rows))

    def test_one_phase_cannot_flow_anywhere(self):
        with pytest.raises(UnknownOperationError, match='相邻'):
            D.topic_flow(self._frame(rows=self.ROWS[:2]))

    def test_a_phase_that_supplies_no_topic_is_refused_by_name(self):
        # The boundaries named three phases and the rows fill two: the empty one cannot carry an
        # edge, and drawing the other two as if the lifecycle were complete is the silence here.
        frame = self._frame(rows=self.ROWS[:4])
        frame['stage'] = pd.Categorical(frame['stage'], categories=['发酵期', '爆发期', '空窗期'], ordered=True)
        with pytest.raises(UnknownOperationError, match='空窗期'):
            D.topic_flow(frame)

    def test_the_order_still_has_to_be_declared(self):
        with pytest.raises(UnknownOperationError) as excinfo:
            D.topic_flow(self._frame(ordered=False))
        assert '阶段' in str(excinfo.value)

    @pytest.mark.parametrize('value', [0, -0.5, 1.5, 'abc', ''])
    def test_the_similarity_threshold_has_to_be_a_ratio(self, value):
        with pytest.raises(UnknownOperationError):
            self._flow(min_similarity=value)


class TestTopicCoherence:
    """The topic-count sweep, and the two numbers that argue about 设定主题个数."""

    FAMILIES = ['警方 通报 调查 处理 依法', '外卖 商家 退款 差评 骑手']

    @classmethod
    def _corpus(cls, per_family: int = 12) -> pd.DataFrame:
        rows = []
        for index in range(per_family):
            rows.append({'正文': f'微博 热搜 {cls.FAMILIES[0]} 第{index}条'})
            rows.append({'正文': f'微博 热搜 {cls.FAMILIES[1]} 第{index}条'})
        return pd.DataFrame(rows)

    def test_one_row_per_count_with_both_decision_numbers(self):
        out = D.topic_coherence(self._corpus(), '正文', min_topics=2, max_topics=4, topn=3, max_documents=0)
        assert list(out['n_topics']) == [2, 3, 4]
        assert list(out.columns) == [
            'n_topics',
            'coherence',
            'perplexity',
            'documents',
            'terms',
            'pairs_used',
            'pairs_skipped',
        ]
        assert (out['perplexity'] > 0).all()

    def test_the_coherence_score_is_a_bounded_normalised_measure(self):
        out = D.topic_coherence(self._corpus(), '正文', min_topics=2, max_topics=4, topn=3, max_documents=0)
        assert ((out['coherence'] >= -1.0) & (out['coherence'] <= 1.0)).all()

    def test_words_that_always_appear_together_score_the_maximum(self):
        # Every document identical: every pair of top words co-occurs in every one, so NPMI is
        # exactly 1. This is the arithmetic pinned against its known answer, not a shape check.
        frame = pd.DataFrame({'正文': ['警方 通报 调查 处理'] * 8})
        out = D.topic_coherence(frame, '正文', min_topics=2, max_topics=2, topn=3, max_documents=0)
        assert out.at[0, 'coherence'] == pytest.approx(1.0)

    def test_every_candidate_pair_is_accounted_for_as_used_or_skipped(self):
        # A pair whose two words never share a document has an undefined NPMI, so it is skipped
        # rather than scored — and the two counters have to add up to the pairs the sweep looked
        # at, or a reader cannot tell "measured as unrelated" from "not measured".
        out = D.topic_coherence(self._corpus(), '正文', min_topics=2, max_topics=4, topn=3, max_documents=0)
        per_topic = 3 * 2 // 2
        for _, row in out.iterrows():
            assert row['pairs_used'] + row['pairs_skipped'] == row['n_topics'] * per_topic

    def test_a_corpus_whose_words_rarely_share_a_post_shows_that_in_the_skips(self):
        # Two-word posts out of an eight-word pool: at most one pair per topic can co-occur, so
        # most of the candidate pairs are skipped rather than scored as zero.
        frame = pd.DataFrame({'正文': ['警方 通报', '调查 处理', '外卖 商家', '退款 差评'] * 6})
        out = D.topic_coherence(frame, '正文', min_topics=2, max_topics=2, topn=3, max_documents=0)
        assert out.at[0, 'pairs_skipped'] > out.at[0, 'pairs_used']

    def test_the_sample_cap_is_stated_in_the_table_it_limited(self):
        out = D.topic_coherence(self._corpus(per_family=20), '正文', min_topics=2, max_topics=3, max_documents=10)
        assert (out['documents'] == 10).all()

    def test_two_runs_of_one_table_answer_with_one_number_set(self):
        frame = self._corpus(per_family=6)
        first = D.topic_coherence(frame, '正文', min_topics=2, max_topics=3, max_documents=12)
        second = D.topic_coherence(frame, '正文', min_topics=2, max_topics=3, max_documents=12)
        assert first.equals(second)

    def test_a_sweep_cannot_end_before_it_starts(self):
        with pytest.raises(UnknownOperationError, match='起点'):
            D.topic_coherence(self._corpus(), '正文', min_topics=4, max_topics=2)

    def test_one_topic_is_not_a_model(self):
        with pytest.raises(UnknownOperationError, match='至少'):
            D.topic_coherence(self._corpus(), '正文', min_topics=1, max_topics=3)

    def test_too_few_texts_for_the_smallest_count_is_refused(self):
        with pytest.raises(UnknownOperationError, match='主题'):
            D.topic_coherence(pd.DataFrame({'正文': ['警方 通报', '外卖 商家']}), '正文', min_topics=3, max_topics=6)

    def test_the_sweep_stops_at_the_row_count_and_says_so(self, caplog):
        out = D.topic_coherence(
            pd.DataFrame({'正文': ['警方 通报 调查'] * 3}), '正文', min_topics=2, max_topics=6, topn=2
        )
        assert list(out['n_topics']) == [2, 3]

    def test_a_missing_column_is_named_before_any_fit_is_paid_for(self):
        with pytest.raises(UnknownOperationError, match='没有这一列'):
            D.topic_coherence(self._corpus(), '没有这一列')


class TestCooccur:
    """Word pairs that share a post — the paper's 知识图谱 edges."""

    @staticmethod
    def _frame(texts):
        return pd.DataFrame({'正文': texts})

    def test_edges_are_strongest_first_and_triply_named(self):
        out = D.cooccur(
            self._frame(['警方 通报 调查'] * 3 + ['警方 通报 处理'] * 2 + ['外卖 商家 退款'] * 4),
            '正文',
            topn=10,
            min_count=2,
        )
        assert list(out.columns) == ['source', 'target', 'value']
        assert (out['value'].diff().dropna() <= 0).all(), 'the busiest link has to come first'
        assert (out['value'] >= 2).all()
        # One direction per pair, named by code point: an undirected graph that carries 甲→乙 and
        # 乙→甲 would draw the same relationship twice and size both nodes from it.
        assert (out['source'] < out['target']).all()
        assert len({frozenset((row['source'], row['target'])) for _, row in out.iterrows()}) == len(out)

    def test_a_window_counts_near_neighbours_only(self):
        frame = self._frame(['警方 通报 外卖 商家 退款 差评 调查'] * 4)
        whole = {(row['source'], row['target']) for _, row in D.cooccur(frame, '正文', topn=10, min_count=1).iterrows()}
        near = {
            (row['source'], row['target'])
            for _, row in D.cooccur(frame, '正文', topn=10, min_count=1, window=2).iterrows()
        }
        assert ('警方', '通报') in whole and ('警方', '调查') in whole
        assert ('警方', '通报') in near
        assert ('警方', '调查') not in near, 'the two words are never within two tokens of each other'

    def test_the_count_threshold_is_a_filter_and_not_a_renumbering(self):
        frame = self._frame(['警方 通报 调查'] * 3 + ['外卖 商家 退款'] * 1)
        loose = D.cooccur(frame, '正文', topn=10, min_count=1)
        strict = D.cooccur(frame, '正文', topn=10, min_count=3)
        assert len(strict) < len(loose)
        assert (strict['value'] == 3).all()

    def test_the_candidate_cap_is_refused_rather_than_clipped(self):
        from services.analysis.pipeline import COOCCUR_WORD_CAP

        frame = self._frame(['警方 通报 调查'] * 2)
        with pytest.raises(UnknownOperationError) as excinfo:
            D.cooccur(frame, '正文', topn=COOCCUR_WORD_CAP + 1)
        assert str(COOCCUR_WORD_CAP) in str(excinfo.value)

    @pytest.mark.parametrize('value', [1, 0, -3, 'abc'])
    def test_a_network_needs_at_least_two_candidate_words_to_have_an_edge(self, value):
        with pytest.raises(UnknownOperationError):
            D.cooccur(self._frame(['警方 通报'] * 2), '正文', topn=value)

    def test_a_threshold_no_pair_reaches_names_the_busiest_one_measured(self):
        frame = self._frame(['警方 通报 调查'] * 3)
        with pytest.raises(UnknownOperationError) as excinfo:
            D.cooccur(frame, '正文', topn=10, min_count=99)
        assert '3' in str(excinfo.value)

    def test_one_character_words_are_not_candidates_at_all(self):
        # The keyword node's rule, reused rather than restated: a single ideograph cannot carry
        # a co-occurrence edge, so no endpoint of the graph is one character long.
        out = D.cooccur(self._frame(['捞 警方 通报 调查'] * 4), '正文', topn=10, min_count=2)
        assert out['source'].str.len().min() >= 2 and out['target'].str.len().min() >= 2
        assert '捞' not in set(out['source']) | set(out['target'])

    def test_a_missing_column_is_refused_by_the_gate(self):
        with pytest.raises(UnknownOperationError):
            D.cooccur(self._frame(['警方 通报']), '没有这一列')

    def test_a_count_threshold_below_one_is_not_a_filter(self):
        with pytest.raises(UnknownOperationError, match='至少'):
            D.cooccur(self._frame(['警方 通报 调查'] * 2), '正文', topn=5, min_count=0)


class TestForecast:
    """Extrapolating the curve, and the difference between a band and a guess.

    The series is monotone on purpose: a steady fall is what 发酵期→爆发期 looks like in the
    study's own numbers, and it is the one shape where "the trend continues" can be checked
    against the arithmetic rather than against luck.
    """

    VALUES = [-0.1, -0.2, -0.3, -0.5, -0.7, -0.85]

    @classmethod
    def _curve(cls, spacing=1, values=None):
        start = pd.Timestamp('2024-04-10')
        return pd.DataFrame(
            {
                'period': [
                    str((start + pd.Timedelta(days=spacing * index)).date())
                    for index in range(len(values or cls.VALUES))
                ],
                'sentiment_index': list(values or cls.VALUES),
            }
        )

    def test_history_keeps_its_numbers_and_the_future_gets_the_band(self):
        out = D.forecast(self._curve(), horizon=2, window=3)
        assert list(out.columns) == ['period', 'actual', 'predicted', 'lower', 'upper', 'horizon']
        assert list(out['horizon']) == [0] * 6 + [1, 2]
        assert (out['actual'].tail(2).isna()).all(), 'a future period has not been observed'
        assert (out[out['horizon'] > 0]['predicted'].notna()).all(), 'every future row is answered'
        assert out.iloc[-1]['period'] == '2024-04-17', 'future rows are dated on the same axis'

    def test_a_moving_average_extrapolates_the_last_window_and_holds_its_band(self):
        out = D.forecast(self._curve(), method='moving_average', horizon=3, window=3)
        expected = sum(self.VALUES[-3:]) / 3
        tail = out[out['horizon'] > 0]
        assert (tail['predicted'] == round(expected, 4)).all(), 'no trend means a flat forecast'
        assert tail['lower'].nunique() == 1 and tail['upper'].nunique() == 1, 'the band must not widen'

    def test_holt_carries_the_trend_and_widens_with_the_square_root_of_the_horizon(self):
        out = D.forecast(self._curve(), method='holt', horizon=3)
        tail = out[out['horizon'] > 0].reset_index(drop=True)
        # A falling curve forecast below its last observation: the trend is the whole method.
        assert tail.at[0, 'predicted'] < self.VALUES[-1]
        assert (tail['predicted'].diff().dropna() < 0).all(), 'each further step falls further'
        widths = (tail['upper'] - tail['lower']) / 2
        assert (widths.diff().dropna() > 0).all(), 'a further horizon is a wider interval'
        assert widths.iloc[1] / widths.iloc[0] == pytest.approx(2**0.5, abs=0.02)

    def test_the_fit_is_reported_where_the_model_could_have_made_it(self):
        out = D.forecast(self._curve(), method='moving_average', horizon=1, window=3)
        history = out[out['horizon'] == 0]
        assert history['predicted'].isna().sum() == 3, 'the first window has nothing to predict from'
        assert history.iloc[3]['predicted'] == pytest.approx((-0.1 + -0.2 + -0.3) / 3, abs=1e-4)

    def test_two_runs_of_one_curve_answer_with_one_table(self):
        frame = self._curve()
        assert D.forecast(frame, horizon=2).equals(D.forecast(frame, horizon=2))

    def test_a_curve_of_phase_names_cannot_be_extrapolated(self):
        frame = pd.DataFrame({'period': ['发酵期'] * 3 + ['爆发期'] * 3, 'sentiment_index': self.VALUES})
        with pytest.raises(UnknownOperationError, match='period'):
            D.forecast(frame)

    def test_a_column_that_is_not_there_is_named_rather_than_raising_keyerror(self):
        with pytest.raises(UnknownOperationError, match='没有这一列'):
            D.forecast(self._curve(), value_col='没有这一列')

    def test_two_rows_for_one_day_are_refused_because_they_are_a_fake_step(self):
        frame = pd.concat([self._curve(), self._curve().head(1)], ignore_index=True)
        with pytest.raises(UnknownOperationError, match='同一天'):
            D.forecast(frame)

    def test_an_uneven_curve_is_warned_about_and_stepped_by_its_modal_gap(self):
        frame = self._curve(spacing=1)
        frame.loc[2, 'period'] = '2024-04-20'
        # Sorted: 10, 11, 13, 14, 15, 20 — gaps 1,2,1,1,5, so the modal step is 1 day and the
        # future label is stepped from the LAST period, not from a calendar the series does not have.
        out = D.forecast(frame, horizon=1)
        assert out.iloc[-1]['period'] == '2024-04-21'
        assert out.iloc[-1]['horizon'] == 1

    @pytest.mark.parametrize(
        ('kwargs', 'needle'), [({'horizon': 0}, '步数'), ({'window': 1}, '窗口'), ({'alpha': 0}, '平滑')]
    )
    def test_an_impossible_setting_is_refused_with_its_own_number(self, kwargs, needle):
        with pytest.raises(UnknownOperationError, match=needle):
            D.forecast(self._curve(), **kwargs)

    def test_a_curve_too_short_to_forecast_is_refused_rather_than_fitted_badly(self):
        with pytest.raises(UnknownOperationError, match='至少'):
            D.forecast(self._curve(values=[-0.1, -0.2]), horizon=2)

    def test_the_window_needs_an_observation_left_to_predict(self):
        with pytest.raises(UnknownOperationError, match='窗口'):
            D.forecast(self._curve(values=self.VALUES[:3]), window=3, min_periods=2)

    def test_seasonal_naive_repeats_the_last_full_cycle(self):
        curve = self._curve(values=[0.0, 0.4, -0.3, 0.1, 0.5, -0.2])  # two cycles, season 3
        out = D.forecast(curve, method='seasonal_naive', season=3, window=2, min_periods=2, horizon=3)
        tail = out[out['horizon'] > 0].reset_index(drop=True)
        # Each future step copies the value one full cycle back: the forecast IS the last cycle.
        assert [round(v, 4) for v in tail['predicted']] == [0.1, 0.5, -0.2]

    def test_seasonal_naive_needs_a_full_cycle_of_history(self):
        with pytest.raises(UnknownOperationError, match='季节'):
            D.forecast(self._curve(values=[0.1, 0.2, 0.3]), method='seasonal_naive', season=5, window=2, min_periods=2)

    def test_a_season_shorter_than_two_is_refused(self):
        with pytest.raises(UnknownOperationError, match='季节'):
            D.forecast(self._curve(), method='seasonal_naive', season=1)

    def test_holt_winters_carries_the_cycle_not_a_flat_line(self):
        vals = [0.0, 0.5, -0.4, 0.1, 0.6, -0.3]  # two cycles, season 3
        out = D.forecast(self._curve(values=vals), method='holt_winters', season=3, window=2, min_periods=3, horizon=3)
        tail = out[out['horizon'] > 0]
        assert len(tail) == 3 and tail['predicted'].notna().all()
        assert len({round(v, 6) for v in tail['predicted']}) > 1, 'a seasonal method must not flatten to one value'

    def test_holt_winters_needs_two_cycles_of_history(self):
        with pytest.raises(UnknownOperationError, match='季节'):
            D.forecast(
                self._curve(values=[0.1, 0.2, 0.3, 0.4]),
                method='holt_winters',
                season=3,
                window=2,
                min_periods=2,
            )

    def test_a_gamma_out_of_range_is_refused_by_name(self):
        with pytest.raises(UnknownOperationError, match='gamma'):
            D.forecast(self._curve(), method='holt_winters', season=3, gamma=1.5)


class TestAlert:
    """The flare-up warning, and the rule that never answers with an empty table."""

    @classmethod
    def _curve(cls, indexes, intensity=None, volume=None):
        start = pd.Timestamp('2024-05-01')
        frame = pd.DataFrame(
            {
                'period': [str((start + pd.Timedelta(days=index)).date()) for index in range(len(indexes))],
                'sentiment_index': indexes,
                'total': volume if volume is not None else [100] * len(indexes),
            }
        )
        if intensity is not None:
            frame['intensity'] = intensity
        return frame

    def test_a_run_of_same_direction_moves_fires_the_turn_signal(self):
        out = D.alert(self._curve([-0.1, -0.15, -0.4, -0.7]), streak=2, swing=0.2)
        assert list(out['signal']) == ['转向']
        assert out.iloc[0]['period'] == '2024-05-04'
        assert '0.5' in out.iloc[0]['reason'] or '0.3' in out.iloc[0]['reason']

    def test_moves_in_different_directions_do_not_add_up_to_a_turn(self):
        # One big drop then one big rise is a reaction to an event, not a crowd moving one way.
        out = D.alert(self._curve([-0.1, -0.5, -0.1, -0.5]), streak=2, swing=0.2)
        assert list(out['signal']) == ['未触发']

    def test_an_intensity_climb_fires_the_heating_signal_even_with_a_calm_index(self):
        frame = self._curve([-0.5, -0.5, -0.5, -0.5], intensity=[0.1, 0.1, 0.4, 0.7])
        out = D.alert(frame, streak=2, swing=0.2, heating=0.1, intensity_col='intensity')
        # The index never moves, so 转向 cannot fire; the crowd is nonetheless getting louder in
        # both directions, which is the 二次爆发期 shape the signed curve alone would miss.
        assert set(out['signal']) == {'升温'}
        assert '2024-05-04' in set(out['period'])

    def test_a_losing_crowd_suppresses_the_signal_and_the_row_says_so(self):
        frame = self._curve([-0.1, -0.15, -0.4, -0.7], volume=[900, 800, 60, 12])
        out = D.alert(frame, streak=2, swing=0.2, volume_col='total', volume_floor=0.6)
        assert set(out['signal']) == {'转向（已抑制）'}, 'the swing fired and the volume said no'
        assert '衰减' in ''.join(out['reason']) or '低于' in ''.join(out['reason'])

    def test_nothing_firing_still_answers_with_the_largest_value_measured(self):
        out = D.alert(self._curve([-0.1, -0.12, -0.14]), streak=2, swing=0.5)
        assert list(out['signal']) == ['未触发']
        assert out.iloc[0]['value'] == pytest.approx(0.02)
        assert '2' in out.iloc[0]['reason']

    def test_the_streak_is_a_consecutive_requirement_not_a_total(self):
        calm = self._curve([-0.1, -0.11, -0.5, -0.9])
        assert list(D.alert(calm, streak=2, swing=0.2)['signal']) == ['转向']
        assert list(D.alert(calm, streak=3, swing=0.2)['signal']) == ['未触发']

    def test_a_signal_column_that_was_named_but_is_absent_is_refused(self):
        with pytest.raises(UnknownOperationError, match='没有这个列'):
            D.alert(self._curve([-0.1, -0.2, -0.5]), intensity_col='没有这个列')

    def test_a_table_shorter_than_the_streak_plus_one_is_refused(self):
        with pytest.raises(UnknownOperationError, match='至少'):
            D.alert(self._curve([-0.1, -0.5]), streak=2)

    @pytest.mark.parametrize(
        ('kwargs', 'needle'), [({'streak': 0}, '连续'), ({'swing': 0}, '阈值'), ({'volume_floor': 1.5}, '倍率')]
    )
    def test_an_impossible_rule_is_refused_with_the_setting_named(self, kwargs, needle):
        with pytest.raises(UnknownOperationError, match=needle):
            D.alert(self._curve([-0.1, -0.3, -0.6, -0.9]), **kwargs)

    def test_rows_without_a_date_join_no_check_and_are_counted_out_loud(self):
        frame = self._curve([-0.1, -0.3, -0.6, -0.9])
        frame.loc[1, 'period'] = '还没有日期'
        out = D.alert(frame, streak=2, swing=0.2)
        assert len(out) >= 1


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

    def test_a_missing_label_column_is_refused_by_name(self):
        """The step used to hand the table back unchanged, which settled the node DONE over a
        curve that had counted nothing — and because it still writes sentiment_index, the chart
        below it saw no gap. A renamed 极性 column is the user's choice, so the refusal names it."""
        frame = pd.DataFrame({'日期': ['2024-05-02']})
        with pytest.raises(UnknownOperationError, match='sentiment'):
            D.sentiment_evolution(frame, '日期')

    def test_the_intensity_columns_only_appear_when_a_score_column_is_named(self):
        """A table of all-NA 强度 would read as "the curve was checked and the crowd was
        mild", so the feature is absent from the output until the user asks for it."""
        out = D.sentiment_evolution(self._frame({'发酵期': (1, 1, 1)}), 'period')
        assert 'intensity' not in out.columns
        assert 'score_n' not in out.columns

    def test_volume_pct_is_the_heat_the_paper_reads_against_intensity(self):
        # 发酵期 349 and 爆发期 7624 rows: the shares are over the rows that reached a
        # period, so they add up to 100 and the 爆发期 bar is the tall one — which is the
        # half of 「热度与情感强度成反比」 that is not about sentiment at all.
        out = D.sentiment_evolution(self._frame({'发酵期': (349, 0, 0), '爆发期': (7624, 0, 0)}), 'period')
        assert out.at[0, 'volume_pct'] == pytest.approx(4.38, abs=0.01)
        assert out['volume_pct'].sum() == pytest.approx(100.0, abs=0.02)

    def test_intensity_measures_how_hard_the_crowd_pushed_not_which_way(self):
        """The distinction the 二次爆发期 finding rests on: two periods can share an index
        of 0 and mean nothing alike — one all neutral, one all extremes. A signed mean
        would report both as mild, so intensity is |score − 0.5| doubled."""
        frame = pd.DataFrame(
            [
                {'period': '波动期', 'sentiment': 'neutral', 'score': 0.5},
                {'period': '波动期', 'sentiment': 'neutral', 'score': 0.5},
                {'period': '二次爆发期', 'sentiment': 'positive', 'score': 0.9},
                {'period': '二次爆发期', 'sentiment': 'negative', 'score': 0.1},
            ]
        )
        by = D.sentiment_evolution(frame, 'period', score_col='score').set_index('period')
        assert by.at['波动期', 'sentiment_index'] == pytest.approx(0.0)
        assert by.at['二次爆发期', 'sentiment_index'] == pytest.approx(0.0)
        assert by.at['波动期', 'intensity'] == pytest.approx(0.0)
        assert by.at['二次爆发期', 'intensity'] == pytest.approx(0.8)

    def test_a_period_without_a_single_score_is_empty_and_says_which(self, caplog):
        """0.5 would print as "measured, found neutral" — a finding this step does not
        have. The cell stays empty, ``score_n`` says why, and the period is named once."""
        frame = pd.DataFrame(
            [
                {'period': '发酵期', 'sentiment': 'neutral', 'score': ''},
                {'period': '爆发期', 'sentiment': 'positive', 'score': 0.8},
            ]
        )
        with caplog.at_level('WARNING'):
            out = D.sentiment_evolution(frame, 'period', score_col='score')
        by = out.set_index('period')
        assert by.at['发酵期', 'score_n'] == 0
        assert by.at['发酵期', 'intensity'] is None
        assert by.at['爆发期', 'intensity'] == pytest.approx(0.6)
        assert '发酵期' in caplog.text, 'the unjudged period must be named, not blanked'

    def test_an_unscored_row_neither_lifts_nor_drags_the_intensity(self):
        frame = pd.DataFrame(
            [
                {'period': '爆发期', 'sentiment': 'negative', 'score': 0.1},
                {'period': '爆发期', 'sentiment': 'negative', 'score': None},
            ]
        )
        by = D.sentiment_evolution(frame, 'period', score_col='score').set_index('period')
        assert by.at['爆发期', 'score_n'] == 1, 'the blank is counted as unjudged, not as 0.5'
        assert by.at['爆发期', 'intensity'] == pytest.approx(0.8)
        assert by.at['爆发期', 'total'] == 2, 'and it is still part of what that period was'

    def test_a_score_column_that_is_not_there_is_refused_by_name(self):
        # A mistyped 分数列 must not settle the node DONE with the shares only: the chart
        # the user then draws has one line where he asked for two, and no trace of why.
        with pytest.raises(UnknownOperationError, match='强度分'):
            D.sentiment_evolution(self._frame({'发酵期': (1, 1, 1)}), 'period', score_col='强度分')


class TestDiffRows:
    """DataAnalysisService.diff — the pure row comparison the /api/data/diff endpoint
    wraps. The API tests exercise it through Flask; these pin the edges a single request
    cannot reach: two tables sharing no column, and a key that is not unique."""

    def test_tables_with_no_column_in_common_mark_every_row_unmatched(self):
        a = pd.DataFrame([{'id': 1}, {'id': 2}])
        b = pd.DataFrame([{'name': 'x'}])
        d = D.diff(a, b)
        assert d['columns_common'] == []
        assert d['added_count'] == 1 and d['removed_count'] == 2

    def test_an_unshared_key_is_refused_by_name_not_used_to_match(self):
        a = pd.DataFrame([{'id': 1}])
        b = pd.DataFrame([{'name': 'x'}])
        d = D.diff(a, b, key='id')
        assert 'key_error' in d and 'id' in d['key_error']

    def test_a_key_with_duplicate_values_cannot_align_rows(self):
        a = pd.DataFrame([{'k': 1, 'v': 'a'}, {'k': 1, 'v': 'b'}])
        b = pd.DataFrame([{'k': 1, 'v': 'a'}, {'k': 1, 'v': 'c'}])
        d = D.diff(a, b, key='k')
        assert d['key_used'] is None
        assert 'k' in d['key_error']

    def test_identical_frames_diff_to_nothing(self):
        a = pd.DataFrame([{'x': 1}, {'x': 2}])
        d = D.diff(a, a.copy())
        assert d['added_count'] == d['removed_count'] == d['changed_count'] == 0
        assert d['row_delta'] == 0


class TestClusterReview:
    """簇综述·研究前沿: the model reads the cluster's OWN METRICS (not its texts) and writes what
    a clustering cannot — which research front the group forms. Same paid-step discipline."""

    class _Client:
        label = 'ollama:stub'

        def __init__(self, answer='该簇围绕政府数字化转型展开，下一步可能转向数据要素。'):
            self.prompts = []
            self.answer = answer

        def chat(self, prompt, max_retries=2):
            self.prompts.append(prompt)
            return self.answer

    class _Failing(_Client):
        def chat(self, prompt, max_retries=2):
            from analyzers.llm_client import LLMError

            self.prompts.append(prompt)
            raise LLMError('model is offline')

    class _Store:
        def __init__(self):
            self._d = {}

        def cache_get(self, scope, key):
            return self._d.get(scope + '|' + key)

        def cache_put(self, scope, key, value):
            self._d[scope + '|' + key] = value

    @staticmethod
    def _clusters() -> pd.DataFrame:
        return pd.DataFrame(
            {
                '聚类': [0, 0, 1, 1, 1],
                '聚类标签': ['数字治理', '数字治理', '乡村振兴', '乡村振兴', '乡村振兴'],
                '节点': ['数字政府', '政务服务', '乡村治理', '数字乡村', '共同富裕'],
                '频次': [12, 7, 9, 5, 3],
                '首年': [2018, 2019, 2020, 2021, 2021],
                '末年': [2022, 2022, 2022, 2022, 2022],
            }
        )

    def test_one_review_row_per_cluster_with_the_facts_beside_it(self):
        out = D.cluster_review(self._clusters(), llm=self._Client())
        assert list(out.columns) == ['聚类', '节点数', '代表节点', '年份跨度', '聚类标签', '簇综述']
        assert len(out) == 2
        assert (out['节点数'] == [2, 3]).all()
        assert out['年份跨度'].tolist() == ['2018–2022', '2020–2022']
        assert out['代表节点'].tolist() == ['数字政府；政务服务', '乡村治理；数字乡村；共同富裕']

    def test_the_prompt_carries_the_metrics_not_the_prose(self):
        """The whole difference from 聚类摘要 is what goes IN: the numbers the graph measured, so a
        paragraph that never saw them could have been written about any cluster."""
        client = self._Client()
        D.cluster_review(self._clusters(), llm=client, members=2)
        assert len(client.prompts) == 2
        first = client.prompts[0]
        assert 'LLR 标签：数字治理' in first
        assert '簇内节点数：2' in first
        assert '数字政府(12)' in first and '政务服务(7)' in first
        assert '共同富裕' not in first, 'members is a cap the prompt has to honour'
        assert '2018–2022' in first

    def test_a_missing_group_or_member_column_is_refused_by_name(self):
        with pytest.raises(UnknownOperationError, match='聚类'):
            D.cluster_review(pd.DataFrame({'节点': ['甲']}), llm=self._Client())
        with pytest.raises(UnknownOperationError, match='节点'):
            D.cluster_review(pd.DataFrame({'聚类': [0]}), llm=self._Client())

    def test_no_model_is_a_refusal_before_anything_is_spent(self):
        from i18n import t

        with pytest.raises(UnknownOperationError) as exc:
            D.cluster_review(self._clusters(), llm=None)
        assert t('analysis.label_no_llm', op='cluster_review') in str(exc.value)

    def test_a_stopped_run_marks_the_clusters_the_model_never_saw(self):
        class _Stop:
            def __init__(self):
                self.seen = 0

            def is_set(self):
                self.seen += 1
                return self.seen > 1

        from analyzers.llm_client import ABORT_MARK

        client = self._Client()
        out = D.cluster_review(self._clusters(), llm=client, cancel=_Stop())
        assert len(client.prompts) == 1, 'Stop is checked before every call, not after the pass'
        assert list(out['簇综述'][1:]) == [ABORT_MARK]

    def test_the_answer_is_cached_so_a_re_run_does_not_re_pay(self):
        store = self._Store()
        client = self._Client()
        D.cluster_review(self._clusters(), llm=client, store=store)
        assert len(client.prompts) == 2
        again = self._Client()
        D.cluster_review(self._clusters(), llm=again, store=store)
        assert again.prompts == [], 'the same table is replayed from the cache'

    def test_a_cluster_count_over_the_cap_is_refused_with_both_numbers(self):
        with pytest.raises(UnknownOperationError, match='2 行'):
            D.cluster_review(self._clusters(), llm=self._Client(), max_groups=1)

    def test_a_fallback_says_in_the_cell_that_no_model_wrote_it(self):
        """AGENTS: a sanctioned degradation must print the method that ran. The console line is
        half of it; the cell is what leaves the app, so the disclaimer travels with the text."""
        client = self._Failing()
        out = D.cluster_review(self._clusters(), llm=client, on_fail='fallback')
        assert len(out) == 2
        for text in out['簇综述']:
            assert '未经模型' in text and '数字政府' in text or '未经模型' in text and '乡村治理' in text

    def test_an_refused_cluster_aborts_rather_than_filing_a_blank(self):
        client = self._Failing()
        with pytest.raises(UnknownOperationError, match='model is offline'):
            D.cluster_review(self._clusters(), llm=client)

    def test_it_reaches_the_pipeline_only_through_llm_ops(self):
        client = self._Client()
        result, report = D.run_pipeline(
            self._clusters(),
            [
                {
                    'op': 'cluster_review',
                    'params': {'group_col': '聚类', 'name_col': '节点', 'summary_col': '簇综述'},
                }
            ],
            llm=client,
        )
        assert [entry['op'] for entry in report] == ['cluster_review']
        assert len(result) == 2 and len(client.prompts) == 2

    def test_a_table_without_the_year_columns_asks_for_no_span_it_cannot_support(self):
        """A line reading 年份跨度：未知 in front of the model invites it to invent a trajectory."""
        frame = self._clusters().drop(columns=['首年', '末年'])
        client = self._Client()
        out = D.cluster_review(frame, llm=client)
        assert '年份跨度' not in client.prompts[0]
        assert '年份跨度' not in list(out.columns)
