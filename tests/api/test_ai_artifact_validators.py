"""A strict format is added by registering a validator, not by editing the turn loop.

The old ``if kind == …`` chain meant a new format needed a change to shared agent code. These cases
prove the seam end to end: a test-only kind with a test-only validator gets the same refusal →
self-repair loop the built-in workflow and memory drafts get, and a legal draft reaches the page.
"""

import pytest

pytestmark = pytest.mark.api


@pytest.fixture
def clean_ai():
    from ai import store

    store.mark_interrupted()
    yield


class StrictNoteProvider:
    """Propose one payload per round, then answer once each has been refused."""

    def __init__(self, provider_id: str, kind: str, payloads: list[dict]):
        from ai.types import ModelSpec, ProviderSpec

        self.kind = kind
        self.payloads = payloads
        capabilities = frozenset({'tools'})
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

    def context_window(self, model: str = '') -> int:
        return 0

    def stream(self, request):
        told = sum(1 for message in request.get('messages', []) if message.get('role') == 'tool')
        if told < len(self.payloads):
            yield {
                'type': 'tool_call',
                'id': f'call_note_{told}',
                'name': 'present_artifact',
                'arguments': {'title': 'Strict note', 'kind': self.kind, 'payload': self.payloads[told]},
            }
            yield {'type': 'done', 'stop_reason': 'tool_calls'}
            return
        yield {'type': 'text_delta', 'text': 'Understood.'}
        yield {'type': 'done', 'stop_reason': 'end_turn'}


def _chat(client, provider_id: str):
    response = client.post(
        '/api/ai/chat?stream=0',
        json={
            'text': 'propose it',
            'provider': provider_id,
            'model': 'fake-model',
            'api_key': 'secret-key',
            'skill': 'project',
            'context': {},
        },
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _register_note_validator(monkeypatch, kind: str = 'strict_note'):
    from ai import validators
    from ai.validators.base import Validation, Validator

    def check(payload: dict) -> Validation:
        source = payload or {}
        code = str(source.get('code') or '').strip()
        if code:
            return Validation(ok=True, payload={'code': code.upper()})
        # A distinct problem per variant, so a cap test can reach the "different drafts" branch
        # rather than the "same problems twice" branch.
        variant = str(source.get('variant') or 'none')
        return Validation(
            ok=False,
            problems=[f'a strict note needs a code (variant {variant})'],
            message='A strict note needs a code.',
        )

    monkeypatch.setitem(validators.VALIDATORS, kind, Validator(kind, check))


def test_a_registered_kind_receives_the_same_refusal_loop_as_a_builtin(client, monkeypatch, clean_ai):
    from ai.providers import PROVIDERS

    _register_note_validator(monkeypatch)
    monkeypatch.setitem(PROVIDERS, 'fake_note_bad', StrictNoteProvider('fake_note_bad', 'strict_note', [{'code': ''}]))
    data = _chat(client, 'fake_note_bad')
    refused = [event for event in data['events'] if event['type'] == 'tool_result' and event.get('ok') is False]
    assert len(refused) == 1 and 'needs a code' in refused[0]['error']
    assert not [event for event in data['events'] if event['type'] == 'artifact']
    # The turn carried on: the model got the reason as this call's result and could repair it.
    assert [event for event in data['events'] if event['type'] == 'text']


def test_a_legal_new_kind_is_normalized_and_painted_as_a_card(client, monkeypatch, clean_ai):
    from ai.providers import PROVIDERS

    _register_note_validator(monkeypatch)
    monkeypatch.setitem(
        PROVIDERS, 'fake_note_ok', StrictNoteProvider('fake_note_ok', 'strict_note', [{'code': '  ab  '}])
    )
    data = _chat(client, 'fake_note_ok')
    artifacts = [event['artifact'] for event in data['events'] if event['type'] == 'artifact']
    assert len(artifacts) == 1
    assert artifacts[0]['kind'] == 'strict_note'
    assert artifacts[0]['payload'] == {'code': 'AB'}


def test_the_repair_cap_names_the_repeated_kind_and_not_another(client, monkeypatch, clean_ai):
    from ai import validators
    from ai.providers import PROVIDERS

    from i18n import t

    _register_note_validator(monkeypatch, 'note_one')
    _register_note_validator(monkeypatch, 'note_two')
    times = validators.MAX_ARTIFACT_REPAIRS + 1
    variants = [{'variant': str(index)} for index in range(times)]
    monkeypatch.setitem(PROVIDERS, 'fake_note_loop', StrictNoteProvider('fake_note_loop', 'note_one', variants))
    data = _chat(client, 'fake_note_loop')
    refused = [event for event in data['events'] if event['type'] == 'tool_result' and event.get('ok') is False]
    assert len(refused) == times
    # Different drafts each time: the cap's OWN sentence, not “the same draft again”.
    assert t('ai.repairCapReached', limit=times - 1) in refused[-1]['error']
    assert t('ai.draftRefusedAgain') not in refused[-1]['error']
    assert t('ai.repairCapReached', limit=times - 1) not in refused[0]['error']

    # The other kind has its own budget; one refusal of it says nothing about note_one.
    monkeypatch.setitem(PROVIDERS, 'fake_note_other', StrictNoteProvider('fake_note_other', 'note_two', [{}]))
    other = _chat(client, 'fake_note_other')
    other_refused = [event for event in other['events'] if event['type'] == 'tool_result' and event.get('ok') is False]
    assert len(other_refused) == 1
    assert t('ai.repairCapReached', limit=times - 1) not in other_refused[0]['error']
