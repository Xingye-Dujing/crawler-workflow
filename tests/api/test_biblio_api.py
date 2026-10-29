"""Upload → biblio → knowledge graph, through the real HTTP routes."""

import io
import json
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.api

SAMPLES = Path(__file__).resolve().parents[2] / 'samples' / 'biblio'


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
    """Wait until the server would ACCEPT a start, not merely until ``running`` is false.

    ``begin_run`` counts a still-alive worker thread as busy (it clears ``running`` a moment
    before the thread exits, so a Stop → Run cannot overlap two writers), and a start sent in
    that window is QUEUED — a 200 with no ``run_id``. Asking the server's own question here is
    what keeps a second run in one test from intermittently landing in the queue.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        thread = app_module.execution_state.get('thread')
        if not app_module.execution_state.get('running') and not (thread is not None and thread.is_alive()):
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
        # CSSCI writes its list as ``1.作者.题名.刊名.年.(期)`` inside 【参考文献】.
        assert preview['参考文献'].startswith('1.')

    @pytest.mark.parametrize(
        ('name', 'fmt', 'rows', 'capability', 'absent'),
        [
            ('biblio_scopus_demo.csv', 'Scopus', 3, 'abstract', 'usage'),
            ('biblio_dimensions_demo.csv', 'Dimensions', 2, 'abstract', 'refs'),
            ('biblio_pubmed_demo.txt', 'PubMed', 2, 'abstract', 'refs'),
            ('biblio_pubmed_csv_demo.csv', 'PubMed', 3, 'doi', 'abstract'),
            ('biblio_ris_demo.ris', 'RIS', 2, 'abstract', 'tc'),
            ('biblio_bibtex_demo.bib', 'BibTeX', 2, 'abstract', 'country'),
            ('biblio_endnote_demo.enw', 'EndNote', 2, 'abstract', 'refs'),
            ('biblio_noteexpress_demo.net', 'NoteExpress', 2, 'abstract', 'refs'),
            ('biblio_wos_table_demo.csv', 'WoS', 3, 'abstract', ''),
            ('biblio_lens_demo.csv', 'Lens', 4, 'tc', 'country'),
        ],
    )
    def test_international_exports_upload_as_records(self, client, name, fmt, rows, capability, absent):
        """The capability map is read off the file, and the empty half of it is the guard.

        ``docs/analysis.md`` promises a user which analyses each export can answer; every
        ``absent`` entry below is a column that file shape genuinely does not write (measured on
        the vendor exports in ``samples/``). A fixture that started carrying one would make that
        promise and the parser disagree, and this is where it surfaces.
        """
        body = _upload(client, name)
        assert body['biblio_format'] == fmt
        assert body['is_txt'] is False
        assert body['row_count'] == rows
        assert body['biblio_capabilities'] is not None
        # Which capability is asserted per case, because a real export that carries no
        # abstract must not be reported as if it did: the PubMed CSV summary is that file.
        assert body['biblio_capabilities'][capability] is True
        if absent:
            assert body['biblio_capabilities'][absent] is False

    def test_a_lens_scholarly_export_reports_the_two_columns_it_does_not_carry(self, client):
        """Its References column is Lens record ids and it has no affiliation column.

        The upload response's capability map is what the biblio node refuses against, so a
        Lens-shaped ``true`` here would promise a co-citation network the file cannot build.
        """
        body = _upload(client, 'biblio_lens_demo.csv')
        assert body['biblio_format'] == 'Lens'
        assert body['biblio_capabilities']['refs'] is False
        assert body['biblio_capabilities']['country'] is False
        assert '国家' not in body['columns']
        assert body['biblio_capabilities']['tc'] is True

    def test_a_lens_patent_export_is_refused_with_a_reason(self, client):
        response = client.post(
            '/api/data/upload',
            data={'file': (io.BytesIO((SAMPLES / 'biblio_lens_patent_demo.csv').read_bytes()), 'lens-export.csv')},
            content_type='multipart/form-data',
        )
        assert response.status_code == 400, response.get_json()
        error = response.get_json()['error']
        assert '专利' in error or 'PATENT' in error.upper(), error
        assert 'Jurisdiction' in error, f'the refusal has to name what it saw: {error}'

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


@pytest.mark.serial
def test_sentiment_and_topic_columns_reach_both_overlay_charts(client, app_module):
    """A label column an upstream step wrote becomes a node attribute and a figure.

    The table is an ordinary CSV (an upstream sentiment step writes this shape), the biblio
    node names both columns, and the two views read only what the biblio table emits — so this
    is the whole overlay path through the real executor: aggregate → columns → chart → LaTeX
    figure plus three-line table.
    """
    payload = (
        '题名,年份,关键词,摘要,sentiment,cluster\n'
        't1,2019,甲;乙,甲 乙,positive,1\n'
        't2,2020,甲;乙,甲 乙,negative,1\n'
        't3,2020,乙;丙,乙 丙,neutral,2\n'
        't4,2021,甲;丙,甲 丙,,\n'
    )
    uploaded = client.post(
        '/api/data/upload',
        data={'file': (io.BytesIO(payload.encode('utf-8')), 'labelled.csv')},
        content_type='multipart/form-data',
    ).get_json()
    assert uploaded['columns'] == ['题名', '年份', '关键词', '摘要', 'sentiment', 'cluster'], uploaded
    params = {
        'entity_type': 'keyword',
        'year_column': '年份',
        'abstract_column': '摘要',
        'min_count': 1,
        'cluster': False,
        'burst': False,
        'pruning': 'none',
        'sentiment_column': 'sentiment',
        'topic_column': 'cluster',
        'export_files': False,
    }
    workflow = {
        'nodes': [
            {
                'id': 'node-1',
                'type': 'upload',
                'title': '上传带标签的表',
                'params': {'dataset_id': uploaded['dataset_id'], 'dataset_name': 'labelled.csv', 'row_count': 4},
            },
            {'id': 'node-2', 'type': 'biblio', 'title': '关键词图谱·叠加', 'params': params},
            {
                'id': 'node-3',
                'type': 'visualize',
                'title': '情感叠加图',
                'params': {
                    'chart_type': 'sentiment_overlay',
                    'engine': 'echarts',
                    'title': '情感叠加',
                    'emit_latex': True,
                    'emit_latex_table': True,
                },
            },
            {
                'id': 'node-4',
                'type': 'visualize',
                'title': '话题叠加图',
                'params': {
                    'chart_type': 'topic_overlay',
                    'engine': 'echarts',
                    'title': '话题叠加',
                    'emit_latex': False,
                    'emit_latex_table': False,
                },
            },
        ],
        'connections': [
            {'from': 'node-1', 'to': 'node-2'},
            {'from': 'node-2', 'to': 'node-3'},
            {'from': 'node-2', 'to': 'node-4'},
        ],
        'settings': {'mode': 'serial', 'headless': True, 'max_workers': 1},
    }
    started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'overlay-e2e'})
    assert started.status_code == 200, started.get_json()
    run_id = started.get_json()['run_id']
    assert _wait_for_worker(app_module), 'the execute thread did not finish in time'
    status = client.get('/api/workflow/status').get_json()
    assert status['completed_nodes'] == 4, status['logs']

    rows = app_module._RUN_STORE.load_rows(run_id, 'node-2')
    by_name = {row['节点']: row for row in rows}
    assert {'情感倾向', '情感分布', '主导话题', '话题分布'} <= set(by_name['甲'])
    assert json.loads(by_name['甲']['情感分布']) == {'negative': 1, 'positive': 1}
    assert by_name['甲']['情感倾向'] == 'negative', 'a tie resolves by label, not by row order'
    log_text = ' '.join(status['logs'])
    assert '1/4' in log_text or '1 of 4' in log_text, 'the unlabelled record is reported, not silently dropped'

    sentiment = status['chart_results']['node-3']
    assert sentiment['option']['series'][0]['type'] == 'bar'
    assert len(sentiment['option']['series']) == 3
    assert sentiment['latex_file'] and sentiment['latex_table_file']
    topic = status['chart_results']['node-4']
    assert topic['option']['series'][0]['type'] == 'heatmap'
    assert topic['option']['visualMap']['max'] == 100
    kinds = {record['kind'] for record in app_module._RUN_STORE.files_for_run(run_id)}
    assert {'latex', 'latex_table'} <= kinds


@pytest.mark.serial
def test_a_biblio_cluster_reaches_the_review_step_by_its_default_names(client, app_module, monkeypatch):
    """The claim the whole 簇综述 feature rests on, measured through the real run path: the columns
    a ``biblio`` node writes (聚类 / 聚类标签 / 节点 / 频次 / 首年 / 末年) ARE the columns
    ``cluster_review`` reads when every box in its panel is left blank.

    Only the model is stubbed — the upload, the graph, the clustering and the row ledger are the
    ones that ship. A unit test that hands the step a hand-written frame proves nothing about that
    alignment, and a mis-named default is exactly the bug that would show up as an empty review
    column in a paper rather than as a red test.
    """
    records = _upload(client, 'biblio_cnki_demo.txt')
    workflow = _workflow(records['dataset_id'], '关键词')
    workflow['nodes'].append(
        {
            'id': 'node-4',
            'type': 'analysis',
            'title': '簇综述',
            'operation': 'cluster_review',
            'params': {'operation': 'cluster_review'},
            'x': 480,
            'y': 220,
        }
    )
    workflow['connections'].append({'from': 'node-2', 'to': 'node-4'})

    prompts = []

    class _Client:
        label = 'ollama:stub'

        def chat(self, prompt, max_retries=2):
            prompts.append(prompt)
            return '该簇围绕数字政府与政务服务展开，下一步可能转向数据要素。'

    from nodes.executors import analysis as analysis_plugin

    monkeypatch.setattr(
        analysis_plugin, 'build_llm_run_ctx', lambda node, op, ctx=None: {'client': _Client(), 'cancel_event': None}
    )
    started = client.post(
        '/api/workflow/execute',
        json={
            'workflow': workflow,
            'workflow_name': 'biblio-review',
            'llm': {'provider': 'ollama', 'model': 'qwen3'},
            # Pinned because the fact lines are worded in the run's own language: a worker thread
            # that forgot to set its language would answer in the server default, and this
            # assertion would then be the thing that broke.
            'lang': 'zh',
        },
    )
    assert started.status_code == 200, started.get_json()
    run_id = started.get_json()['run_id']
    assert _wait_for_worker(app_module), 'the execute thread did not finish in time'
    status = client.get('/api/workflow/status').get_json()
    assert status['completed_nodes'] == 4, status['logs']

    graph_rows = app_module._RUN_STORE.load_rows(run_id, 'node-2')
    reviews = app_module._RUN_STORE.load_rows(run_id, 'node-4')
    clusters = {int(row['聚类']) for row in graph_rows if str(row.get('聚类', '')).strip() != ''}
    assert {int(row['聚类']) for row in reviews} == clusters, 'one review per cluster the graph found'
    labels = {str(row['聚类标签']) for row in graph_rows if str(row.get('聚类标签') or '').strip()}
    assert labels and labels <= {str(row['聚类标签']) for row in reviews}
    # The prompt is made of the graph's own numbers, so a paragraph can be traced back to a cell.
    assert prompts, 'the review step asked the model'
    assert any(any(label in prompt for label in labels) for prompt in prompts)
    assert all('簇内节点数' in prompt for prompt in prompts)
    assert all(str(row['簇综述']).strip() for row in reviews)


def _watch_workflow(dataset_id: str, extra: dict) -> dict:
    """Upload → 关键词图谱, with the monitor's project box filled in."""
    params = {
        'entity_type': 'keyword',
        'year_column': '年份',
        'title_column': '题名',
        'abstract_column': '摘要',
        'slice_years': 1,
        'selection': 'top_n',
        'top_n': 50,
        'link_measure': 'cosine',
        'pruning': 'none',
        'cluster': True,
        'label_method': 'llr',
        'burst': False,
        'export_files': False,
        'watch_project': '数字治理监测',
    }
    params.update(extra)
    return {
        'nodes': [
            {
                'id': 'node-1',
                'type': 'upload',
                'title': '上传文献',
                'params': {'dataset_id': dataset_id, 'dataset_name': 'cnki.txt', 'row_count': 36},
                'x': 0,
                'y': 0,
            },
            {'id': 'node-2', 'type': 'biblio', 'title': '关键词图谱', 'params': params, 'x': 240, 'y': 0},
        ],
        'connections': [{'from': 'node-1', 'to': 'node-2'}],
        'settings': {'mode': 'serial', 'headless': True, 'max_workers': 1},
    }


