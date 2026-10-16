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


class TestTheShapeTheCanvasActuallyStores:
    """Every case here is a verbatim flat node from ``data/workflows/*.json``.

    A canvas writes ``operation`` plus every panel field BESIDE it — no saved file holds a
    ``steps`` list — and the model used to throw those siblings away, computing the DEFAULT
    column name for a node the user had renamed. A renamed 划分阶段 then hid 生命周期 and
    阶段序号 from the lineage, so a downstream step reading them looked like an input nobody
    made, while ``missingColumnProblems`` never fired for any analysis node at all.
    """

    @staticmethod
    def _analysis(params):
        return {'a': {'id': 'a', 'type': 'analysis', 'params': params}}

    def test_a_renamed_phase_box_shows_the_column_it_writes(self):
        nodes = self._analysis(
            {
                'operation': 'bin_time',
                'column': '日期',
                'phase_edges': '0,60',
                'phase_labels': '前期,后期',
                'phase_new_col': '生命周期',
                'phase_order_col': '阶段序号',
                'enabled': True,
            }
        )
        assert compute_columns(nodes, [])['a'] == ['生命周期', '阶段序号'], (
            'the default 阶段 is not what this node writes'
        )

    def test_a_renamed_label_box_shows_the_summary_column_it_writes(self):
        nodes = self._analysis(
            {
                'operation': 'topic_label',
                'label_max_topics': '30',
                'label_on_fail': 'abort',
                'label_samples_col': 'sample_texts',
                'label_summary_col': '主题概括A',
                'label_words_col': 'feature_words',
                'model': 'qwen3.5:4b',
                'enabled': True,
            }
        )
        assert compute_columns(nodes, [])['a'] == ['主题概括A']

    def test_an_empty_bin_name_box_still_writes_the_suffix_the_executor_writes(self):
        """Blank is not "no column": the step answers ``f"{column}_bin"``, so the lineage
        has to name it or the panel hides a column the run really produces."""
        nodes = self._analysis({'operation': 'bin_column', 'column': '评论数', 'bins': '5'})
        assert compute_columns(nodes, [])['a'] == ['评论数_bin']

    def test_compare_platform_names_the_group_column_the_user_typed(self):
        """The fixed ('platform','n') tuple promised a column a renamed 平台 never wrote,
        and hid the real aggregate — both directions of the same lie."""
        renamed = self._analysis(
            {
                'operation': 'compare_platform',
                'compare_platform_col': '平台',
                'compare_value_col': '情感分',
                'compare_agg': 'mean',
            }
        )
        assert compute_columns(renamed, [])['a'] == ['平台', 'n', '情感分_mean']
        counts_only = self._analysis({'operation': 'compare_platform', 'compare_platform_col': '平台'})
        assert compute_columns(counts_only, [])['a'] == ['平台', 'n'], 'no value box means no aggregate column'

    def test_sentiment_evolution_reports_the_index_name_and_only_the_score_columns_given(self):
        without_score = self._analysis(
            {
                'operation': 'sentiment_evolution',
                'column': '日期',
                'index_new_col': '期',
                'label_col': '情感',
                'label_negative': '消极',
                'label_neutral': '中性',
                'label_positive': '积极',
                'enabled': True,
            }
        )
        cols = compute_columns(without_score, [])['a']
        # The producer renames its period column to 'period' no matter what the box held, so the
        # lineage must say 'period' — naming it after the input 日期 flagged a provable miss on a
        # canvas that runs (invariant: a step's output names are the downstream chart's input names).
        assert cols[0] == 'period' and cols[1] == '期', cols
        assert 'intensity' not in cols and 'score_n' not in cols, 'no 分值 column, so no score-derived column'
        with_score = self._analysis(
            {
                'operation': 'sentiment_evolution',
                'column': '日期',
                'label_col': '情感',
                'score_col': '分值',
                'enabled': True,
            }
        )
        scored = compute_columns(with_score, [])['a']
        assert 'sentiment_index' in scored and 'intensity' in scored and 'score_n' in scored, scored

    def test_a_flat_analysis_node_reads_the_column_it_names(self):
        """``referenced_columns`` used to answer ``[]`` for every flat node, which is what
        silenced the edit-time missing-column flag for the whole analysis family."""
        nodes = self._analysis({'operation': 'bin_time', 'column': '日期', 'phase_new_col': '阶段'})
        assert referenced_columns(nodes)['a'] == ['日期']


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
