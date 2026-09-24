"""Tests for the DAG parser/scheduler in engine/workflow.py.

The engine is the piece that turns the canvas into an execution order, so the
contracts pinned here are the ones the executor silently relies on:

- a cycle is *always* fatal for both orderings, with one shared message, and
  that message is translated and names the nodes in the loop,
- an isolated node still gets scheduled (it is a workflow of its own),
- several disconnected sub-workflows are split, ordered by creation index,
- ``validate()`` returns ready-to-print translated text, never a key, and says
  nothing about node types the engine does not own (``resume`` and friends).
"""

import pytest

from engine.workflow import WorkflowEngine, node_label
from i18n import get_lang, set_lang, t

pytestmark = pytest.mark.unit


@pytest.fixture
def en():
    """Pin English message rendering, then hand the thread's language back."""
    previous = get_lang()
    set_lang('en')
    try:
        yield
    finally:
        set_lang(previous)


def _node(nid, ntype='source', **extra):
    node = {'id': nid, 'type': ntype, 'params': {'keyword': '三亚'}}
    node.update(extra)
    return node


def _wf(nodes, connections, settings=None):
    workflow = {'nodes': nodes, 'connections': connections}
    if settings is not None:
        workflow['settings'] = settings
    return workflow


def _chain():
    nodes = [_node('node-1'), _node('node-2', 'analysis'), _node('node-3', 'output')]
    conns = [{'from': 'node-1', 'to': 'node-2'}, {'from': 'node-2', 'to': 'node-3'}]
    return _wf(nodes, conns)


# ─── construction ──────────────────────────────────────────────────────


class TestConstruction:
    def test_nodes_are_indexed_by_id(self):
        engine = WorkflowEngine(_chain())
        assert list(engine.nodes) == ['node-1', 'node-2', 'node-3']
        assert engine.nodes['node-2']['type'] == 'analysis'

    def test_missing_keys_default_to_empty_containers(self):
        engine = WorkflowEngine({})
        assert engine.nodes == {}
        assert engine.connections == []
        assert engine.settings == {}
        assert engine.topological_sort() == []
        assert engine.group_by_level() == []
        assert engine.find_workflows() == []
        # Parsing an absent definition is not an error, but RUNNING one is: a canvas
        # with no nodes has nothing to complain about field by field, and used to
        # "complete" at 0/0.
        assert engine.validate() == [t('engine.empty_canvas')]

    def test_executor_is_kept_for_subworkflows(self):
        sentinel = object()
        engine = WorkflowEngine(_chain(), executor=sentinel)
        assert engine.executor is sentinel


# ─── ordering ──────────────────────────────────────────────────────────


class TestOrdering:
    def test_topological_sort_respects_every_edge(self):
        order = WorkflowEngine(_chain()).topological_sort()
        assert [order.index(n) for n in ('node-1', 'node-2', 'node-3')] == [0, 1, 2]

    def test_topological_sort_includes_isolated_nodes(self):
        wf = _wf([_node('node-1'), _node('node-2')], [])
        assert sorted(WorkflowEngine(wf).topological_sort()) == ['node-1', 'node-2']

    def test_topological_sort_rejects_a_cycle(self, en):
        conns = [{'from': 'node-1', 'to': 'node-2'}, {'from': 'node-2', 'to': 'node-1'}]
        with pytest.raises(ValueError, match='cycle') as err:
            WorkflowEngine(_wf([_node('node-1'), _node('node-2')], conns)).topological_sort()
        # The message has to name the nodes in the loop: the canvas shows the
        # cycle on screen, and an English exclamation pointed at nothing.
        assert 'node-1' in str(err.value) and 'node-2' in str(err.value)

    def test_group_by_level_bundles_independent_nodes(self):
        nodes = [_node('node-1'), _node('node-2', 'analysis'), _node('node-3', 'analysis')]
        conns = [{'from': 'node-1', 'to': 'node-2'}, {'from': 'node-1', 'to': 'node-3'}]
        levels = WorkflowEngine(_wf(nodes, conns)).group_by_level()
        assert [set(level) for level in levels] == [{'node-1'}, {'node-2', 'node-3'}]

    def test_group_by_level_matches_topological_sort_partition(self):
        levels = WorkflowEngine(_chain()).group_by_level()
        assert [n for level in levels for n in level] == WorkflowEngine(_chain()).topological_sort()

    def test_group_by_level_rejects_a_cycle(self, en):
        conns = [
            {'from': 'node-1', 'to': 'node-2'},
            {'from': 'node-2', 'to': 'node-3'},
            {'from': 'node-3', 'to': 'node-1'},
        ]
        nodes = [_node('node-1'), _node('node-2', 'analysis'), _node('node-3', 'output')]
        with pytest.raises(ValueError, match='cycle') as err:
            WorkflowEngine(_wf(nodes, conns)).group_by_level()
        assert 'node-1' in str(err.value) and 'node-3' in str(err.value)