def _execute(client, workflow, name):
    """Run a canvas and wait for it.

    ``lang`` is pinned because the monitor narrates itself in the RUN's language: an assertion on
    console wording that inherits the process default would pass on this box and fail on CI.
    """
    started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': name, 'lang': 'zh'})
    body = started.get_json()
    assert started.status_code == 200 and body.get('run_id'), body
    return body['run_id']


@pytest.mark.serial
def test_a_watched_canvas_files_one_capture_per_run_and_says_so(client, app_module):
    """The monitor's whole point is the SECOND run: the first has nothing to compare with, and the
    second must find the first, report what moved, and leave a file the panel can hand over."""
    from runtime.stores import get_biblio_store

    records = _upload(client, 'biblio_cnki_demo.txt')
    first = _execute(client, _watch_workflow(records['dataset_id'], {}), 'watch-repeat')
    assert _wait_for_worker(app_module)
    assert client.get('/api/workflow/status').get_json()['completed_nodes'] == 2
    # The first run files a capture even though it has nothing to compare with — otherwise a
    # monitor's history would start at its second run and the first week would be missing.
    assert [
        entry
        for entry in app_module._RUN_STORE.files_for_run(first, node_id='node-2')
        if entry['kind'] == 'biblio_watch'
    ]

    biblio = get_biblio_store()
    projects = [p for p in biblio.list_projects() if p['name'] == '数字治理监测']
    assert len(projects) == 1, 'the second run must not create a second project of the same name'
    assert len(biblio.list_snapshots(projects[0]['project_id'])) == 1

    second = _execute(client, _watch_workflow(records['dataset_id'], {}), 'watch-repeat')
    assert _wait_for_worker(app_module)
    status = client.get('/api/workflow/status').get_json()
    assert status['completed_nodes'] == 2, status['logs']
    snapshots = biblio.list_snapshots(projects[0]['project_id'])
    assert len(snapshots) == 2

    logs = '\n'.join(status['logs'])
    assert '[监测]' in logs, status['logs']
    assert '无变化' in logs, 'the same data through the same settings has to be reported as unchanged'
    files = app_module._RUN_STORE.files_for_run(second, node_id='node-2')
    watch_files = [entry for entry in files if entry['kind'] == 'biblio_watch']
    assert len(watch_files) == 1, files
    assert watch_files[0]['name'].endswith('-watch.csv')
    # The panel's own door: it lists a node's artefacts by the ledger's kind filter, so the change
    # table has to be reachable there rather than only on disk.
    page = client.get(f'/api/biblio/table?run_id={second}&node_id=node-2').get_json()
    assert [entry['name'] for entry in page['files']] == [watch_files[0]['name']], page['files']

    rows = app_module._RUN_STORE.load_rows(second, 'node-2')
    assert rows and '节点' in rows[0], 'watching must not change what the node hands downstream'


