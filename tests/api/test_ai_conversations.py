"""Conversation management: title search, pinning, archiving and the download formats.

The list is a page, so search runs in SQLite; pinning is a stored column the order already reads;
archiving hides a conversation without deleting it. Export is a projection of the stored rows, not
a second renderer — the JSON form is the lossless one.
"""

import json
from urllib.parse import unquote

import pytest

pytestmark = pytest.mark.api


def _conversation(client, title: str = '') -> str:
    created = client.post('/api/ai/conversations', json={'provider': 'deepseek', 'model': 'm', 'skill': 'auto'})
    assert created.status_code == 200, created.get_json()
    conversation_id = created.get_json()['conversation']['id']
    if title:
        client.patch('/api/ai/conversations/' + conversation_id, json={'title': title})
    return conversation_id


def _patch(client, conversation_id: str, **fields):
    response = client.patch('/api/ai/conversations/' + conversation_id, json=fields)
    assert response.status_code == 200, response.get_json()
    return response.get_json()['conversation']


def test_stop_does_not_signal_a_conversation_this_account_cannot_see(client, monkeypatch):
    """ACTIVE_STREAMS is process-wide; without the owner check a known id could cancel a
    foreign account's paid turn and make it look like the victim pressed 停止. Process-only
    scopes still stop, so the route itself stays 200."""
    from ai import agent

    signalled = []
    monkeypatch.setattr(agent, 'stop', lambda conversation_id: signalled.append(conversation_id) or True)
    response = client.post('/api/ai/stop', json={'conversation_id': 'c_' + '0' * 24})
    assert response.status_code == 200
    assert response.get_json()['ok'] is True
    assert response.get_json()['stopped'] is False
    assert signalled == []


def test_a_title_search_is_sql_side_and_escapes_like_metacharacters(client):
    exact = _conversation(client, '100% 完成 zz-search')
    other = _conversation(client, '100x 完成 zz-search')
    _conversation(client, '别的话题 zz-search')

    rows = client.get('/api/ai/conversations?q=100%25').get_json()['conversations']
    found = {row['id'] for row in rows}
    # A raw LIKE would return BOTH (and an empty pattern would return the third through `%`).
    assert exact in found
    assert other not in found

    rows = client.get('/api/ai/conversations?q=zz-search').get_json()['conversations']
    assert {exact, other}.issubset({row['id'] for row in rows})


def test_pinning_moves_a_conversation_to_the_top_of_its_page(client):
    older = _conversation(client, 'older')
    newer = _conversation(client, 'newer')
    order = [row['id'] for row in client.get('/api/ai/conversations').get_json()['conversations']]
    assert order.index(newer) < order.index(older)
    _patch(client, older, pinned=True)
    rows = client.get('/api/ai/conversations').get_json()['conversations']
    assert rows[0]['id'] == older
    assert rows[0]['pinned'] == 1
    _patch(client, older, pinned=False)
    order = [row['id'] for row in client.get('/api/ai/conversations').get_json()['conversations']]
    # Unpinning is not activity either: the conversation returns to its recency slot instead of
    # jumping above the chat that was actually used last.
    assert order.index(newer) < order.index(older)


def test_an_archived_conversation_is_hidden_until_asked_for(client):
    kept = _conversation(client, 'keep me')
    gone = _conversation(client, 'hide me')
    _patch(client, gone, archived=True)

    visible = {row['id'] for row in client.get('/api/ai/conversations').get_json()['conversations']}
    assert kept in visible
    assert gone not in visible
    archived = {row['id'] for row in client.get('/api/ai/conversations?archived=1').get_json()['conversations']}
    assert archived == {gone}

    _patch(client, gone, archived=False)
    visible = {row['id'] for row in client.get('/api/ai/conversations').get_json()['conversations']}
    assert {kept, gone}.issubset(visible)
    assert gone not in {row['id'] for row in client.get('/api/ai/conversations?archived=1').get_json()['conversations']}


def test_export_names_the_file_and_projects_the_rows(client):
    from ai import store

    conversation_id = _conversation(client, '周报/草稿')
    store.append_message(conversation_id, 'user', '请总结这次运行')
    assistant = store.append_message(conversation_id, 'assistant', '', status='streaming')
    store.update_message(
        assistant['id'],
        status='done',
        content='这次运行有 2 个失败节点。',
        blocks=[{'type': 'text', 'text': '这次运行有 2 个失败节点。'}],
    )
    store.append_message(
        conversation_id,
        'tool',
        json.dumps({'ok': True}),
        meta={'name': 'run_status'},
    )

    response = client.get('/api/ai/conversations/' + conversation_id + '/export?format=md')
    assert response.status_code == 200
    assert response.mimetype == 'text/markdown'
    disposition = response.headers['Content-Disposition']
    assert disposition.startswith("attachment; filename*=UTF-8''")
    assert '"' not in disposition and '\n' not in disposition
    filename = unquote(disposition.split("UTF-8''", 1)[1])
    assert filename == '周报_草稿.md'
    body = response.get_data(as_text=True)
    assert body.startswith('# 周报/草稿')
    assert '请总结这次运行' in body
    assert '这次运行有 2 个失败节点。' in body
    assert '`run_status`' in body

    payload = client.get('/api/ai/conversations/' + conversation_id + '/export?format=json').get_json()
    assert payload['conversation']['id'] == conversation_id
    assert [row['role'] for row in payload['messages']] == ['user', 'assistant', 'tool']
    assert payload['messages'][1]['blocks'][0]['text'] == '这次运行有 2 个失败节点。'
    assert unquote(
        client.get('/api/ai/conversations/' + conversation_id + '/export?format=json')
        .headers['Content-Disposition']
        .split("UTF-8''", 1)[1]
    ).endswith('.json')


def test_an_unknown_format_and_an_unknown_conversation_are_refused_by_name(client):
    conversation_id = _conversation(client, 'x')
    bad = client.get('/api/ai/conversations/' + conversation_id + '/export?format=pdf')
    assert bad.status_code == 400
    assert bad.get_json()['ok'] is False

    missing = client.get('/api/ai/conversations/nope/export?format=md')
    assert missing.status_code == 404
    assert missing.get_json()['key'] == 'ai.apiNoConversation'
