"""The edit-time output-column model (``nodes/schema.py``) and per-node validate.

These are the truths behind the canvas badges: what a node emits, what it reads, and
which node a validation message belongs to. The cardinal property under test is that an
unknown producer (a crawl) is never turned into a false "missing column" downstream —
the model returns None there, and None propagates. A node type's column rule lives with
the node type (its ``emit_columns`` / ``read_columns`` in ``nodes/executors/<type>.py``);
``nodes/schema.py`` only walks the graph and asks, so the same test also proves the
dispatch kept every answer.
"""

from pathlib import Path

from nodes.schema import compute_columns, referenced_columns

from engine.workflow import WorkflowEngine


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

    def test_a_summarising_step_declares_only_the_columns_it_actually_writes(self):
        """聚类摘要 REDUCES the table to one row per cluster, so promising the upstream columns
        was a lie in the other direction: a chart fed by it was told 节点/频次 would be there and
        met them only at run time — as an absence."""
        nodes = self._analysis(
            {
                'operation': 'cluster_label',
                'cluster_group_col': '簇',
                'cluster_text_col': '正文',
                'cluster_summary_col': '概述',
            }
        )
        assert compute_columns(nodes, [])['a'] == ['簇', 'n_docs', '概述']

    def test_a_review_step_says_it_cannot_tell_rather_than_guessing_its_columns(self):
        """簇综述's row shape depends on which fact columns the upstream table has (年份跨度 only
        when 首年/末年 exist, 聚类标签 only when the node emitted one), so the honest answer is
        unknown — the panel then refuses to claim a lineage it has not measured."""
        nodes = self._analysis({'operation': 'cluster_review', 'review_summary_col': '前沿'})
        assert compute_columns(nodes, [])['a'] is None

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


class TestTheTablesLiveWithTheirOwners:
    """Phase 3: the column contract belongs to the code that produces it.

    ``nodes/schema.py`` aggregates; a table that grows a new op (or an executor that grows one
    without a contract) must be visible here rather than as a silently-unmodelled column set.
    """

    def test_every_process_contract_op_is_an_operation_the_executor_serves(self):
        from services.analysis.process import (
            OUTPUT_ADD_COLUMNS,
            OUTPUT_REPLACE_COLUMNS,
            PROCESS_OPS,
            READ_PARAMS,
        )

        served = set(PROCESS_OPS)
        assert set(OUTPUT_ADD_COLUMNS) <= served
        assert set(OUTPUT_REPLACE_COLUMNS) <= served
        assert set(READ_PARAMS) <= served
        # The three data-dependent ops are intentionally unmodelled (unknown, never a guess).
        assert served - set(OUTPUT_ADD_COLUMNS) - set(OUTPUT_REPLACE_COLUMNS) == {
            'keyword',
            'cluster',
            'ner',
            'bot',
        }

    def test_every_analysis_contract_op_is_a_step_the_service_serves(self):
        from services.analysis.params import (
            STEP_ADD_MAYBE,
            STEP_ADD_ONE,
            STEP_DYNAMIC_REPLACE,
            STEP_PASSTHROUGH,
            STEP_REPLACE,
            STEP_UNKNOWN,
        )
        from services.analysis.pipeline import DataAnalysisService

        served = set(DataAnalysisService._operations())
        declared = (
            set(STEP_REPLACE)
            | set(STEP_ADD_ONE)
            | set(STEP_ADD_MAYBE)
            | set(STEP_PASSTHROUGH)
            | set(STEP_UNKNOWN)
            | set(STEP_DYNAMIC_REPLACE)
            | {'select_columns'}
        )
        assert declared <= served, f'contract names a step the service does not serve: {sorted(declared - served)}'
        assert served - declared == set(), f'step with no lineage entry: {sorted(served - declared)}'

    def test_the_tokenize_modes_are_exactly_the_shapes_it_can_write(self):
        from nodes.executors.tokenize import OUTPUT_COLUMNS, READ_PARAMS

        assert set(OUTPUT_COLUMNS) == {'word_freq', 'words_only', 'csv_line'}
        assert READ_PARAMS == ('text_column',)

    def test_the_old_service_module_is_gone(self):
        """A second home would silently win for whichever importer was updated first."""
        import importlib.util

        assert importlib.util.find_spec('services.node_schema') is None


#: Node types whose table no static view can see — declared, not defaulted.
UNMODELLED_OUTPUTS = {'comment', 'compile', 'output', 'resume', 'source', 'visualize'}

#: Node types that read named columns from their input.
COLUMN_READERS = {'analysis', 'biblio', 'fuse', 'process', 'tokenize', 'visualize'}


class TestTheContractIsDeclaredPerPlugin:
    """``nodes/schema.py`` asks each plugin; it no longer holds the rules itself.

    A type that gains a column rule without a hook (or the reverse) used to be invisible: the
    ``elif`` chain simply did not mention it and the node answered "unknown" forever, which reads
    as a clean run rather than as a missing model. Enumerating both sets makes the omission a
    test failure instead.
    """

    @staticmethod
    def _plugins() -> dict:
        import importlib

        from nodes import registry

        registry.load_builtin_executors()
        return {
            node_type: importlib.import_module(registry.executor_for(node_type).__module__)
            for node_type in sorted(registry.registered_types())
        }

    def test_every_type_either_declares_its_output_or_is_listed_as_unmodelled(self):
        plugins = self._plugins()
        declared = {node_type for node_type, module in plugins.items() if hasattr(module, 'emit_columns')}
        assert declared | UNMODELLED_OUTPUTS == set(plugins), (
            f'a node type has no output contract at all: {sorted(set(plugins) - declared - UNMODELLED_OUTPUTS)}'
        )
        assert not declared & UNMODELLED_OUTPUTS, (
            f'a declared plugin is still listed as unmodelled: {sorted(declared & UNMODELLED_OUTPUTS)}'
        )

    def test_a_reader_is_a_plugin_that_declares_one(self):
        plugins = self._plugins()
        readers = {node_type for node_type, module in plugins.items() if hasattr(module, 'read_columns')}
        assert readers == COLUMN_READERS, f'read_columns lives on: {sorted(readers)}'

    def test_no_plugin_imports_the_lineage_view(self):
        """The view imports the plugins (lazily, at use time); a plugin importing it back would
        make the lineage question unanswerable before ``app`` has finished loading."""
        import ast

        offenders = []
        for module in self._plugins().values():
            path = Path(module.__file__)
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'), str(path))):
                if isinstance(node, ast.ImportFrom) and (node.module or '').startswith('nodes.schema'):
                    offenders.append(f'{path.name}:{node.lineno}')
                if isinstance(node, ast.Import) and any(a.name == 'nodes.schema' for a in node.names):
                    offenders.append(f'{path.name}:{node.lineno}')
        assert offenders == [], f'plugins reaching back into the lineage view: {offenders}'

    def test_a_type_the_registry_does_not_serve_is_unknown_not_an_error(self):
        """Diagnostics runs on canvases written by an older build: an unregistered type must be
        modelled as "nothing is known", never raise while a panel is being drawn."""
        assert compute_columns({'x': {'id': 'x', 'type': 'no_such_node'}}, []) == {'x': None}
        assert referenced_columns({'x': {'id': 'x', 'type': 'no_such_node', 'params': {}}}) == {'x': []}
