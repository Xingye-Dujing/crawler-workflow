"""Tests for the export-artefact endpoints: /api/exports/list|download|delete|clear.

The service module owns the path rules; what these tests pin is the HTTP
contract on top of them — a traversal name must answer 404 rather than 500 or
(worse) the file, a request without a ``name`` must be a 400 the caller can fix,
the listing must survive a directory that does not exist yet, because a fresh
install has no exports and an empty panel is the correct answer there, and the
bulk 清空 must reach nothing the single-file button could not have reached.

``Config.EXPORT_DIR`` is repointed at a temp directory per test by the session
fixture, so nothing here can touch the user's real ``data/exports``.
"""

import os
import time

import pytest

from i18n import t

pytestmark = pytest.mark.api


@pytest.fixture
def export_dir(tmp_path, monkeypatch):
    import app as app_module

    directory = tmp_path / 'exports'
    directory.mkdir()
    (directory / 'run-a.csv').write_text('标题,正文\n三亚,攻略\n', encoding='utf-8')
    (directory / 'script.py').write_text('print(1)', encoding='utf-8')
    (tmp_path / 'outside.csv').write_text('secret\n', encoding='utf-8')
    os.utime(directory / 'run-a.csv', (time.time() + 30, time.time() + 30))
    monkeypatch.setattr(app_module.Config, 'EXPORT_DIR', str(directory))
    return str(directory)


class TestList:
    def test_a_fresh_directory_lists_nothing_rather_than_failing(self, client, monkeypatch):
        import app as app_module

        monkeypatch.setattr(app_module.Config, 'EXPORT_DIR', '')
        body = client.get('/api/exports/list').get_json()
        assert body['ok'] is True and body['exports'] == [] and body['files'] == 0

    def test_files_sizes_and_totals_come_back(self, client, export_dir):
        body = client.get('/api/exports/list').get_json()
        assert body['ok'] is True
        assert {row['name'] for row in body['exports']} == {'run-a.csv', 'script.py'}
        assert body['files'] == 2 and body['bytes'] > 0
        assert body['exports'][0]['name'] == 'run-a.csv', 'newest first'
        assert body['exports'][0]['downloadable'] is True
        assert body['exports'][1]['downloadable'] is False, 'a .py in the folder is shown but not served'

    def test_the_limit_pages_the_rows_not_the_totals(self, client, export_dir):
        """``exports`` is the page; ``files``/``bytes`` describe the whole
        directory, so the panel's header cannot tell the user their 400 exports
        are 200 just because the listing was capped."""
        body = client.get('/api/exports/list?limit=1').get_json()
        assert len(body['exports']) == 1 and body['files'] == 2
        # A nonsense limit is a defaulted limit, never a 500 and never 0 rows.
        assert client.get('/api/exports/list?limit=abc').get_json()['files'] == 2
        assert client.get('/api/exports/list?limit=0').get_json()['files'] == 2
        assert len(client.get('/api/exports/list?limit=99999').get_json()['exports']) <= 500


class TestDownload:
    def test_a_real_export_is_sent_as_an_attachment(self, client, export_dir):
        """The response is closed because the route served it from an open file: left to
        the garbage collector it surfaces as a ResourceWarning, and a warning here is a
        test that noticed something and passed anyway."""
        with client.get('/api/exports/download', query_string={'name': 'run-a.csv'}) as response:
            assert response.status_code == 200
            assert 'attachment' in response.headers.get('Content-Disposition', '')
            assert '三亚' in response.get_data(as_text=True)

    @pytest.mark.parametrize(
        'name',
        ['', 'missing.csv', '../outside.csv', '..\\outside.csv', 'sub/deep.csv', '/etc/passwd', None],
    )
    def test_anything_else_is_a_404_never_a_500(self, client, export_dir, name):
        """404 for both "not there" and "not allowed", so the route cannot be
        used to ask whether some path outside the directory exists."""
        response = client.get('/api/exports/download', query_string={'name': name})
        assert response.status_code == 404
        assert response.get_json()['ok'] is False

    def test_a_script_in_the_folder_is_not_served(self, client, export_dir):
        assert client.get('/api/exports/download', query_string={'name': 'script.py'}).status_code == 404

    def test_the_file_survives_a_download(self, client, export_dir):
        with client.get('/api/exports/download', query_string={'name': 'run-a.csv'}):
            pass
        assert os.path.exists(os.path.join(export_dir, 'run-a.csv'))


