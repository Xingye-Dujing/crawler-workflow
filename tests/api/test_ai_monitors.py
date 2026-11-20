"""Run monitors and the Python extension surface, with a scripted event bus. No network."""

import json

import pytest

pytestmark = pytest.mark.api


@pytest.fixture
def ai_conversation(client):
    response = client.post(
        '/api/ai/conversations', json={'provider': 'deepseek', 'model': 'deepseek-flash', 'skill': 'project'}
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()['conversation']['id']


def test_the_manual_builder_reads_its_names_from_the_matcher_and_arms_through_the_same_door(client, ai_conversation):
    from ai import monitors

    catalog = client.get('/api/ai/monitors/catalog')
    assert catalog.status_code == 200, catalog.get_json()
    names = catalog.get_json()['catalog']
    assert names['events'] == list(monitors.EVENTS)
    assert names['statuses'] == list(monitors.STATUSES)
    assert names['outcomes'] == list(monitors.OUTCOMES)

    created = client.post(
        '/api/ai/monitors',
        json={
            'conversation_id': ai_conversation,
            'spec': {'events': [names['events'][0]], 'statuses': ['failed'], 'note': 'manual builder'},
            'auto_analyze': False,
        },
    )
    assert created.status_code == 200, created.get_json()
    assert created.get_json()['monitor']['spec']['events'] == [names['events'][0]]


def test_a_node_monitor_delivers_one_pending_event_and_ack_clears_it(client, ai_conversation):
    from runtime import run_events

    created = client.post(
        '/api/ai/monitors',
        json={
            'conversation_id': ai_conversation,
            'auto_analyze': True,
            'spec': {
                'run_id': 'run-1',
                'events': ['node.finished'],
                'node_ids': ['n1'],
                'statuses': ['failed'],
                'min_rows': 0,
                'note': 'watch the analysis node',
            },
        },
    )
    assert created.status_code == 200, created.get_json()
    monitor = created.get_json()['monitor']
    assert monitor['spec']['events'] == ['node.finished']

    run_events.publish('node.finished', run_id='run-1', node_id='n1', status='done', rows=10)
    run_events.publish('node.finished', run_id='run-1', node_id='n1', status='failed', rows=0, label='分析 #n1')
    from ai import monitors

    assert monitors.drain(timeout=5) is True

    pending = client.get('/api/ai/monitors/events?pending=1&conversation_id=' + ai_conversation).get_json()
    assert len(pending['events']) == 1, pending
    event = pending['events'][0]
    assert event['event'] == 'node.finished'
    assert event['payload']['status'] == 'failed'
    assert event['payload']['label'] == '分析 #n1'

    acked = client.post('/api/ai/monitors/events/' + event['id'] + '/ack').get_json()
    assert acked['acked'] is True
    assert client.get('/api/ai/monitors/events?pending=1&conversation_id=' + ai_conversation).get_json()['events'] == []
    assert client.delete('/api/ai/monitors/' + monitor['id']).get_json()['deleted'] is True


def test_a_retired_monitor_stops_delivering_even_with_a_warm_cache(client, ai_conversation):
    from ai import monitors, store
    from runtime import run_events

    created = client.post(
        '/api/ai/monitors',
        json={
            'conversation_id': ai_conversation,
            'spec': {'run_id': 'run-budget', 'events': ['run.finished'], 'max_triggers': 2},
        },
    ).get_json()['monitor']
    for _ in range(5):
        run_events.publish('run.finished', run_id='run-budget', outcome='completed')
    assert monitors.drain(timeout=5) is True
    events = client.get('/api/ai/monitors/events?pending=1&conversation_id=' + ai_conversation).get_json()['events']
    # touch_monitor retires the row at 2, but the armed list is cached for 10s: without invalidating
    # it the remaining events kept matching and delivering past max_triggers.
    assert len(events) == 2, events
    row = store.get_monitor(created['id'])
    assert row['status'] == 'done'
    assert int(row['trigger_count']) == 2


def test_a_console_delivery_keeps_no_console_text(client, ai_conversation):
    from ai import monitors
    from runtime import run_events

    created = client.post(
        '/api/ai/monitors',
        json={
            'conversation_id': ai_conversation,
            'spec': {'run_id': 'run-2', 'events': ['run.log'], 'console_contains': '风险'},
        },
    )
    assert created.status_code == 200, created.get_json()
    run_events.publish('run.log', run_id='run-2', line='命中风险页：正文一段 crawled text')
    assert monitors.drain(timeout=5) is True
    event = client.get('/api/ai/monitors/events?pending=1&conversation_id=' + ai_conversation).get_json()['events'][0]
    # The needle matched, but the delivery carries facts only: the model reads the console itself.
    assert 'line' not in event['payload']
    assert 'crawled text' not in json.dumps(event, ensure_ascii=False)


def test_deleting_a_conversation_takes_its_monitors_and_deliveries(client, ai_conversation):
    from ai import monitors
    from runtime import run_events

    created = client.post(
        '/api/ai/monitors',
        json={'conversation_id': ai_conversation, 'spec': {'run_id': 'run-3', 'events': ['run.finished']}},
    ).get_json()['monitor']
    run_events.publish('run.finished', run_id='run-3', outcome='completed')
    assert monitors.drain(timeout=5) is True
    assert client.get('/api/ai/monitors?conversation_id=' + ai_conversation).get_json()['monitors']

    assert client.delete('/api/ai/conversations/' + ai_conversation).get_json()['deleted'] is True
    # No armed monitor survives to fire into a conversation that no longer exists, and no pending
    # delivery survives to be served (or to be reopened by an automatic turn).
    assert client.get('/api/ai/monitors?conversation_id=' + ai_conversation).get_json()['monitors'] == []
    assert client.get('/api/ai/monitors/events?pending=1&conversation_id=' + ai_conversation).get_json()['events'] == []
    assert created['id']


def test_a_console_monitor_needs_a_needle(client, ai_conversation):
    response = client.post(
        '/api/ai/monitors',
        json={'conversation_id': ai_conversation, 'spec': {'events': ['run.log']}},
    )
    assert response.status_code == 400
    assert response.get_json()['key'] == 'ai.monitorNeedle'


def test_python_scripts_are_listed_saved_and_run_with_a_sample(client, monkeypatch):
    from services import python_runtime

    monkeypatch.setattr(python_runtime, 'get_setting', lambda key: True if key == 'ai_allow_python' else '')
    listed = client.get('/api/ai/python/scripts').get_json()['scripts']
    assert any(item['id'] == 'passthrough' and item['builtin'] for item in listed)

    saved = client.post(
        '/api/ai/python/scripts',
        json={
            'id': 'keep_two',
            'name': 'Keep two columns',
            'code': (
                'import json, os\n'
                'rows = [json.loads(line) for line in open(os.environ["CIXI_INPUT"], encoding="utf-8") '
                'if line.strip()]\n'
                'with open(os.environ["CIXI_OUTPUT"], "w", encoding="utf-8") as out:\n'
                '    for row in rows:\n'
                '        out.write(json.dumps({"a": row.get("a"), "b": row.get("b")}, ensure_ascii=False) + "\\n")\n'
            ),
        },
    )
    assert saved.status_code == 200, saved.get_json()
    assert saved.get_json()['script']['version'] == 1

    run = client.post(
        '/api/ai/python/run',
        json={'script_id': 'keep_two', 'rows': [{'a': 1, 'b': 2, 'c': 3}], 'args': {}},
    )
    assert run.status_code == 200, run.get_json()
    body = run.get_json()
    assert body['rows'] == 1
    assert body['sample'] == [{'a': 1, 'b': 2}]

    deleted = client.delete('/api/ai/python/scripts/keep_two').get_json()
    assert deleted['deleted'] is True


def test_the_python_routes_refuse_by_name_on_a_cloud_host(client, monkeypatch):
    from api import ai as ai_api
    from core.config import Config

    monkeypatch.setattr(Config, 'CLOUD_MODE', True)
    with client.application.test_request_context('/api/ai/python/status'):
        answer = ai_api._refuse_python_on_cloud()
    assert answer is not None, 'a cloud host served the Python surface'
    body, status = answer
    assert status == 400 and body.get_json()['key'] == 'ai.pythonCloud'
    with client.application.test_request_context('/api/ai/bootstrap'):
        assert ai_api._refuse_python_on_cloud() is None


def test_python_requires_the_setting_and_refuses_cloud(client, monkeypatch):
    from services import python_runtime

    monkeypatch.setattr(python_runtime, 'get_setting', lambda key: False)
    response = client.post('/api/ai/python/run', json={'code': 'print(1)', 'rows': []})
    assert response.status_code == 400
    assert response.get_json()['key'] == 'ai.pythonDisabled'

    monkeypatch.setattr(python_runtime, 'get_setting', lambda key: True)
    monkeypatch.setattr(python_runtime.Config, 'CLOUD_MODE', True)
    from ai.errors import AIError

    with pytest.raises(AIError) as refused:
        python_runtime.run_code('print(1)', [])
    assert refused.value.key == 'ai.pythonCloud'


def _account_tree(root):
    """One account's ``ai.db`` path, created the way ``runtime.paths`` would name it."""
    root.mkdir(parents=True, exist_ok=True)

    class _Tree:
        ai_db = str(root / 'ai.db')

    return _Tree()


def test_a_monitor_armed_by_an_account_delivers_into_that_accounts_tree(tmp_path, monkeypatch):
    """``threading.Thread`` starts with NO account context, so the delivery worker used to read
    the local owner's ``ai.db``: a monitor armed by a signed-in account matched nothing, and a
    broadcast one wrote that account's run facts into the owner's table. The account travels
    with the queued event; this pins both halves."""
    from ai import monitors, store
    from runtime import account_context, paths, run_events

    owner = account_context.Account(user_id='u1', username='u1')
    mine = _account_tree(tmp_path / 'users' / 'u1')
    system = _account_tree(tmp_path / 'system')

    def active():
        return mine if account_context.current() is owner else system

    monkeypatch.setattr(paths, 'active', active)
    with account_context.use(owner):
        conversation = store.create_conversation('deepseek', 'm', 'project')
        monitors.create(
            conversation['id'],
            {'run_id': 'run-acc', 'events': ['node.finished'], 'statuses': ['failed']},
        )
        run_events.publish('node.finished', run_id='run-acc', node_id='n1', status='failed', rows=0)
    assert monitors.drain(timeout=10) is True
    with account_context.use(owner):
        delivered = store.list_monitor_events(pending_only=True)
    with account_context.use(None):
        assert store.list_monitor_events(pending_only=True) == [], 'the delivery landed in the local tree'
    assert len(delivered) == 1 and delivered[0]['payload']['run_id'] == 'run-acc'
