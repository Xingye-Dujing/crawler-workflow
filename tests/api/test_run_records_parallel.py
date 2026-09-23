"""One run record for a parallel run — with every workflow's name, and what it says about itself.

A canvas can hold several workflows at once (each headed by its own name node). They
are executed as **one** run and recorded as one run, which is correct — that is what
happened. What was wrong is that the record was labelled with the *first* name only,
so a user who ran 热门榜 and 周排行榜 together saw one record called 热门榜 and concluded
the other run's record had been deleted.

Pinned here:

* the stored name carries **every** label, joined in canvas order, and a single-workflow
  run is stored under its plain name exactly as before (identity, not just display:
  the row lookups a refresh depends on match this string);
* a preview still resolves the rows of a run recorded *before* the composition existed —
  the lookup is offered both spellings, because dropping that would make a week-old run
  uninspectable to "fix" a label;
* ``wf_count`` survives an old database (the column is added on open, and every
  pre-existing row reads as one workflow, which is what it was);
* the panel says 并行 ×N and 无头/窗口 from the stored fields, never from a guess.
"""

import json

import pytest
from run_wait import run_finished

from services.run_store import RunStore

pytestmark = [pytest.mark.api, pytest.mark.serial]

RECORDS = [{'标题': f'文{i}', '正文': f'正文{i}', '点赞': i} for i in range(1, 5)]


def _node(nid, ntype, params=None, operation=''):
    node = {'id': nid, 'type': ntype, 'title': ntype, 'params': params or {}}
    if operation:
        node['operation'] = operation
    return node


def _wf(nodes, conns, mode='parallel'):
    return {'nodes': nodes, 'connections': conns, 'settings': {'mode': mode}}


def _two_workflows(ds):
    """Two disconnected upload→output workflows, each with its own name node."""
    nodes = [
        _node('name-1', 'name', {'workflow_name': '热门榜'}),
        _node('up-1', 'upload', {'dataset_id': ds, 'row_count': len(RECORDS)}),
        _node('out-1', 'output', {'filename': 'a.csv'}, 'save_csv'),
        _node('name-2', 'name', {'workflow_name': '周排行榜'}),
        _node('up-2', 'upload', {'dataset_id': ds, 'row_count': len(RECORDS)}),
        _node('out-2', 'output', {'filename': 'b.csv'}, 'save_csv'),
    ]
    conns = [
        {'from': 'name-1', 'to': 'up-1'},
        {'from': 'up-1', 'to': 'out-1'},
        {'from': 'name-2', 'to': 'up-2'},
        {'from': 'up-2', 'to': 'out-2'},
    ]
    return _wf(nodes, conns)


def _one_workflow(ds):
    nodes = [
        _node('name-1', 'name', {'workflow_name': '只看排行榜'}),
        _node('up-1', 'upload', {'dataset_id': ds, 'row_count': len(RECORDS)}),
        _node('out-1', 'output', {'filename': 'one.csv'}, 'save_csv'),
    ]
    conns = [{'from': 'name-1', 'to': 'up-1'}, {'from': 'up-1', 'to': 'out-1'}]
    return _wf(nodes, conns, mode='serial')


def _run(client, app_module, workflow, name, **extra):
    response = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': name, **extra})
    assert response.get_json().get('ok'), response.get_json()
    assert run_finished(app_module), 'the run never settled'


def _listed(client):
    body = client.get('/api/runs/list').get_json()
    assert body['ok'] is True
    return body['runs']


