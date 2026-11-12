"""The two routes the environment panel reads and the install job it starts.

The probe itself is exercised in ``tests/unit/components``; here the boundary is the HTTP shape:
a GET never downloads, an unknown component is a 400, and a running install is a job the panel can
poll. ``environment`` is stubbed so this case cannot touch Chrome or Ollama.
"""

from __future__ import annotations

import pytest
from api import components as components_api

from services.components import jobs


@pytest.fixture(autouse=True)
def _reset_jobs():
    jobs.reset()
    yield
    jobs.reset()


def test_environment_answers_the_matrix_without_probing_devices(client, monkeypatch):
    report = {
        'schema': 1,
        'os': 'win32',
        'root': 'C:/CaiXiHui/components',
        'capabilities': [{'id': 'core', 'label_key': 'env.capCore', 'state': 'ok', 'reason_key': 'env.coreOk'}],
        'components': [],
        'catalog': {'generated_at': '', 'components': 0},
    }
    monkeypatch.setattr(components_api, 'environment', lambda: report)
    body = client.get('/api/environment').get_json()
    assert body['ok'] is True
    assert body['capabilities'][0]['id'] == 'core'
    assert body['root'].endswith('components')


def test_the_environment_reports_both_the_running_and_the_stored_source(client, monkeypatch):
    """The panel needs the stored choice for its buttons and the running one for the matrix:
    they differ right after a switch, and the row must not describe a browser this process
    will never launch."""
    report = {
        'schema': 1,
        'os': 'win32',
        'root': 'C:/CaiXiHui/components',
        'component_source': 'bundled',
        'component_source_preference': 'system',
        'capabilities': [
            {'id': 'crawl_selenium', 'label_key': 'env.capBrowser', 'state': 'ok', 'reason_key': 'env.browserOk'},
        ],
        'components': [],
        'catalog': {'generated_at': '', 'components': 0},
    }
    monkeypatch.setattr(components_api, 'environment', lambda: report)
    body = client.get('/api/environment').get_json()
    assert body['component_source'] == 'bundled'
    assert body['component_source_preference'] == 'system'


def _windows_assets(monkeypatch):
    """The installer's catalogue is Windows-only; ask it for that OS on every test runner."""
    from services.components import catalog as catalog_module

    monkeypatch.setattr(catalog_module, 'platform_asset_key', lambda system=None, machine=None: 'win32')


def test_the_catalogue_lists_the_domestic_defaults(client, monkeypatch):
    _windows_assets(monkeypatch)
    body = client.get('/api/components').get_json()
    assert body['ok'] is True
    rows = {row['id']: row for row in body['components']}
    assert {'app', 'chrome', 'chromedriver', 'node', 'catbus'} <= set(rows)
    assert rows['chrome']['downloadable'] is True
    assert rows['xelatex']['downloadable'] is False, 'detection-only components are not downloaded'
    assert rows['app']['downloadable'] is False, 'the running app cannot replace itself; the installer does that'


def test_the_catalogue_tells_the_panel_whether_an_installer_tree_exists(client, monkeypatch):
    """A source checkout must not be offered “安装器安装的”: the page hides the picker
    and the installer-managed rows from this answer, not from a guess."""
    _windows_assets(monkeypatch)
    monkeypatch.setattr(components_api.component_source, 'installer_available', lambda: False)
    monkeypatch.setattr(components_api.component_source, 'effective', lambda: 'system')
    body = client.get('/api/components').get_json()
    assert body['installer_available'] is False
    assert body['component_source'] == 'system'


def test_a_record_whose_folder_is_gone_is_not_an_installation(client, monkeypatch, tmp_path):
    import shutil

    from services.components.manifest import Manifest

    root = tmp_path / 'install'
    target = root / 'components' / 'node' / '24.0.0'
    target.mkdir(parents=True)
    record = Manifest(root)
    record.record('node', '24.0.0', target, 'a' * 64, 'https://example.com')
    record.save()
    monkeypatch.setattr(components_api, 'install_root', lambda: root)
    rows = {row['id']: row for row in client.get('/api/components').get_json()['components']}
    assert rows['node']['installed'] == '24.0.0'
    shutil.rmtree(target)
    rows = {row['id']: row for row in client.get('/api/components').get_json()['components']}
    assert rows['node']['installed'] == '', 'the manifest record outlived the files it names'


def test_an_unknown_component_is_refused_before_any_download(client):
    response = client.post('/api/components/install', json={'id': 'nope'})
    assert response.status_code == 400
    body = response.get_json()
    assert body['ok'] is False and 'nope' in body['error']


def test_a_detection_only_component_says_so_instead_of_starting_a_failed_job(client, monkeypatch):
    started = []
    monkeypatch.setattr(components_api.jobs, 'start', lambda *args, **kwargs: started.append(args))
    response = client.post('/api/components/install', json={'id': 'xelatex'})
    assert response.status_code == 400
    assert 'xelatex' in response.get_json()['error']
    assert started == [], 'a manual component must not reach the downloader'


def test_the_running_application_refuses_to_install_itself(client, monkeypatch):
    from i18n import t

    started = []
    monkeypatch.setattr(components_api.jobs, 'start', lambda *args, **kwargs: started.append(args))
    response = client.post('/api/components/install', json={'id': 'app'})
    assert response.status_code == 400
    assert response.get_json()['error'] == t('components.appNotSelfInstallable')
    assert started == [], 'the app updates through the installer, never through its own process'


def test_the_panel_reads_the_manifest_from_the_install_root(client, monkeypatch, tmp_path):
    from services.components.manifest import Manifest

    root = tmp_path / 'install'
    target = root / 'components' / 'node' / '24.0.0'
    target.mkdir(parents=True)
    record = Manifest(root)
    record.record('node', '24.0.0', target, 'a' * 64, 'https://example.com')
    record.save()
    monkeypatch.setattr(components_api, 'install_root', lambda: root)
    rows = {row['id']: row for row in client.get('/api/components').get_json()['components']}
    assert rows['node']['installed'] == '24.0.0', 'the manifest lives one level above components/'


def test_install_starts_a_job_and_the_job_can_be_polled(client, monkeypatch):
    _windows_assets(monkeypatch)
    monkeypatch.setattr(
        components_api.jobs,
        'start',
        lambda catalog, component_id, root: {
            'id': 'job1',
            'component': component_id,
            'state': 'running',
            'done': 0,
            'total': 10,
            'error': '',
            'path': '',
            'cancellable': True,
        },
    )
    started = client.post('/api/components/install', json={'id': 'node'}).get_json()
    assert started['ok'] is True and started['job']['id'] == 'job1'
    monkeypatch.setattr(components_api.jobs, 'get', lambda job_id: started['job'] if job_id == 'job1' else None)
    polled = client.get('/api/components/jobs/job1').get_json()
    assert polled['job']['state'] == 'running'
    assert client.get('/api/components/jobs/missing').status_code == 404


def test_the_application_itself_cannot_be_removed_from_the_panel(client):
    response = client.post('/api/components/remove', json={'id': 'app'})
    assert response.status_code == 400
    assert response.get_json()['ok'] is False
