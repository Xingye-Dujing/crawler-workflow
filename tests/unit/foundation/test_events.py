"""The event contract rejects a producer that renamed, dropped or retyped a field.

The bus must never raise into a run, so the validation lives here, before the bus. Each declared
event is exercised with a payload in the shape its producer sends; the sample is deliberately
explicit rather than generated, so a field rename shows up as a failing case with a readable name.
"""

import pytest
from ai import monitors
from runtime import events, run_events

pytestmark = pytest.mark.unit

SAMPLES = {
    'run.started': {'run_id': 'r1', 'workflow': '采集', 'wf_idx': 0, 'resume': False},
    'node.finished': {
        'run_id': 'r1',
        'node_id': 'n1',
        'node_type': 'tokenize',
        'label': '分词 #n1',
        'status': 'done',
        'rows': 120,
        'wf_idx': 0,
        'workflow': '采集',
    },
    'run.finished': {
        'run_id': 'r1',
        'records': ['r1'],
        'workflow': '采集',
        'outcome': 'completed',
        'done': 3,
        'total': 3,
        'failed': 0,
        'skipped': 0,
    },
    'run.log': {'run_id': 'r1', 'line': 'hello', 'wf_idx': None, 'level': 'info'},
}


class TestTheDeclaration:
    def test_every_event_has_a_sample_and_the_sample_validates(self):
        assert set(SAMPLES) == set(events.EVENTS)
        for name, sample in SAMPLES.items():
            assert events.validate(name, sample) == sample

    def test_the_monitor_vocabulary_is_the_declared_one(self):
        assert tuple(events.EVENTS) == tuple(monitors.EVENTS)

    def test_the_field_kinds_are_known(self):
        for spec in events.EVENTS.values():
            for field in spec.fields:
                assert field.kind in events._KINDS, f'{spec.name}.{field.name}: {field.kind}'

    def test_a_field_is_not_declared_twice(self):
        for spec in events.EVENTS.values():
            names = [field.name for field in spec.fields]
            assert len(names) == len(set(names)), spec.name


class TestARefusalNamesTheEventAndField:
    def test_an_unknown_event_lists_the_declared_ones(self):
        with pytest.raises(events.EventError, match='unknown event .*moon.base'):
            events.publish('moon.base', run_id='r1')

    def test_a_missing_field_is_named(self):
        sample = dict(SAMPLES['run.finished'])
        sample.pop('records')
        with pytest.raises(events.EventError, match='missing records'):
            events.validate('run.finished', sample)

    def test_an_extra_field_is_named(self):
        sample = dict(SAMPLES['run.started'], secret='x')
        with pytest.raises(events.EventError, match='unknown field.*secret'):
            events.validate('run.started', sample)

    def test_a_retyped_count_is_refused(self):
        with pytest.raises(events.EventError, match='rows is str, not int'):
            events.validate('node.finished', dict(SAMPLES['node.finished'], rows='120'))

    def test_a_bool_is_not_a_count(self):
        with pytest.raises(events.EventError, match='done is bool, not int'):
            events.validate('run.finished', dict(SAMPLES['run.finished'], done=True))

    def test_records_must_be_a_list_of_strings(self):
        with pytest.raises(events.EventError, match='records is not list'):
            events.validate('run.finished', dict(SAMPLES['run.finished'], records=[{'a': 1}]))

    def test_a_log_index_may_be_absent_and_must_not_be_a_string(self):
        assert events.validate('run.log', SAMPLES['run.log'])['wf_idx'] is None
        with pytest.raises(events.EventError, match='wf_idx is str'):
            events.validate('run.log', dict(SAMPLES['run.log'], wf_idx='0'))


@pytest.fixture
def seen():
    box = []

    def listener(payload):
        box.append(payload)

    run_events.subscribe(listener)
    yield box
    run_events.unsubscribe(listener)


class TestTheBusReceivesTheSameFact:
    def test_publish_delivers_the_event_name_and_the_validated_fields(self, seen):
        events.publish('run.started', **SAMPLES['run.started'])
        payload = next(item for item in seen if item.get('event') == 'run.started')
        assert payload == {'event': 'run.started', **SAMPLES['run.started']}

    def test_an_invalid_payload_reaches_no_listener(self, seen):
        with pytest.raises(events.EventError):
            events.publish('run.started', run_id='r1')
        assert seen == []
