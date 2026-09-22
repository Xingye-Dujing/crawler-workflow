"""Tests for the export-artefact endpoints: /api/exports/list|download|delete.

The service module owns the path rules; what these tests pin is the HTTP
contract on top of them — a traversal name must answer 404 rather than 500 or
(worse) the file, a request without a ``name`` must be a 400 the caller can fix,
and the listing must survive a directory that does not exist yet, because a
fresh install has no exports and an empty panel is the correct answer there.

``Config.EXPORT_DIR`` is repointed at a temp directory per test by the session
fixture, so nothing here can touch the user's real ``data/exports``.
"""

import os
import time

import pytest

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