class TestRecordedName:
    def test_a_parallel_run_is_labelled_with_every_workflow(self, client, app_module, paste):
        _run(client, app_module, _two_workflows(paste(RECORDS, name='ranks')), 'ranks')
        runs = _listed(client)
        assert len(runs) == 1, f'parallel workflows must stay one record, got {len(runs)}'
        assert runs[0]['workflow_name'] == '热门榜 + 周排行榜'
        assert runs[0]['wf_count'] == 2

    def test_a_single_workflow_run_is_still_named_exactly_as_before(self, client, app_module, paste):
        """The label is also the key a refresh looks rows up by, so a lone workflow
        must not acquire a separator or its stored rows become unreachable."""
        _run(client, app_module, _one_workflow(paste(RECORDS, name='solo')), 'solo')
        runs = _listed(client)
        assert runs[0]['workflow_name'] == '只看排行榜'
        assert runs[0]['wf_count'] == 1

    def test_the_names_are_the_workflows_own_labels_not_the_name_the_browser_sent(self, client, app_module, paste):
        """``workflow_name`` in the request is a fallback (a canvas with no name node
        files under its saved file name); naming the workflows is the user's call."""
        _run(client, app_module, _two_workflows(paste(RECORDS, name='ranks')), '哔哩哔哩.json')
        assert _listed(client)[0]['workflow_name'] == '热门榜 + 周排行榜'

    def test_a_run_whose_workflows_share_a_label_is_not_written_twice(self, client, app_module, paste):
        """Two workflows named 热门榜 are one name in the record, not
        ``热门榜 + 热门榜`` — the chips and the lookup both read that string."""
        workflow = _two_workflows(paste(RECORDS, name='ranks'))
        workflow['nodes'][3]['params']['workflow_name'] = '热门榜'
        _run(client, app_module, workflow, 'dup')
        record = _listed(client)[0]
        assert record['workflow_name'] == '热门榜'
        assert record['wf_count'] == 2, 'the label collapsed, but two workflows still ran'


def _stored_node(store):
    """One node id that actually has rows in this database.

    Read from the store rather than written down: which node persists rows is the
    executor's business (an Upload re-reads its file, an Output writes rows), and a
    test that guesses a node id would pass on an empty result.
    """
    rows = store._query('SELECT node_id FROM node_rows LIMIT 1')
    assert rows, 'nothing stored any rows, so the lookup below would prove nothing'
    return str(rows[0]['node_id'])


class TestRowLookupStillWorks:
    def test_rows_recorded_under_a_single_label_resolve_for_a_composed_lookup(self, client, app_module, paste):
        """``A + B`` is the new spelling, ``A`` the old one.

        A preview asks by the composed name; a run recorded before this change filed
        its rows under the lone label. Refusing the old spelling would leave last
        week's data unopenable, which is not what a labelling fix is for.

        The live results are dropped first: while the process still holds them the
        preview answers from memory and never reaches the lookup under test.
        """
        _run(client, app_module, _one_workflow(paste(RECORDS, name='solo')), 'solo')
        store = app_module.get_run_store()
        node = _stored_node(store)
        app_module.execution_state['results'] = {}
        body = client.post('/api/data/preview', json={'node_id': node, 'workflow_name': '只看排行榜 + 别的'}).get_json()
        assert body['ok'] is True, body
        assert len(body['rows']) == len(RECORDS), 'a lookup that only matches the exact new spelling strands older runs'

    def test_a_foreign_workflow_still_resolves_to_nothing(self, client, app_module, paste):
        """The candidate list widens spelling, not ownership: a node id alone is how
        a stranger's table ends up under the user's own node name."""
        _run(client, app_module, _one_workflow(paste(RECORDS, name='solo')), 'solo')
        store = app_module.get_run_store()
        node = _stored_node(store)
        app_module.execution_state['results'] = {}
        body = client.post(
            '/api/data/preview', json={'node_id': node, 'workflow_name': '别人的画布 + 另一个'}
        ).get_json()
        assert body['ok'] is False, f'an unrelated canvas must not be handed these rows: {body}'


class TestOldDatabaseMigrates:
    def test_a_database_created_without_the_column_reads_as_one_workflow(self, tmp_path):
        # ``CREATE TABLE IF NOT EXISTS`` leaves an existing database in the shape it
        # was created in, so a run recorded before wf_count existed would have no
        # value for the panel to read; ADD COLUMN with a default gives every old row
        # the honest one.
        path = str(tmp_path / 'runs.db')
        first = RunStore(path)
        first.start_run('r1', '旧的', 'fp1')
        # Settled on purpose: an open run would also make the reopen below report a
        # stale-record promotion, which is a different feature and would write a
        # console line into whatever test runs next.
        first.finish_run('r1', 'completed')

        import sqlite3

        with sqlite3.connect(path) as conn:
            conn.execute('ALTER TABLE runs DROP COLUMN wf_count')

        reopened = RunStore(path)
        row = reopened.get_run('r1')
        assert row['wf_count'] == 1, 'an old row is a one-workflow run, whatever the panel guesses'
        reopened.start_run('r2', '新的', 'fp2', wf_count=3)
        assert reopened.get_run('r2')['wf_count'] == 3