class TestDelete:
    def test_one_file_goes_and_the_listing_shrinks(self, client, export_dir):
        response = client.post('/api/exports/delete', json={'name': 'run-a.csv'})
        assert response.get_json() == {'ok': True, 'deleted': True, 'name': 'run-a.csv'}
        assert not os.path.exists(os.path.join(export_dir, 'run-a.csv'))
        assert [row['name'] for row in client.get('/api/exports/list').get_json()['exports']] == ['script.py']

    def test_a_missing_name_is_a_400(self, client, export_dir):
        assert client.post('/api/exports/delete', json={}).status_code == 400
        assert client.post('/api/exports/delete', json={'name': '  '}).status_code == 400
        assert client.post('/api/exports/delete', json={'name': 7}).status_code == 400

    @pytest.mark.parametrize('name', ['../outside.csv', 'sub/deep.csv', '/etc/passwd'])
    def test_an_escaping_name_deletes_nothing(self, client, export_dir, tmp_path, name):
        body = client.post('/api/exports/delete', json={'name': name}).get_json()
        assert body['ok'] is False and body['deleted'] is False
        assert (tmp_path / 'outside.csv').exists()

    def test_a_second_delete_reports_false_without_failing(self, client, export_dir):
        assert client.post('/api/exports/delete', json={'name': 'run-a.csv'}).get_json()['ok'] is True
        assert client.post('/api/exports/delete', json={'name': 'run-a.csv'}).get_json()['ok'] is False

    def test_a_malformed_body_is_a_400_not_a_500(self, client, export_dir):
        assert client.post('/api/exports/delete', data='not json', content_type='application/json').status_code == 400


class TestClearAll:
    """``/api/exports/clear`` — the panel's 清空, which must reuse the per-file rules."""

    def test_every_listed_file_goes_and_nothing_outside_the_folder_follows(self, client, export_dir, tmp_path):
        """The bulk route deletes by calling the same resolver the single button calls, over
        exactly the listing the panel shows. That is what keeps the two from drifting: a name
        in a sub-directory is not in the listing, and a sibling of the folder is not either.
        """
        nested = tmp_path / 'exports' / 'sub'
        nested.mkdir()
        (nested / 'deep.csv').write_text('a\n', encoding='utf-8')

        body = client.post('/api/exports/clear', json={'confirm': True}).get_json()

        assert body['ok'] is True
        assert body['removed'] == 2 and body['left'] == 0
        assert not os.path.exists(os.path.join(export_dir, 'run-a.csv'))
        assert not os.path.exists(os.path.join(export_dir, 'script.py'))
        assert (nested / 'deep.csv').exists(), '清空 is not a recursive delete'
        assert (tmp_path / 'outside.csv').exists()

    @pytest.mark.parametrize('payload', [{}, {'confirm': False}, {'confirm': 'yes'}])
    def test_it_refuses_without_an_explicit_confirm(self, client, export_dir, payload):
        assert client.post('/api/exports/clear', json=payload).status_code == 400
        assert os.path.exists(os.path.join(export_dir, 'run-a.csv'))

    def test_a_run_that_is_writing_part_files_here_is_refused_outright(self, client, app_module, export_dir):
        """A streaming node appends into this very directory, and the panel cannot tell a
        finished artefact from one still being written — so unlike the run records (which
        spare the live row and clear the rest), this one declines the whole request."""
        app_module.execution_state.update({'running': True, 'run_id': 'r-live'})
        try:
            response = client.post('/api/exports/clear', json={'confirm': True})
        finally:
            app_module.execution_state.update({'running': False, 'run_id': ''})
        assert response.status_code == 409
        assert t('exports.clearBusy') in response.get_json()['error']
        assert os.path.exists(os.path.join(export_dir, 'run-a.csv'))

    def test_an_empty_folder_is_a_clean_answer_rather_than_an_error(self, client, export_dir):
        assert client.post('/api/exports/clear', json={'confirm': True}).get_json() == {
            'ok': True,
            'removed': 2,
            'left': 0,
        }
        assert client.post('/api/exports/clear', json={'confirm': True}).get_json() == {
            'ok': True,
            'removed': 0,
            'left': 0,
        }

    def test_a_folder_larger_than_the_listing_cap_is_still_emptied(self, client, export_dir):
        """The panel's list is capped (``MAX_ENTRIES``) while 清空 promises the whole folder.

        One pass over a truncated listing would delete the newest few hundred and reload a
        panel that still holds files — reporting a clear that did not happen. So the clear
        repeats until a pass removes nothing, and this proves it against the real cap.
        """
        from services.export_browser import MAX_ENTRIES

        for index in range(MAX_ENTRIES + 3):
            with open(os.path.join(export_dir, f'bulk-{index}.csv'), 'w', encoding='utf-8') as handle:
                handle.write('a\n')
        before = len(os.listdir(export_dir))
        assert before > MAX_ENTRIES, 'the fixture must actually overflow the listing'

        body = client.post('/api/exports/clear', json={'confirm': True}).get_json()

        assert body['ok'] is True
        assert body['removed'] == before and body['left'] == 0
        assert os.listdir(export_dir) == []


