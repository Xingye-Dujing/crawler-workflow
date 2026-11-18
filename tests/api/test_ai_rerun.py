"""Rerunning one failed node from the AI workspace: the extracted decision and its AI door.

The engine is never started here — ``engine.run.begin_run`` is replaced with a recorder — so these
cases pin the refusals (missing file, changed canvas, unknown node, live run), the named sentence
each door answers, and the hand-off to the ONE start path.
"""

import pytest
from runtime.stores import get_workflow_manager

from engine.workflow import effective_workflow
from engine.workflow_rerun import RerunRefusalError, rerun_node
from services.runs.store import NODE_DONE, RUN_COMPLETED, workflow_fingerprint

pytestmark = pytest.mark.api


def _workflow():
    return {
        'name': 'wf',
        'nodes': [
            {'id': 'n1', 'type': 'upload', 'params': {'dataset_id': 'd1'}},
            {'id': 'n2', 'type': 'process', 'params': {'operation': 'keyword'}},
            {'id': 'n3', 'type': 'output', 'params': {}},
        ],
        'connections': [{'from': 'n1', 'to': 'n2'}, {'from': 'n2', 'to': 'n3'}],
    }


def _fingerprint():
    return workflow_fingerprint(effective_workflow(_workflow()))


def _seed_run(store, run_id='run-ai', fingerprint=None, finished=True, node_ids=('n1', 'n2', 'n3')):
    store.start_run(run_id, 'wf', fingerprint or _fingerprint())
    for nid in node_ids:
        store.begin_node(run_id, nid, 'process', fingerprint='node-' + nid)
        store.finish_node(run_id, nid, NODE_DONE)
    if finished:
        store.finish_run(run_id, RUN_COMPLETED)


@pytest.fixture
def fake_begin(monkeypatch):
    calls = []

    def _fake(data, lang):
        calls.append((data, lang))
        return {'status': 200, 'body': {'ok': True, 'run_id': data.get('resume_run_id') or 'new'}}

    import engine.run

    monkeypatch.setattr(engine.run, 'begin_run', _fake)
    return calls


@pytest.fixture
def conversation():
    from ai import store

    return store.create_conversation('deepseek', 'deepseek-flash', 'auto')


def _post(client, conversation_id, **overrides):
    body = {
        'conversation_id': conversation_id,
        'run_id': 'run-ai',
        'workflow_name': 'wf',
        'node_id': 'n2',
    }
    body.update(overrides)
    return client.post('/api/ai/rerun', json=body)


class TestTheExtractedDecision:
    def test_it_wipes_only_the_target_subtree_and_resumes_the_same_run(self, client, app_module, fake_begin):
        store = app_module.get_run_store()
        _seed_run(store)
        answer = rerun_node(_workflow(), 'n2', 'run-ai', workflow_name='wf', lang='zh')
        assert answer['status'] == 200
        assert sorted(answer['body']['invalidated']) == ['n2', 'n3']
        assert answer['body']['rerun_from'] == 'n2'
        assert len(fake_begin) == 1
        sent, _lang = fake_begin[0]
        assert sent['resume_run_id'] == 'run-ai'
        assert sent['queue'] is False
        assert set(sent['rerun_invalidate']['node_ids']) == {'n2', 'n3'}
        # The request never wipes: the claimed worker does, so a refusal keeps every row.
        assert store.get_node_status('run-ai', 'n2') == NODE_DONE

    def test_a_changed_canvas_is_refused_by_name(self, client, app_module, fake_begin):
        store = app_module.get_run_store()
        _seed_run(store, fingerprint='another-canvas')
        with pytest.raises(RerunRefusalError) as caught:
            rerun_node(_workflow(), 'n2', 'run-ai')
        assert caught.value.key == 'api.rerunFingerprintMismatch'
        assert caught.value.status == 409
        assert fake_begin == []

    def test_a_missing_run_is_refused_by_name(self, client, app_module, fake_begin):
        with pytest.raises(RerunRefusalError) as caught:
            rerun_node(_workflow(), 'n2', 'not-a-run')
        assert caught.value.key == 'api.resumeMissing'
        assert caught.value.status == 400
        assert fake_begin == []

    def test_an_unknown_node_is_refused_by_name(self, client, app_module, fake_begin):
        store = app_module.get_run_store()
        _seed_run(store)
        with pytest.raises(RerunRefusalError) as caught:
            rerun_node(_workflow(), 'ghost', 'run-ai')
        assert caught.value.key == 'api.rerunNoNode'
        assert caught.value.params == {'node': 'ghost'}
        assert fake_begin == []

    def test_a_live_run_is_refused_by_name(self, client, app_module, fake_begin):
        store = app_module.get_run_store()
        _seed_run(store, finished=False)
        with pytest.raises(RerunRefusalError) as caught:
            rerun_node(_workflow(), 'n2', 'run-ai')
        assert caught.value.key == 'api.rerunRunLive'
        assert caught.value.status == 409
        assert fake_begin == []

    def test_a_saved_file_never_touches_the_canvas(self, client, app_module):
        """The function takes a workflow dict only for its fingerprint — nothing is loaded anywhere."""
        store = app_module.get_run_store()
        _seed_run(store)
        canvas = _workflow()
        before = [node['id'] for node in canvas['nodes']]
        with pytest.raises(RerunRefusalError) as caught:
            rerun_node(canvas, 'ghost', 'run-ai')
        assert caught.value.status == 400
        assert [node['id'] for node in canvas['nodes']] == before


