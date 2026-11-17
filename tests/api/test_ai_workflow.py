"""The AI HTTP surface, driven by a scripted provider. No network, no paid call."""

import json

import pytest

pytestmark = pytest.mark.api


class FakeProvider:
    def __init__(self, provider_id: str = 'fake_ai'):
        from ai.types import ModelSpec, ProviderSpec

        self.seen_keys = []
        capabilities = frozenset({'thinking', 'tools', 'ask_user'})
        self.spec = ProviderSpec(
            id=provider_id,
            label_key='ai.provider.deepseek',
            notes_key='ai.providerNote.deepseek',
            protocol='openai',
            base_url='',
            models=(ModelSpec('fake-model', 'Fake', 10000, capabilities),),
            capabilities=capabilities,
        )

    def supports(self, capability: str, model: str = '') -> bool:
        return capability in self.spec.capabilities

    def list_models(self, api_key: str = '', _host: str = '') -> list:
        self.seen_keys.append(api_key)
        return [{'id': 'fake-model', 'label': 'Fake'}]

    def stream(self, request):
        if request.get('_ask'):
            yield {
                'type': 'tool_call',
                'id': 'call_1',
                'name': 'ask_user_question',
                'arguments': {
                    'questions': [
                        {
                            'id': 'scope',
                            'question': 'Which data?',
                            'options': [{'label': 'Dataset A'}, {'label': 'Dataset B'}],
                        }
                    ]
                },
            }
            yield {'type': 'done', 'stop_reason': 'tool_calls'}
            return
        yield {'type': 'thinking_delta', 'text': 'thinking'}
        yield {'type': 'text_delta', 'text': 'Hello '}
        yield {'type': 'text_delta', 'text': 'world'}
        yield {'type': 'usage', 'usage': {'prompt_tokens': 4, 'completion_tokens': 2}}
        yield {'type': 'done', 'stop_reason': 'end_turn'}


class AskThenAnswerProvider(FakeProvider):
    def __init__(self):
        super().__init__('fake_ask')

    def stream(self, request):
        has_call = any(
            block.get('type') == 'tool_use'
            for message in request.get('messages', [])
            for block in message.get('blocks') or []
        )
        if not has_call:
            yield from super().stream({'_ask': True})
            return
        yield {'type': 'text_delta', 'text': 'You chose Dataset A.'}
        yield {'type': 'done', 'stop_reason': 'end_turn'}


@pytest.fixture
def fake_ai(monkeypatch):
    from ai.providers import PROVIDERS

    monkeypatch.setitem(PROVIDERS, 'fake_ai', FakeProvider())
    monkeypatch.setitem(PROVIDERS, 'fake_ask', AskThenAnswerProvider())


@pytest.fixture
def clean_ai():
    from ai import store

    store.mark_interrupted()
    yield


def _chat(client, **overrides):
    body = {
        'text': 'hello',
        'provider': 'fake_ai',
        'model': 'fake-model',
        'api_key': 'secret-key',
        'skill': 'project',
        'context': {},
    }
    body.update(overrides)
    return client.post('/api/ai/chat?stream=0', json=body)


def test_chat_returns_canonical_events_and_never_stores_the_key(client, fake_ai, clean_ai):
    response = _chat(client)
    assert response.status_code == 200
    data = response.get_json()
    assert data['ok'] is True
    types = [event['type'] for event in data['events']]
    assert 'meta' in types and 'text' in types and 'done' in types
    conversation_id = data['events'][0]['conversation_id']
    detail = client.get('/api/ai/conversations/' + conversation_id).get_json()
    assert detail['ok'] is True
    assert detail['messages']
    assert 'secret-key' not in json.dumps(detail, ensure_ascii=False)


def test_conversation_list_and_delete(client, fake_ai, clean_ai):
    response = _chat(client)
    conversation_id = response.get_json()['events'][0]['conversation_id']
    listing = client.get('/api/ai/conversations').get_json()
    assert listing['ok'] is True
    assert any(row['id'] == conversation_id for row in listing['conversations'])
    deleted = client.delete('/api/ai/conversations/' + conversation_id).get_json()
    assert deleted['ok'] is True
    assert client.get('/api/ai/conversations/' + conversation_id).status_code == 404


def test_ask_user_pauses_and_answer_resumes(client, fake_ai, clean_ai):
    response = _chat(client, provider='fake_ask', model='fake-model', text='which?')
    data = response.get_json()
    events = data['events']
    meta = next(event for event in events if event['type'] == 'meta')
    question = next(event for event in events if event['type'] == 'question')
    assert any(event['type'] == 'paused' for event in events)
    assert question['questions'][0]['question'] == 'Which data?'
    answer = {
        'conversation_id': meta['conversation_id'],
        'message_id': question['message_id'],
        'question_id': question['question_id'],
        'answers': [{'id': 'scope', 'selected': ['Dataset A']}],
        'api_key': 'secret-key',
    }
    resumed = client.post('/api/ai/answer?stream=0', json=answer)
    assert resumed.status_code == 200, resumed.get_json()
    resumed_events = resumed.get_json()['events']
    assert any(event['type'] == 'text' and 'Dataset A' in event.get('text', '') for event in resumed_events)


