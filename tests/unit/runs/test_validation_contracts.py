"""What a consumer's declared reads are checked against: recorded shape first, contract second.

``columns_for`` answers ``{node_id: columns | None}`` for the effective graph. The recorded shape
of a settled run under the current fingerprint wins (it is the table this node would receive); a
producer's declared ``emit_columns`` answers before the first run. A store failure costs only the
recorded half — the declared contract still applies, so a locked ``runs.db`` never takes the badge
down with it.
"""

import pytest

from services.validation import contracts

pytestmark = pytest.mark.unit


class FakeStore:
    def __init__(self, schemas=None, raises=None):
        self.schemas = schemas or {}
        self.raises = raises
        self.calls = []

    def schemas_for(self, fingerprints):
        self.calls.append(fingerprints)
        if self.raises is not None:
            raise self.raises
        return self.schemas


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr('runtime.stores.get_run_store', lambda: fake)
    return fake


def _workflow(*nodes, connections=None):
    return {'nodes': list(nodes), 'connections': connections or [], 'settings': {}}


def _tokenize(nid='t', params=None):
    return {'id': nid, 'type': 'tokenize', 'params': params or {}}


def _source(nid='s'):
    return {'id': nid, 'type': 'source', 'params': {'platform': 'zhihu', 'collect': 'posts'}}


def test_a_recorded_shape_wins_over_the_declared_contract(store):
    workflow = _workflow(_tokenize())
    store.schemas = {'t': ['自定义列']}
    assert contracts.columns_for(workflow) == {'t': ['自定义列']}
    assert store.calls and 't' in store.calls[0], 'the read is keyed by the node fingerprint'


def test_the_declared_contract_answers_without_a_run(store):
    workflow = _workflow(_tokenize())
    assert contracts.columns_for(workflow) == {'t': ['word', 'frequency']}


def test_an_unknown_producer_stays_unknown(store):
    workflow = _workflow(_source())
    assert contracts.columns_for(workflow) == {'s': None}


def test_a_disabled_node_is_not_on_the_effective_graph(store):
    workflow = _workflow(_tokenize('t', {'enabled': False}), _source())
    assert 't' not in contracts.columns_for(workflow)


def test_a_store_failure_keeps_the_declared_contract(monkeypatch, caplog):
    monkeypatch.setattr('runtime.stores.get_run_store', lambda: FakeStore(raises=RuntimeError('locked')))
    workflow = _workflow(_tokenize())
    assert contracts.columns_for(workflow) == {'t': ['word', 'frequency']}
    assert [record for record in caplog.records if record.exc_info], 'the failure keeps its traceback'
