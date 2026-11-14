"""Settings presets and the export/import package.

The store's ordinary save is covered by ``test_settings_api.py``; this file pins the
two features that move a *whole* configuration: the 慢速采集 preset (apply/restore with
an exact snapshot) and the portable package (machine paths opt-in, unknown keys
reported, dry-run first).
"""

import json

import pytest
from runtime import settings

pytestmark = pytest.mark.api


@pytest.fixture(autouse=True)
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / 'settings.json'
    monkeypatch.setattr(settings, '_PATH', str(path))
    monkeypatch.setattr(settings, '_values', None)
    monkeypatch.setattr(settings, '_preset_state', {})
    yield path
    settings._values = None
    settings._preset_state = {}


def _post(client, path, body):
    return client.post(path, json=body)


class TestPreset:
    def test_schema_lists_every_group_and_preset(self, client):
        body = client.get('/api/settings/schema').get_json()
        assert body['ok'] is True
        assert body['schema']['groups']
        keys = {field['key'] for field in body['schema']['settings']}
        assert 'crawl_pace_scale' in keys and 'crawl_pace_scale' in settings.DEFAULTS
        assert 'slow' in body['schema']['presets']
        assert body['read_only'] is False

    def test_apply_writes_concrete_values_and_snapshots_what_it_replaced(self, client):
        before = client.get('/api/settings').get_json()['settings']
        body = _post(client, '/api/settings/preset', {'action': 'apply', 'preset': 'slow'}).get_json()
        assert body['ok'] is True
        after = body['settings']
        assert after['crawl_pace_scale'] == 4.0
        assert after['same_platform_queue'] is True
        assert body['preset']['active'] == 'slow'
        assert body['preset']['can_restore'] is True

        restored = _post(client, '/api/settings/preset', {'action': 'restore'}).get_json()
        assert restored['ok'] is True
        for key in settings.PRESETS['slow']['values']:
            assert restored['settings'][key] == before[key], key
        assert restored['preset']['active'] == ''

    def test_a_manual_edit_marks_the_preset_customized_but_still_restores(self, client):
        before = client.get('/api/settings').get_json()['settings']
        _post(client, '/api/settings/preset', {'action': 'apply', 'preset': 'slow'})
        _post(client, '/api/settings', {'crawl_pace_scale': 2.5})
        state = client.get('/api/settings').get_json()['preset']
        assert state['customized'] is True
        restored = _post(client, '/api/settings/preset', {'action': 'restore'}).get_json()
        assert restored['settings']['crawl_pace_scale'] == before['crawl_pace_scale']

    def test_applying_twice_keeps_the_original_snapshot(self, client):
        before = client.get('/api/settings').get_json()['settings']
        _post(client, '/api/settings/preset', {'action': 'apply', 'preset': 'slow'})
        _post(client, '/api/settings/preset', {'action': 'apply', 'preset': 'slow'})
        restored = _post(client, '/api/settings/preset', {'action': 'restore'}).get_json()
        for key in settings.PRESETS['slow']['values']:
            assert restored['settings'][key] == before[key], key

    @pytest.mark.parametrize('preset', ['standard', 'slow', 'night'])
    def test_every_preset_applies_and_restores_exactly(self, client, preset):
        """Three bundles are only honest if each one is one click and one click back.

        The snapshot rule is the same for all of them (see ``apply_preset``): the first
        bundle applied keeps the ORIGINAL values, so switching between presets still
        restores what the user had before any of them.
        """
        before = client.get('/api/settings').get_json()['settings']
        applied = _post(client, '/api/settings/preset', {'action': 'apply', 'preset': preset}).get_json()
        assert applied['ok'] is True, applied
        assert applied['preset']['active'] == preset
        for key, value in settings.PRESETS[preset]['values'].items():
            assert applied['settings'][key] == value, f'{preset} did not write {key}'

        restored = _post(client, '/api/settings/preset', {'action': 'restore'}).get_json()
        for key in settings.PRESETS[preset]['values']:
            assert restored['settings'][key] == before[key], f'{preset} left {key} changed'

    def test_unknown_preset_and_bad_action_are_named_refusals(self, client):
        assert _post(client, '/api/settings/preset', {'action': 'apply', 'preset': 'turbo'}).status_code == 400
        assert _post(client, '/api/settings/preset', {'action': 'dance'}).status_code == 400


class TestExport:
    def test_a_portable_export_never_carries_machine_paths(self, client):
        client.post('/api/settings', json={'driver_path': '/opt/chromedriver'})
        payload = client.get('/api/settings/export').get_json()
        assert payload['kind'] == settings.EXPORT_KIND
        assert 'driver_path' not in payload['values']
        assert 'machine' not in payload

    def test_include_machine_adds_them_under_their_own_block(self, client):
        client.post('/api/settings', json={'driver_path': '/opt/chromedriver'})
        payload = client.get('/api/settings/export?include_machine=1').get_json()
        assert payload['machine']['driver_path'] == '/opt/chromedriver'

    def test_the_download_is_a_json_attachment(self, client):
        response = client.get('/api/settings/export')
        assert response.headers['Content-Disposition'].startswith('attachment;')
        assert response.get_json()['schema'] == settings.SCHEMA_VERSION


