"""The artifact preview endpoint describes a change without applying it.

Validation stays authoritative and the apply endpoints stay the only door that writes. These cases
pin both halves: a legal preview is only a description, and an illegal draft or an unknown kind is
refused BY NAME instead of painting a card the app cannot act on.
"""

import pytest

pytestmark = pytest.mark.api


@pytest.fixture(autouse=True)
def clean_memories():
    def wipe():
        from ai_host.manager import WorkspaceManager

        workspace = WorkspaceManager().workspace('default')
        for row in workspace.store.list_memories('default'):
            workspace.store.delete_memory('default', row['id'])

    wipe()
    yield
    wipe()


def test_a_preview_describes_a_memory_without_writing_it(client):
    response = client.post('/api/ai/ws/artifacts/preview', json={'kind': 'memory', 'payload': {'text': 'preview me'}})
    assert response.status_code == 200
    data = response.get_json()
    assert data['ok'] is True
    assert 'preview me' in data['preview']['summary']
    assert data['preview']['selectable'] is False
    assert client.get('/api/ai/ws/memories').get_json()['memories'] == [], 'a preview wrote a memory'


def test_an_illegal_draft_is_refused_with_the_validators_sentence(client):
    from ai.validators.memory import MAX_MEMORY_CHARS

    from i18n import t

    response = client.post('/api/ai/ws/artifacts/preview', json={'kind': 'memory', 'payload': {'text': ''}})
    assert response.status_code == 400
    data = response.get_json()
    assert data['ok'] is False
    assert t('ai.memoryDraftRefused', limit=MAX_MEMORY_CHARS) in data['error']


def test_an_unregistered_kind_is_refused_by_name(client):
    response = client.post('/api/ai/ws/artifacts/preview', json={'kind': 'plan', 'payload': {}})
    assert response.status_code == 400
    data = response.get_json()
    assert data['ok'] is False
    assert data['key'] == 'ai.preview.unknown'


def test_a_workflow_preview_diffs_against_the_current_canvas(client):
    response = client.post(
        '/api/ai/ws/artifacts/preview',
        json={
            'kind': 'workflow_draft',
            'payload': {
                'nodes': [
                    {'id': 'n1', 'type': 'name', 'params': {'workflow_name': 'draft'}},
                    {'id': 'n2', 'type': 'analysis', 'params': {'operation': 'topic_label'}},
                ],
                'connections': [{'from': 'n1', 'to': 'n2'}],
            },
            'current': {
                'nodes': [{'id': 'n1', 'type': 'name', 'params': {'workflow_name': 'current'}}],
                'connections': [],
            },
        },
    )
    assert response.status_code == 200, response.get_json()
    preview = response.get_json()['preview']
    assert preview['selectable'] is True
    actions = {item['id']: item['action'] for item in preview['items']}
    assert actions['n1'] == 'change' and actions['n2'] == 'add'
