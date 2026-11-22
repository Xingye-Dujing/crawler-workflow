"""Saved-workflow management through the domain service, including the delete-only approval rule."""

import json

import pytest
from ai.errors import AIError

pytestmark = pytest.mark.unit


def _saved(manager, name):
    with open(manager.path_for(name), encoding='utf-8') as handle:
        return json.load(handle)


def _payload(label='demo'):
    return {
        'nodes': [
            {
                'id': 'upload-1',
                'type': 'upload',
                'x': 0,
                'y': 0,
                'title': label,
                'params': {'dataset_id': 'ds1'},
            },
            {
                'id': 'output-1',
                'type': 'output',
                'x': 200,
                'y': 0,
                'title': 'Save',
                'params': {'operation': 'save', 'format': 'csv', 'filename': 'export.csv'},
            },
        ],
        'connections': [{'from': 'upload-1', 'to': 'output-1'}],
        'settings': {},
    }


@pytest.fixture
def manager(tmp_path):
    from services.workflows.manager import WorkflowManager

    row = WorkflowManager(str(tmp_path))
    row.save('demo', _payload())
    return row


@pytest.fixture
def wired(monkeypatch, manager):
    from ai import tools

    monkeypatch.setattr(tools, '_workflow_manager', lambda: manager)
    from ai import approvals

    approvals.reset()
    yield manager
    approvals.reset()


def test_list_and_read_return_the_saved_file(wired):
    from ai import tools

    listing = tools.tool_workflow_list({}, {})
    assert listing['count'] == 1
    assert listing['workflows'][0]['name'] == 'demo'
    read = tools.tool_workflow_read({'name': 'demo'}, {})
    assert read['name'] == 'demo'
    assert read['workflow']['nodes'][0]['id'] == 'upload-1'


def test_a_missing_workflow_is_refused_by_name(wired):
    from ai import tools

    with pytest.raises(AIError) as missing:
        tools.tool_workflow_read({'name': 'nope'}, {})
    assert missing.value.key == 'ai.workflowNotFound'


def test_update_replaces_the_same_file_only_after_validation(wired):
    from ai import tools

    payload = _payload('changed')
    result = tools.tool_workflow_update({'name': 'demo', 'workflow': payload}, {})
    assert result['ok'] is True and result['name'] == 'demo'
    assert _saved(wired, 'demo')['nodes'][0]['title'] == 'changed'
    with pytest.raises(AIError) as invalid:
        tools.tool_workflow_update({'name': 'demo', 'workflow': {'nodes': [{'type': 'no-such-node'}]}}, {})
    assert invalid.value.key == 'ai.workflowDraftInvalid'
    # The refused draft did not touch the good file.
    assert _saved(wired, 'demo')['nodes'][0]['title'] == 'changed'


def test_rename_never_overwrites_and_delete_removes(wired):
    from ai import tools

    wired.save('other', _payload('other'))
    with pytest.raises(AIError) as taken:
        tools.tool_workflow_rename({'name': 'demo', 'new_name': 'other'}, {})
    assert taken.value.key == 'ai.workflowNameTaken'
    renamed = tools.tool_workflow_rename({'name': 'demo', 'new_name': 'renamed'}, {})
    assert renamed == {'ok': True, 'previous': 'demo', 'name': 'renamed'}
    assert wired.load('renamed')['name'] == 'renamed'
    deleted = tools.tool_workflow_delete({'name': 'renamed'}, {})
    assert deleted['ok'] is True and wired.load('renamed') is None


def test_delete_needs_an_approval_even_with_auto_approve_on(wired, monkeypatch):
    from ai import approvals, tools

    monkeypatch.setattr(tools, 'get_setting', lambda key: True)
    with pytest.raises(AIError) as refused:
        tools.execute('workflow_delete', {'name': 'demo'}, {'conversation_id': 'c1'}, allowed={'workflow_delete'})
    assert refused.value.key == 'ai.approvalRequired'
    assert wired.load('demo') is not None, 'a refused delete removed the file'

    approvals.grant('c1', 'workflow_delete', {'name': 'demo'}, approvals.ONCE)
    result = tools.execute('workflow_delete', {'name': 'demo'}, {'conversation_id': 'c1'}, allowed={'workflow_delete'})
    assert result['deleted'] == 'demo'
    assert wired.load('demo') is None


