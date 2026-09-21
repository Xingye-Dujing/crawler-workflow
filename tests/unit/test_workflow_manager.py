"""Tests for services/workflow_manager.py — saved canvases on disk.

A workflow name is typed in the UI and becomes a file name, so the pinned
contracts are the safety ones: one file per name (overwrite, never a pile of
variants), the name is carried *inside* the payload (the run reports it to the
execution history), and nothing a user types can walk out of the directory.
"""
import json
import os

import pytest

from services.workflow_manager import WorkflowManager

pytestmark = pytest.mark.unit

WORKFLOW = {'nodes': [{'id': 'node-1', 'type': 'source', 'params': {'keyword': '三亚'}}], 'connections': []}


@pytest.fixture
def manager(tmp_path):
    return WorkflowManager(workflow_dir=str(tmp_path / 'workflows'))


class TestNameCleaning:
    def test_the_cap_matches_the_public_constant(self, manager):
        assert WorkflowManager.MAX_NAME_LENGTH == 60
        assert len(manager.clean_name('长' * 200)) == 60

    @pytest.mark.parametrize('raw, expected', [
        ('  带空格  ', '带空格'),
        ('../escape', '_escape'),
        ('a/b/c', 'a_b_c'),
        ('windows\\path', 'windows_path'),
        ('bad:chars*?"<>|', 'bad_chars______'),
        ('...', 'untitled'),
        ('', 'untitled'),
        ('   ', 'untitled'),
    ])
    def test_names_become_single_path_components(self, manager, raw, expected):
        clean = manager.clean_name(raw)
        assert clean == expected
        assert not os.path.isabs(clean)
        assert '/' not in clean and '\\' not in clean

    def test_cleaning_is_idempotent(self, manager):
        once = manager.clean_name('  我的/工作流  ')
        assert manager.clean_name(once) == once

    def test_control_characters_become_underscores(self, manager):
        # They are replaced, not removed: the name stays addressable afterwards.
        assert manager.clean_name('\x01\x02') == '__'
        assert manager._path_for('\x01\x02').endswith('__.json')


class TestSaveLoad:
    def test_save_returns_the_path_and_load_returns_the_payload(self, manager):
        path = manager.save('周报', dict(WORKFLOW))
        assert path == os.path.join(manager.workflow_dir, '周报.json')
        assert manager.load('周报') == dict(WORKFLOW, name='周报')

    def test_the_cleaned_name_travels_inside_the_file(self, manager):
        manager.save('  我的 工作流  ', dict(WORKFLOW))
        assert manager.load('我的 工作流')['name'] == '我的 工作流'
        assert list(manager.list_workflows()) == ['我的 工作流']

    def test_saving_never_mutates_the_caller_payload(self, manager):
        payload = dict(WORKFLOW)
        manager.save('wf', payload)
        assert 'name' not in payload

    def test_one_name_is_one_file_and_a_second_save_overwrites(self, manager):
        manager.save('wf', {'nodes': [1]})
        manager.save('wf', {'nodes': [2]})
        assert len(manager.list_workflows()) == 1
        assert manager.load('wf')['nodes'] == [2]

    def test_names_that_clean_to_the_same_stem_share_a_file(self, manager):
        manager.save('a/b', {'v': 1})
        manager.save('a\\b', {'v': 2})
        assert manager.load('a/b') == {'v': 2, 'name': 'a_b'}
        assert manager.list_workflows() == ['a_b']

    def test_the_file_is_utf8_json(self, manager):
        path = manager.save('中文名字', dict(WORKFLOW))
        with open(path, encoding='utf-8') as handle:
            assert json.load(handle)['name'] == '中文名字'

    def test_a_none_payload_still_produces_a_named_file(self, manager):
        assert manager.load('空') is None
        manager.save('空', None)
        assert manager.load('空') == {'name': '空'}

    def test_loading_an_unknown_name_is_none(self, manager):
        assert manager.load('没有这个') is None

    def test_a_damaged_file_is_none_rather_than_a_crash(self, manager):
        with open(manager.save('坏', dict(WORKFLOW)), 'w', encoding='utf-8') as handle:
            handle.write('{ not json')
        assert manager.load('坏') is None

    def test_round_trip_of_a_full_workflow(self, manager):
        payload = dict(WORKFLOW, settings={'parallel': True}, name='ignored')
        manager.save('完整', payload)
        loaded = manager.load('完整')
        assert loaded['settings'] == {'parallel': True}
        assert loaded['name'] == '完整'  # the manager owns the name field


class TestListingAndDeleting:
    def test_only_json_files_are_listed(self, manager):
        manager.save('wf', dict(WORKFLOW))
        with open(os.path.join(manager.workflow_dir, 'notes.txt'), 'w', encoding='utf-8') as handle:
            handle.write('ignore me')
        assert manager.list_workflows() == ['wf']

    def test_an_empty_directory_lists_nothing(self, manager):
        assert manager.list_workflows() == []

    def test_a_missing_directory_lists_nothing(self, tmp_path):
        assert WorkflowManager(workflow_dir=str(tmp_path / 'gone')).list_workflows() == []

    def test_delete_removes_the_file(self, manager):
        manager.save('临时', dict(WORKFLOW))
        manager.delete('临时')
        assert manager.load('临时') is None
        assert manager.list_workflows() == []

    def test_deleting_a_name_that_was_never_saved_is_quiet(self, manager):
        manager.save('keep', dict(WORKFLOW))
        manager.delete('ghost')
        assert manager.list_workflows() == ['keep']

    def test_the_directory_is_created_for_the_app_default(self, monkeypatch, tmp_path):
        from config import Config

        target = tmp_path / 'default-workflows'
        monkeypatch.setattr(Config, 'WORKFLOW_DIR', str(target))
        manager = WorkflowManager()
        assert manager.workflow_dir == str(target) and target.is_dir()
