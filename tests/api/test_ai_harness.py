"""The Harness seam: legal vocabulary, the working folder, and the workflow round trip.

No browser, no provider, no network. These are the server facts a workflow draft and a command
depend on, and they are the ones a model gets wrong when the prompt is thin.
"""

import os

import pytest

pytestmark = pytest.mark.api


class TestVocabulary:
    def test_every_node_type_is_named_with_its_params(self):
        from ai import vocabulary
        from nodes.catalog import NODE_TYPES

        catalog = {row['type']: row for row in vocabulary.node_catalog()}
        assert set(catalog) == set(NODE_TYPES)
        assert 'operation' in catalog['analysis']['params']
        assert 'chart_type' in catalog['visualize']['params']
        assert catalog['source']['params_from'] == 'capabilities'

    def test_the_prompt_names_every_platform_mode_and_chart(self):
        from ai import vocabulary

        from services.charts.registry import SPECS

        text = vocabulary.prompt_block()
        for row in vocabulary.platform_matrix():
            assert row['platform'] in text
        for spec in SPECS:
            assert spec.key in text
        # A display word the model used to invent is NOT a node type, and the rules say so.
        assert 'analysis（' in text or 'analysis' in text

    def test_the_analysis_catalog_keeps_its_required_columns(self):
        from ai import vocabulary

        rows = {row['operation']: row for row in vocabulary.analysis_catalog()}
        assert rows['groupby_agg']['needs_column'] == ['group_col', 'agg_col']
        assert rows['filter_rows']['allowed']['op']

    def test_the_workflow_schema_is_the_file_shape_the_canvas_loads(self):
        from ai import vocabulary

        schema = vocabulary.workflow_schema()
        assert schema['shape']['nodes'][0]['type'] == '<node type>'
        assert 'connections' in schema['shape']
        assert 'type=' in schema['rules']


class TestDraftValidation:
    def _payload(self):
        return {
            'nodes': [
                {'id': 'n1', 'type': 'upload', 'x': 0, 'y': 0, 'params': {'dataset_id': 'ds1'}},
                {
                    'id': 'n2',
                    'type': 'output',
                    'x': 200,
                    'y': 0,
                    'params': {'operation': 'save', 'format': 'csv', 'filename': 'export.csv'},
                },
            ],
            'connections': [{'from': 'n1', 'to': 'n2'}],
        }

    def test_a_legal_draft_passes_structure_and_the_engine(self):
        from ai import workflow_draft

        report = workflow_draft.validate(self._payload())
        assert report['structural'] == []
        assert report['engine'] == []
        assert report['ok'] is True

    def test_a_display_word_is_refused_by_name(self):
        from ai import workflow_draft

        payload = self._payload()
        payload['nodes'][0]['type'] = '分析'
        report = workflow_draft.validate(payload)
        assert report['ok'] is False
        assert any('分析' in item for item in report['structural'])

    def test_params_that_are_a_sentence_are_refused(self):
        from ai import workflow_draft

        payload = self._payload()
        payload['nodes'][0]['params'] = '去重，按评论内容'
        assert any('params' in item for item in workflow_draft.problems(payload))

    def test_saving_never_overwrites_a_users_workflow(self):
        from ai import workflow_draft

        first = workflow_draft.save(self._payload(), 'AI 流程')
        second = workflow_draft.save(self._payload(), 'AI 流程')
        assert first['name'] == 'AI 流程'
        assert second['name'] != first['name']
        assert os.path.isfile(first['path'])


