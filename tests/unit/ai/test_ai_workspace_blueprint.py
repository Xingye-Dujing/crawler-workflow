"""The framework-backed surface answers on its own blueprint, beside the old /api/ai.

A turn is durable: `/chat` creates it, `/turns/<id>/events` replays or follows it, and commands are
data. This test drives a bare Flask app so the migration surface is proven without touching the old
routes (parity keeps both until the switch is removed).
"""

from __future__ import annotations

import pytest
from agent_workspace import ChatRequest
from ai_host.manager import WorkspaceManager
from api.ai_workspace import create_blueprint
from flask import Flask

pytestmark = pytest.mark.unit


@pytest.fixture
def manager(tmp_path):
    manager = WorkspaceManager(root=tmp_path / 'ai')
    workspace = manager.workspace('default')
    workspace.settings.set('chat.default_provider', 'complete')
    yield manager
    manager.close()


@pytest.fixture
def client(manager):
    app = Flask(__name__)
    app.register_blueprint(create_blueprint(manager))
    return app.test_client()


def _chat(client, text='hello', **payload):
    return client.post('/api/ai/ws/chat', json={'text': text, 'stream': False, **payload})


class TestTheSurface:
    def test_chat_returns_a_turn_that_is_durable_and_replayable(self, client):
        response = _chat(client, 'hello')
        assert response.status_code == 200
        body = response.get_json()
        assert body['ok'] is True and body['text']
        turn_id = next(item['turn_id'] for item in body['events'] if item['type'] == 'meta')
        turn = client.get(f'/api/ai/ws/turns/{turn_id}').get_json()
        assert turn['ok'] is True and turn['turn']['state'] == 'settled'
        replay = client.get(f'/api/ai/ws/turns/{turn_id}/events', query_string={'stream': 0})
        assert [item['seq'] for item in replay.get_json()['events']] == list(range(1, len(body['events']) + 1))

    def test_a_turn_can_be_reattached_after_the_client_stops(self, client, manager):
        request = ChatRequest(text='hello', provider='complete')
        stream = manager.workspace('default').ask(request)
        first = next(stream)
        stream.close()
        turn_id = first['turn_id']
        for _ in range(100):
            if manager.workspace('default').turn(turn_id)['state'] == 'settled':
                break
            import time

            time.sleep(0.02)
        replay = client.get(f'/api/ai/ws/turns/{turn_id}/events', query_string={'stream': 0}).get_json()
        assert replay['events'][-1]['type'] == 'done'

    def test_commands_and_the_stop_steer_verbs_answer(self, client):
        body = _chat(client, 'hello').get_json()
        conversation_id = next(item['conversation_id'] for item in body['events'] if item['type'] == 'meta')
        status = client.post('/api/ai/ws/command', json={'name': 'status', 'conversation_id': conversation_id})
        assert status.get_json()['result']['turn']['state'] == 'settled'
        assert client.post('/api/ai/ws/stop', json={'conversation_id': conversation_id}).get_json()['ok'] is False
        steer = client.post('/api/ai/ws/steer', json={'conversation_id': conversation_id, 'text': 'x'})
        assert steer.get_json()['ok'] is False
        pending = client.get('/api/ai/ws/pending', query_string={'conversation_id': conversation_id}).get_json()
        assert pending['pending'] == []

    def test_auto_reaches_the_frameworks_router_and_says_what_it_chose(self, client):
        """The panel's default is auto; the turn must record the skill it picked, not answer as
        general with no trace of the decision."""
        body = _chat(client, '怎么用这个项目开始？', skill='auto').get_json()
        meta = next(item for item in body['events'] if item['type'] == 'meta')
        assert meta['skill'] == 'project'
        assert meta['context']['skill'] == {'requested': 'auto', 'chosen': 'project'}

    def test_an_unknown_turn_is_named(self, client):
        missing = client.get('/api/ai/ws/turns/turn_nope')
        assert missing.status_code == 404
        assert missing.get_json()['key'] == 'turn.unknown'

    def test_a_text_attachment_is_extracted_host_side(self, client):
        import base64

        data = base64.b64encode(b'the attached words').decode()
        body = _chat(client, 'read it', attachments=[{'name': 'a.txt', 'data': data}]).get_json()
        assert body['ok'] is True
        assert 'the attached words' in body['text']

    def test_the_generic_surface_answers(self, client):
        assert client.get('/api/ai/ws/health').get_json()['ok'] is True
        assert client.get('/api/ai/ws/skills').get_json()['skills']
        assert client.get('/api/ai/ws/files').get_json()['files'] == []
        assert client.get('/api/ai/ws/monitors').get_json()['monitors'] == []
        assert client.get('/api/ai/ws/python/status').get_json()['ok'] is True
        assert client.get('/api/ai/ws/references', query_string={'q': 'x'}).get_json()['ok'] is True
        assert isinstance(client.post('/api/ai/ws/context', json={'query': 'x'}).get_json(), dict)
        assert client.get('/api/ai/ws/plugins').get_json()['ok'] is True
        assert client.get('/api/ai/ws/bootstrap').get_json()['ok'] is not False
        body = client.post('/api/ai/ws/command', json={'name': 'init'}).get_json()
        assert body['result']['tools'] > 0
        assert body['result']['skills'] > 0

    def test_a_known_host_command_runs_through_the_same_surface(self, client):
        body = client.post('/api/ai/ws/command', json={'name': 'init'}).get_json()
        assert body['result']['tools'] > 0
        assert body['result']['skills'] > 0

    def test_provider_models_balance_and_test(self, client):
        assert client.get('/api/ai/ws/providers/complete/models').get_json()['ok'] is True
        balance = client.get('/api/ai/ws/providers/complete/balance').get_json()
        assert balance['ok'] is True and balance['supported'] is False
        tested = client.post('/api/ai/ws/providers/complete/test', json={'model': ''}).get_json()
        assert tested['ok'] is True and 'latency_ms' in tested

    def test_conversation_detail_patch_and_context(self, client):
        body = _chat(client, 'hello').get_json()
        conversation_id = next(item['conversation_id'] for item in body['events'] if item['type'] == 'meta')
        detail = client.get(f'/api/ai/ws/conversations/{conversation_id}').get_json()
        assert detail['ok'] is True and detail['messages']
        renamed = client.patch(f'/api/ai/ws/conversations/{conversation_id}', json={'title': 'Renamed'})
        assert renamed.get_json()['conversation']['title'] == 'Renamed'
        assert isinstance(
            client.post(f'/api/ai/ws/conversations/{conversation_id}/context', json={'query': 'x'}).get_json(), dict
        )
        skill = client.get('/api/ai/ws/skills/general').get_json()
        assert skill['ok'] is True and skill['skill']['id'] == 'general'

    def test_host_domain_endpoints_smoke(self, client):
        workspace = client.get('/api/ai/ws/workspace').get_json()
        assert workspace['ok'] is True and 'workspace' in workspace
        catalog = client.get('/api/ai/ws/monitors/catalog').get_json()
        assert catalog['ok'] is True and catalog['catalog']['events']
        report = client.post('/api/ai/ws/workflow/validate', json={'nodes': [], 'connections': []}).get_json()
        assert report['ok'] is True and 'report' in report
        unknown = client.post('/api/ai/ws/artifacts/preview', json={'kind': 'moonbase', 'payload': {}})
        assert unknown.status_code == 400 and unknown.get_json()['key'] == 'ai.preview.unknown'
        chart = client.post('/api/ai/ws/chart/preview', json={'spec': {'chart_type': 'nope'}})
        assert chart.status_code == 400 and chart.get_json()['key'] == 'ai.chartSpecRefused'
        rerun = client.post('/api/ai/ws/rerun', json={'conversation_id': 'nope', 'run_id': 'r', 'node_id': 'n'})
        assert rerun.status_code == 404

    def test_a_uploaded_file_can_be_attached_by_id(self, client):
        import io

        conversation = client.post('/api/ai/ws/conversations', json={'title': 'Files'}).get_json()
        conversation_id = conversation['conversation']['id']
        response = client.post(
            '/api/ai/ws/files',
            data={'file': (io.BytesIO(b'hello from the document'), 'note.txt'), 'conversation_id': conversation_id},
            content_type='multipart/form-data',
        ).get_json()
        assert response['ok'] is True
        attachment = response['attachment']
        body = _chat(client, 'read it', conversation_id=conversation_id, attachments=[attachment['id']]).get_json()
        assert body['ok'] is True
        assert 'hello from the document' in body['text']
        listed = client.get(f'/api/ai/ws/conversations/{conversation_id}/files').get_json()['attachments']
        assert [row['id'] for row in listed] == [attachment['id']]

    def test_codebooks_and_plugin_surface(self, client):
        assert client.get('/api/ai/ws/codebooks').get_json()['ok'] is True
        missing = client.get('/api/ai/ws/codebooks/nope')
        assert missing.status_code == 404
        assert client.get('/api/ai/ws/plugins').get_json()['ok'] is True

    def test_the_wire_names_are_the_frontend_ones(self, client):
        """The host maps canonical engine events to the names the existing panel parses."""
        body = _chat(client, 'hello').get_json()
        types = [item['type'] for item in body['events']]
        assert 'text' in types
        assert 'text_delta' not in types

    def test_a_node_trace_is_listed_and_openable(self, client, manager, monkeypatch):
        import services.llm_trace as trace

        monkeypatch.setattr(trace, '_MANAGER', manager)
        run = 'run_trace_case'
        _client, conversation_id = trace.start_node_trace(run, 'n1', 'clean', None, provider='local BERT')
        listed = client.get(f'/api/ai/ws/traces/{run}').get_json()['conversations']
        assert [row['id'] for row in listed] == [conversation_id]
        detail = client.get(f'/api/ai/ws/conversations/{conversation_id}').get_json()
        assert detail['conversation']['skill'] == 'node_trace'
        apply = client.post(f'/api/ai/ws/traces/{conversation_id}/apply', json={'result': {}})
        assert apply.status_code == 400

    def test_conversations_memories_artifacts_settings_and_usage(self, client):
        created = client.post('/api/ai/ws/conversations', json={'title': 'T'}).get_json()
        conversation_id = created['conversation']['id']
        listed = client.get('/api/ai/ws/conversations').get_json()['conversations']
        assert any(row['id'] == conversation_id for row in listed)

        memory = client.post('/api/ai/ws/memories', json={'text': 'remember this'}).get_json()
        assert memory['ok'] is True
        assert any(row['text'] == 'remember this' for row in client.get('/api/ai/ws/memories').get_json()['memories'])
        assert client.delete(f'/api/ai/ws/memories/{memory["memory"]["id"]}').get_json()['ok'] is True

        assert client.get('/api/ai/ws/artifacts').get_json()['artifacts'] == []
        settings = client.get('/api/ai/ws/settings').get_json()
        assert settings['ok'] is True and settings['schema']
        assert client.get('/api/ai/ws/usage').get_json()['ok'] is True
        assert client.get('/api/ai/ws/bootstrap').get_json()['ok'] is not False
        assert client.delete(f'/api/ai/ws/conversations/{conversation_id}').get_json()['ok'] is True
