"""Artifact validators: one format, one module, one registration.

The turn loop used to carry a branch per strict kind. These cases pin the registry as that seam: a
new format is a new module plus one ``register`` call, a duplicate is refused, and the two built-in
validators keep the shapes their existing callers publish.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def _legal_draft() -> dict:
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


def test_every_builtin_kind_has_one_validator():
    from ai import validators

    assert validators.registered_kinds() == frozenset({'memory', 'workflow', 'workflow_draft'})


def test_a_duplicate_registration_is_refused(monkeypatch):
    from ai import validators
    from ai.validators.base import Validation, Validator

    first = Validator('strict_note', lambda payload: Validation(ok=True))
    monkeypatch.setitem(validators.VALIDATORS, 'strict_note', first)
    with pytest.raises(ValueError, match='already has a validator'):
        validators.register(Validator('strict_note', lambda payload: Validation(ok=True)))


def test_an_unregistered_kind_has_no_validation():
    from ai import validators

    assert validators.check('markdown', {'anything': 'goes'}) is None


def test_workflow_validator_keeps_the_published_report_shape():
    from ai import validators

    legal = validators.check('workflow_draft', _legal_draft())
    assert legal is not None and legal.ok is True
    assert set(legal.report) == {'ok', 'structural', 'engine'}
    assert legal.report['ok'] is True

    draft = _legal_draft()
    draft['nodes'][0]['type'] = '分析'
    illegal = validators.check('workflow', draft)
    assert illegal is not None and illegal.ok is False
    assert any('分析' in problem for problem in illegal.problems)
    assert set(illegal.report) == {'ok', 'structural', 'engine'}
    assert '分析' in illegal.message


def test_memory_validator_normalizes_a_legal_draft_and_refuses_an_empty_one():
    from ai import store, validators

    legal = validators.check('memory', {'text': '  用默认账号  '})
    assert legal is not None and legal.ok is True
    assert legal.payload == {'text': '用默认账号'}

    empty = validators.check('memory', {'text': '   '})
    assert empty is not None and empty.ok is False
    assert empty.problems == ['memory needs non-empty text']
    assert str(store.MAX_MEMORY_CHARS) in empty.message

    long_text = {'text': 'x' * (store.MAX_MEMORY_CHARS + 1)}
    assert validators.check('memory', long_text).problems == [
        f'memory text exceeds {store.MAX_MEMORY_CHARS} characters'
    ]


def test_refusal_notes_are_scoped_to_the_kind():
    from ai.agent import AgentService

    from i18n import t

    service = AgentService()
    service._draft_refusals = {}
    assert service._refusal_note(['bad'], 'memory') == ''
    assert service._refusal_note(['bad'], 'workflow') == ''
    # The second *same* problem set of a kind is the existing “stop resending” note.
    assert service._refusal_note(['bad'], 'memory') == t('ai.draftRefusedAgain')
    # A different kind starts its own budget; a workflow refusal cannot silence a memory draft.
    assert service._refusal_note(['other'], 'workflow') == ''


def test_a_kind_hits_the_repair_cap_on_different_problem_sets():
    from ai import validators
    from ai.agent import AgentService

    from i18n import t

    service = AgentService()
    service._draft_refusals = {}
    for index in range(validators.MAX_ARTIFACT_REPAIRS):
        note = service._refusal_note([f'problem {index}'], 'strict_note')
        expected = (
            ''
            if index < validators.MAX_ARTIFACT_REPAIRS - 1
            else t('ai.repairCapReached', limit=validators.MAX_ARTIFACT_REPAIRS)
        )
        assert note == expected


def test_a_new_turn_resets_the_refusal_counter(monkeypatch):
    """retry() and answer() go straight to _loop, never through send()'s old reset.

    A counter that survived into the next turn answered an identical bad draft with “stop
    resending” (or the repair cap) it had not earned in that conversation. The reset now lives in
    the one method all three entry points reach.
    """
    from ai import agent, skills, store

    from i18n import t

    class DoneProvider:
        def __init__(self):
            from ai.types import ModelSpec, ProviderSpec

            self.spec = ProviderSpec(
                id='done_provider',
                label_key='x',
                notes_key='y',
                protocol='openai',
                base_url='',
                models=(ModelSpec('m', 'M', 1000),),
            )

        def supports(self, capability, model=''):
            return False

        def context_window(self, model=''):
            return 0

        def stream(self, request):
            yield {'type': 'text_delta', 'text': 'ok'}
            yield {'type': 'done', 'stop_reason': 'end_turn'}

    monkeypatch.setattr(agent, 'get_setting', lambda key, default=None: default)
    service = agent.AgentService()
    conversation = store.create_conversation('done_provider', 'm', 'auto')
    store.append_message(conversation['id'], 'user', 'hi', status='done')

    def run_turn():
        list(
            service._loop(
                conversation=conversation,
                turn_id='t-refusals',
                skill=skills.get_skill('project'),
                skill_reason='auto',
                provider=DoneProvider(),
                model='m',
                api_key='',
                thinking=False,
                web_search=False,
                safety='high',
                context_meta={},
                run_id='',
            )
        )

    # First turn earns one bad-draft count, then a second identical one is refused.
    service._draft_refusals = {}
    assert service._refusal_note(['bad'], 'memory') == ''
    assert service._refusal_note(['bad'], 'memory') == t('ai.draftRefusedAgain')

    # Each fresh turn (the retry/answer path) must start with a clean counter.
    run_turn()
    assert service._draft_refusals == {}
    assert service._refusal_note(['bad'], 'memory') == ''
    run_turn()
    assert service._draft_refusals == {}
    assert service._refusal_note(['bad'], 'memory') == ''


def test_reset_then_load_restores_the_builtin_validators():
    from ai import validators

    before = validators.registered_kinds()
    validators.reset_for_tests()
    assert validators.registered_kinds() == frozenset()
    validators.load_builtin_validators()
    assert validators.registered_kinds() == before


def test_no_validator_imports_the_http_layer():
    """A validator is server fact, like a node executor: Flask must not reach into a run thread."""
    root = Path(__file__).resolve().parents[3] / 'backend' / 'ai' / 'validators'
    for path in sorted(root.glob('*.py')):
        text = path.read_text(encoding='utf-8')
        assert 'from app import' not in text and 'import app' not in text, path
        assert 'from api import' not in text and 'from api.' not in text, path
