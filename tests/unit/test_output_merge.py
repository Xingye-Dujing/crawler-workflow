"""The save node is the canvas's merge point.

Several batches of one crawl are the normal reason to wire two nodes into a save node, and
this node used to take only the FIRST of them and mention the rest in one console line — so
a canvas that showed three tables exported one of them and reported success. That is the
silent half of the picture this project refuses everywhere else.

What these tests pin is the pair of refusals that make the merge trustworthy, not the
concatenation itself: a parent carrying no rows at all, and parents whose columns differ.
The second one matters most — ``pd.concat`` answers a column mismatch with an outer join,
which fabricates empty cells and produces a file that looks complete.
"""

import pandas as pd
import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def exec_():
    """The application module, imported inside the test and never at module scope."""
    import app

    return app


A = [{'正文': 'a1', '点赞数': 1}, {'正文': 'a2', '点赞数': 2}]
B = [{'正文': 'b1', '点赞数': 3}]


def _save_node():
    return {
        'id': 'node-9',
        'type': 'output',
        'title': '输出',
        'operation': 'save',
        'params': {'operation': 'save', 'format': 'csv', 'filename': 'merged.csv'},
    }


class TestMergingUpstreamTables:
    def test_one_upstream_hands_over_exactly_what_it_produced(self, exec_):
        node = _save_node()
        rows = exec_._execute_output_node(node, list(A), upstream=[('node-1', list(A))])
        assert rows == A

    def test_two_upstreams_become_one_table_in_connection_order(self, exec_):
        node = _save_node()
        rows = exec_._execute_output_node(node, list(A), upstream=[('node-1', list(A)), ('node-2', list(B))])
        assert [r['正文'] for r in rows] == ['a1', 'a2', 'b1'], 'the order the wires were drawn is the order it reads'
        assert len(rows) == 3

    def test_the_merged_table_is_what_travels_onward(self, exec_):
        """The reason to merge HERE rather than in a node of its own: a chain of analyses
        hangs off this node, so it has to hand on everything it wrote to the file."""
        node = _save_node()
        rows = exec_._execute_output_node(node, list(A), upstream=[('node-1', list(A)), ('node-2', list(B))])
        assert len(rows) == 3, 'a downstream node must see both tables'

    def test_the_exported_file_holds_the_merged_rows(self, exec_, tmp_path, monkeypatch):
        monkeypatch.setattr(exec_.Config, 'EXPORT_DIR', str(tmp_path))
        node = _save_node()
        exec_._execute_output_node(node, list(A), upstream=[('node-1', list(A)), ('node-2', list(B))])
        written = pd.read_csv(tmp_path / 'merged.csv')
        assert len(written) == 3
        assert list(written.columns) == ['正文', '点赞数']

    def test_an_empty_upstream_is_not_a_refusal(self, exec_):
        """An empty batch is a real answer — a crawl window with no posts — so the row
        counts of the others still add up and nothing is invented to fill the gap."""
        node = _save_node()
        rows = exec_._execute_output_node(node, list(A), upstream=[('node-1', list(A)), ('node-2', [])])
        assert len(rows) == 2

    def test_a_column_mismatch_is_refused_and_the_columns_are_named(self, exec_):
        """``pd.concat`` would outer-join these: 点赞数 would come back as NaN for every row
        of the second table, and the file would look like a complete table with holes."""
        node = _save_node()
        other = [{'正文': 'b1', '转发数': 9}]
        with pytest.raises(ValueError) as err:
            exec_._execute_output_node(node, list(A), upstream=[('node-1', list(A)), ('node-2', other)])
        message = str(err.value)
        assert 'node-2' in message, message
        assert '转发数' in message and '点赞数' in message, 'the refusal must name both sides'

    def test_a_reordered_column_list_is_not_a_mismatch(self, exec_):
        """The set is what has to agree: the same columns in another order is still the same
        table, and pandas aligns them by name."""
        node = _save_node()
        other = [{'点赞数': 3, '正文': 'b1'}]
        rows = exec_._execute_output_node(node, list(A), upstream=[('node-1', list(A)), ('node-2', other)])
        assert [r['正文'] for r in rows] == ['a1', 'a2', 'b1']

    def test_a_parent_that_carries_no_table_is_refused_by_name(self, exec_):
        """A visualize node answers a chart spec and an output node may answer a refusal;
        neither is rows. Skipping such a parent silently would export the rest as if the
        canvas had only those."""
        node = _save_node()
        with pytest.raises(ValueError) as err:
            exec_._execute_output_node(
                node,
                list(A),
                upstream=[('node-1', list(A)), ('node-2', {'engine': 'echarts', 'option': {}})],
            )
        message = str(err.value)
        assert 'node-2' in message, message

    def test_a_direct_caller_with_no_upstream_list_still_works(self, exec_):
        # ``/api/analysis``-style callers and older tests call this with rows and nothing
        # else; there is no wire to merge, so the rows in hand are the whole answer.
        node = _save_node()
        assert exec_._execute_output_node(node, list(A)) == A


class TestMergeIsGraphCheckedToo:
    """What can be decided without data is decided at validation time.

    A save node with no wire at all, and one fed only by nodes that carry no rows, both
    passed ``validate()`` and then wrote an empty file over a green node.
    """

    @staticmethod
    def _errors(exec_, nodes, connections):
        from engine.workflow import WorkflowEngine

        return WorkflowEngine({'nodes': nodes, 'connections': connections}).validate()

    def test_an_output_node_with_no_upstream_is_refused(self, exec_):
        nodes = [_save_node()]
        errors = self._errors(exec_, nodes, [])
        assert errors and any('node-9' in e for e in errors), errors

    def test_an_output_node_fed_only_by_a_name_node_is_refused(self, exec_):
        nodes = [
            {'id': 'node-1', 'type': 'name', 'title': '命名', 'params': {'workflow_name': 'W'}},
            _save_node(),
        ]
        errors = self._errors(exec_, nodes, [{'from': 'node-1', 'to': 'node-9'}])
        assert errors and any('node-9' in e for e in errors), errors

    def test_an_output_node_fed_only_by_a_chart_is_refused(self, exec_):
        nodes = [
            {'id': 'node-1', 'type': 'resume', 'title': '续跑', 'params': {}},
            {'id': 'node-2', 'type': 'visualize', 'title': '图', 'params': {'chart_type': 'line', 'x_field': 'a'}},
            _save_node(),
        ]
        errors = self._errors(exec_, nodes, [{'from': 'node-1', 'to': 'node-2'}, {'from': 'node-2', 'to': 'node-9'}])
        assert errors and any('node-9' in e for e in errors), errors

    def test_an_output_node_fed_by_rows_and_a_chart_is_left_to_the_run(self, exec_):
        """Statically this canvas is fine — there IS a table — and the chart wire is refused
        at run time with the parent named. Deciding it here would mean guessing what the
        chart node will answer before it has answered."""
        nodes = [
            {'id': 'node-1', 'type': 'resume', 'title': '续跑', 'params': {}},
            {'id': 'node-2', 'type': 'visualize', 'title': '图', 'params': {'chart_type': 'line', 'x_field': 'a'}},
            _save_node(),
        ]
        errors = self._errors(
            exec_,
            nodes,
            [
                {'from': 'node-1', 'to': 'node-9'},
                {'from': 'node-1', 'to': 'node-2'},
                {'from': 'node-2', 'to': 'node-9'},
            ],
        )
        assert not errors, errors
