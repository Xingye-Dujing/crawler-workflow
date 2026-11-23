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

    def test_an_unknown_turn_is_named(self, client):
        missing = client.get('/api/ai/ws/turns/turn_nope')
        assert missing.status_code == 404
        assert missing.get_json()['key'] == 'turn.unknown'