class TestImport:
    def _payload(self, **values):
        return {'kind': settings.EXPORT_KIND, 'schema': settings.SCHEMA_VERSION, 'values': values}

    def test_dry_run_reports_the_diff_without_writing(self, client):
        body = _post(
            client,
            '/api/settings/import',
            {'payload': self._payload(crawl_pace_scale=2.5), 'dry_run': True},
        ).get_json()
        assert body['ok'] is True
        assert body['changed'] == ['crawl_pace_scale']
        assert client.get('/api/settings').get_json()['settings']['crawl_pace_scale'] == 1.0

    def test_merge_applies_only_the_keys_in_the_package(self, client):
        current = client.get('/api/settings').get_json()['settings']['element_timeout']
        _post(client, '/api/settings/import', {'payload': self._payload(crawl_pace_scale=2.5)})
        after = client.get('/api/settings').get_json()['settings']
        assert after['crawl_pace_scale'] == 2.5
        assert after['element_timeout'] == current

    def test_unknown_keys_are_reported_not_stored(self, client):
        body = _post(
            client,
            '/api/settings/import',
            {'payload': self._payload(not_a_setting=1)},
        ).get_json()
        assert body['ok'] is True
        assert 'not_a_setting' in body['skipped']
        assert 'not_a_setting' not in client.get('/api/settings').get_json()['settings']

    def test_a_future_schema_is_refused_by_name(self, client):
        response = _post(
            client,
            '/api/settings/import',
            {'payload': {'kind': settings.EXPORT_KIND, 'schema': settings.SCHEMA_VERSION + 1, 'values': {}}},
        )
        assert response.status_code == 400
        assert 'newer' in response.get_json()['error']

    def test_machine_paths_need_the_explicit_opt_in(self, client):
        client.post('/api/settings', json={'driver_path': '/opt/keep-me'})
        payload = {'kind': settings.EXPORT_KIND, 'schema': settings.SCHEMA_VERSION, 'machine': {'driver_path': '/new'}}
        body = _post(client, '/api/settings/import', {'payload': payload}).get_json()
        assert body['ok'] is True
        assert body['skipped'] == ['driver_path']
        assert client.get('/api/settings').get_json()['settings']['driver_path'] == '/opt/keep-me'

    def test_include_machine_applies_the_path(self, client):
        payload = {'kind': settings.EXPORT_KIND, 'schema': settings.SCHEMA_VERSION, 'machine': {'driver_path': '/new'}}
        _post(client, '/api/settings/import', {'payload': payload, 'include_machine': True})
        assert client.get('/api/settings').get_json()['settings']['driver_path'] == '/new'

    def test_machine_paths_from_another_platform_are_not_written(self, client):
        """A Windows export's drive-letter path on Linux is a refusal waiting in the crawl.
        The package names the platform that wrote it, so an opt-in import must still skip it."""
        client.post('/api/settings', json={'driver_path': '/opt/keep-me'})
        payload = {
            'kind': settings.EXPORT_KIND,
            'schema': settings.SCHEMA_VERSION,
            'platform': 'win32' if __import__('sys').platform != 'win32' else 'linux',
            'machine': {'driver_path': '/new'},
        }
        body = _post(client, '/api/settings/import', {'payload': payload, 'include_machine': True}).get_json()
        assert body['ok'] is True
        assert body['skipped'] == ['driver_path']
        assert client.get('/api/settings').get_json()['settings']['driver_path'] == '/opt/keep-me'

    def test_replace_resets_keys_missing_from_the_package(self, client):
        client.post('/api/settings', json={'crawl_pace_scale': 3.0})
        _post(
            client,
            '/api/settings/import',
            {
                'payload': self._payload(crawl_pace_scale=2.0),
                'mode': 'replace',
                'confirm_replace': True,
            },
        )
        after = client.get('/api/settings').get_json()['settings']
        assert after['crawl_pace_scale'] == 2.0
        assert after['element_timeout'] == settings.DEFAULTS['element_timeout']

    def test_replace_without_confirmation_is_refused(self, client):
        response = _post(client, '/api/settings/import', {'payload': self._payload(), 'mode': 'replace'})
        assert response.status_code == 400

    def test_a_round_trip_reproduces_the_export(self, client, tmp_path):
        client.post('/api/settings', json={'crawl_pace_scale': 2.0, 'element_timeout': 22})
        exported = client.get('/api/settings/export').get_json()
        client.post('/api/settings', json={'crawl_pace_scale': 1.0, 'element_timeout': 15})
        _post(client, '/api/settings/import', {'payload': exported})
        after = client.get('/api/settings').get_json()['settings']
        assert after['crawl_pace_scale'] == 2.0
        assert after['element_timeout'] == 22
        assert json.loads(json.dumps(exported)) == exported, 'the package must be plain JSON'
