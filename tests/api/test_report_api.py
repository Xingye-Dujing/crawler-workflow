"""Tests for the report endpoints: /api/report/generate and /api/report/view.

The generate route has two data sources (the run this page is holding, and a
stored run) and the view route is the *only* door through which an HTML file in
the export folder can reach a browser — a door that used to be shut for a good
reason (``.html`` is refused by the download route). So the interesting
assertions here are about which names resolve, what policy the response carries,
and that a report never fails because a paragraph of AI prose failed.
"""

import pytest

pytestmark = pytest.mark.api

ROWS = [
    {'标题': '三亚', '正文': '张先生在海边游泳', 'emotion': 'Joy'},
    {'标题': '海口', '正文': '李女士在开会', 'emotion': 'Anger'},
]


def _stored_run(app_module, run_id='run-rep-1', workflow_name='stored-wf'):
    """One finished run with two nodes' tables, written straight into the store.

    Going through /api/workflow/execute to obtain a run id would test the
    executor again; what is under test here is reading a *stored* run back.
    """
    from services.run_store import NODE_DONE, RUN_COMPLETED

    store = app_module.get_run_store()
    store.start_run(run_id, workflow_name, 'fp-1', node_total=2)
    store.begin_node(run_id, 'node-1', 'source', title='数据源')
    store.append_rows(run_id, 'node-1', ROWS)
    store.finish_node(run_id, 'node-1', NODE_DONE)
    store.begin_node(run_id, 'node-2', 'output', title='输出')
    store.finish_node(run_id, 'node-2', NODE_DONE)
    store.finish_run(run_id, RUN_COMPLETED)
    return store


class TestGenerate:
    def test_a_server_that_has_never_run_says_so(self, client):
        response = client.post('/api/report/generate', json={})
        assert response.status_code == 400
        assert 'nothing to report' in response.get_json()['error']

    def test_the_run_this_page_holds_becomes_a_file(self, client, app_module, data_root):
        app_module.execution_state['results'] = {'node-1': ROWS, 'node-2': []}
        app_module.execution_state['workflow_name'] = 'in-memory-wf'
        body = client.post(
            '/api/report/generate',
            json={'nodes': [{'id': 'node-1', 'title': '数据源 #node-1'}, {'id': 'node-2', 'title': '输出'}]},
        ).get_json()
        assert body['ok'] is True
        assert body['name'].startswith('report-')
        assert body['name'].endswith('.html')
        written = (data_root / 'data' / 'exports' / body['name']).read_text(encoding='utf-8')
        # Both tables are in it, and the empty one says it is empty rather than
        # vanishing: 'nothing here' and 'I forgot to look' must not read alike.
        assert '张先生在海边游泳' in written
        assert '输出' in written
        assert 'in-memory-wf' in written

    def test_a_report_shows_up_as_a_report_not_as_a_download(self, client, app_module):
        app_module.execution_state['results'] = {'node-1': ROWS}
        name = client.post('/api/report/generate', json={}).get_json()['name']
        rows = client.get('/api/exports/list').get_json()['exports']
        entry = next(row for row in rows if row['name'] == name)
        assert entry['kind'] == 'report'
        # The panel's own rule: .html is listed but never handed over as a file.
        assert entry['downloadable'] is False

    def test_a_stored_run_is_read_back_out_of_the_store(self, client, app_module):
        _stored_run(app_module)
        body = client.post('/api/report/generate', json={'run_id': 'run-rep-1'}).get_json()
        assert body['ok'] is True
        # The store carries the node titles, so the report names its tables the
        # way the run did ('数据源'), not by bare node ids.
        assert body['name'].startswith('report-stored')
        text = _report_text(client, app_module, body['name'])
        assert '张先生在海边游泳' in text, 'the stored rows never reached the document'
        assert '数据源' in text and '输出' in text
        assert 'run-rep-1' in text

    def test_an_unknown_run_is_not_found_rather_than_empty(self, client, app_module):
        _stored_run(app_module)
        app_module.execution_state['results'] = {'node-1': ROWS}
        response = client.post('/api/report/generate', json={'run_id': 'never-ran'})
        assert response.status_code == 404
        assert 'never-ran' in response.get_json()['error']

    def test_a_run_that_stored_nothing_refuses(self, client, app_module):
        from services.run_store import NODE_DONE, RUN_COMPLETED

        store = app_module.get_run_store()
        store.start_run('run-void', 'void-wf', 'fp', node_total=1)
        store.begin_node('run-void', 'node-1', 'source', title='数据源')
        store.finish_node('run-void', 'node-1', NODE_DONE)
        store.finish_run('run-void', RUN_COMPLETED)
        response = client.post('/api/report/generate', json={'run_id': 'run-void'})
        assert response.status_code == 400

    @pytest.mark.parametrize(
        'payload, field',
        [
            ({'title': 5}, 'title'),
            ({'include_conclusion': True, 'llm': 'ollama'}, 'llm'),
        ],
    )
    def test_a_wrongly_typed_field_is_a_400_named_by_field(self, client, app_module, payload, field):
        app_module.execution_state['results'] = {'node-1': ROWS}
        response = client.post('/api/report/generate', json=payload)
        assert response.status_code == 400
        assert field in response.get_json()['error']

    def test_an_unused_settings_blob_is_not_a_reason_to_refuse(self, client, app_module):
        # The frontend always sends its AI settings; a report that does not ask
        # the model must not be refused over a field it will never read.
        app_module.execution_state['results'] = {'node-1': ROWS}
        assert client.post('/api/report/generate', json={'llm': 'ollama'}).status_code == 200


