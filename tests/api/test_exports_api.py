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
        response = client.get('/api/exports/download', query_string={'name': 'run-a.csv'})
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
        client.get('/api/exports/download', query_string={'name': 'run-a.csv'})
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