class TestWorkingFolder:
    def test_a_relative_or_missing_folder_is_refused(self):
        from ai import workspace
        from ai.errors import AIError

        with pytest.raises(AIError) as relative:
            workspace.set_folder('relative/dir')
        assert relative.value.key == 'ai.workspaceNotAbsolute'
        with pytest.raises(AIError) as missing:
            workspace.set_folder(os.path.join(os.getcwd(), 'no-such-folder-xyz'))
        assert missing.value.key == 'ai.workspaceNotFound'

    def test_reading_writing_and_escaping_the_root(self, tmp_path):
        from ai import workspace
        from ai.errors import AIError

        workspace.set_folder(str(tmp_path))
        try:
            written = workspace.write_text('note.txt', 'hello')
            assert written['bytes'] == 5
            assert workspace.read_text('note.txt')['content'] == 'hello'
            listed = workspace.list_dir('')
            assert any(row['name'] == 'note.txt' for row in listed['entries'])
            with pytest.raises(AIError) as escape:
                workspace.read_text('../outside.txt')
            assert escape.value.key == 'ai.workspaceOutside'
        finally:
            workspace.set_folder('')

    def test_a_command_is_not_a_shell(self, tmp_path):
        from ai import workspace
        from ai.errors import AIError

        workspace.set_folder(str(tmp_path))
        try:
            with pytest.raises(AIError) as shell:
                workspace.run_command('echo hi > out.txt')
            assert shell.value.key == 'ai.cmdShellRefused'
            with pytest.raises(AIError) as denied:
                workspace.run_command('format c:')
            assert denied.value.key == 'ai.cmdNotAllowed'
        finally:
            workspace.set_folder('')

    def test_a_csv_becomes_a_dataset_with_the_upload_parsers(self, tmp_path):
        from ai import workspace

        (tmp_path / 'rows.csv').write_text('名称,数量\n甲,2\n乙,3\n', encoding='utf-8')
        workspace.set_folder(str(tmp_path))
        try:
            result = workspace.import_table('rows.csv')
            assert result['rows'] == 2
            assert result['columns'] == ['名称', '数量']
            assert result['dataset_id']
        finally:
            workspace.set_folder('')


class TestHarnessTools:
    def test_the_new_verbs_are_offered_and_gated(self):
        from ai import tools

        names = {tool['name'] for tool in tools.schemas(allow_files=True)}
        assert {'workspace_info', 'workspace_read', 'run_cmd', 'app_errors', 'apply_workflow'} <= names
        without = {tool['name'] for tool in tools.schemas(allow_files=False)}
        assert 'run_cmd' not in without
        assert tools.TOOLS['apply_workflow'].control is True


class TestWorkspaceApi:
    def test_bootstrap_carries_the_workspace_state(self, client):
        body = client.get('/api/ai/bootstrap').get_json()
        assert body['ok'] is True
        assert 'workspace' in body
        assert 'folder' in body['workspace']

    def test_setting_a_folder_round_trips(self, client, tmp_path):
        response = client.post('/api/ai/workspace', json={'path': str(tmp_path)})
        body = response.get_json()
        assert body['ok'] is True
        assert body['workspace']['folder'] == str(tmp_path)
        listing = client.get('/api/ai/workspace/browse?path=' + str(tmp_path)).get_json()
        assert listing['ok'] is True
        assert listing['path'] == str(tmp_path)
        client.post('/api/ai/workspace', json={'path': ''})

    def test_a_bad_path_answers_in_the_envelope(self, client):
        body = client.post('/api/ai/workspace', json={'path': 'relative'}).get_json()
        assert body['ok'] is False
        assert body['key'] == 'ai.workspaceNotAbsolute'

    def test_the_validate_endpoint_reports_both_kinds_of_problem(self, client):
        payload = {'nodes': [{'id': 'n1', 'type': '分析', 'x': 0, 'y': 0, 'params': {}}]}
        body = client.post('/api/ai/workflow/validate', json={'workflow': payload}).get_json()
        assert body['ok'] is True
        assert body['report']['ok'] is False
        assert body['report']['structural']

    def test_an_unknown_draft_shape_is_still_json(self, client):
        response = client.post('/api/ai/workflow/validate', json={'workflow': 'nope'})
        body = response.get_json()
        assert response.status_code == 200
        assert body['ok'] is True
        assert body['report']['ok'] is False
