"""Design-time parameter checks for an analysis node (``services/analysis/step_checks.py``).

The node's badge and the run's own ``validate_step`` refusal must be the same rule: a box the
step cannot run without is flagged while the canvas is drawn, not after the crawl above it was
paid for. The matrix tests below walk ``STEP_PARAMS`` itself, so a new contract entry is
covered the day it is written instead of the day a user meets an empty column.
"""

import pytest
from frontend_catalogue import catalog_keys
from nodes.executors.analysis import param_errors
from nodes.schema import param_errors as canvas_param_errors

from services.analysis.contracts import NO_DEFAULT, STEP_PARAMS
from services.analysis.step_checks import (
    _OP_PARAM_LABELS,
    PARAM_LABELS,
    TWO_TABLE_KEYS,
    param_label,
    param_problems,
)

#: Every op that requires a named column, with the canonic key it requires. Read from the
#: table rather than typed twice; the parametrization below turns it into cases.
REQUIRED_ONE = [(op, key) for op, spec in STEP_PARAMS.items() for key in spec.get('one', ())]
REQUIRED_NONBLANK = [(op, key) for op, spec in STEP_PARAMS.items() for key in spec.get('nonblank', ())]
NO_FALLBACK_ENUMS = [
    (op, key)
    for op, spec in STEP_PARAMS.items()
    for key, (default, _allowed) in (spec.get('enums') or {}).items()
    if default is NO_DEFAULT
]


class TestRequiredParameters:
    @pytest.mark.parametrize('op, key', REQUIRED_ONE, ids=[f'{op}.{key}' for op, key in REQUIRED_ONE])
    def test_a_blank_required_column_is_a_problem(self, op, key):
        problems = param_problems(op, {key: ''})
        assert any(p['code'] == 'need_param' and p['param'] == key for p in problems), problems

    @pytest.mark.parametrize('op, key', REQUIRED_NONBLANK, ids=[f'{op}.{key}' for op, key in REQUIRED_NONBLANK])
    def test_a_blank_nonblank_parameter_is_a_problem(self, op, key):
        assert any(p['code'] == 'need_param' and p['param'] == key for p in param_problems(op, {key: '  '}))

    @pytest.mark.parametrize('op, key', NO_FALLBACK_ENUMS, ids=[f'{op}.{key}' for op, key in NO_FALLBACK_ENUMS])
    def test_a_select_with_no_fallback_is_refused_when_empty(self, op, key):
        assert any(p['code'] == 'need_param' and p['param'] == key for p in param_problems(op, {key: ''}))

    def test_a_named_column_satisfies_the_check(self):
        assert not param_problems('topic_model', {'column': '正文'})


class TestPanelDefaultsAreNotProblems:
    """A blank box that the step itself answers with a declared hand-off is a workflow, not a
    mistake — the badge must not paint a fresh form red."""

    def test_an_untouched_label_step_is_clean(self):
        # normalize_analysis_params resolves the blank boxes to feature_words / 主题概括.
        assert not param_errors({'type': 'analysis', 'params': {'operation': 'topic_label'}})

    def test_an_untouched_two_read_step_is_clean(self):
        assert not param_errors({'type': 'analysis', 'params': {'operation': 'forecast'}})

    def test_a_blank_column_list_means_every_column_for_the_optional_list_steps(self):
        assert not param_problems('drop_null', {'columns': []})
        assert not param_problems('select_columns', {'columns': []})

    def test_a_blank_stage_topic_count_keeps_the_steps_own_default(self):
        # ``topics`` is a count list, and the operation's signature owns its default; the badge
        # must not refuse the hand-off 分阶段 LDA's own form leaves blank.
        node = {'type': 'analysis', 'params': {'operation': 'topic_by_stage', 'column': '正文'}}
        assert not param_errors(node)
        assert not param_problems('topic_by_stage', {'column': '正文', 'stage_col': '阶段', 'topics': []})


class TestTwoTableKeys:
    def test_a_join_without_keys_is_reported(self):
        problems = param_problems('join_tables', {'how': 'left', 'left_on': '', 'right_on': '  '})
        assert [(p['code'], p['param']) for p in problems] == [
            ('need_param', 'left_on'),
            ('need_param', 'right_on'),
        ]

    def test_a_cross_join_needs_no_keys(self):
        assert not param_problems('join_tables', {'how': 'cross', 'left_on': '', 'right_on': ''})

    def test_an_anti_join_without_keys_is_reported(self):
        problems = param_problems('anti_join', {'left_on': '', 'right_on': ''})
        assert [(p['code'], p['param']) for p in problems] == [
            ('need_param', 'left_on'),
            ('need_param', 'right_on'),
        ]

    def test_the_declared_two_table_steps_are_the_registered_ones(self):
        assert set(TWO_TABLE_KEYS) == {'join_tables', 'anti_join'}


