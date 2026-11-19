"""Confirmed memories: the store, the API, the context they enter, and the artifact that proposes one.

A memory is the one thing the assistant carries into every later turn without being asked, so its
rules are deliberately narrow: the user confirms it, a duplicate is not an error, and both bounds
(a long entry, a full store) refuse BY NAME instead of truncating or evicting silently.
"""

import pytest

pytestmark = pytest.mark.api


@pytest.fixture(autouse=True)
def clean_memories():
    """One isolated data root is shared by the file, so every case starts and ends empty."""
    from ai import store

    def wipe():
        for row in store.list_memories():
            store.delete_memory(row['id'])

    wipe()
    yield
    wipe()


def test_memories_are_listed_added_and_deleted(client):
    listing = client.get('/api/ai/memories').get_json()
    assert listing['ok'] is True
    assert listing['memories'] == []
    from ai import store

    assert listing['limit'] == store.MAX_MEMORIES

    saved = client.post('/api/ai/memories', json={'text': '  这个项目的微博采集用默认账号  '}).get_json()
    assert saved['ok'] is True, saved
    assert saved['duplicate'] is False
    assert saved['memory']['text'] == '这个项目的微博采集用默认账号'

    rows = client.get('/api/ai/memories').get_json()['memories']
    assert [row['text'] for row in rows] == ['这个项目的微博采集用默认账号']

    assert client.delete('/api/ai/memories/' + saved['memory']['id']).get_json()['deleted'] is True
    assert client.get('/api/ai/memories').get_json()['memories'] == []


def test_the_same_fact_twice_is_the_same_row(client):
    first = client.post('/api/ai/memories', json={'text': 'Use  the default account'}).get_json()
    second = client.post('/api/ai/memories', json={'text': ' use the default ACCOUNT '}).get_json()
    assert second['ok'] is True
    assert second['duplicate'] is True
    assert second['memory']['id'] == first['memory']['id']
    assert len(client.get('/api/ai/memories').get_json()['memories']) == 1


def test_an_empty_memory_is_refused_by_name(client):
    data = client.post('/api/ai/memories', json={'text': '   '}).get_json()
    assert data['ok'] is False
    assert data['key'] == 'ai.apiNoText'


def test_a_memory_too_long_is_refused_not_cut(client):
    from ai import store

    data = client.post('/api/ai/memories', json={'text': 'x' * (store.MAX_MEMORY_CHARS + 1)}).get_json()
    assert data['ok'] is False
    assert data['key'] == 'ai.memoryTooLong'
    assert client.get('/api/ai/memories').get_json()['memories'] == []


def test_a_full_store_refuses_instead_of_evicting(client, monkeypatch):
    from ai import store

    monkeypatch.setattr(store, 'MAX_MEMORIES', 2)
    assert client.post('/api/ai/memories', json={'text': 'one'}).get_json()['ok'] is True
    assert client.post('/api/ai/memories', json={'text': 'two'}).get_json()['ok'] is True
    data = client.post('/api/ai/memories', json={'text': 'three'}).get_json()
    assert data['ok'] is False
    assert data['key'] == 'ai.memoryFull'
    # The two the user kept are still there: a full store is not a reason to drop one.
    assert [row['text'] for row in client.get('/api/ai/memories').get_json()['memories']] == ['two', 'one']


def test_a_memory_reaches_the_context_once_and_the_cut_is_reported(client, monkeypatch):
    from ai import context, store

    client.post('/api/ai/memories', json={'text': '默认账号是 default'})
    text, meta = context.build_context('how do I crawl weibo?')
    assert '默认账号是 default' in text
    # One heading, added by build_context: the section used to carry its own and print “## 项目记忆”
    # inside itself, which made the inspector's count disagree with what the model saw.
    assert text.count('## 项目记忆') == 1
    assert meta['memories'] == {'total': 1, 'shown': 1, 'omitted': 0}

    monkeypatch.setattr(context, 'MEMORY_CONTEXT_LIMIT', 2)
    for index in range(3):
        store.save_memory(f'fact {index}')
    text, meta = context.build_context('anything')
    assert text.count('- fact ') == 2
    assert meta['memories'] == {'total': 4, 'shown': 2, 'omitted': 2}


