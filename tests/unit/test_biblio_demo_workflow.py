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
    assert {node['type'] for node in off} == {'biblio', 'visualize', 'fuse', 'upload'}
    shape = next((node.get('params') or {}) for node in off if node['type'] == 'biblio')
    assert shape['output_shape'] == 'dual_map'
    # Blank by design: the basemap is the user's own journal-category table, never bundled.
    assert not str(shape.get('basemap_dataset_id') or '').strip()


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