def test_update_with_auto_approve_off_names_the_request_tool(wired, monkeypatch):
    from ai import tools

    monkeypatch.setattr(tools, 'get_setting', lambda key: False)
    with pytest.raises(AIError) as refused:
        tools.execute(
            'workflow_update',
            {'name': 'demo', 'workflow': _payload()},
            {'conversation_id': 'c1'},
            allowed={'workflow_update'},
        )
    assert refused.value.key == 'ai.approvalRequired'
    assert refused.value.params['tool'] == 'workflow_update'


def test_export_writes_a_named_bundle_into_the_export_directory(wired, monkeypatch):
    from ai import tools

    import services.exports.writer as writer
    import services.workflows.bundle as bundle

    seen = {}

    def fake_save(export_dir, filename, data):
        seen.update({'dir': export_dir, 'filename': filename, 'bytes': data})
        return {'name': filename, 'path': export_dir + '/' + filename, 'size': len(data)}

    monkeypatch.setattr(bundle, 'build_bundle', lambda names, workflow_manager=None: (b'zip-bytes', 'proj.zip', []))
    monkeypatch.setattr(writer, 'save_bytes', fake_save)
    result = tools.tool_workflow_export({'name': 'demo'}, {})
    assert result['ok'] is True and result['export'] == 'proj.zip'
    assert seen['filename'] == 'proj.zip' and seen['bytes'] == b'zip-bytes'


def test_workflow_run_uses_the_scheduled_start_path(wired, monkeypatch):
    from ai import tools

    import engine.run_schedule as schedule

    calls = []

    def fake_start(task, manual):
        calls.append((task, manual))
        return {'ok': True, 'queued': False, 'run_id': 'r_1'}

    monkeypatch.setattr(schedule, 'start_scheduled_run', fake_start)
    result = tools.tool_workflow_run({'name': 'demo'}, {})
    assert result['run_id'] == 'r_1' and result['queued'] is False
    assert calls[0][0]['workflow'] == 'demo' and calls[0][1] is True


def test_workflow_run_refusal_is_named(wired, monkeypatch):
    from ai import tools

    import engine.run_schedule as schedule

    monkeypatch.setattr(
        schedule,
        'start_scheduled_run',
        lambda task, manual: {'ok': False, 'error': 'needs a login'},
    )
    with pytest.raises(AIError) as refused:
        tools.tool_workflow_run({'name': 'demo'}, {})
    assert refused.value.key == 'ai.workflowRunFailed'
    assert 'needs a login' in refused.value.params['detail']


def test_workflow_stop_delegates_to_the_run_service(monkeypatch):
    from ai import tools

    import engine.run as run_engine

    seen = []

    def fake_stop():
        seen.append(True)
        return {'status': 200, 'body': {'ok': True, 'browsers': 1, 'records': ['r_1']}}

    monkeypatch.setattr(run_engine, 'stop_run', fake_stop)
    result = tools.tool_workflow_stop({}, {})
    assert seen == [True]
    assert result == {'ok': True, 'browsers': 1, 'records': ['r_1']}


def test_export_list_and_delete_use_the_export_service(monkeypatch):
    from ai import tools

    import services.exports.browser as browser

    monkeypatch.setattr(browser, 'list_exports', lambda directory, limit=50: [{'name': 'chart.png', 'size': 3}])
    removed = []
    monkeypatch.setattr(browser, 'delete_export_file', lambda directory, name: removed.append(name) or True)
    listed = tools.tool_export_list({}, {})
    assert [row['name'] for row in listed['exports']] == ['chart.png']
    deleted = tools.tool_export_delete({'name': 'chart.png'}, {})
    assert deleted['deleted'] == 'chart.png'
    assert removed == ['chart.png']