class TestConclusion:
    def test_the_model_paragraph_lands_in_the_document(self, client, app_module, monkeypatch):
        app_module.execution_state['results'] = {'node-1': ROWS}
        asked = {}

        def fake_chat(self, prompt, max_retries=2):
            asked['prompt'] = prompt
            return '数据以正面情绪为主。\n\n机构名未出现。'

        monkeypatch.setattr(app_module.LLMClient, 'chat', fake_chat)
        body = client.post(
            '/api/report/generate',
            json={'include_conclusion': True, 'llm': {'provider': 'ollama', 'model': 'm'}},
        ).get_json()
        assert '数据以正面情绪为主' in _report_text(client, app_module, body['name'])
        # The prompt is built from the counts, not from the crawled sentences.
        assert '张先生在海边游泳' not in asked['prompt']
        assert '2 rows' in asked['prompt']

    def test_the_document_speaks_the_language_it_was_asked_in(self, client, app_module):
        app_module.execution_state['results'] = {'node-1': ROWS}
        english = client.post('/api/report/generate', json={'title': 'lang'}).get_json()['name']
        chinese = client.post('/api/report/generate', json={'title': 'lang'}, headers={'X-Lang': 'zh'}).get_json()[
            'name'
        ]
        assert 'Tables' in _report_text(client, app_module, english)
        assert '数据表' in _report_text(client, app_module, chinese)

    def test_a_failing_conclusion_costs_a_paragraph_not_the_report(self, client, app_module, monkeypatch):
        app_module.execution_state['results'] = {'node-1': ROWS}

        def boom(self, prompt, max_retries=2):
            raise RuntimeError('daemon down')

        monkeypatch.setattr(app_module.LLMClient, 'chat', boom)
        response = client.post('/api/report/generate', json={'include_conclusion': True})
        assert response.status_code == 200
        body = response.get_json()
        text = _report_text(client, app_module, body['name'])
        assert 'Conclusion' not in text
        assert '张先生在海边游泳' in text

    def test_no_conclusion_is_asked_for_by_default(self, client, app_module, monkeypatch):
        app_module.execution_state['results'] = {'node-1': ROWS}

        def never(self, prompt, max_retries=2):
            raise AssertionError('the report asked a model it was not told to ask')

        monkeypatch.setattr(app_module.LLMClient, 'chat', never)
        assert client.post('/api/report/generate', json={}).status_code == 200


class TestView:
    def test_a_report_is_served_with_script_forbidden(self, client, app_module):
        app_module.execution_state['results'] = {'node-1': ROWS}
        name = client.post('/api/report/generate', json={}).get_json()['name']
        response = client.get(f'/api/report/view?name={name}')
        assert response.status_code == 200
        assert response.mimetype == 'text/html'
        policy = response.headers['Content-Security-Policy']
        assert 'sandbox' in policy, 'a crawled document must not be able to run'
        assert 'script-src' not in policy and 'allow-scripts' not in policy
        assert response.headers['X-Content-Type-Options'] == 'nosniff'
        assert response.headers['Content-Disposition'].startswith('inline')
        assert b'<script' not in response.data

    def test_a_report_named_in_chinese_is_served_whole(self, client, app_module):
        """A user types a Chinese title, so this is the normal case, not an edge.

        The disposition header carries that name. Written by hand it holds
        characters a header may not, and Werkzeug gave up on the response
        halfway — the browser sat waiting for a document that never arrived.
        Handing the name to ``send_file`` is what makes it encode properly.
        """
        app_module.execution_state['results'] = {'node-1': ROWS}
        name = client.post('/api/report/generate', json={'title': '季度报告'}).get_json()['name']
        assert not name.isascii(), 'the fixture stopped testing what it was written for'
        response = client.get('/api/report/view', query_string={'name': name})
        assert response.status_code == 200
        assert len(response.data) > 500, 'a truncated body reads as a broken page'
        disposition = response.headers['Content-Disposition']
        assert disposition.startswith('inline')
        assert "filename*=UTF-8''" in disposition

    @pytest.mark.parametrize(
        'name',
        [
            'notes.html',
            'report-x.txt',
            '../../backend/config.py',
            'report-',
            '',
            'data/results.csv',
        ],
    )
    def test_only_a_generated_report_resolves(self, client, app_module, name):
        app_module.execution_state['results'] = {'node-1': ROWS}
        client.post('/api/report/generate', json={'title': 'ok'})
        response = client.get('/api/report/view', query_string={'name': name})
        assert response.status_code == 404

    def test_a_report_that_was_deleted_is_not_found(self, client, app_module):
        app_module.execution_state['results'] = {'node-1': ROWS}
        name = client.post('/api/report/generate', json={}).get_json()['name']
        assert client.post('/api/exports/delete', json={'name': name}).get_json()['ok'] is True
        assert client.get(f'/api/report/view?name={name}').status_code == 404


def _report_text(client, app_module, name: str) -> str:
    """The report body, read back through the route that is allowed to serve it."""
    response = client.get(f'/api/report/view?name={name}')
    assert response.status_code == 200
    return response.get_data(as_text=True)
