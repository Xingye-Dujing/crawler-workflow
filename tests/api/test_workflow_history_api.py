"""HTTP contract for canvas history: the panel must never assemble a restore itself."""

import json

import pytest

from services.workflow_history import WorkflowHistoryStore

pytestmark = pytest.mark.api

CANVAS = {
    'nodes': [
        {'id': 'node-0', 'type': 'name', 'title': 'N', 'params': {'workflow_name': '日报'}},
        {'id': 'node-1', 'type': 'process', 'title': 'P', 'params': {'operation': 'drop_null'}},
    ],
    'connections': [{'from': 'node-0', 'to': 'node-1'}],
    'settings': {'mode': 'serial', 'view': {'zoom': 1.25}, 'disabledTypes': []},
}


def _save(client, label='状态一', name='日报', workflow=None):
    response = client.post(
        '/api/workflow/history/save',
        json={'label': label, 'workflow_name': name, 'workflow': workflow if workflow is not None else CANVAS},
    )
    return response


class TestSnapshotsApi:
    def test_save_list_get_and_delete(self, client):
        saved = _save(client)
        assert saved.status_code == 200
        header = saved.get_json()['snapshot']
        assert header['nodes'] == 2 and header['connections'] == 1
        assert header['workflow_name'] == '日报'

        listed = client.get('/api/workflow/history').get_json()
        assert listed['ok'] is True
        assert listed['max'] == 100
        assert listed['snapshots'][0]['id'] == header['id']
        assert 'workflow' not in listed['snapshots'][0]

        full = client.get('/api/workflow/history/get?id=' + header['id']).get_json()
        assert full['ok'] is True
        assert full['snapshot']['workflow'] == CANVAS
        assert full['snapshot']['workflow']['settings']['view']['zoom'] == 1.25

        deleted = client.post('/api/workflow/history/delete', json={'id': header['id']}).get_json()
        assert deleted == {'ok': True, 'deleted': True, 'baselines_cleared': []}
        assert client.get('/api/workflow/history').get_json()['snapshots'] == []

    def test_rename_updates_the_label_and_keeps_the_payload(self, client):
        header = _save(client).get_json()['snapshot']
        response = client.post('/api/workflow/history/rename', json={'id': header['id'], 'label': '重排前'})
        assert response.status_code == 200
        renamed = response.get_json()['snapshot']
        assert renamed['label'] == '重排前'
        assert renamed['created_at'] == header['created_at']
        assert client.get('/api/workflow/history').get_json()['snapshots'][0]['label'] == '重排前'
        assert client.get('/api/workflow/history/get?id=' + header['id']).get_json()['snapshot']['workflow'] == CANVAS

    def test_rename_refuses_a_missing_snapshot_and_bad_types(self, client):
        missing = client.post('/api/workflow/history/rename', json={'id': 'nope', 'label': 'x'})
        assert missing.status_code == 404
        assert 'nope' in missing.get_json()['error']
        for body in (
            {'id': 3, 'label': 'x'},
            {'id': 'nope', 'label': 3},
            {'label': 'x'},
            {},
        ):
            response = client.post('/api/workflow/history/rename', json=body)
            assert response.status_code == 400, body
        saved = _save(client).get_json()['snapshot']
        too_long = client.post('/api/workflow/history/rename', json={'id': saved['id'], 'label': 'x' * 81})
        assert too_long.status_code == 400
        assert '80' in too_long.get_json()['error']

    def test_a_missing_snapshot_is_a_named_404(self, client):
        response = client.get('/api/workflow/history/get?id=nope')
        assert response.status_code == 404
        body = response.get_json()
        assert body['ok'] is False and 'nope' in body['error']

    def test_a_payload_without_nodes_is_a_400(self, client):
        for bad in ({}, [], 'x', {'nodes': 'nope'}):
            response = _save(client, workflow=bad)
            assert response.status_code == 400, bad

    def test_label_and_workflow_name_must_be_strings(self, client):
        for field in ('label', 'workflow_name'):
            body = {'label': 'x', 'workflow_name': 'wf', 'workflow': CANVAS}
            body[field] = 7
            response = client.post('/api/workflow/history/save', json=body)
            assert response.status_code == 400
            assert field in response.get_json()['error']

    def test_a_full_history_is_a_409_and_keeps_the_earlier_rows(self, client, monkeypatch):
        monkeypatch.setattr(WorkflowHistoryStore, 'MAX_SNAPSHOTS', 2)
        first = _save(client, '一').get_json()['snapshot']
        second = _save(client, '二').get_json()['snapshot']
        response = _save(client, '三')
        assert response.status_code == 409
        assert '2' in response.get_json()['error']
        assert [row['id'] for row in client.get('/api/workflow/history').get_json()['snapshots']] == [
            second['id'],
            first['id'],
        ]

    def test_delete_is_idempotent_but_still_clears_a_baseline_once(self, client):
        header = _save(client).get_json()['snapshot']
        client.post(
            '/api/workflow/history/layout',
            json={'workflow_name': '日报', 'strategy': 'baseline', 'snapshot_id': header['id']},
        )
        first = client.post('/api/workflow/history/delete', json={'id': header['id']}).get_json()
        second = client.post('/api/workflow/history/delete', json={'id': header['id']}).get_json()
        assert first['deleted'] is True and first['baselines_cleared'] == ['日报']
        assert second['deleted'] is False and second['baselines_cleared'] == []
        layout = client.get('/api/workflow/history/layout?workflow=日报').get_json()['layout']
        assert layout['strategy'] == 'algorithm'


