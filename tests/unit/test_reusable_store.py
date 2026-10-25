"""Reusable-node templates: a fragment is validated before any canvas can offer it."""

import json

import pytest

from config import Config
from services import reusable_store
from services.reusable_store import (
    TemplateCorruptError,
    delete_template,
    get_template,
    list_templates,
    rename_template,
    save_template,
)


@pytest.fixture(autouse=True)
def isolated_reusable_dir(tmp_path, monkeypatch):
    """Templates are files on disk; one test's row must not become another's duplicate name."""
    monkeypatch.setattr(Config, 'REUSABLE_DIR', str(tmp_path / 'reusable_nodes'))


def fragment(**overrides):
    payload = {
        'name': '清洗流水线',
        'description': '两步清洗',
        'nodes': [
            {
                'id': 'n1',
                'type': 'process',
                'title': '清洗',
                'params': {'operation': 'clean'},
                'x': 0,
                'y': 0,
                'w': 220,
                'h': 90,
            },
            {
                'id': 'n2',
                'type': 'analysis',
                'title': '去空',
                'params': {'operation': 'drop_null'},
                'x': 300,
                'y': 0,
                'w': 220,
                'h': 80,
            },
        ],
        'connections': [{'from': 'n1', 'to': 'n2'}],
        'inputs': ['n1'],
        'outputs': ['n2'],
    }
    payload.update(overrides)
    return payload


class TestSaveAndRead:
    def test_round_trip_and_listing(self):
        saved = save_template(fragment())
        assert saved['id'].startswith('r-')
        assert saved['created_at'] and saved['updated_at']
        rows = list_templates()
        assert rows[0]['id'] == saved['id']
        assert rows[0]['nodes'] == 2
        assert rows[0]['inputs'] == 1
        assert rows[0]['broken'] is False
        full = get_template(saved['id'])
        assert full['name'] == '清洗流水线'
        assert full['nodes'][1]['params']['operation'] == 'drop_null'
        assert full['nodes'][0]['w'] == 220
        assert delete_template(saved['id']) is True
        assert get_template(saved['id']) is None
        assert list_templates() == []

    def test_an_update_keeps_id_and_created_at(self):
        first = save_template(fragment())
        changed = fragment(name='清洗流水线 v2')
        changed['id'] = first['id']
        second = save_template(changed)
        assert second['id'] == first['id']
        assert second['created_at'] == first['created_at']
        assert second['name'] == '清洗流水线 v2'
        assert len(list_templates()) == 1

    def test_a_duplicate_name_is_refused_but_the_same_row_may_update(self):
        first = save_template(fragment())
        with pytest.raises(ValueError) as exc:
            save_template(fragment())
        assert '清洗流水线' in str(exc.value)
        changed = fragment()
        changed['id'] = first['id']
        assert save_template(changed)['id'] == first['id']

    def test_a_template_survives_a_restart(self):
        saved = save_template(fragment())
        assert get_template(saved['id'])['name'] == '清洗流水线'


class TestRename:
    def test_rename_changes_the_name_and_nothing_else(self):
        first = save_template(fragment())
        renamed = rename_template(first['id'], '  清洗流水线 v2  ')
        assert renamed['id'] == first['id']
        assert renamed['name'] == '清洗流水线 v2'
        full = get_template(first['id'])
        assert full['name'] == '清洗流水线 v2'
        assert full['nodes'] == first['nodes']
        assert full['connections'] == first['connections']
        assert full['created_at'] == first['created_at']
        assert list_templates()[0]['name'] == '清洗流水线 v2'

    def test_a_duplicate_blank_or_over_long_name_is_refused(self):
        first = save_template(fragment())
        save_template(fragment(name='另一个模板'))
        with pytest.raises(ValueError) as exc:
            rename_template(first['id'], '另一个模板')
        assert '另一个模板' in str(exc.value)
        with pytest.raises(ValueError) as exc:
            rename_template(first['id'], '   ')
        assert str(exc.value)
        with pytest.raises(ValueError) as exc:
            rename_template(first['id'], 'x' * 81)
        assert '80' in str(exc.value)
        assert get_template(first['id'])['name'] == '清洗流水线'

    def test_a_missing_or_malformed_id_is_named(self):
        assert rename_template('r-000000000000', '新名字') is None
        with pytest.raises(ValueError) as exc:
            rename_template('bad', '新名字')
        assert 'bad' in str(exc.value)

    def test_a_corrupt_file_is_refused_instead_of_overwritten(self):
        saved = save_template(fragment())
        path = reusable_store._path(saved['id'])
        with open(path, 'w', encoding='utf-8') as f:
            f.write('{not json')
        with pytest.raises(ValueError) as exc:
            rename_template(saved['id'], '新名字')
        assert saved['id'] in str(exc.value)