def test_asking_web_search_of_go_refuses_by_name(client, monkeypatch):
    from ai.providers import PROVIDERS
    from ai.providers.opencode_go import OpenCodeGoProvider

    monkeypatch.setitem(PROVIDERS, 'opencode_go', OpenCodeGoProvider())
    response = _chat(
        client,
        provider='opencode_go',
        model='deepseek-v4.1-flash',
        web_search=True,
        skill='project',
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body['key'] == 'ai.capabilityRefused'


def test_skill_studio_crud_and_plugin_install(client, fake_ai, clean_ai):
    skill = {
        'id': 'demo.skill',
        'prompt': 'Answer only from the supplied docs.',
        'context': ['project', 'docs'],
        'tools': ['project_facts', 'docs_search'],
        'suggested': ['hello'],
        'ask_policy': 'auto',
    }
    saved = client.post('/api/ai/skills', json=skill)
    assert saved.status_code == 200, saved.get_json()
    assert saved.get_json()['skill']['id'] == 'demo.skill'
    fetched = client.get('/api/ai/skills/demo.skill').get_json()
    assert fetched['skill']['prompt'].startswith('Answer only')
    forked = client.post('/api/ai/skills/demo.skill/fork', json={'id': 'demo.skill.copy'})
    assert forked.status_code == 200, forked.get_json()
    plugin = {
        'id': 'demo.pack',
        'name': 'Demo pack',
        'version': '1.0.0',
        'api': 1,
        'kind': 'skill-pack',
        'permissions': ['read:docs'],
        'skills': [{**skill, 'id': 'demo.pack.reader'}],
    }
    installed = client.post('/api/ai/plugins/install', json=plugin)
    assert installed.status_code == 200, installed.get_json()
    listed = client.get('/api/ai/plugins').get_json()
    assert any(row['id'] == 'demo.pack' for row in listed['plugins'])
    assert client.delete('/api/ai/plugins/demo.pack').status_code == 200
    client.delete('/api/ai/skills/demo.skill')
    client.delete('/api/ai/skills/demo.skill.copy')


def _tool_pack(tools_spec: list, plugin_id: str = 'demo.tools') -> dict:
    return {
        'id': plugin_id,
        'name': 'Demo tools',
        'version': '1.0.0',
        'api': 1,
        'kind': 'tool-pack',
        'permissions': ['net:http'],
        'tools': tools_spec,
    }


def _http_tool(name: str) -> dict:
    return {
        'name': name,
        'description': 'demo',
        'url': 'https://example.com/hook',
        'allowed_hosts': ['example.com'],
    }


def test_a_refused_tool_pack_never_replaces_the_builtin_it_collides_with(client, clean_ai):
    """The registry's duplicate check runs BEFORE the table ``tools.execute`` reads.

    Assigning into ``tools.TOOLS`` first meant a manifest the route then refused (400) had
    already installed its handler under that name for every later turn until restart.
    """
    from ai import tools
    from extensions import HOST

    before = tools.TOOLS['project_facts']
    refusal = client.post('/api/ai/plugins/install', json=_tool_pack([_http_tool('project_facts')]))
    assert refusal.status_code == 400, refusal.get_json()
    assert tools.TOOLS['project_facts'] is before
    assert HOST.get('tools', 'project_facts') is before


def test_a_pack_that_fails_on_a_later_entry_installs_nothing(client, clean_ai):
    """Two tools of three used to stay callable after the route answered 400."""
    from ai import tools
    from extensions import HOST

    pack = _tool_pack([_http_tool('demo_first_tool'), _http_tool('project_facts')], 'demo.partial')
    assert client.post('/api/ai/plugins/install', json=pack).status_code == 400
    assert 'demo_first_tool' not in tools.TOOLS
    assert HOST.get('tools', 'demo_first_tool') is None


def test_disabling_a_tool_pack_withdraws_it_and_enabling_brings_it_back(client, clean_ai):
    """A switch that only relabelled the row left the tool callable."""
    from ai import tools
    from extensions import HOST

    assert client.post('/api/ai/plugins/install', json=_tool_pack([_http_tool('demo_live_tool')])).status_code == 200
    try:
        assert 'demo_live_tool' in tools.TOOLS
        assert client.post('/api/ai/plugins/demo.tools/enable', json={'enabled': False}).status_code == 200
        assert 'demo_live_tool' not in tools.TOOLS
        assert HOST.get('tools', 'demo_live_tool') is None
        assert client.post('/api/ai/plugins/demo.tools/enable', json={'enabled': True}).status_code == 200
        assert 'demo_live_tool' in tools.TOOLS
    finally:
        client.delete('/api/ai/plugins/demo.tools')
    assert 'demo_live_tool' not in tools.TOOLS


def test_a_non_admin_may_not_install_a_process_wide_pack(client, clean_ai, monkeypatch):
    """A tool/provider/code pack writes tables every account reads; a skill pack is per account."""
    import api.ai as ai_api

    monkeypatch.setattr(ai_api, 'accounts_mode', lambda: True)
    monkeypatch.setattr(ai_api, 'is_admin', lambda: False)
    refused = client.post('/api/ai/plugins/install', json=_tool_pack([_http_tool('demo_nope_tool')], 'demo.nope'))
    assert refused.status_code == 403
    skill_pack = {
        'id': 'demo.ownskills',
        'name': 'Own skills',
        'version': '1.0.0',
        'api': 1,
        'kind': 'skill-pack',
        'permissions': [],
        'skills': [{'id': 'demo.ownskills.one', 'prompt': 'Answer briefly.'}],
    }
    assert client.post('/api/ai/plugins/install', json=skill_pack).status_code == 200
    assert client.delete('/api/ai/plugins/demo.ownskills').status_code == 200


def test_the_provider_key_travels_in_a_header_not_the_url(client, fake_ai):
    """A documented deployment puts a reverse proxy in front: its access log writes the request
    line, so a ``?key=sk-…`` URL would put the user's credential in the operator's log file."""
    from ai.providers import PROVIDERS

    provider = PROVIDERS['fake_ai']
    body = client.get('/api/ai/providers/fake_ai/models', headers={'X-Provider-Key': 'sk-header'}).get_json()
    assert body['ok'] is True and body['models'] == [{'id': 'fake-model', 'label': 'Fake'}]
    assert provider.seen_keys[-1] == 'sk-header'

    # The query string is no longer read: a stale client would get an unauthenticated list
    # (and, more importantly, the key would already be in the log).
    client.get('/api/ai/providers/fake_ai/models?key=sk-query')
    assert provider.seen_keys[-1] == ''


def test_a_pack_installed_by_one_account_is_not_anothers_to_use(client, clean_ai):
    """Installing is machine-level (admin-only), USING is per account.

    Without this, account B's agent was offered account A's HTTP tool and could call it — posting
    B's conversation arguments to a host only A had approved — and A's provider id resolved from
    B's settings request.
    """
    from ai import plugins, tools
    from ai.errors import AIError
    from runtime import account_context
    from runtime.account_context import Account

    alice = Account('u_' + 'a' * 12, 'alice')
    bob = Account('u_' + 'b' * 12, 'bob')
    pack = _tool_pack([_http_tool('demo_scoped_tool')], 'demo.scoped')
    try:
        with account_context.use(alice):
            plugins.install(pack)
            assert plugins.visible_tool('demo_scoped_tool') is True
            assert any(row['name'] == 'demo_scoped_tool' for row in tools.schemas())
        with account_context.use(bob):
            assert plugins.visible_tool('demo_scoped_tool') is False
            assert all(row['name'] != 'demo_scoped_tool' for row in tools.schemas()), 'offered to the wrong account'
            with pytest.raises(AIError) as refusal:
                tools.execute('demo_scoped_tool', {}, {})
            assert refusal.value.key == 'ai.toolRefused'
            assert refusal.value.params.get('reason') == 'not available for this account'
    finally:
        with account_context.use(alice):
            plugins.uninstall('demo.scoped')
    assert 'demo_scoped_tool' not in tools.TOOLS


def test_a_provider_pack_is_invisible_to_another_account(client, clean_ai):
    from ai import plugins
    from ai.errors import AIError
    from ai.providers.registry import get_provider
    from runtime import account_context
    from runtime.account_context import Account

    alice = Account('u_' + 'c' * 12, 'alice')
    bob = Account('u_' + 'd' * 12, 'bob')
    pack = {
        'id': 'demo.provider',
        'name': 'Demo provider',
        'version': '1.0.0',
        'api': 1,
        'kind': 'provider-pack',
        'permissions': ['provider:custom'],
        'providers': [
            {
                'id': 'demo_provider',
                'base_url': 'https://example.com/v1',
                'models': [{'id': 'demo-model'}],
            }
        ],
    }
    try:
        with account_context.use(alice):
            plugins.install(pack)
            assert get_provider('demo_provider').spec.id == 'demo_provider'
        with account_context.use(bob):
            with pytest.raises(AIError) as refusal:
                get_provider('demo_provider')
            assert refusal.value.key == 'ai.unknownProvider'
    finally:
        with account_context.use(alice):
            plugins.uninstall('demo.provider')
