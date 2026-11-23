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
                'fix': None,
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


class TestAFixIsADeclaredRepair:
    """A problem may carry a mechanical repair the settings panel applies in one click.

    The shape is ``{'set': {param: value}}`` and it may only name top-level node parameters. The
    engine refuses a malformed fix by name rather than letting a broken button reach the panel.
    """

    def _enum_manifest(self, default='csv'):
        from capabilities_kernel.manifest import ParamSpec, Rule

        return replace(
            _manifest(),
            validators=(),
            params=(ParamSpec(name='format', type='string', default=default, enum=('csv', 'json'), widget='select'),),
            rules=(Rule(kind='enum_param', code='x.bad_option', message_key='x.bad_option', param='format'),),
        )

    def test_an_off_list_enum_offers_the_declared_default(self):
        found = engine.static_problems(self._enum_manifest(), {'params': {'format': 'xlsx'}})
        assert [problem['code'] for problem in found] == ['x.bad_option']
        assert found[0]['fix'] == {'set': {'format': 'csv'}}

    def test_a_blank_default_has_no_fix(self):
        found = engine.static_problems(self._enum_manifest(default=''), {'params': {'format': 'xlsx'}})
        assert found and 'fix' not in found[0]

    def test_a_malformed_fix_is_a_named_plugin_failure(self, monkeypatch):
        found = _run(
            lambda _node, _context: [{'code': 'x', 'message_key': 'x', 'fix': {'set': {}}}],
            monkeypatch,
        )
        assert [problem['code'] for problem in found] == ['engine.validator_failed']

    def test_a_fix_for_a_non_parameter_value_is_refused(self, monkeypatch):
        found = _run(
            lambda _node, _context: [{'code': 'x', 'message_key': 'x', 'fix': {'set': {'': 1}}}],
            monkeypatch,
        )
        assert [problem['code'] for problem in found] == ['engine.validator_failed']

    def test_the_entry_carries_the_box_and_the_fix(self, monkeypatch):
        monkeypatch.setattr(
            registry,
            'resolve',
            lambda _reference: (
                lambda _node, _context: [
                    {'code': 'x.blank', 'message_key': 'x.blank', 'param': 'x_field', 'fix': {'set': {'x_field': '��'}}}
                ]
            ),
        )
        workflow = {'nodes': [{'id': 'c', 'type': 'compile', 'params': {}}], 'connections': []}
        entry = next(entry for entry in WorkflowEngine(workflow).validate_detailed() if entry['code'] == 'x.blank')
        assert entry['param'] == 'x_field'
        assert entry['severity'] == 'error'
        assert entry['fix'] == {'set': {'x_field': '��'}}


class TestThePreflightSeam:
    """``preflight(node, sample)`` is called only when a sample exists, and a broken one is named.

    The engine never opens a database: the caller passes ``samples`` and a node absent from the
    mapping is simply not preflighted. That keeps a unit test, an AI draft and a canvas with no
    stored run on the same code path.
    """

    @staticmethod
    def _preflighted():
        return replace(_manifest(), validators=(), preflight='fake.preflight:check')

    def test_a_missing_sample_never_calls_the_hook(self, monkeypatch):
        called = []

        def handler(node, sample):
            called.append((node, sample))
            return []

        monkeypatch.setattr(registry, 'resolve', lambda _reference: handler)
        engine.validation_problems(self._preflighted(), {'id': 'c', 'type': 'compile'}, _context())
        assert called == []

    def test_the_hook_gets_the_sample(self, monkeypatch):
        seen = {}

        def handler(_node, sample):
            seen['sample'] = sample
            return []

        monkeypatch.setattr(registry, 'resolve', lambda _reference: handler)
        engine.validation_problems(self._preflighted(), {'id': 'c', 'type': 'compile'}, _context(), sample=[{'x': 1}])
        assert seen['sample'] == [{'x': 1}]

    def test_a_raising_preflight_is_named(self, monkeypatch):
        monkeypatch.setattr(registry, 'resolve', lambda _reference: (_ for _ in ()).throw(RuntimeError('boom')))
        found = engine.validation_problems(
            self._preflighted(), {'id': 'c', 'type': 'compile'}, _context(), sample=[{'x': 1}]
        )
        assert [problem['code'] for problem in found] == ['engine.preflight_failed']
        assert found[0]['context']['ref'] == 'fake.preflight:check'

    def test_a_malformed_preflight_result_is_named(self, monkeypatch):
        monkeypatch.setattr(registry, 'resolve', lambda _reference: lambda _node, _sample: [{'code': 'x'}])
        found = engine.validation_problems(
            self._preflighted(), {'id': 'c', 'type': 'compile'}, _context(), sample=[{'x': 1}]
        )
        assert [problem['code'] for problem in found] == ['engine.preflight_failed']