class TestParallelResumeIndependence:
    """Each workflow inside a parallel run keeps its own 断点续跑 state.

    One record does not mean one checkpoint. The canvas ran 热门榜 and 周排行榜 as a
    single run, and if the resume state were shared, continuing after the second
    workflow's export failed would either re-run the first one's work or — worse —
    hand the first workflow's rows to the second and call it "restored". Both
    directions are pinned here: unchanged nodes come back per workflow, an edited
    node is recomputed for its own workflow only.
    """

    STEPS_HOT = [{'op': 'filter_rows', 'params': {'column': '城市', 'op': 'eq', 'value': '三亚'}}]
    STEPS_WEEK = [{'op': 'filter_rows', 'params': {'column': '城市', 'op': 'eq', 'value': '海口'}}]

    CITIES = [{'城市': '三亚', '热度': 1}, {'城市': '海口', '热度': 2}, {'城市': '三亚', '热度': 3}]

    def _flow(self, ds, export_b='parquet', steps_a=None):
        """Two chains; only B's export is broken, so the run is resumable."""
        nodes = [
            _node('name-1', 'name', {'workflow_name': '热门榜'}),
            _node('up-1', 'upload', {'dataset_id': ds, 'row_count': len(self.CITIES)}),
            _node('an-1', 'analysis', {'steps': steps_a or self.STEPS_HOT}),
            _node('out-1', 'output', {'format': 'csv', 'filename': 'hot'}, 'save'),
            _node('name-2', 'name', {'workflow_name': '周排行榜'}),
            _node('up-2', 'upload', {'dataset_id': ds, 'row_count': len(self.CITIES)}),
            _node('an-2', 'analysis', {'steps': self.STEPS_WEEK}),
            _node('out-2', 'output', {'format': export_b, 'filename': 'week'}, 'save'),
        ]
        conns = [
            {'from': 'name-1', 'to': 'up-1'},
            {'from': 'up-1', 'to': 'an-1'},
            {'from': 'an-1', 'to': 'out-1'},
            {'from': 'name-2', 'to': 'up-2'},
            {'from': 'up-2', 'to': 'an-2'},
            {'from': 'an-2', 'to': 'out-2'},
        ]
        return _wf(nodes, conns)

    @pytest.fixture
    def first_attempt(self, client, app_module, paste):
        """A parallel run whose second workflow died after the first one finished."""
        ds = paste(self.CITIES, name='cities')
        started = client.post('/api/workflow/execute', json={'workflow': self._flow(ds), 'workflow_name': 'cities'})
        assert started.status_code == 200, started.get_json()
        run_id = started.get_json()['run_id']
        assert run_finished(app_module), 'the run never settled'
        return ds, run_id

    def test_the_failed_parallel_run_is_one_resumable_record_of_both_names(self, client, app_module, first_attempt):
        _ds, run_id = first_attempt
        record = app_module.get_run_store().get_run(run_id)
        assert record['status'] == 'failed', record['note']
        assert record['workflow_name'] == '热门榜 + 周排行榜'
        assert record['wf_count'] == 2
        listed = client.post('/api/runs/resumable', json={'workflow': self._flow('unused')}).get_json()
        assert run_id in [entry['run_id'] for entry in listed['runs']], listed

    def test_each_workflow_resumes_with_its_own_rows(self, client, app_module, first_attempt):
        """The point of the whole feature: both components continue, and neither
        borrows the other's data."""
        ds, run_id = first_attempt
        store = app_module.get_run_store()
        before = {nid: store.row_count(run_id, nid) for nid in ('an-1', 'an-2')}
        assert [row['城市'] for row in store.load_rows(run_id, 'an-1')] == ['三亚', '三亚'], before
        assert [row['城市'] for row in store.load_rows(run_id, 'an-2')] == ['海口'], before

        continued = client.post(
            '/api/workflow/execute',
            json={'workflow': self._flow(ds, export_b='csv'), 'workflow_name': 'cities', 'resume_run_id': run_id},
        )
        assert continued.status_code == 200, continued.get_json()
        assert run_finished(app_module), 'the continued run never settled'

        after = app_module.get_run_store().get_run(run_id)
        assert after['status'] == 'completed', after['note']
        nodes = {node['node_id']: node for node in after['nodes']}
        assert nodes['an-1']['status'] == 'restored', nodes['an-1']
        assert nodes['an-2']['status'] == 'restored', nodes['an-2']
        assert nodes['out-1']['status'] == 'restored', nodes['out-1']
        kept = [row['城市'] for row in store.load_rows(run_id, 'an-1')]
        assert kept == ['三亚', '三亚'], 'workflow A lost its own rows'
        assert [row['城市'] for row in store.load_rows(run_id, 'an-2')] == ['海口'], 'workflow B lost its own rows'
        assert {nid: store.row_count(run_id, nid) for nid in ('an-1', 'an-2')} == before, 'a continue re-stored rows'
        names = [record['workflow_name'] for record in _listed(client)]
        assert names == ['热门榜 + 周排行榜'], 'one record, both names'

    def test_editing_one_workflow_leaves_the_other_one_restored(self, client, app_module, first_attempt):
        """Independence the other way: narrowing 热门榜 must not silently keep its
        old answer, and must not cost 周排行榜 a second pass either."""
        ds, run_id = first_attempt
        flow = self._flow(ds, export_b='csv', steps_a=self.STEPS_WEEK)
        client.post(
            '/api/workflow/execute', json={'workflow': flow, 'workflow_name': 'cities', 'resume_run_id': run_id}
        )
        assert run_finished(app_module)
        nodes = {node['node_id']: node for node in app_module.get_run_store().get_run(run_id)['nodes']}
        assert nodes['an-1']['status'] != 'restored', 'an edited node was reported as reused'
        assert nodes['an-2']['status'] == 'restored', "the other workflow paid for work it didn't need"
        rows = app_module.get_run_store().load_rows(run_id, 'an-1')
        assert [row['城市'] for row in rows] == ['海口'], f'the edited filter is what must have run: {rows}'