class TestSmartClear:
    """``/api/exports/ledger`` + ``/clear-run`` + ``/clear-run-parts`` — the 智能清除 pair.

    These act on the run→files ledger, not a directory scan: a run's files are what the ledger
    says they are. The tests seed a run's files through the real store (the same singleton the
    route reads), create them on disk in the temp export dir, then assert what a clear removes,
    what it keeps (a 「固定」 file; the merged file under a shards-only clear; the OTHER node's
    shards), and that the ledger tracks reality afterwards.
    """

    def _seed(self, app_module, export_dir, run_id, entries):
        """Create each ``(node_id, name, kind)`` file on disk and record it against *run_id*."""
        store = app_module.get_run_store()
        store.start_run(run_id, '热门榜', 'fp-smart')
        for node_id, name, kind in entries:
            with open(os.path.join(export_dir, name), 'w', encoding='utf-8') as handle:
                handle.write('x\n')
            store.record_file(run_id, node_id, name, kind)
        return store

    def test_the_ledger_lists_only_runs_that_wrote_files(self, client, app_module, export_dir):
        self._seed(app_module, export_dir, 'r1', [('node-2', 'a.part001.csv', 'part'), ('', 'a.csv', 'merged')])
        ledger = client.get('/api/exports/ledger').get_json()['ledger']
        assert [e['run_id'] for e in ledger] == ['r1']
        assert ledger[0]['workflow_name'] == '热门榜'
        assert {f['name'] for f in ledger[0]['files']} == {'a.part001.csv', 'a.csv'}
        assert ledger[0]['node_ids'] == ['node-2']
        # A run that wrote nothing is not offered — the selector is only ever actionable entries.
        app_module.get_run_store().start_run('r-empty', '空', 'fp-e')
        assert 'r-empty' not in [e['run_id'] for e in client.get('/api/exports/ledger').get_json()['ledger']]

    def test_clear_run_removes_every_file_the_record_wrote(self, client, app_module, export_dir):
        store = self._seed(
            app_module,
            export_dir,
            'r1',
            [
                ('node-2', 'a.part001.csv', 'part'),
                ('node-2', 'a.csv', 'merged'),
                ('node-2', 'a.live.csv', 'live'),
                ('', 'report-x.html', 'report'),
            ],
        )
        body = client.post('/api/exports/clear-run', json={'run_id': 'r1', 'confirm': True}).get_json()
        assert body['ok'] is True and body['removed'] == 4 and body['requested'] == 4
        for name in ('a.part001.csv', 'a.csv', 'a.live.csv', 'report-x.html'):
            assert not os.path.exists(os.path.join(export_dir, name))
        assert os.path.exists(os.path.join(export_dir, 'run-a.csv')), (
            '按运行清除 is not 清空: files no run wrote stay put'
        )
        assert store.files_for_run('r1') == [], 'the map follows the files it described'

    def test_clear_run_skips_a_pinned_file_and_keeps_its_ledger_row(self, client, app_module, export_dir):
        from services import lock_store

        store = self._seed(app_module, export_dir, 'r1', [('node-2', 'a.csv', 'merged'), ('node-2', 'b.csv', 'export')])
        lock_store.set_locked('exports', 'a.csv', True)
        try:
            body = client.post('/api/exports/clear-run', json={'run_id': 'r1', 'confirm': True}).get_json()
        finally:
            lock_store.set_locked('exports', 'a.csv', False)
        assert body['removed'] == 1 and body['skipped_locked'] == 1
        assert os.path.exists(os.path.join(export_dir, 'a.csv')), '「固定」 outlives a clear'
        assert not os.path.exists(os.path.join(export_dir, 'b.csv'))
        # The skipped file is still in the ledger (it exists); the removed one is forgotten.
        assert {f['name'] for f in store.files_for_run('r1')} == {'a.csv'}

    def test_clear_run_refuses_without_confirm_and_while_a_run_is_writing(self, client, app_module, export_dir):
        self._seed(app_module, export_dir, 'r1', [('node-2', 'a.csv', 'merged')])
        assert client.post('/api/exports/clear-run', json={'run_id': 'r1'}).status_code == 400
        assert os.path.exists(os.path.join(export_dir, 'a.csv'))
        assert client.post('/api/exports/clear-run', json={'run_id': '', 'confirm': True}).status_code == 400
        app_module.execution_state.update({'running': True, 'run_id': 'r-live'})
        try:
            response = client.post('/api/exports/clear-run', json={'run_id': 'r1', 'confirm': True})
        finally:
            app_module.execution_state.update({'running': False, 'run_id': ''})
        assert response.status_code == 409
        assert t('exports.clearBusy') in response.get_json()['error']
        assert os.path.exists(os.path.join(export_dir, 'a.csv'))

    def test_clear_run_leaves_the_run_record_and_rows_untouched(self, client, app_module, export_dir):
        # This clears DISK artefacts, not history: the record and its checkpointed rows survive.
        store = self._seed(app_module, export_dir, 'r1', [('node-2', 'a.csv', 'merged')])
        store.begin_node('r1', 'node-2', 'source', '标题', 'fp')
        store.append_rows('r1', 'node-2', [{'正文': '三亚'}])
        client.post('/api/exports/clear-run', json={'run_id': 'r1', 'confirm': True})
        assert store.get_run('r1') is not None
        assert len(store.load_rows('r1', 'node-2')) == 1

    def test_clear_run_parts_targets_only_that_nodes_shards(self, client, app_module, export_dir):
        store = self._seed(
            app_module,
            export_dir,
            'r1',
            [
                ('node-2', 'a.part001.csv', 'part'),
                ('node-2', 'a.part002.csv', 'part'),
                ('node-2', 'a.csv', 'merged'),
                ('node-3', 'b.part001.csv', 'part'),
                ('node-3', 'b.csv', 'merged'),
            ],
        )
        body = client.post(
            '/api/exports/clear-run-parts', json={'run_id': 'r1', 'node_id': 'node-2', 'confirm': True}
        ).get_json()
        assert body['ok'] is True and body['removed'] == 2 and body['requested'] == 2
        for name in ('a.part001.csv', 'a.part002.csv'):
            assert not os.path.exists(os.path.join(export_dir, name)), 'the target node’s shards go'
        for name in ('a.csv', 'b.part001.csv', 'b.csv'):
            assert os.path.exists(os.path.join(export_dir, name)), 'merged + the OTHER node survive untouched'
        # node-2 keeps its merged row but loses the part rows; node-3 is entirely intact.
        assert {f['name'] for f in store.files_for_run('r1', node_id='node-2')} == {'a.csv'}
        assert {f['name'] for f in store.files_for_run('r1', node_id='node-3')} == {'b.part001.csv', 'b.csv'}

    def test_clear_run_parts_refuses_without_confirm(self, client, app_module, export_dir):
        self._seed(app_module, export_dir, 'r1', [('node-2', 'a.part001.csv', 'part')])
        assert (
            client.post('/api/exports/clear-run-parts', json={'run_id': 'r1', 'node_id': 'node-2'}).status_code == 400
        )
        assert client.post('/api/exports/clear-run-parts', json={'run_id': 'r1', 'confirm': True}).status_code == 400, (
            'a node_id is required'
        )
        assert os.path.exists(os.path.join(export_dir, 'a.part001.csv'))

    def test_clearing_a_single_file_forgets_it_from_every_ledger(self, client, app_module, export_dir):
        # The per-row 删除 and 清空 must not leave a ledger promising a file that is gone.
        self._seed(app_module, export_dir, 'r1', [('node-2', 'a.csv', 'merged')])
        client.post('/api/exports/delete', json={'name': 'a.csv'})
        assert 'r1' not in [e['run_id'] for e in client.get('/api/exports/ledger').get_json()['ledger']]