# ─── sub-workflows ─────────────────────────────────────────────────────


class TestSubworkflows:
    def _two_workflows(self):
        nodes = [
            _node('node-1'),
            _node('node-2', 'output', operation='save'),
            _node('node-7'),
            _node('node-8', 'analysis'),
        ]
        conns = [
            {'from': 'node-1', 'to': 'node-2'},
            {'from': 'node-7', 'to': 'node-8'},
            {'from': 'node-8', 'to': 'node-1'},
        ]
        return _wf(nodes, conns)

    def test_find_workflows_uses_undirected_connectivity(self):
        components = WorkflowEngine(_chain()).find_workflows()
        assert components == [{'node-1', 'node-2', 'node-3'}]

    def test_find_workflows_splits_disconnected_graphs(self):
        engine = WorkflowEngine(_wf([_node('node-1'), _node('node-5', 'process', operation='p')], []))
        assert engine.find_workflows() == [{'node-1'}, {'node-5'}]

    def test_find_workflows_follows_edges_backwards(self):
        # A -> B, C -> B: one component, even though B has no outbound edge.
        wf = _wf(
            [_node('node-1'), _node('node-2', 'output', operation='s'), _node('node-3')],
            [{'from': 'node-1', 'to': 'node-2'}, {'from': 'node-3', 'to': 'node-2'}],
        )
        assert WorkflowEngine(wf).find_workflows() == [{'node-1', 'node-2', 'node-3'}]

    def test_sort_workflows_orders_by_lowest_node_index(self):
        components = [{'node-7', 'node-8'}, {'node-1', 'node-2'}, {'node-3'}]
        ordered = WorkflowEngine.sort_workflows(components)
        assert [min(c) for c in ordered] == ['node-1', 'node-3', 'node-7']

    def test_sort_workflows_uses_the_minimum_not_the_first_id(self):
        ordered = WorkflowEngine.sort_workflows([{'node-9', 'node-2'}, {'node-3'}])
        assert ordered == [{'node-9', 'node-2'}, {'node-3'}]

    def test_sort_workflows_of_nothing_is_nothing(self):
        assert WorkflowEngine.sort_workflows([]) == []

    def test_a_workflow_with_otherly_named_nodes_still_orders(self):
        """A hand-edited workflow file is allowed to name its nodes anything.

        Reading the id suffix with ``int()`` used to raise ValueError on 'n1',
        and because nothing between ``sort_workflows`` and the HTTP handler
        caught it, the entire run died before any node executed — a file that
        could have been run in a strange order instead ran not at all.
        """
        ordered = WorkflowEngine.sort_workflows([{'n1', 'n2'}, {'node-1', 'node-2'}, {'beta'}])
        # Numbered ids first, in their creation order; the rest by name, which
        # is the only order left to them.
        assert ordered == [{'node-1', 'node-2'}, {'beta'}, {'n1', 'n2'}]

    def test_ids_without_any_number_are_ordered_by_name(self):
        # Deterministic, whatever the set iteration order of the run.
        first = WorkflowEngine.sort_workflows([{'zeta'}, {'alpha'}, {'mid-3'}])
        assert [sorted(c)[0] for c in first] == ['mid-3', 'alpha', 'zeta']

    def test_extract_subworkflow_keeps_only_internal_edges_and_settings(self):
        engine = WorkflowEngine(
            _wf(
                [_node('node-1', platform='zhihu'), _node('node-2', 'output', operation='s'), _node('node-7')],
                [{'from': 'node-1', 'to': 'node-2'}, {'from': 'node-7', 'to': 'node-1'}],
                settings={'parallel': True},
            ),
            executor='exec',
        )
        sub = engine.extract_subworkflow({'node-1', 'node-2'})
        assert isinstance(sub, WorkflowEngine)
        assert sorted(sub.nodes) == ['node-1', 'node-2']
        assert sub.connections == [{'from': 'node-1', 'to': 'node-2'}]
        assert sub.settings == {'parallel': True}
        assert sub.executor == 'exec'

    def test_extract_subworkflow_drops_unknown_member_ids(self):
        # A wire to a deleted node no longer joins the component at all (naming an id
        # the canvas does not hold is how the ordering was once told there was a
        # cycle), so the component is only the node that exists and extraction has
        # nothing to filter — which is why both answers stay one rule.
        engine = WorkflowEngine(_wf([_node('node-1')], [{'from': 'node-1', 'to': 'node-2'}]))
        component = engine.find_workflows()[0]
        assert component == {'node-1'}
        assert list(engine.extract_subworkflow(component).nodes) == ['node-1']
        # The dangling wire itself is still reported, by validate().
        assert any('node-2' in error for error in engine.validate()), engine.validate()