class TestLayoutApi:
    def test_default_layout_is_algorithm(self, client):
        body = client.get('/api/workflow/history/layout?workflow=日报').get_json()
        assert body['ok'] is True
        assert body['layout']['strategy'] == 'algorithm'
        assert body['layout']['snapshot'] is None

    def test_setting_and_reading_a_baseline(self, client):
        header = _save(client, '排布基准').get_json()['snapshot']
        response = client.post(
            '/api/workflow/history/layout',
            json={'workflow_name': '日报', 'strategy': 'baseline', 'snapshot_id': header['id']},
        )
        assert response.status_code == 200
        layout = response.get_json()['layout']
        assert layout['strategy'] == 'baseline'
        assert layout['snapshot']['label'] == '排布基准'
        assert client.get('/api/workflow/history/layout?workflow=日报').get_json()['layout'] == layout

    def test_switching_back_to_algorithm_keeps_the_snapshot_row(self, client):
        header = _save(client).get_json()['snapshot']
        client.post(
            '/api/workflow/history/layout',
            json={'workflow_name': 'wf', 'strategy': 'baseline', 'snapshot_id': header['id']},
        )
        body = client.post(
            '/api/workflow/history/layout', json={'workflow_name': 'wf', 'strategy': 'algorithm'}
        ).get_json()
        assert body['layout']['strategy'] == 'algorithm'
        assert body['layout']['snapshot'] is None
        assert client.get('/api/workflow/history/get?id=' + header['id']).status_code == 200

    def test_refusals_are_named(self, client):
        header = _save(client).get_json()['snapshot']
        cases = [
            {'workflow_name': '', 'strategy': 'algorithm'},
            {'workflow_name': 'wf', 'strategy': 'baseline'},
            {'workflow_name': 'wf', 'strategy': 'baseline', 'snapshot_id': 'missing'},
            {'workflow_name': 'wf', 'strategy': 'sideways'},
            {'workflow_name': 7, 'strategy': 'algorithm'},
            {'workflow_name': 'wf', 'strategy': 7},
            {'workflow_name': 'wf', 'strategy': 'algorithm', 'snapshot_id': 7},
        ]
        for body in cases:
            response = client.post('/api/workflow/history/layout', json=body)
            assert response.status_code == 400, body
            assert response.get_json()['error'], body
        # The valid baseline still exists; none of the refusals wrote a row.
        assert client.get('/api/workflow/history/get?id=' + header['id']).status_code == 200

    def test_the_list_renders_chinese_payloads_as_json(self, client):
        _save(client, '中文快照', '工作流')
        listed = client.get('/api/workflow/history').get_json()
        text = json.dumps(listed, ensure_ascii=False)
        assert '中文快照' in text and '工作流' in text

    def test_renaming_a_workflow_carries_its_baseline_and_deleting_it_drops_it(self, client):
        saved_workflow = client.post('/api/workflow/save', json={'name': 'old', 'workflow': CANVAS})
        assert saved_workflow.status_code == 200
        header = _save(client, '基准', 'old').get_json()['snapshot']
        client.post(
            '/api/workflow/history/layout',
            json={'workflow_name': 'old', 'strategy': 'baseline', 'snapshot_id': header['id']},
        )
        renamed = client.post('/api/workflow/rename', json={'name': 'old', 'new_name': 'new'})
        assert renamed.status_code == 200
        assert client.get('/api/workflow/history/layout?workflow=new').get_json()['layout']['strategy'] == 'baseline'
        assert client.get('/api/workflow/history/layout?workflow=old').get_json()['layout']['strategy'] == 'algorithm'
        assert client.post('/api/workflow/delete', json={'name': 'new'}).status_code == 200
        assert client.get('/api/workflow/history/layout?workflow=new').get_json()['layout']['strategy'] == 'algorithm'
