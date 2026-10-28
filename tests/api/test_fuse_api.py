"""Cross-source fusion through the real routes: two uploads → fuse → bibliometrics → graph.

The unit tests prove the fold; this proves the node is wired — that the engine hands it BOTH
parents (not one merged table that lost their names), that its output feeds a ``biblio`` node with
no remapping, and that the graph that comes out can say which terms live in both corpora.
"""

import io
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.api

SAMPLES = Path(__file__).resolve().parents[2] / 'samples'


def _sample(name: str) -> Path:
    """Samples live under their domain folder; this test needs a biblio export and a text table."""
    for domain in ('biblio', 'fuse', 'vendor'):
        candidate = SAMPLES / domain / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f'no sample named {name} under {SAMPLES}')


def _upload(client, name: str) -> str:
    response = client.post(
        '/api/data/upload',
        data={'file': (io.BytesIO(_sample(name).read_bytes()), name)},
        content_type='multipart/form-data',
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()['dataset_id']


def _canvas(literature: str, posts: str) -> dict:
    return {
        'nodes': [
            {
                'id': 'n-lit',
                'type': 'upload',
                'title': '文献',
                'params': {'dataset_id': literature, 'dataset_name': 'cnki.txt', 'row_count': 36},
                'x': 0,
                'y': 0,
            },
            {
                'id': 'n-posts',
                'type': 'upload',
                'title': '社媒',
                'params': {'dataset_id': posts, 'dataset_name': 'posts.csv', 'row_count': 8},
                'x': 0,
                'y': 260,
            },
            {
                'id': 'n-fuse',
                'type': 'fuse',
                'title': '跨源融合',
                'params': {'source_labels': 'n-lit = 文献', 'keep_undated': True, 'export_files': True},
                'x': 260,
                'y': 130,
            },
            {
                'id': 'n-graph',
                'type': 'biblio',
                'title': '融合关键词图谱',
                'params': {
                    'entity_type': 'keyword',
                    'entity_column': '关键词',
                    'year_column': '年份',
                    'title_column': '题名',
                    'slice_years': 2,
                    'selection': 'top_n',
                    'top_n': 50,
                    'min_count': 1,
                    'link_measure': 'cosine',
                    'pruning': 'none',
                    'cluster': False,
                    'burst': False,
                    'output_shape': 'nodes',
                    'export_files': False,
                },
                'x': 520,
                'y': 130,
            },
            {
                'id': 'n-chart',
                'type': 'visualize',
                'title': '融合图谱',
                'params': {
                    'chart_type': 'knowledge_graph',
                    'engine': 'echarts',
                    'title': '文献 × 社媒 关键词共现',
                    'emit_latex': True,
                    'emit_latex_table': True,
                },
                'x': 780,
                'y': 130,
            },
        ],
        'connections': [
            {'from': 'n-lit', 'to': 'n-fuse'},
            {'from': 'n-posts', 'to': 'n-fuse'},
            {'from': 'n-fuse', 'to': 'n-graph'},
            {'from': 'n-graph', 'to': 'n-chart'},
        ],
        'settings': {'mode': 'serial', 'headless': True, 'max_workers': 1},
    }


def _wait(app_module, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not app_module.execution_state.get('running'):
            return True
        time.sleep(0.1)
    return False


@pytest.mark.serial
def test_two_sources_fuse_into_one_graph_that_names_their_overlap(client, app_module):
    literature = _upload(client, 'biblio_cnki_demo.txt')
    posts = _upload(client, 'weibo.csv')
    started = client.post(
        '/api/workflow/execute',
        json={'workflow': _canvas(literature, posts), 'workflow_name': 'fuse-e2e'},
    )
    assert started.status_code == 200, started.get_json()
    run_id = started.get_json()['run_id']
    assert _wait(app_module), 'the execute thread did not finish in time'

    status = client.get('/api/workflow/status').get_json()
    assert status['running'] is False
    assert status['completed_nodes'] == 5, status['logs']

    store = app_module._RUN_STORE
    fused = store.load_rows(run_id, 'n-fuse')
    assert fused and {'关键词', '年份', '来源'} <= set(fused[0])
    assert {row['来源'] for row in fused} >= {'文献', '微博', '知乎', '抖音'}

    graph = store.load_rows(run_id, 'n-graph')
    assert graph and '来源' in graph[0] and '跨源' in graph[0]
    both = {row['节点'] for row in graph if row['跨源']}
    assert both, 'a fused graph with no term shared by the two corpora proves nothing'
    # A term that only one corpus uses is still in the graph, and says so.
    assert any(not row['跨源'] for row in graph)

    option = status['chart_results']['n-chart']['option']
    assert option['series'][0]['links']
    assert status['chart_results']['n-chart']['latex']

    files = store.files_for_run(run_id, node_id='n-fuse')
    assert [entry['kind'] for entry in files] == ['fuse_records']
    assert '融合' in files[0]['name']
    assert any('跨源融合' in line or 'fusion' in line.lower() for line in status['logs'])


@pytest.mark.serial
def test_a_fusion_node_with_one_parent_still_works_as_a_normalizer(client, app_module):
    """One source is not a mistake here: it is how a crawled table becomes the record shape a
    ``biblio`` node can read, which is the same node doing half its job."""
    posts = _upload(client, 'weibo.csv')
    canvas = _canvas(posts, posts)
    canvas['nodes'] = [node for node in canvas['nodes'] if node['id'] != 'n-lit']
    canvas['connections'] = [conn for conn in canvas['connections'] if conn['from'] != 'n-lit']
    started = client.post(
        '/api/workflow/execute',
        json={'workflow': canvas, 'workflow_name': 'fuse-single'},
    )
    assert started.status_code == 200, started.get_json()
    assert _wait(app_module)
    status = client.get('/api/workflow/status').get_json()
    assert status['completed_nodes'] == 4, status['logs']


@pytest.mark.serial
def test_a_fusion_that_cannot_find_an_entity_refuses_by_naming_the_parent(client, app_module):
    literature = _upload(client, 'biblio_cnki_demo.txt')
    posts = _upload(client, 'weibo.csv')
    canvas = _canvas(literature, posts)
    canvas['nodes'][2]['params']['entity_columns'] = '不存在的列'
    started = client.post('/api/workflow/execute', json={'workflow': canvas, 'workflow_name': 'fuse-refuse'})
    assert started.status_code == 200, started.get_json()
    assert _wait(app_module)
    status = client.get('/api/workflow/status').get_json()
    assert status['completed_nodes'] == 2, 'the fusion and everything after it must not settle DONE'
    assert status['failed_nodes'] == 1
    reason = ' | '.join(line for line in status['logs'] if 'n-fuse' in line)
    assert '不存在的列' in reason, reason