class TestStepOwnedShapeRequirements:
    """``bin_time`` refuses its own boxes with names ``STEP_PARAMS`` cannot hold."""

    def test_a_blank_boundary_list_is_reported(self):
        problems = param_problems('bin_time', {'column': '日期', 'edges': [], 'labels': []})
        assert [(p['code'], p['param']) for p in problems] == [('need_param', 'edges')]

    def test_the_name_list_must_describe_one_phase_per_interval(self):
        problems = param_problems('bin_time', {'column': '日期', 'edges': ['0', '60'], 'labels': []})
        assert problems == [
            {
                'code': 'labels_mismatch',
                'op': 'bin_time',
                'param': 'labels',
                'field': 'settings.phaseLabels',
                'edges': 2,
                'expected': 1,
                'given': 0,
            }
        ]

    def test_a_matching_pair_is_clean(self):
        assert not param_problems('bin_time', {'column': '日期', 'edges': ['0', '60'], 'labels': ['前期']})

    def test_the_panel_spellings_are_read_through_the_normalizer(self):
        node = {
            'type': 'analysis',
            'params': {
                'operation': 'bin_time',
                'column': '日期',
                'phase_edges': '0, 60, 120',
                'phase_labels': '前期, 后期',
                'phase_new_col': '阶段',
            },
        }
        assert not param_errors(node)
        node['params']['phase_labels'] = '前期'
        assert [p['code'] for p in param_errors(node)] == ['labels_mismatch']


class TestEnumsAndRenames:
    def test_a_value_outside_the_declared_list_names_the_allowed_ones(self):
        problems = param_problems('convert_type', {'column': 'a', 'dtype': 'integer'})
        assert problems == [
            {
                'code': 'bad_option',
                'op': 'convert_type',
                'param': 'dtype',
                'field': 'settings.dtype',
                'value': 'integer',
                'allowed': ['str', 'int', 'float', 'bool', 'datetime'],
            }
        ]

    def test_a_rename_with_no_new_name_is_reported(self):
        problems = param_problems('rename_columns', {'mapping': {'标题': ''}})
        assert problems[0]['code'] == 'rename_blank'
        assert problems[0]['cols'] == ['标题']

    def test_a_rename_with_no_source_is_reported(self):
        problems = param_problems('rename_columns', {'mapping': {}})
        assert [(p['code'], p['param']) for p in problems] == [('need_param', 'rename_from')]


class TestTheNodePlugin:
    def test_flat_panel_params_are_resolved_through_the_normalizer(self):
        # The panel stores ``column`` on this step; the check is about the canonical value.
        node = {'type': 'analysis', 'params': {'operation': 'dedupe_similar', 'column': ''}}
        assert param_errors(node) == [
            {'code': 'need_param', 'op': 'dedupe_similar', 'param': 'column', 'field': 'settings.column'}
        ]

    def test_a_steps_list_is_checked_step_by_step(self):
        node = {
            'type': 'analysis',
            'params': {'steps': [{'op': 'bin_column', 'column': ''}, {'op': 'topic_model', 'column': '正文'}]},
        }
        assert [p['op'] for p in param_errors(node)] == ['bin_column']

    def test_the_node_level_operation_is_read_like_the_executor_reads_it(self):
        node = {'type': 'analysis', 'operation': 'filter_rows', 'params': {}}
        assert [p['param'] for p in param_errors(node)] == ['column']

    def test_the_filter_comparison_does_not_swallow_the_step_name(self):
        """``filter_rows`` compares with a kwarg literally called ``op``; the step's own name is
        ``operation`` on the panel. A merge that let the comparison answer as the step turned
        the node's parameters unreadable (the bug this pair of keys now keeps apart)."""
        node = {'type': 'analysis', 'params': {'operation': 'filter_rows', 'column': '正文', 'op': 'eq'}}
        assert not param_errors(node)

    def test_a_dict_shaped_steps_value_is_named(self):
        node = {'type': 'analysis', 'params': {'steps': {'op': 'drop_null'}}}
        assert [p['code'] for p in param_errors(node)] == ['steps_shape']

    def test_only_analysis_nodes_answer(self):
        assert canvas_param_errors(
            {
                'a': {'id': 'a', 'type': 'analysis', 'params': {'operation': 'dedupe_similar'}},
                's': {'id': 's', 'type': 'source', 'params': {}},
            }
        ) == {
            'a': [{'code': 'need_param', 'op': 'dedupe_similar', 'param': 'column', 'field': 'settings.column'}],
            's': [],
        }


class TestTheDiagnosticsPayload:
    def test_the_canvas_walker_answers_per_node(self):
        assert canvas_param_errors(
            {
                'a': {'id': 'a', 'type': 'analysis', 'params': {'operation': 'dedupe_similar'}},
                'u': {'id': 'u', 'type': 'upload', 'params': {}},
            }
        ) == {
            'a': [{'code': 'need_param', 'op': 'dedupe_similar', 'param': 'column', 'field': 'settings.column'}],
            'u': [],
        }


class TestTheWordingBelongsToTheBrowser:
    def test_every_badge_label_is_a_key_both_browser_languages_declare(self):
        catalogs = catalog_keys()
        keys = set(PARAM_LABELS.values()) | set(_OP_PARAM_LABELS.values())
        missing = [
            f'{key} missing from {lang}' for key in sorted(keys) for lang, table in catalogs.items() if key not in table
        ]
        assert not missing, '\n'.join(missing)

    def test_the_op_specific_table_wins_over_the_generic_one(self):
        assert param_label('topic_timeline', 'words_col') == 'settings.timelineWordsColumn'
        assert param_label('topic_label', 'words_col') == 'settings.labelWordsColumn'
        assert param_label('dedupe_similar', 'column') == 'settings.column'
