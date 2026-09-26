"""The per-item "lock" (#182): 清空 / 删除 must spare a locked entry.

The panels list 导出产物 / 运行记录 / 工作流文件 and each has a bulk clear and a
per-row delete. A lock is the user's promise that one entry survives both. These
tests pin the HTTP contract on top of the tiny ``lock_store`` — that clearing
spares the locked key, that a direct delete of a locked key is refused (409, not a
silent no-op the panel would then misreport), and that the lock state round-trips
through ``/api/locks``.

``Config.DATA_DIR`` is redirected to a throwaway root by ``tests/conftest.py`` before
``app`` is imported, and ``lock_store`` resolves its file from ``Config.DATA_DIR`` at
call time, so every lock written here lands in the isolated directory, never the user's.
"""

import pytest

pytestmark = pytest.mark.api


@pytest.fixture
def export_dir(tmp_path, monkeypatch):
    import app as app_module

    directory = tmp_path / 'exports'
    directory.mkdir()
    (directory / 'keep.csv').write_text('a,b\n1,2\n', encoding='utf-8')
    (directory / 'drop.csv').write_text('a,b\n3,4\n', encoding='utf-8')
    monkeypatch.setattr(app_module.Config, 'EXPORT_DIR', str(directory))
    return directory


class TestLockRoundTrip:
    def test_locking_then_reading_lists_the_key(self, client):
        posted = client.post('/api/locks', json={'panel': 'exports', 'key': 'keep.csv', 'locked': True}).get_json()
        assert posted['ok'] is True and posted['locks'] == ['keep.csv']
        assert client.get('/api/locks').get_json()['locks']['exports'] == ['keep.csv']

    def test_unlocking_removes_the_key(self, client):
        client.post('/api/locks', json={'panel': 'workflows', 'key': 'flow', 'locked': True})
        after = client.post('/api/locks', json={'panel': 'workflows', 'key': 'flow', 'locked': False}).get_json()
        assert after['locks'] == []

    def test_an_unknown_panel_is_refused(self, client):
        resp = client.post('/api/locks', json={'panel': 'secrets', 'key': 'x', 'locked': True})
        assert resp.get_json()['ok'] is False and resp.status_code == 400

    def test_a_blank_key_is_refused(self, client):
        resp = client.post('/api/locks', json={'panel': 'exports', 'key': '   ', 'locked': True})
        assert resp.status_code == 400


class TestExportsRespectLock:
    def test_clear_spares_the_locked_file_and_removes_the_rest(self, client, export_dir):
        client.post('/api/locks', json={'panel': 'exports', 'key': 'keep.csv', 'locked': True})
        body = client.post('/api/exports/clear', json={'confirm': True}).get_json()
        assert body['removed'] == 1 and body['left'] == 1
        assert (export_dir / 'keep.csv').exists(), 'the locked artefact was swept by 清空'
        assert not (export_dir / 'drop.csv').exists(), 'an unlocked artefact must still go'

    def test_deleting_a_locked_file_is_refused(self, client, export_dir):
        client.post('/api/locks', json={'panel': 'exports', 'key': 'keep.csv', 'locked': True})
        resp = client.post('/api/exports/delete', json={'name': 'keep.csv'})
        assert resp.status_code == 409
        assert (export_dir / 'keep.csv').exists()

    def test_unlocking_releases_the_delete(self, client, export_dir):
        client.post('/api/locks', json={'panel': 'exports', 'key': 'keep.csv', 'locked': True})
        client.post('/api/locks', json={'panel': 'exports', 'key': 'keep.csv', 'locked': False})
        body = client.post('/api/exports/delete', json={'name': 'keep.csv'}).get_json()
        assert body['ok'] is True and not (export_dir / 'keep.csv').exists()


class TestWorkflowsRespectLock:
    def test_deleting_a_locked_workflow_is_refused(self, client):
        client.post('/api/locks', json={'panel': 'workflows', 'key': 'flow-a', 'locked': True})
        resp = client.post('/api/workflow/delete', json={'name': 'flow-a'})
        assert resp.status_code == 409


class TestRunsRespectLock:
    def test_clear_spares_a_locked_run_and_removes_the_rest(self, client, app_module):
        from services.run_store import RUN_COMPLETED

        store = app_module._RUN_STORE
        for run_id in ('r-keep', 'r-drop'):
            store.start_run(run_id, 'wf', 'fp', node_total=0)
            store.finish_run(run_id, RUN_COMPLETED)
        client.post('/api/locks', json={'panel': 'runs', 'key': 'r-keep', 'locked': True})
        body = client.post('/api/runs/clear', json={'confirm': True}).get_json()
        assert body['ok'] is True
        remaining = client.get('/api/runs/list').get_json()['runs']
        ids = {run['run_id'] for run in remaining}
        assert 'r-keep' in ids, '清空 swept a locked run'
        assert 'r-drop' not in ids, 'an unlocked run must still be cleared'

    def test_deleting_a_locked_run_is_refused(self, client, app_module):
        from services.run_store import RUN_COMPLETED

        store = app_module._RUN_STORE
        store.start_run('r-locked', 'wf', 'fp', node_total=0)
        store.finish_run('r-locked', RUN_COMPLETED)
        client.post('/api/locks', json={'panel': 'runs', 'key': 'r-locked', 'locked': True})
        resp = client.post('/api/runs/delete', json={'run_id': 'r-locked'})
        assert resp.status_code == 409
        assert store.get_run('r-locked') is not None
