"""The edit-time output-column model (services/node_schema) and per-node validate.

These are the truths behind the canvas badges: what a node emits, what it reads, and
which node a validation message belongs to. The cardinal property under test is that an
unknown producer (a crawl) is never turned into a false "missing column" downstream —
the model returns None there, and None propagates.
"""

from engine.workflow import WorkflowEngine
from services.node_schema import compute_columns, referenced_columns


def _wf(nodes, connections):
    return {'nodes': nodes, 'connections': connections, 'settings': {}}


class TestComputeColumns:
    def test_a_crawl_source_is_unknown(self):
        nodes = {'s': {'id': 's', 'type': 'source', 'params': {'platform': 'zhihu'}}}
        assert compute_columns(nodes, []) == {'s': None}

    def test_topic_map_replaces_with_its_fixed_chart_contract(self):
        # Even fed by an unknown source, topic_map's OWN output is a known fixed set —
        # that is exactly the column contract a downstream chart is checked against.
        nodes = {
            's': {'id': 's', 'type': 'source', 'params': {'platform': 'zhihu'}},
            'a': {'id': 'a', 'type': 'analysis', 'params': {'steps': [{'op': 'topic_map', 'column': 'cleaned_text'}]}},
        }
        cols = compute_columns(nodes, [{'from': 's', 'to': 'a'}])
        assert cols['a'] == ['topic', 'pc1', 'pc2', 'prevalence_pct', 'doc_n', 'feature_words']

    def test_a_process_add_on_an_unknown_upstream_stays_unknown(self):
        nodes = {
            's': {'id': 's', 'type': 'source', 'params': {'platform': 'zhihu'}},
            'p': {'id': 'p', 'type': 'process', 'params': {'operation': 'clean', 'text_column': '正文'}},
        }
        cols = compute_columns(nodes, [{'from': 's', 'to': 'p'}])
        assert cols['p'] is None, 'clean passes through, and its input is unknown'

    def test_a_switch_dependent_op_is_unknown(self):
        # keyword/ner/cluster/bot shapes depend on a switch or the data; never guessed.
        nodes = {'k': {'id': 'k', 'type': 'process', 'params': {'operation': 'keyword', 'text_column': '正文'}}}
        assert compute_columns(nodes, [])['k'] is None

    def test_tokenize_replaces_by_output_mode(self):
        nodes = {'t': {'id': 't', 'type': 'tokenize', 'params': {'text_column': '正文', 'output_mode': 'word_freq'}}}
        assert compute_columns(nodes, [])['t'] == ['word', 'frequency']

    def test_bin_time_declares_the_order_column_it_actually_writes(self):
        """阶段序号列 is a real emitted column whenever the box names one — and 各阶段's
        lifecycle tables/charts READ it. Left out of the model, the lineage panel hid the column
        this canvas produced, so a downstream step that asked for it looked like an input nobody
        made."""
        nodes = {
            'a': {
                'id': 'a',
                'type': 'analysis',
                'params': {
                    'steps': [
                        {'op': 'bin_time', 'column': '时间', 'phase_new_col': '阶段', 'phase_order_col': '阶段序号'}
                    ]
                },
            }
        }
        assert compute_columns(nodes, [])['a'] == ['阶段', '阶段序号']

    def test_bin_time_without_an_order_box_keeps_its_single_column(self):
        """A blank order box really does mean "no order column" — the model must not invent one,
        or the panel would promise a column the run never writes."""
        nodes = {
            'a': {
                'id': 'a',
                'type': 'analysis',
                'params': {'steps': [{'op': 'bin_time', 'column': '时间', 'phase_new_col': '阶段'}]},
            }
        }
        assert compute_columns(nodes, [])['a'] == ['阶段']


class TestReferencedColumns:
    def test_a_chart_reads_its_named_fields(self):
        nodes = {
            'v': {'id': 'v', 'type': 'visualize', 'params': {'chart_type': 'bar', 'x_field': 'stage', 'y_field': 'n'}}
        }
        assert sorted(referenced_columns(nodes)['v']) == ['n', 'stage']

    def test_an_analysis_step_reads_its_named_column(self):
        nodes = {
            'a': {'id': 'a', 'type': 'analysis', 'params': {'steps': [{'op': 'topic_map', 'column': 'cleaned_text'}]}}
        }
        assert referenced_columns(nodes)['a'] == ['cleaned_text']


class TestValidateDetailed:
    def _two_problem_canvas(self):
        return _wf(
            [
                {'id': 'u', 'type': 'upload', 'title': 'U', 'params': {}},
                {'id': 'v', 'type': 'visualize', 'title': 'V', 'params': {'chart_type': 'bar'}},
            ],
            [],
        )

    def test_messages_are_the_same_list_in_the_same_order(self):
        engine = WorkflowEngine(self._two_problem_canvas())
        flat = engine.validate()
        detailed = [e['message'] for e in engine.validate_detailed()]
        assert detailed == flat

    def test_each_problem_is_attributed_to_its_node(self):
        engine = WorkflowEngine(self._two_problem_canvas())
        by_id = {e['id'] for e in engine.validate_detailed() if e['id']}
        assert {'u', 'v'} <= by_id

    def test_a_canvas_wide_problem_has_no_node(self):
        engine = WorkflowEngine(_wf([], []))
        entries = engine.validate_detailed()
        assert entries[0]['id'] is None
        assert entries[0]['code'] == 'engine.empty_canvas'