# ─── validate ──────────────────────────────────────────────────────────


class TestValidate:
    def test_a_wired_workflow_is_accepted(self):
        wf = _wf(
            [
                _node('node-1', platform='zhihu'),
                _node('node-2', 'analysis', params={'operation': 'emotion'}),
                _node('node-3', 'output', operation='csv'),
            ],
            [{'from': 'node-1', 'to': 'node-2'}, {'from': 'node-2', 'to': 'node-3'}],
        )
        assert WorkflowEngine(wf).validate() == []

    def test_blank_keyword_counts_as_missing(self, en):
        wf = _wf([_node('node-1', platform='zhihu', params={'keyword': '   '})], [])
        errors = WorkflowEngine(wf).validate()
        assert len(errors) == 1
        assert 'the required field keyword is empty' in errors[0]
        # The node is named by its type label + id, not a bare 'node-1'.
        assert 'Data Source #node-1' in errors[0]

    def test_platform_may_come_from_params(self, en):
        wf = _wf([_node('node-1', params={'platform': 'weibo', 'keyword': 'kw'})], [])
        assert WorkflowEngine(wf).validate() == []

    def test_a_wire_to_a_missing_node_is_named_not_called_a_cycle(self, en):
        """A dangling endpoint used to be reported as a cycle with an empty node list.

        The ghost id entered the in-degree table, so the ordering placed more ids than
        ``self.nodes`` holds and the cycle branch printed the difference — which is the
        empty set. The user was told to hunt a loop that does not exist, in a sentence
        whose own slot was blank.
        """
        ghost = _wf([_node('node-1', 'upload', params={'dataset_id': 'd1'})], [{'from': 'node-1', 'to': 'ghost'}])
        engine = WorkflowEngine(ghost)
        assert engine.topological_sort() == ['node-1'], 'a dangling wire must not upset the ordering'
        errors = engine.validate()
        assert len(errors) == 1, errors
        assert 'ghost' in errors[0] and 'node-1' in errors[0], errors
        assert 'cycle' not in errors[0], 'a missing node is not a loop'

    def test_a_real_cycle_is_still_a_cycle_and_still_named(self, en):
        """The guard above must not swallow the case it was not written for."""
        looped = _wf([_node('node-1', 'upload', params={'dataset_id': 'd1'})], [{'from': 'node-1', 'to': 'node-1'}])
        engine = WorkflowEngine(looped)
        errors = engine.validate()
        assert any('cycle' in error and 'node-1' in error for error in errors), errors

    def test_an_empty_canvas_is_refused_not_completed(self, en):
        """Zero nodes has no cycle, no missing field and nothing to report.

        Validation therefore said nothing, the worker found 0 workflows, ran none, and
        the run closed as ``completed`` with 「0/0 个节点完成」 and a 已完成 toast —
        the exact phrasing a refused definition is pinned (elsewhere in this file) never
        to use. The browser gates this canvas; the backend must too, because a
        hand-edited file reaches it directly.
        """
        assert WorkflowEngine(_wf([], [])).validate() == [t('engine.empty_canvas')]

    def test_a_mode_the_platform_does_not_offer_is_named_as_such(self, en):
        """The matrix lookup falls back to the platform's first mode so old canvases
        still render — which used to mean a node asking for 某作者的作品 on weibo was
        validated as a keyword search. The user then read 「缺少关键词」 for a field
        the panel never showed them, or worse, the wrong crawl ran.

        The refusal is scoped to platforms that offer a choice; a single-mode
        platform has nothing to be confused with, and its stale keys are history
        (see the WeChat case in TestValidateUsesLabels).
        """
        wf = _wf([_node('node-1', params={'platform': 'weibo', 'keyword': 'kw', 'mode': 'author'})], [])
        errors = WorkflowEngine(wf).validate()
        assert len(errors) == 1
        assert 'no such collection mode' in errors[0]
        assert 'Data Source #node-1' in errors[0] and 'weibo' in errors[0]
        assert 'keyword is empty' not in errors[0]

    def test_a_canvas_that_names_no_mode_keeps_working(self, en):
        """The fallback is for nodes saved before the mode selector existed: an
        empty mode is not a mistake, so it must validate as the platform's own
        default (keyword) and not be refused."""
        wf = _wf([_node('node-1', params={'platform': 'weibo', 'keyword': 'kw', 'mode': ''})], [])
        assert WorkflowEngine(wf).validate() == []

    def test_a_cycle_is_fatal_and_names_the_nodes_in_it(self, en):
        conns = [{'from': 'node-1', 'to': 'node-2'}, {'from': 'node-2', 'to': 'node-1'}]
        nodes = [_node('node-1', platform='zhihu'), _node('node-2', 'output', operation='csv')]
        errors = WorkflowEngine(_wf(nodes, conns)).validate()
        assert len(errors) == 1
        # Used to be one untranslated English exclamation with no node in it,
        # while every other validation message named its node in the console's
        # language — the loop is drawn on the canvas, so the message can point.
        assert 'cycle' in errors[0]
        assert 'Data Source #node-1' in errors[0] and 'Output #node-2' in errors[0]

    def test_name_node_must_lead_and_have_a_downstream(self, en):
        wf = _wf(
            [_node('node-1', 'name', params={'workflow_name': '周报'}), _node('node-2', 'output', operation='s')],
            [{'from': 'node-2', 'to': 'node-1'}],
        )
        errors = WorkflowEngine(wf).validate()
        assert any('name node must lead' in e for e in errors)
        assert any('must connect to a downstream node' in e for e in errors)

    @pytest.mark.parametrize(
        'node, expected',
        [
            (_node('node-1', params={}), 'source node has no platform'),
            (_node('node-1', params={'keyword': ''}), 'source node has no platform'),
            (_node('node-1', platform='zhihu', params={}), 'the required field keyword is empty'),
            (_node('node-1', platform='wechat', params={}), 'the required field article URLs is empty'),
            (_node('node-1', 'upload', params={}), 'upload node has no file selected'),
            (_node('node-1', 'process', operation=''), 'process node has no operation'),
            (_node('node-1', 'output', operation=''), 'output node has no operation'),
            (_node('node-1', 'analysis', params={}), 'analysis node has no operation/steps configured'),
            (_node('node-1', 'tokenize', params={}), 'tokenize node is missing its text column'),
            (_node('node-1', 'visualize', params={}), 'visualize node has no chart type'),
            (_node('node-1', 'name', params={'workflow_name': ' '}), 'the name node needs a workflow name'),
        ],
    )
    def test_each_misconfiguration_names_its_node(self, en, node, expected):
        errors = WorkflowEngine(_wf([node], [])).validate()
        assert any(expected in e for e in errors), errors
        assert all('#node-1' in e for e in errors)

    def test_wechat_source_is_satisfied_by_urls_only(self, en):
        node = _node('node-1', platform='wechat', params={'urls': 'https://mp.weixin.qq.com/s/abc'})
        assert WorkflowEngine(_wf([node], [])).validate() == []

    def test_an_operation_written_only_in_params_is_still_a_configured_node(self, en):
        """The canvas writes ``operation`` twice — on the node and in its params —
        and every executor reads either. Validation that looked only at the node
        refused a hand-edited file the runner would have executed fine, so the
        strictness had no counterpart in the behaviour it was guarding."""
        process = {'id': 'node-1', 'type': 'process', 'params': {'operation': 'clean', 'text_column': '正文'}}
        output = {'id': 'node-2', 'type': 'output', 'params': {'operation': 'save', 'filename': 'a.csv'}}
        assert WorkflowEngine(_wf([process, output], [])).validate() == []

    def test_an_operation_written_only_on_the_node_is_still_a_configured_analysis(self, en):
        """The mirror case, and the one the analysis branch missed: its executor
        reads `node['operation']` first, so a file carrying only that field runs —
        refusing it there while accepting it for process and output was an
        inconsistency in the gate, not a guard."""
        analysis = {'id': 'node-1', 'type': 'analysis', 'operation': 'select_columns', 'params': {'columns': 'a'}}
        assert WorkflowEngine(_wf([analysis], [])).validate() == []

    def test_analysis_accepts_a_step_list(self, en):
        node = _node('node-1', 'analysis', params={'steps': [{'op': 'drop_null'}]})
        assert WorkflowEngine(_wf([node], [])).validate() == []

    def test_visualize_needs_chart_and_x_field(self, en):
        node = _node('node-1', 'visualize', params={'chart_type': 'bar'})
        errors = WorkflowEngine(_wf([node], [])).validate()
        assert errors == ['Node Visualize #node-1: visualize node is missing the x field']

    @pytest.mark.parametrize('ntype', ['resume', 'unknown', 'clean', ''])
    def test_node_types_the_engine_does_not_own_pass_silently(self, en, ntype):
        node = _node('node-1', ntype, params={})
        assert WorkflowEngine(_wf([node], [])).validate() == []

    def test_every_node_is_checked(self, en):
        nodes = [
            _node('node-1', params={}),
            _node('node-2', 'upload', params={}),
            _node('node-3', 'process', operation=''),
        ]
        errors = WorkflowEngine(_wf(nodes, [])).validate()
        assert len(errors) == 3
        # Every message names its own node — type label plus the id suffix.
        assert sorted(e.split('#')[-1].split(':')[0].strip() for e in errors) == ['node-1', 'node-2', 'node-3']
        assert all(e.startswith('Node ') for e in errors)

    def test_messages_are_rendered_in_the_active_language(self):
        # The language is process state another test (or a request handler) may
        # have moved, so both renderings are pinned here rather than assumed.
        nodes = [_node('node-1', params={})]
        previous = get_lang()
        try:
            set_lang('zh')
            zh = WorkflowEngine(_wf(nodes, [])).validate()
            set_lang('en')
            en = WorkflowEngine(_wf(nodes, [])).validate()
        finally:
            set_lang(previous)
        assert zh != en
        assert '没有选择平台' in zh[0]


