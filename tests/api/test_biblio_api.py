"""Upload → biblio → knowledge graph, through the real HTTP routes."""

import io
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.api

SAMPLES = Path(__file__).resolve().parents[2] / 'samples'


def _upload(client, name: str):
    payload = (SAMPLES / name).read_bytes()
    response = client.post(
        '/api/data/upload',
        data={'file': (io.BytesIO(payload), name)},
        content_type='multipart/form-data',
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _wait_for_worker(app_module, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not app_module.execution_state.get('running'):
            return True
        time.sleep(0.05)
    return False


def _workflow(dataset_id: str, columns: str):
    params = {
        'entity_type': 'keyword',
        'time_start': '',
        'time_end': '',
        'slice_years': 1,
        'selection': 'top_n',
        'top_n': 50,
        'top_pct': 10,
        'g_index': 25,
        'min_count': 1,
        'link_measure': 'cosine',
        'max_links_per_node': 10,
        'lrf': 2.5,
        'pruning': 'none',
        'cluster': True,
        'cluster_count': '',
        'label_method': 'llr',
        'top_terms': 5,
        'burst': True,
        'burst_gamma': 0.5,
        'burst_min_duration': 2,
        'burst_weight': 2.0,
        'burst_top': 20,
        'export_files': False,
    }
    return {
        'nodes': [
            {
                'id': 'node-1',
                'type': 'upload',
                'title': '上传文献',
                'params': {'dataset_id': dataset_id, 'dataset_name': 'demo.txt', 'row_count': 36},
                'x': 0,
                'y': 0,
            },
            {'id': 'node-2', 'type': 'biblio', 'title': '关键词图谱', 'params': params, 'x': 240, 'y': 0},
            {
                'id': 'node-3',
                'type': 'visualize',
                'title': '知识图谱',
                'params': {
                    'chart_type': 'knowledge_graph',
                    'engine': 'echarts',
                    'title': '关键词知识图谱',
                    'emit_latex': False,
                    'emit_latex_table': False,
                },
                'x': 480,
                'y': 0,
            },
        ],
        'connections': [{'from': 'node-1', 'to': 'node-2'}, {'from': 'node-2', 'to': 'node-3'}],
        'settings': {'mode': 'serial', 'headless': True, 'max_workers': 1},
    }


class TestBibliographicUpload:
    def test_an_undecodable_txt_keeps_the_old_text_fallback(self, client):
        response = client.post(
            '/api/data/upload',
            data={'file': (io.BytesIO(b'\xff\xff\xff'), 'odd.txt')},
            content_type='multipart/form-data',
        )
        body = response.get_json()
        assert response.status_code == 200, body
        assert body['is_txt'] is True
        assert body['biblio_format'] is None
        assert body['columns'] == ['content']
        assert body['row_count'] == 1

    def test_cnki_refworks_is_imported_as_records(self, client):
        body = _upload(client, 'biblio_cnki_demo.txt')
        assert body['biblio_format'] == 'CNKI'
        assert body['is_txt'] is False
        assert body['row_count'] == 36
        assert '关键词' in body['columns']
        assert body['warnings'] == []

    def test_cssci_keeps_references(self, client):
        body = _upload(client, 'biblio_cssci_demo.txt')
        assert body['biblio_format'] == 'CSSCI'
        assert body['row_count'] == 16
        assert '参考文献' in body['columns']
        preview = body['preview'][0]
        assert '[1]' in preview['参考文献']

    @pytest.mark.parametrize(
        ('name', 'fmt', 'rows'),
        [
            ('biblio_scopus_demo.csv', 'Scopus', 3),
            ('biblio_dimensions_demo.csv', 'Dimensions', 2),
            ('biblio_lens_demo.csv', 'Lens', 2),
            ('biblio_pubmed_demo.xml', 'PubMed', 2),
            ('biblio_ris_demo.ris', 'RIS', 2),
            ('biblio_bibtex_demo.bib', 'BibTeX', 2),
            ('biblio_endnote_demo.enw', 'EndNote', 2),
        ],
    )
    def test_international_exports_upload_as_records(self, client, name, fmt, rows):
        body = _upload(client, name)
        assert body['biblio_format'] == fmt
        assert body['is_txt'] is False
        assert body['row_count'] == rows
        assert body['biblio_capabilities'] is not None
        assert body['biblio_capabilities']['abstract'] is True

    def test_an_ordinary_csv_is_still_an_ordinary_table(self, client):
        response = client.post(
            '/api/data/upload',
            data={'file': (io.BytesIO('name,age\n张三,20\n'.encode()), 'people.csv')},
            content_type='multipart/form-data',
        )
        body = response.get_json()
        assert response.status_code == 200, body
        assert body['biblio_format'] is None
        assert body['columns'] == ['name', 'age']
        assert body['row_count'] == 1


@pytest.mark.serial
def test_upload_biblio_visualize_end_to_end(client, app_module):
    uploaded = _upload(client, 'biblio_cnki_demo.txt')
    started = client.post(
        '/api/workflow/execute',
        json={'workflow': _workflow(uploaded['dataset_id'], '关键词'), 'workflow_name': 'biblio-e2e'},
    )
    assert started.status_code == 200, started.get_json()
    run_id = started.get_json()['run_id']
    assert _wait_for_worker(app_module), 'the execute thread did not finish in time'

    status = client.get('/api/workflow/status').get_json()
    assert status['running'] is False
    assert status['completed_nodes'] == 3, status['logs']
    assert {'node-1', 'node-2', 'node-3'} <= set(status['results'])
    assert 'node-3' in status['chart_results']
    assert status['chart_results']['node-3']['engine'] == 'echarts'
    assert status['chart_results']['node-3']['option']['series']

    store = app_module._RUN_STORE
    assert store is not None
    run = store.get_run(run_id)
    assert run['status'] == 'completed'
    biblio_rows = store.load_rows(run_id, 'node-2')
    assert biblio_rows
    assert '节点' in biblio_rows[0] and '连接' in biblio_rows[0]
    assert any('文献计量完成' in line or 'Bibliometrics done' in line for line in status['logs'])


@pytest.mark.serial
def test_dual_map_overlay_runs_end_to_end(client, app_module):
    """The basemap is a dataset the node reaches BY ID, never a second input edge: a second
    input would merge the journal-category table into the record table."""
    records = _upload(client, 'biblio_cssci_demo.txt')
    basemap = _upload(client, 'biblio_basemap_demo.csv')
    assert basemap['biblio_format'] is None, 'a two-column mapping table is an ordinary dataset'
    params = {
        'entity_type': 'journal',
        'year_column': '年份',
        'title_column': '题名',
        'reference_column': '参考文献',
        'slice_years': 2,
        'selection': 'top_n',
        'top_n': 50,
        'link_measure': 'cosine',
        'pruning': 'none',
        'cluster': False,
        'burst': False,
        'output_shape': 'dual_map',
        'basemap_dataset_id': basemap['dataset_id'],
        'export_files': False,
    }
    workflow = {
        'nodes': [
            {
                'id': 'node-1',
                'type': 'upload',
                'title': '上传文献',
                'params': {'dataset_id': records['dataset_id'], 'dataset_name': 'cssci.txt', 'row_count': 16},
                'x': 0,
                'y': 0,
            },
            {'id': 'node-2', 'type': 'biblio', 'title': '双图叠加', 'params': params, 'x': 240, 'y': 0},
            {
                'id': 'node-3',
                'type': 'visualize',
                'title': '双图叠加图',
                'params': {
                    'chart_type': 'dual_map',
                    'engine': 'echarts',
                    'title': '期刊—学科双图叠加',
                    'emit_latex': True,
                    'emit_latex_table': True,
                },
                'x': 480,
                'y': 0,
            },
        ],
        'connections': [{'from': 'node-1', 'to': 'node-2'}, {'from': 'node-2', 'to': 'node-3'}],
        'settings': {'mode': 'serial', 'headless': True, 'max_workers': 1},
    }
    started = client.post(
        '/api/workflow/execute',
        json={'workflow': workflow, 'workflow_name': 'biblio-dual-map'},
    )
    assert started.status_code == 200, started.get_json()
    run_id = started.get_json()['run_id']
    assert _wait_for_worker(app_module), 'the execute thread did not finish in time'

    status = client.get('/api/workflow/status').get_json()
    assert status['running'] is False
    assert status['completed_nodes'] == 3, status['logs']
    option = status['chart_results']['node-3']['option']
    sides = {entry['name'] for entry in option['series'][0]['categories']}
    assert len(sides) == 2
    assert option['series'][0]['links']

    rows = app_module._RUN_STORE.load_rows(run_id, 'node-2')
    assert {'map', 'source', 'target', 'weight'} <= set(rows[0])
    assert {row['map'] for row in rows} == {'journal', 'category', 'overlay'}
    # LaTeX for the overlay figure and its appendix table ships with the chart result.
    assert status['chart_results']['node-3']['latex']
    assert status['chart_results']['node-3']['latex_table']
    # The chart's own LaTeX is FILED and registered, not just returned inline: that name is the
    # only handle the panel's 编译为 PDF button may send, and the server compiles nothing else.
    assert str(status['chart_results']['node-3'].get('latex_file') or '').endswith('.txt')
    ledger = app_module._RUN_STORE.files_for_run(run_id, 'node-3')
    assert {row['kind'] for row in ledger} == {'latex', 'latex_table'}, ledger


@pytest.mark.serial
def test_structural_variation_table_runs_end_to_end(client, app_module):
    """The shape switch lives in the node executor, not in the algorithm, so only a run proves
    that what lands downstream — and what a chart or a save node would then read — is the
    variation table rather than the node table."""
    uploaded = _upload(client, 'biblio_cnki_demo.txt')
    params = {
        'entity_type': 'keyword',
        'slice_years': 1,
        'selection': 'top_n',
        'top_n': 50,
        'min_count': 1,
        'link_measure': 'cosine',
        'pruning': 'none',
        'cluster': False,
        'burst': False,
        'variation': True,
        'variation_min': 0.0,
        'output_shape': 'variation',
        'export_files': False,
    }
    workflow = {
        'nodes': [
            {
                'id': 'node-1',
                'type': 'upload',
                'title': '上传文献',
                'params': {'dataset_id': uploaded['dataset_id'], 'dataset_name': 'cnki.txt', 'row_count': 36},
                'x': 0,
                'y': 0,
            },
            {'id': 'node-2', 'type': 'biblio', 'title': '结构变异', 'params': params, 'x': 240, 'y': 0},
        ],
        'connections': [{'from': 'node-1', 'to': 'node-2'}],
        'settings': {'mode': 'serial', 'headless': True, 'max_workers': 1},
    }
    started = client.post(
        '/api/workflow/execute',
        json={'workflow': workflow, 'workflow_name': 'variation-e2e'},
    )
    assert started.status_code == 200, started.get_json()
    run_id = started.get_json()['run_id']
    assert _wait_for_worker(app_module), 'the execute thread did not finish in time'
    status = client.get('/api/workflow/status').get_json()
    assert status['completed_nodes'] == 2, status['logs']

    rows = app_module._RUN_STORE.load_rows(run_id, 'node-2')
    assert rows, status['logs']
    assert '结构变化' in rows[0] and '连接' not in rows[0]
    assert {'起始年', '结束年', '新增邻居', '消失邻居'} <= set(rows[0])
    assert any('结构变异' in line or 'Structural variation' in line for line in status['logs'])
