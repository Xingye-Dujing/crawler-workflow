"""Token budgets: a named refusal before a fresh turn, a soft question inside one."""

import pytest

pytestmark = pytest.mark.api


class _BudgetProvider:
    """First round calls a real read tool and spends past the cap; a second round must not start."""

    def __init__(self, provider_id='fake_budget'):
        from ai.types import ModelSpec, ProviderSpec

        caps = frozenset({'thinking', 'tools', 'ask_user'})
        self.spec = ProviderSpec(
            id=provider_id,
            label_key='ai.provider.deepseek',
            notes_key='ai.providerNote.deepseek',
            protocol='openai',
            base_url='',
            models=(ModelSpec('fake-model', 'Fake', 10000, caps),),
            capabilities=caps,
        )
        self.calls = 0

    def supports(self, capability, model=''):
        return capability in self.spec.capabilities

    def context_window(self, model=''):
        return 0

    def stream(self, request):
        self.calls += 1
        if self.calls == 1:
            yield {'type': 'tool_call', 'id': 'call_1', 'name': 'project_facts', 'arguments': {}}
            yield {'type': 'usage', 'usage': {'prompt_tokens': 100, 'completion_tokens': 50}}
            yield {'type': 'done', 'stop_reason': 'tool_calls'}
            return
        yield {'type': 'text_delta', 'text': 'should never run'}
        yield {'type': 'done', 'stop_reason': 'end_turn'}


@pytest.fixture
def clean_budget():
    from ai import store

    store.mark_interrupted()
    yield
    store.mark_interrupted()


def _cap(monkeypatch, conversation_limit=0, daily_limit=0):
    from ai import costs

    real = costs.get_setting

    def setting(key, *args, **kwargs):
        if key == 'ai_budget_conversation_tokens':
            return conversation_limit
        if key == 'ai_budget_daily_tokens':
            return daily_limit
        return real(key, *args, **kwargs)

    monkeypatch.setattr(costs, 'get_setting', setting)


def test_a_spent_budget_refuses_a_new_turn_before_any_provider_call(client, monkeypatch, clean_budget):
    from ai import store
    from ai.providers import PROVIDERS

    provider = _BudgetProvider('fake_budget_refuse')
    monkeypatch.setitem(PROVIDERS, provider.spec.id, provider)
    _cap(monkeypatch, conversation_limit=120)
    conversation = store.create_conversation('deepseek', 'fake-model', 'project')
    store.save_usage(
        conversation['id'], 'm1', 'deepseek', 'fake-model', {'prompt_tokens': 100, 'completion_tokens': 50}
    )

    response = client.post(
        '/api/ai/chat?stream=0',
        json={
            'conversation_id': conversation['id'],
            'provider': provider.spec.id,
            'model': 'fake-model',
            'api_key': 'k',
            'text': 'hello',
        },
    )
    data = response.get_json()
    assert data['ok'] is False
    assert data['key'] == 'ai.budgetExceeded'
    assert provider.calls == 0, 'the provider was called after the cap refused the turn'


def test_reaching_the_cap_mid_turn_asks_once_instead_of_running_another_round(client, monkeypatch, clean_budget):
    from ai.providers import PROVIDERS

    provider = _BudgetProvider()
    monkeypatch.setitem(PROVIDERS, provider.spec.id, provider)
    _cap(monkeypatch, conversation_limit=120)

    response = client.post(
        '/api/ai/chat?stream=0',
        json={'provider': provider.spec.id, 'model': 'fake-model', 'api_key': 'k', 'text': 'poke the project'},
    )
    events = response.get_json()['events']
    questions = [event for event in events if event.get('type') == 'question']
    assert len(questions) == 1, events
    assert questions[0]['questions'][0]['id'] == 'token_budget'
    assert any(event.get('type') == 'paused' and event.get('reason') == 'token_budget' for event in events)
    assert provider.calls == 1, 'the agent started a second paid round after reaching the cap'
