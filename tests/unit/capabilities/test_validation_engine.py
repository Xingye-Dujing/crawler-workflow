"""A validator that raises or returns garbage becomes a named problem, never a 500.

The engine calls capability-owned validators while answering ``/api/workflow/diagnostics``. A plugin
bug must keep the canvas's other badges alive and say which reference failed; it must not hide the
bug by passing either. Both halves are pinned here, on a fake resolver so no executor file is needed.
"""

from dataclasses import replace

import pytest
from capabilities_kernel import registry

from engine.workflow import WorkflowEngine
from services.validation import engine

pytestmark = pytest.mark.unit


def _manifest():
    manifest = registry.manifest_for_node('compile')
    assert manifest is not None
    return replace(manifest, validators=('fake.validator:check',))


def _context():
    nodes = {
        'c': {'id': 'c', 'type': 'compile', 'title': '编译'},
        'p': {'id': 'p', 'type': 'upload', 'title': '上传'},
    }
    connections = [{'from': 'p', 'to': 'c'}]
    return engine.ValidationContext(
        node_id='c',
        label='编译 #c',
        nodes=nodes,
        connections=connections,
        data_inputs=frozenset({'c'}),
    )


def _run(handler, monkeypatch, node=None):
    monkeypatch.setattr(registry, 'resolve', lambda _reference: handler)
    return engine.validation_problems(_manifest(), node or {'id': 'c', 'type': 'compile'}, _context())


class TestTheContextAnswersTheGraphFacts:
    def test_parents_labels_and_shapes(self):
        context = _context()
        assert context.parent_ids() == ['p']
        assert context.label_of('p') == '上传 #p'
        assert context.has_data_input() is True
        assert context.has_incoming() is True
        assert context.has_output() is False

    def test_an_unknown_node_is_empty_not_a_guess(self):
        assert _context().node('moonbase') == {}


class TestAValidValidator:
    def test_a_valid_problem_is_normalised(self, monkeypatch):
        def handler(_node, _context):
            return [{'code': 'custom.code', 'message_key': 'custom.message', 'context': {'n': 1}}]

        assert _run(handler, monkeypatch) == [
            {
                'code': 'custom.code',
                'message_key': 'custom.message',
                'severity': 'error',
                'param': '',
                'context': {'n': 1},
            },
        ]

    def test_static_rules_still_run_alongside(self, monkeypatch):
        monkeypatch.setattr(registry, 'resolve', lambda _reference: lambda _node, _context: [])
        tokenize = registry.manifest_for_node('tokenize')
        assert tokenize is not None
        manifest = replace(tokenize, validators=('fake.validator:check',))
        found = engine.validation_problems(manifest, {'id': 't', 'type': 'tokenize'}, _context())
        assert [problem['code'] for problem in found] == ['engine.tokenize_no_column']


class TestABadValidatorIsNamed:
    def test_an_exception_becomes_validator_failed(self, monkeypatch):
        def handler(_node, _context):
            raise RuntimeError('boom')

        found = _run(handler, monkeypatch)
        assert [problem['code'] for problem in found] == ['engine.validator_failed']
        assert found[0]['context']['ref'] == 'fake.validator:check'
        assert 'boom' in found[0]['context']['err']

    def test_a_non_list_result_is_refused(self, monkeypatch):
        found = _run(lambda _node, _context: {'code': 'x', 'message_key': 'x'}, monkeypatch)
        assert [problem['code'] for problem in found] == ['engine.validator_failed']

    def test_a_problem_without_a_message_key_is_refused(self, monkeypatch):
        found = _run(lambda _node, _context: [{'code': 'x'}], monkeypatch)
        assert [problem['code'] for problem in found] == ['engine.validator_failed']

    def test_an_unregistered_severity_is_refused(self, monkeypatch):
        found = _run(lambda _node, _context: [{'code': 'x', 'message_key': 'x', 'severity': 'fatal'}], monkeypatch)
        assert [problem['code'] for problem in found] == ['engine.validator_failed']

    def test_a_non_object_context_is_refused(self, monkeypatch):
        found = _run(lambda _node, _context: [{'code': 'x', 'message_key': 'x', 'context': 'nope'}], monkeypatch)
        assert [problem['code'] for problem in found] == ['engine.validator_failed']

    def test_a_broken_reference_is_named_not_raised(self, monkeypatch):
        monkeypatch.setattr(registry, 'resolve', lambda _reference: (_ for _ in ()).throw(KeyError('moonbase')))
        assert (
            engine.validation_problems(_manifest(), {'id': 'c', 'type': 'compile'}, _context())[0]['context']['ref']
            == 'fake.validator:check'
        )


class TestTheEngineStillReportsIt:
    def test_a_broken_validator_does_not_500_validate_detailed(self, monkeypatch):
        monkeypatch.setattr(registry, 'resolve', lambda _reference: (_ for _ in ()).throw(RuntimeError('boom')))
        workflow = {
            'nodes': [{'id': 'c', 'type': 'compile', 'params': {}}],
            'connections': [],
        }
        entries = WorkflowEngine(workflow).validate_detailed()
        names = [entry['code'] for entry in entries if entry['id'] == 'c']
        assert 'engine.validator_failed' in names