@pytest.mark.serial
def test_a_narrower_window_is_reported_as_a_parameter_change_not_as_a_vanishing_field(client, app_module):
    """A monitor that blames the field for someone editing the node is worse than no monitor."""
    from runtime.stores import get_biblio_store

    records = _upload(client, 'biblio_cssci_demo.txt')
    _execute(client, _watch_workflow(records['dataset_id'], {'watch_project': '窗口监测'}), 'watch-window')
    assert _wait_for_worker(app_module)
    run_id = _execute(
        client,
        _watch_workflow(records['dataset_id'], {'watch_project': '窗口监测', 'top_n': 6}),
        'watch-window',
    )
    assert _wait_for_worker(app_module)
    status = client.get('/api/workflow/status').get_json()
    assert status['completed_nodes'] == 2, status['logs']
    logs = '\n'.join(status['logs'])
    assert 'top_n' in logs, f'the changed parameter must be named: {status["logs"]}'
    assert '参数' in logs or '监测' in logs, status['logs']
    projects = [p for p in get_biblio_store().list_projects() if p['name'] == '窗口监测']
    assert len(projects) == 1
    assert len(get_biblio_store().list_snapshots(projects[0]['project_id'])) == 2
    assert [
        entry
        for entry in app_module._RUN_STORE.files_for_run(run_id, node_id='node-2')
        if entry['kind'] == 'biblio_watch'
    ]