class TestPanelTags:
    """The chips beside the name are read from stored facts (mode, wf_count, headless)."""

    def test_a_parallel_record_carries_both_facts_the_chips_render_from(self, client, app_module, paste):
        _run(client, app_module, _two_workflows(paste(RECORDS, name='ranks')), 'ranks')
        record = _listed(client)[0]
        assert record['mode'] == 'parallel'
        assert record['wf_count'] == 2
        assert record['headless'] == 1, 'the default is a headless run, and 无头 must not be invented'
        # The label text itself is built in JS from these three fields (see
        # harness_runsmgr.mjs); no string here has to be parsed for it.
        assert json.dumps(record['workflow_name'])

    def test_the_same_canvas_run_serially_is_stored_as_serial(self, client, app_module, paste):
        """Two workflows and one workflow-at-a-time are different facts, and the
        record has to keep them apart: labelling a 串行 run 并行 describes a
        concurrency that never happened (this is what a user caught on screen)."""
        flow = _two_workflows(paste(RECORDS, name='ranks'))
        flow['settings']['mode'] = 'serial'
        _run(client, app_module, flow, 'ranks')
        record = _listed(client)[0]
        assert record['mode'] == 'serial'
        assert record['wf_count'] == 2, 'it did run both workflows — just not at the same time'
        assert record['workflow_name'] == '热门榜 + 周排行榜', 'the naming rule does not depend on the mode'

    def test_a_visible_window_run_is_stored_differently_from_a_headless_one(self, client, app_module, paste):
        """Otherwise 窗口 could never appear and 无头 would be printed on every record."""
        workflow = _two_workflows(paste(RECORDS, name='ranks'))
        workflow['settings']['headless'] = False
        _run(client, app_module, workflow, 'ranks')
        assert _listed(client)[0]['headless'] == 0