def test_one_accounts_memories_are_not_anothers():
    from ai import store
    from runtime import account_context

    with account_context.use(account_context.Account('u_111111111111', 'alice')):
        store.save_memory('alice remembers this')
        assert [row['text'] for row in store.list_memories()] == ['alice remembers this']
    with account_context.use(account_context.Account('u_222222222222', 'bob')):
        assert store.list_memories() == []
        store.save_memory('bob remembers that')
        assert [row['text'] for row in store.list_memories()] == ['bob remembers that']
    with account_context.use(account_context.Account('u_111111111111', 'alice')):
        assert [row['text'] for row in store.list_memories()] == ['alice remembers this']


class MemoryArtifactProvider:
    """Propose one memory artifact, then answer. The user applies it; the tool never writes."""

    def __init__(self, payload: dict):
        from ai.types import ModelSpec, ProviderSpec

        self.payload = payload
        capabilities = frozenset({'tools'})
        self.spec = ProviderSpec(
            id='fake_memory',
            label_key='ai.provider.deepseek',
            notes_key='ai.providerNote.deepseek',
            protocol='openai',
            base_url='',
            models=(ModelSpec('fake-model', 'Fake', 10000, capabilities),),
            capabilities=capabilities,
        )

    def supports(self, capability: str, model: str = '') -> bool:
        return capability in self.spec.capabilities

    def context_window(self, model: str = '') -> int:
        return 0

    def stream(self, request):
        used = any(
            block.get('type') == 'tool_use'
            for message in request.get('messages') or []
            for block in message.get('blocks') or []
        )
        if not used:
            yield {
                'type': 'tool_call',
                'id': 'call_mem',
                'name': 'present_artifact',
                'arguments': {
                    'title': '记住这条',
                    'kind': 'memory',
                    'payload': self.payload,
                },
            }
            yield {'type': 'done', 'stop_reason': 'tool_calls'}
            return
        yield {'type': 'text_delta', 'text': '可以。'}
        yield {'type': 'done', 'stop_reason': 'end_turn'}


def _propose(client, monkeypatch, payload: dict) -> dict:
    from ai.providers import PROVIDERS

    monkeypatch.setitem(PROVIDERS, 'fake_memory', MemoryArtifactProvider(payload))
    response = client.post(
        '/api/ai/chat?stream=0',
        json={
            'text': '记住：这个项目用默认账号',
            'provider': 'fake_memory',
            'model': 'fake-model',
            'api_key': 'secret-key',
            'skill': 'project',
            'context': {},
        },
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def test_a_memory_artifact_is_proposed_and_nothing_is_stored_yet(client, monkeypatch):
    data = _propose(client, monkeypatch, {'text': '  这个项目用默认账号  '})
    artifacts = [event['artifact'] for event in data['events'] if event['type'] == 'artifact']
    assert artifacts and artifacts[0]['kind'] == 'memory'
    assert artifacts[0]['payload'] == {'text': '这个项目用默认账号'}
    # Proposing is not writing: the studio's list is still empty until the user applies it.
    assert client.get('/api/ai/memories').get_json()['memories'] == []


def test_an_empty_memory_artifact_goes_back_to_the_model_as_a_refusal(client, monkeypatch):
    data = _propose(client, monkeypatch, {'text': '   '})
    assert not [event for event in data['events'] if event['type'] == 'artifact']
    refused = [event for event in data['events'] if event['type'] == 'tool_result' and event.get('ok') is False]
    assert refused, data['events']
    # The turn continued instead of dying: the model can shorten its proposal and try again.
    assert [event for event in data['events'] if event['type'] == 'text']
