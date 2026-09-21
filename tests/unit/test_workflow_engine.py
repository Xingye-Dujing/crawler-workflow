"""Tests for the DAG parser/scheduler in engine/workflow.py.

The engine is the piece that turns the canvas into an execution order, so the
contracts pinned here are the ones the executor silently relies on:

- a cycle is *always* fatal for both orderings, with one shared message,
- an isolated node still gets scheduled (it is a workflow of its own),
- several disconnected sub-workflows are split, ordered by creation index,
- ``validate()`` returns ready-to-print translated text, never a key, and says
  nothing about node types the engine does not own (``resume`` and friends).
"""

import pytest

from engine.workflow import WorkflowEngine
from i18n import get_lang, set_lang

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
        assert engine.validate() == []

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

    def test_topological_sort_rejects_a_cycle(self):
        conns = [{'from': 'node-1', 'to': 'node-2'}, {'from': 'node-2', 'to': 'node-1'}]
        with pytest.raises(ValueError, match='Workflow contains a cycle!'):
            WorkflowEngine(_wf([_node('node-1'), _node('node-2')], conns)).topological_sort()

    def test_group_by_level_bundles_independent_nodes(self):
        nodes = [_node('node-1'), _node('node-2', 'analysis'), _node('node-3', 'analysis')]
        conns = [{'from': 'node-1', 'to': 'node-2'}, {'from': 'node-1', 'to': 'node-3'}]
        levels = WorkflowEngine(_wf(nodes, conns)).group_by_level()
        assert [set(level) for level in levels] == [{'node-1'}, {'node-2', 'node-3'}]

    def test_group_by_level_matches_topological_sort_partition(self):
        levels = WorkflowEngine(_chain()).group_by_level()
        assert [n for level in levels for n in level] == WorkflowEngine(_chain()).topological_sort()

    def test_group_by_level_rejects_a_cycle(self):
        conns = [
            {'from': 'node-1', 'to': 'node-2'},
            {'from': 'node-2', 'to': 'node-3'},
            {'from': 'node-3', 'to': 'node-1'},
        ]
        nodes = [_node('node-1'), _node('node-2', 'analysis'), _node('node-3', 'output')]
        with pytest.raises(ValueError, match='Workflow contains a cycle!'):
            WorkflowEngine(_wf(nodes, conns)).group_by_level()


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
        # A connection may point at a deleted node; the component still names it.
        engine = WorkflowEngine(_wf([_node('node-1')], [{'from': 'node-1', 'to': 'node-2'}]))
        component = engine.find_workflows()[0]
        assert 'node-2' in component
        assert list(engine.extract_subworkflow(component).nodes) == ['node-1']


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
        assert WorkflowEngine(wf).validate() == ['Node node-1: source node has no keyword']

    def test_platform_may_come_from_params(self, en):
        wf = _wf([_node('node-1', params={'platform': 'weibo', 'keyword': 'kw'})], [])
        assert WorkflowEngine(wf).validate() == []

    def test_cycle_is_reported_verbatim_and_untranslated(self, en):
        conns = [{'from': 'node-1', 'to': 'node-2'}, {'from': 'node-2', 'to': 'node-1'}]
        nodes = [_node('node-1', platform='zhihu'), _node('node-2', 'output', operation='csv')]
        errors = WorkflowEngine(_wf(nodes, conns)).validate()
        assert errors == ['Workflow contains a cycle!']

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
            (_node('node-1', platform='zhihu', params={}), 'source node has no keyword'),
            (_node('node-1', platform='wechat', params={}), 'WeChat source needs at least one article URL'),
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
        assert all(e.startswith('Node node-1') for e in errors)

    def test_wechat_source_is_satisfied_by_urls_only(self, en):
        node = _node('node-1', platform='wechat', params={'urls': 'https://mp.weixin.qq.com/s/abc'})
        assert WorkflowEngine(_wf([node], [])).validate() == []

    def test_analysis_accepts_a_step_list(self, en):
        node = _node('node-1', 'analysis', params={'steps': [{'op': 'drop_null'}]})
        assert WorkflowEngine(_wf([node], [])).validate() == []

    def test_visualize_needs_chart_and_x_field(self, en):
        node = _node('node-1', 'visualize', params={'chart_type': 'bar'})
        errors = WorkflowEngine(_wf([node], [])).validate()
        assert errors == ['Node node-1: visualize node is missing the x field']

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
        assert sorted(e.split(':')[0] for e in errors) == ['Node node-1', 'Node node-2', 'Node node-3']

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
