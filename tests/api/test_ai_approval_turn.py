"""The approval card's backend half: a pause on request_approval and the grant its answer makes.

``ai_auto_approve`` is ON by default, so this file is about the user who turned it off. Nothing
here reaches a provider or the network: the scripted provider answers from the stored transcript.
"""

import pytest
from ai import approvals

pytestmark = pytest.mark.api


class FakeProvider:
    def __init__(self, provider_id: str, detail=None):
        from ai.types import ModelSpec, ProviderSpec

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
        self.detail = detail

    def supports(self, capability: str, model: str = '') -> bool:
        return capability in self.spec.capabilities

    def context_window(self, model: str = '') -> int:
        return 0

    def stream(self, request):
        answered = any(message.get('role') == 'tool' for message in request.get('messages', []))
        if not answered:
            yield {
                'type': 'tool_call',
                'id': 'call_approve',
                'name': 'request_approval',
                'arguments': {
                    'action': 'run_cmd',
                    'summary': 'Run the test suite',
                    'detail': self.detail if self.detail is not None else {'command': 'pytest -q'},
                },
            }
            yield {'type': 'done', 'stop_reason': 'tool_calls'}
            return
        yield {'type': 'text_delta', 'text': 'Done.'}
        yield {'type': 'done', 'stop_reason': 'end_turn'}


@pytest.fixture(autouse=True)
def _clean_approvals():
    approvals.reset()
    yield
    approvals.reset()


def _install(monkeypatch, detail=None):
    from ai.providers import PROVIDERS

    provider = FakeProvider('fake_approval', detail=detail)
    monkeypatch.setitem(PROVIDERS, 'fake_approval', provider)


def _chat(client, text='run the tests', conversation_id=''):
    return client.post(
        '/api/ai/chat?stream=0',
        json={
            'text': text,
            'conversation_id': conversation_id,
            'provider': 'fake_approval',
            'model': 'fake-model',
            'api_key': 'secret-key',
            'skill': 'project',
            'context': {},
        },
    )


def _answer(client, conversation_id, question, option_value):
    question_row = question['questions'][0]
    label = next(item['label'] for item in question_row['options'] if item.get('value') == option_value)
    return client.post(
        '/api/ai/answer?stream=0',
        json={
            'conversation_id': conversation_id,
            'message_id': question['message_id'],
            'question_id': question['question_id'],
            'answers': [{'id': question_row['id'], 'selected': [label]}],
            'api_key': 'secret-key',
        },
    )


def test_the_question_offers_all_three_choices(client, monkeypatch):
    _install(monkeypatch)
    data = _chat(client).get_json()
    assert data['ok'] is True
    events = data['events']
    question = next(event for event in events if event['type'] == 'question')
    row = question['questions'][0]
    assert row['kind'] == 'approval'
    assert [item.get('value') for item in row['options']] == ['once', 'session', 'deny']
    assert len(row['options']) == 3
    assert any(event['type'] == 'paused' and event.get('reason') == 'awaiting_approval' for event in events)
    # The question is a real tool call on the assistant row, so the provider's pairing stays valid.
    assert question['tool_call_id']


def test_a_session_approval_is_reused_by_the_resumed_turn(client, monkeypatch):
    _install(monkeypatch)
    events = _chat(client).get_json()['events']
    meta = next(event for event in events if event['type'] == 'meta')
    question = next(event for event in events if event['type'] == 'question')
    resumed = _answer(client, meta['conversation_id'], question, 'session')
    assert resumed.status_code == 200
    assert resumed.get_json()['ok'] is True
    args = {'command': 'pytest -q'}
    assert approvals.consume(meta['conversation_id'], 'run_cmd', args) is True
    assert approvals.consume(meta['conversation_id'], 'run_cmd', args) is True


def test_a_once_approval_is_spent_after_one_call(client, monkeypatch):
    _install(monkeypatch)
    events = _chat(client).get_json()['events']
    meta = next(event for event in events if event['type'] == 'meta')
    question = next(event for event in events if event['type'] == 'question')
    _answer(client, meta['conversation_id'], question, 'once')
    args = {'command': 'pytest -q'}
    assert approvals.consume(meta['conversation_id'], 'run_cmd', args) is True
    assert approvals.consume(meta['conversation_id'], 'run_cmd', args) is False


def test_a_denial_grants_nothing(client, monkeypatch):
    _install(monkeypatch)
    events = _chat(client).get_json()['events']
    meta = next(event for event in events if event['type'] == 'meta')
    question = next(event for event in events if event['type'] == 'question')
    _answer(client, meta['conversation_id'], question, 'deny')
    assert approvals.consume(meta['conversation_id'], 'run_cmd', {'command': 'pytest -q'}) is False


def test_a_new_message_cancels_the_pending_approval(client, monkeypatch):
    _install(monkeypatch)
    events = _chat(client).get_json()['events']
    meta = next(event for event in events if event['type'] == 'meta')
    assert any(event['type'] == 'question' for event in events)
    again = _chat(client, text='never mind', conversation_id=meta['conversation_id'])
    assert again.status_code == 200
    # The abandoned question can no longer be answered, and the grant it might have made is gone.
    detail = client.get('/api/ai/conversations/' + meta['conversation_id']).get_json()
    assert detail['pending_questions'] == []
    assert approvals.consume(meta['conversation_id'], 'run_cmd', {'command': 'pytest -q'}) is False


def test_a_detail_that_is_not_a_json_object_is_a_named_refusal(client, monkeypatch):
    """Without the exact arguments there is nothing a grant could be keyed by, so nothing is asked."""
    _install(monkeypatch, detail='not json at all')
    events = _chat(client).get_json()['events']
    types = [event['type'] for event in events]
    assert 'question' not in types
    result = next(event for event in events if event['type'] == 'tool_result')
    assert result['ok'] is False
    assert result['name'] == 'request_approval'
    assert 'detail' in result['error']
