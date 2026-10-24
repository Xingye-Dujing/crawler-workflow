"""The bibliometrics demo canvas: every chart the service can draw is reachable from it.

`data/workflows/` is authored work, not runtime state, so this reads the real file. A node the
demo cannot run (the dual map wants a journal-category basemap the repository does not ship) is
shipped switched OFF — and a disabled node is not on the canvas, which is exactly what
``effective_workflow`` has to prove here.
"""

import json
from pathlib import Path

import pytest

from engine.workflow import WorkflowEngine, effective_workflow
from services.chart_contracts import BIBLIO_CHART_TYPES

pytestmark = pytest.mark.unit

_DEMO = Path(__file__).resolve().parents[2] / 'data' / 'workflows' / '文献计量演示：CNKI 与 CSSCI 知识图谱.json'


def _draft():
    return json.loads(_DEMO.read_text(encoding='utf-8'))


def _graph(draft: dict) -> dict:
    return {'nodes': draft['nodes'], 'connections': draft['connections']}


def test_the_demo_is_a_valid_graph_once_its_off_nodes_are_dropped():
    draft = _draft()
    live = effective_workflow(_graph(draft))
    assert len(live['nodes']) < len(draft['nodes']), 'the dual map ships switched off'
    engine = WorkflowEngine(live)
    assert engine.validate() == []
    assert engine.dangling_connections() == []


def test_every_bibliometric_view_is_on_the_demo_canvas():
    charts = {
        str((node.get('params') or {}).get('chart_type') or '')
        for node in _draft()['nodes']
        if node.get('type') == 'visualize'
    }
    assert set(BIBLIO_CHART_TYPES) <= charts, f'demo is missing {sorted(set(BIBLIO_CHART_TYPES) - charts)}'


def test_the_dual_map_chain_is_off_and_names_the_dataset_it_wants():
    off = [node for node in _draft()['nodes'] if not (node.get('params') or {}).get('enabled', True)]
    assert {node['type'] for node in off} == {'analysis', 'biblio', 'visualize', 'fuse', 'upload'}
    shapes = {str((node.get('params') or {}).get('output_shape') or '') for node in off if node['type'] == 'biblio'}
    assert shapes == {'nodes', 'dual_map'}, shapes
    dual = next(
        (node.get('params') or {}) for node in off if (node.get('params') or {}).get('output_shape') == 'dual_map'
    )
    # Blank by design: the basemap is the user's own journal-category table, never bundled.
    assert not str(dual.get('basemap_dataset_id') or '').strip()


def test_the_variation_table_is_on_the_demo_canvas_and_runs():
    """Structural variation needs nothing the repository lacks, so unlike the dual map and the
    fusion chain it ships switched ON — a capability no demo uses is a capability nobody finds."""
    live = effective_workflow(_graph(_draft()))['nodes']
    variation = [
        node
        for node in live
        if node.get('type') == 'biblio' and (node.get('params') or {}).get('output_shape') == 'variation'
    ]
    assert len(variation) == 1
    params = variation[0]['params']
    assert params['variation'] is True
    assert params['cluster'] is False and params['burst'] is False


def test_the_fusion_chain_is_off_until_the_third_dataset_is_uploaded():
    """The fusion needs a crawled / uploaded social table the repository does not register as a
    dataset, so it ships switched off — and a disabled node is not on the canvas, which the
    graph-validity case above already proves."""
    draft = _draft()
    fuse = next(node for node in draft['nodes'] if node['type'] == 'fuse')
    assert not (fuse.get('params') or {}).get('enabled', True)
    assert fuse['params']['source_labels'], 'the literature parent must be named, not guessed'
    parents = [conn['from'] for conn in draft['connections'] if conn['to'] == fuse['id']]
    assert len(parents) == 2, 'fusion with one wire is not fusion'
    graph = effective_workflow(_graph(draft))
    assert fuse['id'] not in graph['nodes'], 'the off chain must not reach validation or the run'


def test_the_cluster_review_node_ships_off_because_it_costs_model_calls():
    """The research-front review is the demo's one step that pays Ollama once per cluster, so it
    cannot be left switched on the way the variation table is — and it must be attached to a
    biblio node that actually clusters, or the server refuses it for want of a 聚类 column.

    Its column boxes ship blank on purpose: the defaults are the names a ``biblio`` node writes
    (聚类 / 聚类标签 / 节点 / 频次 / 首年 / 末年), and a demo that hard-copied them into the file
    would stop testing the thing that matters — that an untouched form lines up with the node.
    """
    draft = _draft()
    review = next(node for node in draft['nodes'] if (node.get('params') or {}).get('operation') == 'cluster_review')
    assert not (review['params']).get('enabled', True)
    assert not [key for key, value in review['params'].items() if key.startswith('review_') and str(value or '')]
    parents = [conn['from'] for conn in draft['connections'] if conn['to'] == review['id']]
    assert len(parents) == 1
    upstream = next(node for node in draft['nodes'] if node['id'] == parents[0])
    assert upstream['type'] == 'biblio' and (upstream.get('params') or {}).get('cluster') is True
    assert review['id'] not in effective_workflow(_graph(draft))['nodes']


def test_the_watch_node_ships_off_because_it_writes_outside_the_run():
    """Monitoring is the one demo capability whose effect outlives the run: enabling it files a
    capture into ``data/biblio.db`` on EVERY run and keeps a history the user never asked for while
    trying the charts out. So it ships switched off, with the project name already filled in — the
    reader sees what to type rather than discovering it from a manual.

    It is wired to its own ``biblio`` node rather than reusing 节点 2 because the watched node is
    the one that must carry clustering and bursting: those are what the diff has to say anything
    about (新簇 / 新突现).
    """
    draft = _draft()
    watched = [node for node in draft['nodes'] if str((node.get('params') or {}).get('watch_project') or '').strip()]
    assert len(watched) == 1
    params = watched[0]['params']
    assert params['enabled'] is False
    assert params['cluster'] is True and params['burst'] is True
    assert not str(params.get('watch_baseline') or '').strip(), 'the default baseline is the capture before'
    graph = effective_workflow(_graph(draft))
    assert watched[0]['id'] not in graph['nodes'], 'the off watch must not file anything during the demo'
