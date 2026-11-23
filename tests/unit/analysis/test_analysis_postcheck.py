"""The analysis node's after-run data check: a pipeline that emptied a non-empty table.

The preflight judges a sample before the run; this hook runs on the rows the node really produced.
Zero rows from a non-empty input is the silent-empty failure — the node settles DONE, the console
says completed, and everything downstream skips as “upstream empty”. A pipeline that filters or
joins is exempt: zero rows there is the answer the user asked for.
"""

import pytest
from nodes.executors.analysis import postcheck

pytestmark = pytest.mark.unit

_INPUT = [{'正文': '甲'}, {'正文': '乙'}, {'正文': '丙'}]


def _node(**params):
    return {'id': 'a', 'type': 'analysis', 'params': params}


class TestAZeroRowPipeline:
    def test_a_non_emptier_chain_that_outputs_nothing_is_named(self):
        found = postcheck(_node(operation='topic_map', column='正文'), [], _INPUT)
        assert [problem['code'] for problem in found] == ['engine.empty_output']
        assert found[0]['severity'] == 'warning'
        assert found[0]['context'] == {'rows': 3, 'op': 'topic_map'}

    def test_the_flat_operation_shape_is_read(self):
        found = postcheck(_node(operation='drop_null', columns='正文'), [], _INPUT)
        assert found[0]['context']['op'] == 'drop_null'

    def test_the_last_step_of_a_chain_names_itself(self):
        node = _node(
            steps=[
                {'op': 'extract_time', 'column': '发布时间', 'new_col': '日期'},
                {'op': 'bin_time', 'column': '日期', 'phase_edges': '0,60', 'phase_labels': '前期,后期'},
            ]
        )
        found = postcheck(node, [], _INPUT)
        assert found[0]['context']['op'] == 'bin_time'


class TestWhenZeroRowsIsTheAnswer:
    def test_a_filter_that_matches_nothing_is_not_flagged(self):
        assert postcheck(_node(steps=[{'op': 'filter_rows', 'column': '正文'}]), [], _INPUT) == []

    def test_a_join_that_matches_nothing_is_not_flagged(self):
        assert postcheck(_node(steps=[{'op': 'join_tables', 'left_on': 'a', 'right_on': 'b'}]), [], _INPUT) == []

    def test_an_anti_join_that_removes_everything_is_not_flagged(self):
        assert postcheck(_node(steps=[{'op': 'anti_join', 'left_on': 'a', 'right_on': 'b'}]), [], _INPUT) == []


class TestWhatIsNotAZeroRowRun:
    def test_a_non_empty_output_is_clean(self):
        assert postcheck(_node(operation='topic_map'), [{'topic': '甲'}], _INPUT) == []

    def test_an_empty_input_is_already_skipped_by_the_run_loop(self):
        assert postcheck(_node(operation='topic_map'), [], []) == []
