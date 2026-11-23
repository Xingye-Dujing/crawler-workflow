"""The preflight's rows: which stored table a node's validation may look at.

A chart preflight may only judge the table the node would receive NOW. ``samples_for`` answers with
rows from the newest stored run whose recorded node fingerprint equals the current graph's, taken
from the node's DATA parents and flattened exactly like the engine's fan-in. No stored run under
that fingerprint means "no sample", never a guess; a name node is metadata and contributes no rows.
"""

import pytest

from services.validation import samples as sample_service

pytestmark = pytest.mark.unit


class FakeStore:
    def __init__(self, rows=None):
        self.rows = rows or {}
        self.calls = []

    def sample_rows(self, node_id, fingerprint, limit):
        self.calls.append((str(node_id), str(fingerprint), int(limit)))
        return self.rows.get(str(node_id), ('', []))


@pytest.fixture(autouse=True)
def _clear_cache():
    sample_service.clear_cache()
    yield
    sample_service.clear_cache()


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr('runtime.stores.get_run_store', lambda: fake)
    return fake


def _workflow(parent_types=('upload',), params=None):
    nodes = {
        'v': {
            'id': 'v',
            'type': 'visualize',
            'params': params or {'chart_type': 'bar', 'x_field': 'X'},
        },
    }
    connections = []
    for index, parent_type in enumerate(parent_types):
        nid = f'p{index + 1}'
        nodes[nid] = {'id': nid, 'type': parent_type, 'params': {}}
        connections.append({'from': nid, 'to': 'v'})
    return {'nodes': list(nodes.values()), 'connections': connections, 'settings': {}}


def _fingerprints(workflow):
    from engine.workflow import effective_workflow
    from services.runs.store.identity import fingerprints_for_workflow

    return fingerprints_for_workflow(effective_workflow(workflow))


def test_a_parents_stored_rows_become_the_sample(store):
    workflow = _workflow()
    store.rows['p1'] = ('run-1', [{'X': '甲'}])
    found = sample_service.samples_for(workflow)
    assert found == {'v': [{'X': '甲'}]}
    assert store.calls == [('p1', _fingerprints(workflow)['p1'], sample_service.SAMPLE_LIMIT)]


def test_two_parents_are_flattened_like_the_engines_fan_in(store):
    workflow = _workflow(('upload', 'upload'))
    store.rows['p1'] = ('run-1', [{'X': '甲'}])
    store.rows['p2'] = ('run-1', [{'X': '乙'}])
    assert sample_service.samples_for(workflow) == {'v': [{'X': '甲'}, {'X': '乙'}]}


def test_a_parent_with_no_stored_run_means_no_sample(store):
    workflow = _workflow()
    assert sample_service.samples_for(workflow) == {}
    assert store.calls, 'the store was asked (and answered "nothing stored")'


def test_a_name_parent_is_metadata_not_data(store):
    workflow = _workflow(('name',))
    assert sample_service.samples_for(workflow) == {}
    assert store.calls == []


def test_a_workflow_without_a_preflighted_node_reads_nothing(store):
    workflow = {
        'nodes': [
            {'id': 'u', 'type': 'upload', 'params': {}},
            {'id': 'o', 'type': 'output', 'params': {'operation': 'save', 'format': 'csv'}},
        ],
        'connections': [{'from': 'u', 'to': 'o'}],
        'settings': {},
    }
    assert sample_service.samples_for(workflow) == {}
    assert store.calls == []


def test_a_sample_is_cached_for_its_ttl(store):
    workflow = _workflow()
    store.rows['p1'] = ('run-1', [{'X': '甲'}])
    sample_service.samples_for(workflow)
    sample_service.samples_for(workflow)
    assert len(store.calls) == 1, 'a diagnostics poll per keystroke must not re-read the table'


def test_the_cache_is_keyed_by_account_root(store, monkeypatch):
    workflow = _workflow()
    store.rows['p1'] = ('run-1', [{'X': '甲'}])
    roots = iter(['/a/runs.db', '/b/runs.db'])
    monkeypatch.setattr(sample_service, '_data_root', lambda: next(roots))
    sample_service.samples_for(workflow)
    sample_service.samples_for(workflow)
    assert len(store.calls) == 2, 'another account must not read the first one’s rows from the cache'


def test_an_empty_but_stored_run_is_a_zero_row_sample(store):
    """A finished producer that really produced nothing is evidence of zero rows; the preflight
    still declines to judge a chart on it, but the distinction is made here, not at the hook."""
    workflow = _workflow()
    store.rows['p1'] = ('run-1', [])
    assert sample_service.samples_for(workflow) == {'v': []}