class TestTheHttpDoor:
    def test_a_failed_node_is_rerun_from_the_saved_file(self, client, app_module, fake_begin, conversation):
        store = app_module.get_run_store()
        _seed_run(store)
        get_workflow_manager().save('wf', _workflow())
        response = _post(client, conversation['id'])
        body = response.get_json()
        assert response.status_code == 200, body
        assert body['ok'] is True
        assert sorted(body['invalidated']) == ['n2', 'n3']
        assert body['node_id'] == 'n2'
        assert body['run_id'] == 'run-ai'
        assert len(fake_begin) == 1

    def test_a_missing_workflow_file_is_named(self, client, app_module, fake_begin, conversation):
        store = app_module.get_run_store()
        _seed_run(store)
        response = _post(client, conversation['id'], workflow_name='never-saved')
        body = response.get_json()
        assert response.status_code == 404
        assert body['ok'] is False
        assert 'never-saved' in body['error']
        assert fake_begin == []

    def test_a_changed_canvas_is_refused_with_the_workspace_sentence(
        self, client, app_module, fake_begin, conversation
    ):
        store = app_module.get_run_store()
        _seed_run(store, fingerprint='another-canvas')
        get_workflow_manager().save('wf', _workflow())
        response = _post(client, conversation['id'])
        body = response.get_json()
        assert response.status_code == 409
        assert body['key'] == 'api.rerunFingerprintMismatch'
        assert '画布' in body['error'] or 'canvas' in body['error'].lower()
        assert fake_begin == []

    def test_a_live_run_is_refused(self, client, app_module, fake_begin, conversation):
        store = app_module.get_run_store()
        _seed_run(store, finished=False)
        get_workflow_manager().save('wf', _workflow())
        response = _post(client, conversation['id'])
        assert response.status_code == 409
        assert fake_begin == []

    def test_blank_arguments_are_refused(self, client, conversation):
        body = _post(client, conversation['id'], node_id='').get_json()
        assert body['ok'] is False
        assert 'run_id' in body['error'] or 'node_id' in body['error'] or 'workflow_name' in body['error']

    def test_a_run_with_no_saved_workflow_is_named(self, client, conversation):
        response = _post(client, conversation['id'], workflow_name='')
        body = response.get_json()
        assert response.status_code == 400
        assert body['ok'] is False
        assert body['error']

    def test_an_unknown_conversation_is_a_404(self, client):
        response = client.post(
            '/api/ai/rerun',
            json={'conversation_id': 'c_missing', 'run_id': 'r', 'workflow_name': 'wf', 'node_id': 'n2'},
        )
        assert response.status_code == 404


class RerunProvider:
    """Calls rerun_node once, then answers."""

    def __init__(self):
        from ai.types import ModelSpec, ProviderSpec

        capabilities = frozenset({'thinking', 'tools', 'ask_user'})
        self.spec = ProviderSpec(
            id='fake_rerun',
            label_key='ai.provider.deepseek',
            notes_key='ai.providerNote.deepseek',
            protocol='openai',
            base_url='',
            models=(ModelSpec('fake-model', 'Fake', 10000, capabilities),),
            capabilities=capabilities,
        )

    def supports(self, capability: str, model: str = '') -> bool:
        return capability in self.spec.capabilities

    def context_window(self, model: str = '') -> int:
        return 0

    def stream(self, request):
        answered = any(message.get('role') == 'tool' for message in request.get('messages', []))
        if not answered:
            yield {
                'type': 'tool_call',
                'id': 'call_rerun',
                'name': 'rerun_node',
                'arguments': {'run_id': 'run-ai', 'workflow_name': 'wf', 'node_id': 'n2'},
            }
            yield {'type': 'done', 'stop_reason': 'tool_calls'}
            return
        yield {'type': 'text_delta', 'text': 'Rerunning it.'}
        yield {'type': 'done', 'stop_reason': 'end_turn'}


def test_the_agent_reruns_a_node_and_does_not_load_the_canvas(client, app_module, monkeypatch, fake_begin):
    from ai import store
    from ai.providers import PROVIDERS

    monkeypatch.setitem(PROVIDERS, 'fake_rerun', RerunProvider())
    store.mark_interrupted()
    _seed_run(app_module.get_run_store())
    get_workflow_manager().save('wf', _workflow())
    response = client.post(
        '/api/ai/chat?stream=0',
        json={
            'text': 'rerun the failed node',
            'provider': 'fake_rerun',
            'model': 'fake-model',
            'api_key': 'secret-key',
            'skill': 'monitor',
            'context': {},
        },
    )
    data = response.get_json()
    assert data['ok'] is True, data
    events = data['events']
    started = [event for event in events if event['type'] == 'rerun_started']
    assert len(started) == 1
    assert started[0]['run_id'] == 'run-ai'
    assert started[0]['node_id'] == 'n2'
    assert len(fake_begin) == 1
    # Loading a workflow is the OTHER tool's effect; a rerun must not replace the user's canvas.
    assert not [event for event in events if event['type'] == 'workflow_apply']
