"""GET /api/models — the registry the bert-mode picker names its models from.

The registry is a runtime file (``data/model_registry.json``) the operator keeps by
hand; the endpoint's whole job is to hand the browser friendly NAMES (「网暴模型」) so a
node does not have to be configured with a raw path. Two invariants drive every case:

* A missing, non-list or half-written registry is an EMPTY list, never an error —
  a node always accepts a path, so "nothing is registered" is a complete answer and
  the first boot must not flash a console failure over a file nobody created yet.
* An entry with no ``path`` is not addressable, so it is dropped: a name with no
  folder behind it would let the picker select a model the run cannot load.

``Config.DATA_DIR`` is pointed at each test's own ``tmp_path`` so one test's registry
file is never another's precondition.
"""

import json

import pytest

from config import Config

pytestmark = pytest.mark.api


def _registry(tmp_path, payload_text):
    (tmp_path / 'model_registry.json').write_text(payload_text, encoding='utf-8')


class TestModelsEndpoint:
    def test_missing_registry_is_an_empty_list_not_an_error(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path))
        assert client.get('/api/models').get_json() == {'ok': True, 'models': []}

    def test_it_returns_the_registered_name_path_and_desc(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path))
        _registry(
            tmp_path,
            json.dumps(
                [
                    {'name': '网暴模型', 'path': 'C:\\models\\netbully', 'desc': '六分类立场'},
                    {'name': 'other', 'path': 'C:\\models\\other'},
                ],
                ensure_ascii=False,
            ),
        )
        body = client.get('/api/models').get_json()
        assert body['ok'] is True
        assert [m['name'] for m in body['models']] == ['网暴模型', 'other'], 'friendly names, in registry order'
        assert body['models'][0]['path'] == 'C:\\models\\netbully'
        assert body['models'][0]['desc'] == '六分类立场'
        # a model with no desc still travels, as the empty string rather than a missing key
        assert body['models'][1]['desc'] == ''

    def test_an_entry_without_a_path_is_dropped(self, client, tmp_path, monkeypatch):
        """A name is only useful if the node can be run, and a model runs off its path."""
        monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path))
        _registry(
            tmp_path,
            json.dumps(
                [
                    {'name': 'ghost', 'path': '   '},
                    {'name': 'real', 'path': 'C:\\models\\real'},
                ],
                ensure_ascii=False,
            ),
        )
        models = client.get('/api/models').get_json()['models']
        assert [m['name'] for m in models] == ['real'], models

    def test_a_non_list_registry_is_treated_as_empty(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path))
        _registry(tmp_path, json.dumps({'name': 'oops'}))
        assert client.get('/api/models').get_json()['models'] == []

    def test_malformed_json_is_treated_as_empty(self, client, tmp_path, monkeypatch):
        """A file someone half-edited by hand must not take the boot down with it."""
        monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path))
        _registry(tmp_path, '{ this is not json ')
        assert client.get('/api/models').get_json()['models'] == []

    def test_a_non_dict_entry_is_dropped_without_aborting_the_list(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path))
        _registry(tmp_path, json.dumps(['not-a-model', {'name': 'real', 'path': 'C:\\m'}], ensure_ascii=False))
        assert [m['name'] for m in client.get('/api/models').get_json()['models']] == ['real']

    def test_it_is_read_only(self, client):
        assert client.post('/api/models', json={}).status_code == 405