class TestClearName:
    """``/api/exports/clear-name`` removes one shard BATCH by name (the panel's per-shard button).
    The whole value is in what it refuses to touch: the merged file, other stems, other extensions
    and 「固定」pinned shards survive, and a non-shard name / a missing confirm / a live run are each refused."""

    def _seed_shards(self, export_dir):
        for name in ['a.part000.csv', 'a.part001.csv', 'a.csv', 'b.part000.csv', 'a.part000.json']:
            with open(os.path.join(export_dir, name), 'w', encoding='utf-8') as handle:
                handle.write('x\n')

    def test_clears_the_whole_batch_and_keeps_merged_and_other_kinds(self, client, export_dir):
        self._seed_shards(export_dir)
        body = client.post('/api/exports/clear-name', json={'name': 'a.part000.csv', 'confirm': True}).get_json()
        assert body['ok'] is True and body['removed'] == 2 and body['requested'] == 2, body
        assert not os.path.exists(os.path.join(export_dir, 'a.part000.csv'))
        assert not os.path.exists(os.path.join(export_dir, 'a.part001.csv'))
        assert os.path.exists(os.path.join(export_dir, 'a.csv')), 'the merged file must survive a shard-batch clear'
        assert os.path.exists(os.path.join(export_dir, 'b.part000.csv')), 'a different stem must survive'
        assert os.path.exists(os.path.join(export_dir, 'a.part000.json')), 'a different extension must survive'

    def test_a_non_shard_name_is_refused_by_name(self, client, export_dir):
        self._seed_shards(export_dir)
        response = client.post('/api/exports/clear-name', json={'name': 'a.csv', 'confirm': True})
        assert response.status_code == 400, 'a merged file is not a batch; the route must name the refusal'
        assert os.path.exists(os.path.join(export_dir, 'a.part000.csv')), 'a refusal deletes nothing'

    def test_it_refuses_without_an_explicit_confirm(self, client, export_dir):
        self._seed_shards(export_dir)
        assert client.post('/api/exports/clear-name', json={'name': 'a.part000.csv'}).status_code == 400
        assert os.path.exists(os.path.join(export_dir, 'a.part001.csv'))

    def test_a_live_run_is_refused_outright(self, client, app_module, export_dir):
        self._seed_shards(export_dir)
        app_module.execution_state.update({'running': True, 'run_id': 'r-live'})
        try:
            response = client.post('/api/exports/clear-name', json={'name': 'a.part000.csv', 'confirm': True})
            assert response.status_code == 409, 'a streaming node is writing these very shards'
        finally:
            app_module.execution_state.update({'running': False, 'run_id': ''})
        assert os.path.exists(os.path.join(export_dir, 'a.part001.csv')), 'a refused clear touches nothing'

    def test_a_pinned_shard_is_kept_and_reported(self, client, export_dir):
        self._seed_shards(export_dir)
        client.post('/api/locks', json={'panel': 'exports', 'key': 'a.part001.csv', 'locked': True})
        try:
            body = client.post('/api/exports/clear-name', json={'name': 'a.part000.csv', 'confirm': True}).get_json()
            assert body['removed'] == 1 and body['skipped_locked'] == 1, body
            assert os.path.exists(os.path.join(export_dir, 'a.part001.csv')), 'a 固定 shard outlives the batch clear'
        finally:
            # Release the pin: the lock store is process-wide, and a left-behind 「固定」 entry
            # would make a later test that asserts the exact lock set see a key it never added.
            client.post('/api/locks', json={'panel': 'exports', 'key': 'a.part001.csv', 'locked': False})