class TestValidation:
    @pytest.mark.parametrize(
        'bad,needle',
        [
            ({'name': ''}, '名字'),
            ({'nodes': []}, '至少'),
            ({'nodes': [{'id': 'n1', 'type': 'source'}]}, 'source'),
            ({'nodes': [{'id': 'n1', 'type': 'process'}, {'id': 'n1', 'type': 'process'}]}, 'n1'),
            ({'connections': [{'from': 'n1', 'to': 'missing'}]}, 'missing'),
            ({'connections': [{'from': 'n1', 'to': 'n1'}]}, 'n1'),
            ({'connections': [{'from': 'n1', 'to': 'n2'}, {'from': 'n2', 'to': 'n1'}]}, '环'),
            ({'inputs': ['missing']}, 'missing'),
            ({'outputs': []}, '输出'),
            ({'outputs': ['n1', 'n2']}, '输出'),
            ({'outputs': ['n1']}, '后续'),
        ],
    )
    def test_a_broken_fragment_is_refused_by_name(self, bad, needle):
        payload = fragment()
        for key, value in bad.items():
            payload[key] = value
        with pytest.raises(ValueError) as exc:
            save_template(payload)
        assert needle in str(exc.value)

    def test_a_fragment_may_contain_a_single_node(self):
        payload = fragment(
            nodes=[{'id': 'only', 'type': 'process', 'params': {}}],
            connections=[],
            inputs=['only'],
            outputs=['only'],
        )
        assert save_template(payload)['outputs'] == ['only']

    def test_the_size_cap_is_named(self, monkeypatch):
        monkeypatch.setattr(reusable_store, 'MAX_NODES', 1)
        with pytest.raises(ValueError) as exc:
            save_template(fragment())
        assert '1' in str(exc.value)

    def test_inputs_and_outputs_must_be_lists(self):
        for key in ('inputs', 'outputs'):
            payload = fragment()
            payload[key] = 'n1'
            with pytest.raises(ValueError):
                save_template(payload)


class TestBrokenFiles:
    def test_a_corrupt_file_is_still_listed_so_it_can_be_deleted(self):
        saved = save_template(fragment())
        path = reusable_store._path(saved['id'])
        with open(path, 'w', encoding='utf-8') as f:
            f.write('{not json')
        rows = list_templates()
        assert rows[0]['id'] == saved['id']
        assert rows[0]['broken'] is True
        with pytest.raises(TemplateCorruptError):
            get_template(saved['id'])
        assert delete_template(saved['id']) is True

    def test_an_unknown_id_reads_as_missing_not_an_error(self):
        assert get_template('nope') is None
        assert get_template('r-000000000000') is None

    def test_the_store_is_a_directory_of_plain_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr(reusable_store.Config, 'REUSABLE_DIR', str(tmp_path / 'reusable_nodes'))
        saved = save_template(fragment())
        path = tmp_path / 'reusable_nodes' / f'{saved["id"]}.json'
        payload = json.loads(path.read_text(encoding='utf-8'))
        assert payload['name'] == '清洗流水线'