class TestTheColumnContract:
    """A consumer's declared reads against its data parents' known table shapes.

    The engine never opens a database: ``columns`` is the caller's mapping (a settled run's
    recorded schema, else the producer's declared contract). The rule is silent unless every data
    parent is known — a missing column is a refusal only when the table is provably known — and a
    ``name`` parent is metadata, not a table.
    """

    @staticmethod
    def _with_reads(reads='fake.reader:columns'):
        manifest = _manifest()
        return replace(manifest, validators=(), ports=replace(manifest.ports, read_columns=reads))

    @staticmethod
    def _resolver(handler):
        def resolve(reference):
            if reference != 'fake.reader:columns':
                raise KeyError(reference)
            return handler

        return resolve

    def test_a_missing_read_is_named(self, monkeypatch):
        monkeypatch.setattr(registry, 'resolve', self._resolver(lambda _node: ['正文']))
        found = engine.validation_problems(
            self._with_reads(), {'id': 'c', 'type': 'compile'}, _context(), columns={'p': ['X']}
        )
        assert [problem['code'] for problem in found] == ['engine.missing_column']
        assert found[0]['context']['columns'] == '正文'

    def test_a_present_read_is_clean(self, monkeypatch):
        monkeypatch.setattr(registry, 'resolve', self._resolver(lambda _node: ['正文']))
        found = engine.validation_problems(
            self._with_reads(), {'id': 'c', 'type': 'compile'}, _context(), columns={'p': ['正文', 'X']}
        )
        assert found == []

    def test_an_unknown_upstream_is_not_judged(self, monkeypatch):
        monkeypatch.setattr(registry, 'resolve', self._resolver(lambda _node: ['正文']))
        for columns in ({'p': None}, {}):
            found = engine.validation_problems(
                self._with_reads(), {'id': 'c', 'type': 'compile'}, _context(), columns=columns
            )
            assert found == []

    def test_without_evidence_nothing_is_checked(self, monkeypatch):
        monkeypatch.setattr(registry, 'resolve', self._resolver(lambda _node: ['正文']))
        assert engine.validation_problems(self._with_reads(), {'id': 'c', 'type': 'compile'}, _context()) == []

    def test_a_name_parent_is_metadata_not_a_table(self, monkeypatch):
        monkeypatch.setattr(registry, 'resolve', self._resolver(lambda _node: ['正文']))
        context = engine.ValidationContext(
            node_id='c',
            label='编译 #c',
            nodes={'c': {'id': 'c', 'type': 'compile'}, 'n': {'id': 'n', 'type': 'name'}},
            connections=[{'from': 'n', 'to': 'c'}],
            data_inputs=frozenset(),
        )
        assert engine.validation_problems(self._with_reads(), {'id': 'c', 'type': 'compile'}, context, columns={}) == []

    def test_no_parent_is_not_judged(self, monkeypatch):
        monkeypatch.setattr(registry, 'resolve', self._resolver(lambda _node: ['正文']))
        context = engine.ValidationContext(
            node_id='c',
            label='编译 #c',
            nodes={'c': {'id': 'c', 'type': 'compile'}},
            connections=[],
            data_inputs=frozenset(),
        )
        assert engine.validation_problems(self._with_reads(), {'id': 'c', 'type': 'compile'}, context, columns={}) == []

    def test_a_broken_read_hook_is_named(self, monkeypatch):
        monkeypatch.setattr(registry, 'resolve', lambda _reference: (_ for _ in ()).throw(RuntimeError('boom')))
        found = engine.validation_problems(
            self._with_reads(), {'id': 'c', 'type': 'compile'}, _context(), columns={'p': ['正文']}
        )
        assert [problem['code'] for problem in found] == ['engine.read_columns_failed']
        assert found[0]['context']['ref'] == 'fake.reader:columns'

    def test_a_manifest_without_a_read_hook_is_not_checked(self, monkeypatch):
        monkeypatch.setattr(registry, 'resolve', self._resolver(lambda _node: ['正文']))
        found = engine.validation_problems(
            self._with_reads(''), {'id': 'c', 'type': 'compile'}, _context(), columns={'p': []}
        )
        assert found == []