class TestNodeLabel:
    def test_a_titled_node_reads_as_its_name_plus_id(self):
        assert node_label({'title': '知乎采集'}, 'node-7') == '知乎采集 #node-7'

    def test_title_is_stripped(self):
        assert node_label({'title': '  清洗  '}, 'node-1') == '清洗 #node-1'

    def test_untitled_node_falls_back_to_the_type_label(self, en):
        # No title (older saved workflows dropped it) still reads as the
        # type's label, not a bare id — 'Data Source #node-3' beats 'node-3'.
        assert node_label({'type': 'source'}, 'node-3') == 'Data Source #node-3'

    def test_no_title_and_no_known_type_still_reads_as_the_id(self):
        assert node_label({}, 'node-3') == 'node-3'
        assert node_label(None, 'node-3') == 'node-3'
        assert node_label({'type': 'not-a-real-type'}, 'node-3') == 'node-3'

    def test_a_title_equal_to_the_id_is_not_doubled(self):
        # A saved workflow that stored the raw id as the title must not read
        # "node-1 #node-1" — one honest label, not the same token twice.
        assert node_label({'title': 'node-1'}, 'node-1') == 'node-1'


class TestValidateUsesLabels:
    def test_a_renamed_node_is_named_in_the_error(self, en):
        node = _node('node-2', params={})
        node['title'] = '微博抓取'
        errors = WorkflowEngine(_wf([node], [])).validate()
        assert '微博抓取 #node-2' in errors[0]

    def test_source_comments_mode_needs_urls_not_keyword(self, en):
        node = {
            'id': 'node-1',
            'type': 'source',
            'title': '评论抓取',
            'params': {'platform': 'zhihu', 'collect': 'comments', 'urls': ''},
        }
        errors = WorkflowEngine(_wf([node], [])).validate()
        assert any('the required field article URLs is empty' in e for e in errors)
        # A keyword must NOT be demanded once comments mode is chosen.
        assert not any('keyword' in e for e in errors)

    def test_source_comments_mode_is_satisfied_by_urls(self):
        node = {
            'id': 'node-1',
            'type': 'source',
            'params': {'platform': 'zhihu', 'collect': 'comments', 'urls': 'https://www.zhihu.com/question/1'},
        }
        assert WorkflowEngine(_wf([node], [])).validate() == []

    def test_comments_mode_flags_links_of_a_foreign_platform(self, en):
        # The platform select binds the node to ONE site — a weibo link under
        # zhihu (and an unknown domain) must be named before the run, exactly
        # like the JS pre-run validation and the crawl-time filter agree.
        node = {
            'id': 'node-1',
            'type': 'source',
            'params': {
                'platform': 'zhihu',
                'collect': 'comments',
                'urls': 'https://www.zhihu.com/question/1\nhttps://weibo.com/123/AbC\nhttps://example.com/x',
            },
        }
        errors = WorkflowEngine(_wf([node], [])).validate()
        assert any('2 link(s) do not match the selected platform (zhihu)' in e for e in errors)

    def test_wechat_node_reads_a_stale_comments_flag_as_article_crawl(self, en):
        # WeChat has no comment adapter, so its entry in the matrix carries a
        # single mode: a stale collect='comments' left in an old file resolves to
        # that mode and validates as the URL-driven crawl it really is.
        node = {
            'id': 'node-1',
            'type': 'source',
            'params': {'platform': 'wechat', 'collect': 'comments', 'urls': 'https://mp.weixin.qq.com/s/abc'},
        }
        assert WorkflowEngine(_wf([node], [])).validate() == []
        empty = {
            'id': 'node-1',
            'type': 'source',
            'params': {'platform': 'wechat', 'collect': 'comments', 'urls': ''},
        }
        errors = WorkflowEngine(_wf([empty], [])).validate()
        assert any('the required field article URLs is empty' in e for e in errors)
        assert not any('comments' in e for e in errors), 'wechat must not be routed through the comment engine'
