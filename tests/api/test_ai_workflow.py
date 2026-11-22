"""The AI HTTP surface, driven by a scripted provider. No network, no paid call."""

import json

import pytest

pytestmark = pytest.mark.api


class FakeProvider:
    def __init__(self, provider_id: str = 'fake_ai'):
        from ai.types import ModelSpec, ProviderSpec

        self.seen_keys = []
        capabilities = frozenset({'thinking', 'tools', 'ask_user'})
        self.spec = ProviderSpec(
            id=provider_id,
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
        # 0 = "no window to fit": a scripted provider has nothing to trim against.
        return 0

    def list_models(self, api_key: str = '', _host: str = '') -> list:
        self.seen_keys.append(api_key)
        return [{'id': 'fake-model', 'label': 'Fake'}]

    def stream(self, request):
        if request.get('_ask'):
            yield {
                'type': 'tool_call',
                'id': 'call_1',
                'name': 'ask_user_question',
                'arguments': {
                    'questions': [
                        {
                            'id': 'scope',
                            'question': 'Which data?',
                            'options': [{'label': 'Dataset A'}, {'label': 'Dataset B'}],
                        }
                    ]
                },
            }
            yield {'type': 'done', 'stop_reason': 'tool_calls'}
            return
        yield {'type': 'thinking_delta', 'text': 'thinking'}
        yield {'type': 'text_delta', 'text': 'Hello '}
        yield {'type': 'text_delta', 'text': 'world'}
        yield {'type': 'usage', 'usage': {'prompt_tokens': 4, 'completion_tokens': 2}}
        yield {'type': 'done', 'stop_reason': 'end_turn'}


class RecordingProvider(FakeProvider):
    """One tool round, then an answer, and it KEEPS every request it was handed."""

    def __init__(self):
        super().__init__('fake_record')
        self.requests = []

    def stream(self, request):
        self.requests.append(request)
        planned = any(
            block.get('type') == 'tool_use'
            for message in request.get('messages') or []
            for block in message.get('blocks') or []
        )
        if not planned:
            yield {
                'type': 'tool_call',
                'id': 'call_plan',
                'name': 'update_plan',
                'arguments': {'steps': [{'title': 'look', 'status': 'pending'}]},
            }
            yield {'type': 'done', 'stop_reason': 'tool_calls'}
            return
        yield {'type': 'text_delta', 'text': 'done'}
        yield {'type': 'done', 'stop_reason': 'end_turn'}


class AskThenAnswerProvider(FakeProvider):
    def __init__(self):
        super().__init__('fake_ask')

    def stream(self, request):
        has_call = any(
            block.get('type') == 'tool_use'
            for message in request.get('messages', [])
            for block in message.get('blocks') or []
        )
        if not has_call:
            yield from super().stream({'_ask': True})
            return
        yield {'type': 'text_delta', 'text': 'You chose Dataset A.'}
        yield {'type': 'done', 'stop_reason': 'end_turn'}


class WindowedProvider(FakeProvider):
    """A provider that reports a model window, so the agent has something to fit the history into.

    Every other fake returns 0 ("no window to fit"), which is why the trimming path had never run
    through a real turn.
    """

    def __init__(self):
        super().__init__('fake_window')

    def context_window(self, model: str = '') -> int:
        return 3000


@pytest.fixture
def fake_ai(monkeypatch):
    from ai.providers import PROVIDERS

    monkeypatch.setitem(PROVIDERS, 'fake_ai', FakeProvider())
    monkeypatch.setitem(PROVIDERS, 'fake_ask', AskThenAnswerProvider())
    monkeypatch.setitem(PROVIDERS, 'fake_record', RecordingProvider())
    monkeypatch.setitem(PROVIDERS, 'fake_window', WindowedProvider())


@pytest.fixture
def clean_ai():
    from ai import store

    store.mark_interrupted()
    yield


def _chat(client, **overrides):
    body = {
        'text': 'hello',
        'provider': 'fake_ai',
        'model': 'fake-model',
        'api_key': 'secret-key',
        'skill': 'project',
        'context': {},
    }
    body.update(overrides)
    return client.post('/api/ai/chat?stream=0', json=body)


def test_chat_returns_canonical_events_and_never_stores_the_key(client, fake_ai, clean_ai):
    response = _chat(client)
    assert response.status_code == 200
    data = response.get_json()
    assert data['ok'] is True
    types = [event['type'] for event in data['events']]
    assert 'meta' in types and 'text' in types and 'done' in types
    conversation_id = data['events'][0]['conversation_id']
    detail = client.get('/api/ai/conversations/' + conversation_id).get_json()
    assert detail['ok'] is True
    assert detail['messages']
    assert 'secret-key' not in json.dumps(detail, ensure_ascii=False)


def test_a_reader_that_disconnects_mid_answer_leaves_an_interrupted_row(client, fake_ai, clean_ai):
    """The reload / closed-panel case: the SSE reader goes away before the answer's ending.

    The agent suspends at a ``yield``, so a disconnect means it never writes the round's verdict.
    Without a settlement at the disconnect the row stayed ``streaming`` for the whole session, and
    the next page load drew a half answer that read like a finished one (only a server restart
    swept it). The status is what the workspace turns into "this answer was cut off".
    """
    from ai import store

    body = {
        'text': 'hello',
        'provider': 'fake_ai',
        'model': 'fake-model',
        'api_key': 'secret-key',
        'skill': 'project',
        'context': {},
    }
    response = client.post('/api/ai/chat', json=body)
    assert response.status_code == 200, response.get_json()
    stream = response.response
    first = next(iter(stream)).decode('utf-8')
    assert '"type": "meta"' in first, first
    conversation_id = json.loads(first.split('data: ', 1)[1])['conversation_id']
    assert [row['status'] for row in store.list_messages(conversation_id) if row['role'] == 'assistant'] == [
        'streaming'
    ]
    # A concurrent answer in ANOTHER conversation must not be swept with it: the settlement is keyed
    # by the conversation this stream owned, or a reload in one chat marks a live answer elsewhere
    # as interrupted.
    other = store.create_conversation('fake_ai', 'fake-model', 'auto')
    foreign = store.append_message(other['id'], 'assistant', '一半', blocks=[], status='streaming')
    stream.close()
    rows = store.list_messages(conversation_id)
    assert [row['status'] for row in rows if row['role'] == 'assistant'] == ['interrupted'], rows
    try:
        assert store.get_message(foreign['id'])['status'] == 'streaming', 'the sweep reached another conversation'
    finally:
        store.update_message(foreign['id'], status='done')
    detail = client.get('/api/ai/conversations/' + conversation_id).get_json()
    assert any(row['status'] == 'interrupted' for row in detail['messages'])


def test_a_raw_stream_fault_settles_the_assistant_row(client, monkeypatch, clean_ai):
    """A non-AIError raised inside a round used to leave the assistant row `streaming` forever.

    The old generic `except` set `ended = True`, so the disconnect settlement in `finally` was
    skipped — even though the browser got a `done` frame. A real store fault (e.g.
    ``sqlite3.OperationalError`` from save_usage) then left a half answer that a reload drew as
    still generating. The generic branch must reach the same settlement as a closed connection.
    """
    import api.ai as ai_api
    from ai import store
    from ai.providers import PROVIDERS

    class BoomProvider(FakeProvider):
        def __init__(self):
            super().__init__('fake_boom')

        def stream(self, request):
            yield {'type': 'text_delta', 'text': 'half an answer'}
            raise RuntimeError('a raw provider fault')

    monkeypatch.setitem(PROVIDERS, 'fake_boom', BoomProvider())
    settled = []
    real_mark = ai_api.store.mark_interrupted

    def spy(cid=''):
        settled.append(cid)
        return real_mark(cid)

    monkeypatch.setattr(ai_api.store, 'mark_interrupted', spy)

    response = client.post(
        '/api/ai/chat',
        json={
            'text': 'hello',
            'provider': 'fake_boom',
            'model': 'fake-model',
            'api_key': 'secret-key',
            'skill': 'project',
            'context': {},
        },
    )
    assert response.status_code == 200, response.get_json()
    events = [
        json.loads(frame[len('data: ') :])
        for chunk in response.response
        for frame in chunk.decode('utf-8').split('\n\n')
        if frame.startswith('data: ')
    ]
    # The done SSE behaviour stays intact: the error branch still emits both frames.
    assert any(event.get('type') == 'error' for event in events)
    assert any(event.get('type') == 'done' and event.get('stop_reason') == 'error' for event in events)
    conversation_id = next(event['conversation_id'] for event in events if event.get('type') == 'meta')
    assert conversation_id in settled, 'the raw fault did not settle the conversation this stream owns'
    rows = store.list_messages(conversation_id)
    assert [row['status'] for row in rows if row['role'] == 'assistant'] == ['interrupted'], rows


def test_a_paused_turn_is_not_a_cut_connection(client, fake_ai, clean_ai):
    """`paused` is an ENDING of this stream (the answer resumes through /api/ai/answer). Leaving it out
    of the settlement's ending events would mark a waiting turn interrupted the moment the browser
    closes the panel."""
    from ai import store

    body = {
        'text': 'which?',
        'provider': 'fake_ask',
        'model': 'fake-model',
        'api_key': 'secret-key',
        'skill': 'project',
        'context': {},
    }
    response = client.post('/api/ai/chat', json=body)
    assert response.status_code == 200, response.get_json()
    stream = response.response
    conversation_id = ''
    paused = False
    for chunk in stream:
        text = chunk.decode('utf-8')
        for frame in text.split('\n\n'):
            if not frame.startswith('data: '):
                continue
            event = json.loads(frame[len('data: ') :])
            conversation_id = event.get('conversation_id') or conversation_id
            if event.get('type') == 'paused':
                paused = True
        if paused:
            break
    assert paused, 'the scripted question never paused the turn'
    stream.close()
    rows = store.list_messages(conversation_id)
    # A pause leaves the row `waiting` (not `streaming`), so the disconnect sweep must not turn it
    # into `interrupted`: the answer is coming back through /api/ai/answer, not being cut.
    assert [row['status'] for row in rows if row['role'] == 'assistant'] == ['waiting'], rows
    assert store.pending_questions(conversation_id), 'the question did not survive the closed stream'


def test_a_real_turn_reports_the_replay_cap_and_the_window_it_trimmed(client, fake_ai, clean_ai):
    """Two numbers the inspector shows exist only after a real turn built them: the size the context
    block was capped to at write time, and how many messages the model's window forced out. The
    trimming function has a unit test; nothing proved the turn calls it and reports it."""
    first = _chat(client, provider='fake_window', model='fake-model', text='问' * 20000)
    assert first.status_code == 200, first.get_json()
    conversation_id = first.get_json()['events'][0]['conversation_id']
    second = _chat(
        client,
        provider='fake_window',
        model='fake-model',
        text='再问一次',
        conversation_id=conversation_id,
    )
    assert second.status_code == 200, second.get_json()
    meta = second.get_json()['events'][0]['context']
    assert meta['replay_chars'] >= 1000 and meta['replay_truncated'] in (True, False), meta
    history = meta.get('history') or {}
    assert history.get('window') == 3000, meta
    assert history.get('dropped', 0) > 0, f'a 3000-token window kept everything: {history}'
    assert history['kept'] >= 1, history


def test_the_project_context_reaches_the_provider_on_every_round(client, fake_ai, clean_ai):
    """The context is part of the TURN, so a tool round must carry it too — and it must reach
    whichever transport the user picked (`base.replay_context`), not only DeepSeek's."""
    from ai.providers import PROVIDERS

    response = _chat(client, provider='fake_record', model='fake-model')
    assert response.status_code == 200, response.get_json()
    conversation_id = response.get_json()['events'][0]['conversation_id']
    provider = PROVIDERS['fake_record']
    assert len(provider.requests) == 2, provider.requests
    for request in provider.requests:
        newest = [message for message in request['messages'] if message['role'] == 'user'][-1]
        assert '<cai_xi_hui_context>' in newest['content'], newest['content'][:200]

    # A second turn replays turn one's row BYTE FOR BYTE. A block that changes after its turn is
    # over invalidates every message after it, so the whole transcript is re-billed at the
    # cache-miss price — that is the difference this test exists to keep.
    first_before = [row for row in provider.requests[0]['messages'] if row['role'] == 'user'][0]['content']
    again = _chat(client, provider='fake_record', model='fake-model', text='and again', conversation_id=conversation_id)
    assert again.status_code == 200, again.get_json()
    first_after = [row for row in provider.requests[-1]['messages'] if row['role'] == 'user'][0]['content']
    assert first_after == first_before


def test_conversation_list_and_delete(client, fake_ai, clean_ai):
    response = _chat(client)
    conversation_id = response.get_json()['events'][0]['conversation_id']
    listing = client.get('/api/ai/conversations').get_json()
    assert listing['ok'] is True
    assert any(row['id'] == conversation_id for row in listing['conversations'])
    deleted = client.delete('/api/ai/conversations/' + conversation_id).get_json()
    assert deleted['ok'] is True
    assert client.get('/api/ai/conversations/' + conversation_id).status_code == 404


def test_ask_user_pauses_and_answer_resumes(client, fake_ai, clean_ai):
    response = _chat(client, provider='fake_ask', model='fake-model', text='which?')
    data = response.get_json()
    events = data['events']
    meta = next(event for event in events if event['type'] == 'meta')
    question = next(event for event in events if event['type'] == 'question')
    assert any(event['type'] == 'paused' for event in events)
    assert question['questions'][0]['question'] == 'Which data?'
    answer = {
        'conversation_id': meta['conversation_id'],
        'message_id': question['message_id'],
        'question_id': question['question_id'],
        'answers': [{'id': 'scope', 'selected': ['Dataset A']}],
        'api_key': 'secret-key',
    }
    resumed = client.post('/api/ai/answer?stream=0', json=answer)
    assert resumed.status_code == 200, resumed.get_json()
    resumed_events = resumed.get_json()['events']
    assert any(event['type'] == 'text' and 'Dataset A' in event.get('text', '') for event in resumed_events)


def test_answer_needs_only_the_question_id_after_a_reopen(client, fake_ai, clean_ai):
    """A reopened card has no live message element; the question row must be enough.

    The old route trusted the browser's ``message_id`` and answered 404 "找不到消息：" when a
    reload, a conversation switch or a repaint had cleared it. The question row remembers the
    assistant row that asked, so the server derives it and the answer resumes.
    """
    response = _chat(client, provider='fake_ask', model='fake-model', text='which?')
    events = response.get_json()['events']
    meta = next(event for event in events if event['type'] == 'meta')
    question = next(event for event in events if event['type'] == 'question')

    # No message_id at all — the restored-card shape.
    answer = {
        'conversation_id': meta['conversation_id'],
        'question_id': question['question_id'],
        'answers': [{'id': 'scope', 'selected': ['Dataset A']}],
        'api_key': 'secret-key',
    }
    resumed = client.post('/api/ai/answer?stream=0', json=answer)
    assert resumed.status_code == 200, resumed.get_json()
    assert any(
        event['type'] == 'text' and 'Dataset A' in event.get('text', '') for event in resumed.get_json()['events']
    )


def test_a_stale_message_id_cannot_misdirect_a_question_answer(client, fake_ai, clean_ai):
    """The question row wins over a stale id the browser kept from another turn."""
    response = _chat(client, provider='fake_ask', model='fake-model', text='which?')
    events = response.get_json()['events']
    meta = next(event for event in events if event['type'] == 'meta')
    question = next(event for event in events if event['type'] == 'question')

    answer = {
        'conversation_id': meta['conversation_id'],
        'message_id': 'msg_from_another_turn',
        'question_id': question['question_id'],
        'answers': [{'id': 'scope', 'selected': ['Dataset A']}],
        'api_key': 'secret-key',
    }
    resumed = client.post('/api/ai/answer?stream=0', json=answer)
    assert resumed.status_code == 200, resumed.get_json()
    assert any(
        event['type'] == 'text' and 'Dataset A' in event.get('text', '') for event in resumed.get_json()['events']
    )


def test_a_new_message_does_not_cancel_a_pending_question(client, fake_ai, clean_ai):
    """The question must outlive a second message; the old code cancelled it silently.

    A refusal by name is the honest queue boundary for now: the question stays pending and can
    still be answered. The full mailbox (queue + steer) lands with the turn runner.
    """
    response = _chat(client, provider='fake_ask', model='fake-model', text='which?')
    events = response.get_json()['events']
    meta = next(event for event in events if event['type'] == 'meta')
    question = next(event for event in events if event['type'] == 'question')

    second = _chat(
        client,
        provider='fake_ask',
        model='fake-model',
        text='also this',
        conversation_id=meta['conversation_id'],
    )
    assert second.status_code == 400, second.get_json()
    assert second.get_json()['key'] == 'ai.questionPending'

    from ai import store

    assert store.pending_questions(meta['conversation_id']), 'the question was cancelled by the new message'
    answer = {
        'conversation_id': meta['conversation_id'],
        'question_id': question['question_id'],
        'answers': [{'id': 'scope', 'selected': ['Dataset A']}],
        'api_key': 'secret-key',
    }
    resumed = client.post('/api/ai/answer?stream=0', json=answer)
    assert resumed.status_code == 200, resumed.get_json()


def test_an_answer_can_reference_a_file_and_the_model_sees_it(client, fake_ai, clean_ai, monkeypatch):
    """The question card's answer box takes `@`: the server resolves it into the resumed turn.

    Resolved server-side and bounded, exactly like the composer's references — the browser sends
    ids it already has, never a path or a whole table.
    """
    from ai import agent as agent_module

    monkeypatch.setattr(agent_module.references, 'resolve', lambda refs: ('<ref: 语料 120 行>', []))
    response = _chat(client, provider='fake_ask', model='fake-model', text='which?')
    events = response.get_json()['events']
    meta = next(event for event in events if event['type'] == 'meta')
    question = next(event for event in events if event['type'] == 'question')
    answer = {
        'conversation_id': meta['conversation_id'],
        'message_id': question['message_id'],
        'question_id': question['question_id'],
        'answers': [{'id': 'scope', 'selected': ['Dataset A'], 'custom': '用这个'}],
        'references': [{'kind': 'dataset', 'id': 'd1'}],
        'api_key': 'secret-key',
    }
    resumed = client.post('/api/ai/answer?stream=0', json=answer)
    assert resumed.status_code == 200, resumed.get_json()
    stored = client.get('/api/ai/conversations/' + meta['conversation_id']).get_json()
    tool_row = next(
        message
        for message in stored['messages']
        if message['role'] == 'tool' and 'answer_to_pending_question' in str(message.get('content') or '')
    )
    assert '语料 120 行' in tool_row['content']


def test_referenced_secrets_are_redacted_before_the_provider_sees_them(client, fake_ai, clean_ai, monkeypatch):
    """references.resolve() runs after build_context()'s redaction, so its text needs its own pass.

    A token inside a referenced export/dataset otherwise reached the provider verbatim and was
    stored on the user row that is replayed for every later turn.
    """
    from ai import agent as agent_module
    from ai.providers import PROVIDERS

    monkeypatch.setattr(agent_module.references, 'resolve', lambda refs: ('导出 token = sk-abcdefgh12345678', []))
    response = _chat(
        client,
        provider='fake_record',
        model='fake-model',
        text='check this',
        references=[{'kind': 'export', 'id': 'e1'}],
    )
    assert response.status_code == 200, response.get_json()
    sent = json.dumps(PROVIDERS['fake_record'].requests, ensure_ascii=False, default=str)
    assert 'sk-abcdefgh12345678' not in sent, 'a referenced secret reached the provider'
    assert '[redacted]' in sent, 'the referenced text was not redacted at all'
    # The scrub is a reported fact, so the inspector can say a reference was cleaned.
    events = response.get_json()['events']
    meta = next(event for event in events if event['type'] == 'meta')
    assert meta['context']['redacted'].get('引用') == 1, meta['context'].get('redacted')


def test_referenced_secrets_are_redacted_in_the_answer_replay(client, fake_ai, clean_ai, monkeypatch):
    """The answer box's `@` resolves AFTER redaction too; its tool row is replayed forever."""
    from ai import agent as agent_module

    # Respect an empty refs list, as the real resolver does: the setup turn has no `@` references,
    # so its context must not be scrubbed — only the resumed answer's references are.
    monkeypatch.setattr(
        agent_module.references,
        'resolve',
        lambda refs: ('<ref> token = sk-abcdefgh12345678', []) if refs else ('', []),
    )
    response = _chat(client, provider='fake_ask', model='fake-model', text='which?')
    events = response.get_json()['events']
    meta = next(event for event in events if event['type'] == 'meta')
    question = next(event for event in events if event['type'] == 'question')
    resumed = client.post(
        '/api/ai/answer?stream=0',
        json={
            'conversation_id': meta['conversation_id'],
            'message_id': question['message_id'],
            'question_id': question['question_id'],
            'answers': [{'id': 'scope', 'selected': ['Dataset A']}],
            'references': [{'kind': 'export', 'id': 'e1'}],
            'api_key': 'secret-key',
        },
    )
    assert resumed.status_code == 200, resumed.get_json()
    stored = client.get('/api/ai/conversations/' + meta['conversation_id']).get_json()
    tool_row = next(
        message
        for message in stored['messages']
        if message['role'] == 'tool' and 'answer_to_pending_question' in str(message.get('content') or '')
    )
    assert '<ref>' in tool_row['content']
    assert 'sk-abcdefgh12345678' not in tool_row['content'], 'a referenced secret was stored in the replay block'
    assert '[redacted]' in tool_row['content']
    resumed_events = resumed.get_json()['events']
    resumed_meta = next(event for event in resumed_events if event['type'] == 'meta')
    assert resumed_meta['context']['redacted'].get('引用') == 1, resumed_meta['context'].get('redacted')


def test_asking_web_search_of_go_refuses_by_name(client, monkeypatch):
    from ai.providers import PROVIDERS
    from ai.providers.opencode_go import OpenCodeGoProvider

    monkeypatch.setitem(PROVIDERS, 'opencode_go', OpenCodeGoProvider())
    response = _chat(
        client,
        provider='opencode_go',
        model='deepseek-v4.1-flash',
        web_search=True,
        skill='project',
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body['key'] == 'ai.capabilityRefused'


def test_a_document_reaches_a_provider_without_files_as_extracted_text(client, fake_ai, clean_ai):
    """A local model has no Files API. The server extracts the document's words, and the turn
    carries them as context — the attachment used to be refused by a `files` check instead."""
    from ai import files, store
    from ai.providers import PROVIDERS

    conversation = store.create_conversation('fake_record', 'fake-model', 'auto')
    body = '附件正文：今天讨论的是采析绘的断点续跑。'.encode()
    path, digest = files.save_local(body, 'note.txt')
    row = store.add_attachment(conversation['id'], 'note.txt', 'text/plain', len(body), digest, 'user_data', '', path)
    response = _chat(
        client,
        provider='fake_record',
        model='fake-model',
        skill='project',
        conversation_id=conversation['id'],
        attachments=[row['id']],
    )
    assert response.status_code == 200, response.get_json()
    sent = json.dumps(
        [request.get('messages') for request in PROVIDERS['fake_record'].requests],
        ensure_ascii=False,
        default=str,
    )
    assert '今天讨论的是采析绘的断点续跑' in sent
    assert not _turn_errors(response.get_json())


def test_an_image_is_refused_by_the_vision_capability_not_files(client, fake_ai, clean_ai, tmp_path):
    from ai import store

    conversation = store.create_conversation('fake_ai', 'fake-model', 'auto')
    image = tmp_path / 'shot.png'
    image.write_bytes(b'\x89PNG\r\n\x1a\n')
    row = store.add_attachment(
        conversation['id'], 'shot.png', 'image/png', image.stat().st_size, 'digest', 'user_data', '', str(image)
    )
    response = _chat(
        client,
        provider='fake_ai',
        model='fake-model',
        skill='project',
        conversation_id=conversation['id'],
        attachments=[row['id']],
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body['key'] == 'ai.capabilityRefused'
    assert 'vision' in body['error']


def test_upload_accepts_a_provider_without_a_files_api_and_extracts_text(client, clean_ai):
    """The upload route used to answer `ai.fileUnsupported` for anything but DeepSeek."""
    import io

    from ai import store

    conversation = store.create_conversation('ollama', 'qwen3.5:9b', 'auto')
    response = client.post(
        '/api/ai/files',
        data={
            'conversation_id': conversation['id'],
            'provider': 'ollama',
            'file': (io.BytesIO('本地模型也能读的正文'.encode()), 'note.txt'),
        },
        content_type='multipart/form-data',
    )
    assert response.status_code == 200, response.get_json()
    attachment = response.get_json()['attachment']
    assert attachment['file_id'] == ''
    # Eager extraction ran at upload; a later turn reads the cache.
    from ai import file_text
    from ai import store as ai_store

    extracted = file_text.extract_attachment(ai_store.get_attachment(attachment['id']))
    assert '本地模型也能读的正文' in extracted['text']


def test_upload_refuses_a_legacy_doc_at_upload_time(client, clean_ai):
    import io

    from ai import store

    conversation = store.create_conversation('ollama', 'qwen3.5:9b', 'auto')
    response = client.post(
        '/api/ai/files',
        data={
            'conversation_id': conversation['id'],
            'provider': 'ollama',
            'file': (io.BytesIO(b'\xd0\xcf\x11\xe0binary'), 'old.doc'),
        },
        content_type='multipart/form-data',
    )
    assert response.status_code == 400
    assert response.get_json()['key'] == 'ai.attachConvert'
    assert store.list_attachments(conversation['id']) == []


def test_skill_studio_crud_and_plugin_install(client, fake_ai, clean_ai):
    skill = {
        'id': 'demo.skill',
        'prompt': 'Answer only from the supplied docs.',
        'context': ['project', 'docs'],
        'tools': ['project_facts', 'docs_search'],
        'suggested': ['hello'],
        'ask_policy': 'auto',
    }
    saved = client.post('/api/ai/skills', json=skill)
    assert saved.status_code == 200, saved.get_json()
    assert saved.get_json()['skill']['id'] == 'demo.skill'
    fetched = client.get('/api/ai/skills/demo.skill').get_json()
    assert fetched['skill']['prompt'].startswith('Answer only')
    forked = client.post('/api/ai/skills/demo.skill/fork', json={'id': 'demo.skill.copy'})
    assert forked.status_code == 200, forked.get_json()
    plugin = {
        'id': 'demo.pack',
        'name': 'Demo pack',
        'version': '1.0.0',
        'api': 1,
        'kind': 'skill-pack',
        'permissions': ['read:docs'],
        'skills': [{**skill, 'id': 'demo.pack.reader'}],
    }
    installed = client.post('/api/ai/plugins/install', json=plugin)
    assert installed.status_code == 200, installed.get_json()
    listed = client.get('/api/ai/plugins').get_json()
    assert any(row['id'] == 'demo.pack' for row in listed['plugins'])
    assert client.delete('/api/ai/plugins/demo.pack').status_code == 200
    client.delete('/api/ai/skills/demo.skill')
    client.delete('/api/ai/skills/demo.skill.copy')


def _tool_pack(tools_spec: list, plugin_id: str = 'demo.tools') -> dict:
    return {
        'id': plugin_id,
        'name': 'Demo tools',
        'version': '1.0.0',
        'api': 1,
        'kind': 'tool-pack',
        'permissions': ['net:http'],
        'tools': tools_spec,
    }


def _http_tool(name: str) -> dict:
    return {
        'name': name,
        'description': 'demo',
        'url': 'https://example.com/hook',
        'allowed_hosts': ['example.com'],
    }


def test_a_refused_tool_pack_never_replaces_the_builtin_it_collides_with(client, clean_ai):
    """The registry's duplicate check runs BEFORE the table ``tools.execute`` reads.

    Assigning into ``tools.TOOLS`` first meant a manifest the route then refused (400) had
    already installed its handler under that name for every later turn until restart.
    """
    from ai import tools
    from extensions import HOST

    before = tools.TOOLS['project_facts']
    refusal = client.post('/api/ai/plugins/install', json=_tool_pack([_http_tool('project_facts')]))
    assert refusal.status_code == 400, refusal.get_json()
    assert tools.TOOLS['project_facts'] is before
    assert HOST.get('tools', 'project_facts') is before


def test_a_pack_that_fails_on_a_later_entry_installs_nothing(client, clean_ai):
    """Two tools of three used to stay callable after the route answered 400."""
    from ai import tools
    from extensions import HOST

    pack = _tool_pack([_http_tool('demo_first_tool'), _http_tool('project_facts')], 'demo.partial')
    assert client.post('/api/ai/plugins/install', json=pack).status_code == 400
    assert 'demo_first_tool' not in tools.TOOLS
    assert HOST.get('tools', 'demo_first_tool') is None


def test_disabling_a_tool_pack_withdraws_it_and_enabling_brings_it_back(client, clean_ai):
    """A switch that only relabelled the row left the tool callable."""
    from ai import tools
    from extensions import HOST

    assert client.post('/api/ai/plugins/install', json=_tool_pack([_http_tool('demo_live_tool')])).status_code == 200
    try:
        assert 'demo_live_tool' in tools.TOOLS
        assert client.post('/api/ai/plugins/demo.tools/enable', json={'enabled': False}).status_code == 200
        assert 'demo_live_tool' not in tools.TOOLS
        assert HOST.get('tools', 'demo_live_tool') is None
        assert client.post('/api/ai/plugins/demo.tools/enable', json={'enabled': True}).status_code == 200
        assert 'demo_live_tool' in tools.TOOLS
    finally:
        client.delete('/api/ai/plugins/demo.tools')
    assert 'demo_live_tool' not in tools.TOOLS


def test_a_non_admin_may_not_install_a_process_wide_pack(client, clean_ai, monkeypatch):
    """A tool/provider/code pack writes tables every account reads; a skill pack is per account."""
    from runtime import account_context
    from runtime.account_context import Account

    monkeypatch.setattr('services.accounts.service.accounts_mode', lambda: True)
    with account_context.use(Account('u_aaaaaaaaaaaa', 'reader', 'user')):
        refused = client.post('/api/ai/plugins/install', json=_tool_pack([_http_tool('demo_nope_tool')], 'demo.nope'))
        assert refused.status_code == 403
        skill_pack = {
            'id': 'demo.ownskills',
            'name': 'Own skills',
            'version': '1.0.0',
            'api': 1,
            'kind': 'skill-pack',
            'permissions': [],
            'skills': [{'id': 'demo.ownskills.one', 'prompt': 'Answer briefly.'}],
        }
        assert client.post('/api/ai/plugins/install', json=skill_pack).status_code == 200
        assert client.delete('/api/ai/plugins/demo.ownskills').status_code == 200


def test_a_non_admin_may_not_enable_or_delete_a_process_wide_pack(client, clean_ai, monkeypatch):
    """Install wasn't the only door: enable re-registers and delete releases the same machine-wide
    contributions, so both need the admin check install already had."""
    from ai import tools
    from runtime import account_context
    from runtime.account_context import Account

    assert (
        client.post(
            '/api/ai/plugins/install', json=_tool_pack([_http_tool('demo_guard_tool')], 'demo.guard')
        ).status_code
        == 200
    )
    try:
        monkeypatch.setattr('services.accounts.service.accounts_mode', lambda: True)
        with account_context.use(Account('u_aaaaaaaaaaaa', 'reader', 'user')):
            assert client.post('/api/ai/plugins/demo.guard/enable', json={'enabled': False}).status_code == 403
            assert client.delete('/api/ai/plugins/demo.guard').status_code == 403
            assert 'demo_guard_tool' in tools.TOOLS, 'a refused write must leave the pack callable'
    finally:
        with account_context.use(None):
            client.delete('/api/ai/plugins/demo.guard')


def test_the_provider_key_travels_in_a_header_not_the_url(client, fake_ai):
    """A documented deployment puts a reverse proxy in front: its access log writes the request
    line, so a ``?key=sk-…`` URL would put the user's credential in the operator's log file."""
    from ai.providers import PROVIDERS

    provider = PROVIDERS['fake_ai']
    body = client.get('/api/ai/providers/fake_ai/models', headers={'X-Provider-Key': 'sk-header'}).get_json()
    assert body['ok'] is True and body['models'] == [{'id': 'fake-model', 'label': 'Fake'}]
    assert provider.seen_keys[-1] == 'sk-header'

    # The query string is no longer read: a stale client would get an unauthenticated list
    # (and, more importantly, the key would already be in the log).
    client.get('/api/ai/providers/fake_ai/models?key=sk-query')
    assert provider.seen_keys[-1] == ''


def test_a_pack_installed_by_one_account_is_not_anothers_to_use(client, clean_ai):
    """Installing is machine-level (admin-only), USING is per account.

    Without this, account B's agent was offered account A's HTTP tool and could call it — posting
    B's conversation arguments to a host only A had approved — and A's provider id resolved from
    B's settings request.
    """
    from ai import plugins, tools
    from ai.errors import AIError
    from runtime import account_context
    from runtime.account_context import Account

    alice = Account('u_' + 'a' * 12, 'alice')
    bob = Account('u_' + 'b' * 12, 'bob')
    pack = _tool_pack([_http_tool('demo_scoped_tool')], 'demo.scoped')
    try:
        with account_context.use(alice):
            plugins.install(pack)
            assert plugins.visible_tool('demo_scoped_tool') is True
            assert any(row['name'] == 'demo_scoped_tool' for row in tools.schemas())
        with account_context.use(bob):
            assert plugins.visible_tool('demo_scoped_tool') is False
            assert all(row['name'] != 'demo_scoped_tool' for row in tools.schemas()), 'offered to the wrong account'
            with pytest.raises(AIError) as refusal:
                tools.execute('demo_scoped_tool', {}, {})
            assert refusal.value.key == 'ai.toolRefused'
            assert refusal.value.params.get('reason') == 'not available for this account'
    finally:
        with account_context.use(alice):
            plugins.uninstall('demo.scoped')
    assert 'demo_scoped_tool' not in tools.TOOLS


def test_a_plugin_id_cannot_be_reused_by_another_account(client, clean_ai):
    """Contributions are released by the bare ``plugin:<id>`` owner, so a second account installing
    a different pack under the same id would have its uninstall clobber the first account's tools."""
    from ai import plugins
    from ai.errors import AIError
    from runtime import account_context
    from runtime.account_context import Account

    alice = Account('u_' + 'a' * 12, 'alice')
    bob = Account('u_' + 'b' * 12, 'bob')
    with account_context.use(alice):
        plugins.install(_tool_pack([_http_tool('demo_id_tool')], 'demo.sameid'))
    try:
        with account_context.use(bob):
            with pytest.raises(AIError) as refusal:
                plugins.install(_tool_pack([_http_tool('demo_other_tool')], 'demo.sameid'))
            assert refusal.value.key == 'ai.pluginConflict'
    finally:
        with account_context.use(alice):
            plugins.uninstall('demo.sameid')


def test_a_provider_pack_is_invisible_to_another_account(client, clean_ai):
    from ai import plugins
    from ai.errors import AIError
    from ai.providers.registry import get_provider
    from runtime import account_context
    from runtime.account_context import Account

    alice = Account('u_' + 'c' * 12, 'alice')
    bob = Account('u_' + 'd' * 12, 'bob')
    pack = {
        'id': 'demo.provider',
        'name': 'Demo provider',
        'version': '1.0.0',
        'api': 1,
        'kind': 'provider-pack',
        'permissions': ['provider:custom'],
        'providers': [
            {
                'id': 'demo_provider',
                'base_url': 'https://example.com/v1',
                'models': [{'id': 'demo-model'}],
            }
        ],
    }
    try:
        with account_context.use(alice):
            plugins.install(pack)
            assert get_provider('demo_provider').spec.id == 'demo_provider'
        with account_context.use(bob):
            with pytest.raises(AIError) as refusal:
                get_provider('demo_provider')
            assert refusal.value.key == 'ai.unknownProvider'
    finally:
        with account_context.use(alice):
            plugins.uninstall('demo.provider')


class LoopProvider(FakeProvider):
    """Calls the cheapest read tool forever, so the budget is the only thing that can stop it."""

    def __init__(self):
        super().__init__('fake_loop')
        self.calls = 0

    def stream(self, request):
        self.calls += 1
        yield {'type': 'tool_call', 'id': f'call_{self.calls}', 'name': 'project_facts', 'arguments': {}}
        yield {'type': 'done', 'stop_reason': 'tool_calls'}


def test_the_tool_budget_asks_the_user_instead_of_failing(client, monkeypatch, clean_ai):
    """A soft limit: the turn pauses on a question whose answer resumes it with a fresh budget."""
    from ai import agent
    from ai.providers import PROVIDERS

    monkeypatch.setitem(PROVIDERS, 'fake_loop', LoopProvider())
    real_get = agent.get_setting
    monkeypatch.setattr(
        agent, 'get_setting', lambda key, *a, **k: 1 if key == 'ai_max_tool_rounds' else real_get(key, *a, **k)
    )
    response = _chat(client, provider='fake_loop', model='fake-model', text='poke the project')
    data = response.get_json()
    assert data['ok'] is True
    events = data['events']
    question = next(event for event in events if event['type'] == 'question')
    assert question['questions'][0]['id'] == 'tool_budget'
    assert any(event['type'] == 'paused' and event.get('reason') == 'tool_budget' for event in events)
    conversation_id = events[0]['conversation_id']
    stored = client.get('/api/ai/conversations/' + conversation_id).get_json()
    assert any(block.get('type') == 'skill' for message in stored['messages'] for block in message.get('blocks') or [])


class ApplyProvider(FakeProvider):
    """Calls apply_workflow once, then answers."""

    def __init__(self):
        super().__init__('fake_apply')

    def stream(self, request):
        answered = any(message.get('role') == 'tool' for message in request.get('messages', []))
        if not answered:
            yield {
                'type': 'tool_call',
                'id': 'call_apply',
                'name': 'apply_workflow',
                'arguments': {
                    'name': 'AI 合法流程',
                    'workflow': {
                        'nodes': [
                            {'id': 'n1', 'type': 'upload', 'x': 0, 'y': 0, 'params': {'dataset_id': 'ds1'}},
                            {
                                'id': 'n2',
                                'type': 'output',
                                'x': 200,
                                'y': 0,
                                'params': {'operation': 'save', 'format': 'csv', 'filename': 'x.csv'},
                            },
                        ],
                        'connections': [{'from': 'n1', 'to': 'n2'}],
                    },
                },
            }
            yield {'type': 'done', 'stop_reason': 'tool_calls'}
            return
        yield {'type': 'text_delta', 'text': 'Loaded.'}
        yield {'type': 'done', 'stop_reason': 'end_turn'}


def test_apply_workflow_validates_saves_and_asks_the_page_to_load(client, monkeypatch, clean_ai):
    from ai.providers import PROVIDERS

    monkeypatch.setitem(PROVIDERS, 'fake_apply', ApplyProvider())
    response = _chat(client, provider='fake_apply', model='fake-model', text='build it')
    data = response.get_json()
    assert data['ok'] is True
    applied = [event for event in data['events'] if event['type'] == 'workflow_apply']
    assert len(applied) == 1
    assert applied[0]['name'] == 'AI 合法流程'
    assert applied[0]['workflow']['connections'] == [{'from': 'n1', 'to': 'n2'}]
    assert client.get('/api/workflow/list').get_json()['workflows']


class BadDraftProvider(FakeProvider):
    """Presents an illegal workflow draft, then answers once it has been told why."""

    def __init__(self):
        super().__init__('fake_bad_draft')

    def stream(self, request):
        told = any(message.get('role') == 'tool' for message in request.get('messages', []))
        if not told:
            yield {
                'type': 'tool_call',
                'id': 'call_draft',
                'name': 'present_artifact',
                'arguments': {
                    'title': 'Bad draft',
                    'kind': 'workflow',
                    'payload': {'nodes': [{'id': 'n1', 'type': '分析'}]},
                },
            }
            yield {'type': 'done', 'stop_reason': 'tool_calls'}
            return
        yield {'type': 'text_delta', 'text': 'The draft was refused; here is why.'}
        yield {'type': 'done', 'stop_reason': 'end_turn'}


def test_an_illegal_draft_goes_back_to_the_model_instead_of_ending_the_turn(client, monkeypatch, clean_ai):
    """A refusal must be the call's tool result, never an AIError.

    Raising ended the turn with the ``tool_use`` unpaired: the user saw “工作流草稿无法载入” and
    nothing repaired it, and the NEXT message died with the provider's 400 “unresolved tool
    call”. The model now gets the problems in the same turn and can fix its own draft.
    """
    from ai.providers import PROVIDERS

    monkeypatch.setitem(PROVIDERS, 'fake_bad_draft', BadDraftProvider())
    response = _chat(client, provider='fake_bad_draft', model='fake-model', text='build it')
    data = response.get_json()
    assert data['ok'] is True
    events = data['events']
    refused = [event for event in events if event['type'] == 'tool_result' and event['name'] == 'present_artifact']
    assert refused and refused[0]['ok'] is False


class ArtifactAndQuestionProvider(FakeProvider):
    """One round that asks a question AND presents an artifact — both must land."""

    def __init__(self):
        super().__init__('fake_mixed')

    def stream(self, request):
        yield {
            'type': 'tool_call',
            'id': 'call_mem',
            'name': 'present_artifact',
            'arguments': {'title': '记住这条', 'kind': 'memory', 'payload': {'text': '这个项目用默认账号'}},
        }
        yield {
            'type': 'tool_call',
            'id': 'call_q',
            'name': 'ask_user_question',
            'arguments': {
                'questions': [{'id': 'scope', 'question': 'Which data?', 'options': [{'label': 'Dataset A'}]}]
            },
        }
        yield {'type': 'done', 'stop_reason': 'tool_calls'}


def test_a_round_with_a_question_still_answers_its_other_calls(client, monkeypatch, clean_ai):
    """Returning at the question first left the sibling tool_use unpaired and its artifact unseen."""
    from ai.providers import PROVIDERS

    monkeypatch.setitem(PROVIDERS, 'fake_mixed', ArtifactAndQuestionProvider())
    response = _chat(client, provider='fake_mixed', text='do both')
    events = response.get_json()['events']
    types = [event['type'] for event in events]
    assert 'artifact' in types, types
    assert 'question' in types, types
    assert types[-1] == 'paused'
    artifact_index = types.index('artifact')
    question_index = types.index('question')
    assert artifact_index < question_index, 'the artifact must be produced before the turn pauses'


def test_a_tool_call_left_without_a_result_is_repaired_before_replay():
    """One crashed turn must not poison the conversation.

    Every provider refuses a later turn whose history holds a ``tool_use`` with no result
    (DeepSeek: “unresolved tool call”). The repair answers it synthetically and drops tool rows
    whose call is gone with a skipped assistant row.
    """
    from ai.agent import _repair_tool_pairs

    messages = [
        {'role': 'user', 'content': 'go', 'blocks': [], 'meta': {}},
        {
            'role': 'assistant',
            'content': '',
            'blocks': [
                {'type': 'tool_use', 'id': 'call_a', 'name': 'workspace_list', 'input': {}},
                {'type': 'tool_use', 'id': 'call_b', 'name': 'run_cmd', 'input': {}},
            ],
            'meta': {},
        },
        {'role': 'tool', 'content': '{}', 'tool_call_id': 'call_a', 'is_error': False, 'meta': {}},
        {'role': 'tool', 'content': '{}', 'tool_call_id': 'call_ghost', 'is_error': False, 'meta': {}},
    ]
    repaired = _repair_tool_pairs(messages)
    ids = [message.get('tool_call_id') for message in repaired if message['role'] == 'tool']
    assert sorted(ids) == ['call_a', 'call_b'], 'the unanswered call gets a result, the orphan is dropped'
    synthetic = next(message for message in repaired if message.get('tool_call_id') == 'call_b')
    assert synthetic['is_error'] is True
    assert synthetic['role'] == 'tool'


class RepeatingDraftProvider(FakeProvider):
    """Sends the same illegal draft twice in one turn, then answers."""

    def __init__(self):
        super().__init__('fake_repeat_draft')

    def stream(self, request):
        seen = sum(1 for message in request.get('messages', []) if message.get('role') == 'tool')
        if seen < 2:
            yield {
                'type': 'tool_call',
                'id': f'call_draft_{seen}',
                'name': 'present_artifact',
                'arguments': {
                    'title': 'Bad draft',
                    'kind': 'workflow',
                    'payload': {'nodes': [{'id': 'n1', 'type': '分析'}]},
                },
            }
            yield {'type': 'done', 'stop_reason': 'tool_calls'}
            return
        yield {'type': 'text_delta', 'text': 'I cannot build that without a dataset.'}
        yield {'type': 'done', 'stop_reason': 'end_turn'}


def test_the_same_refused_draft_twice_is_told_to_stop_resending(client, monkeypatch, clean_ai):
    """A small model looped five identical submissions in one live turn.

    The second refusal of the SAME draft (same problems) carries no new information, so it now says
    so: change it, or ask the user for the missing data.
    """
    from ai.providers import PROVIDERS

    monkeypatch.setitem(PROVIDERS, 'fake_repeat_draft', RepeatingDraftProvider())
    data = _chat(client, provider='fake_repeat_draft', model='fake-model', text='build it').get_json()
    refused = [event for event in data['events'] if event['type'] == 'tool_result']
    assert len(refused) == 2, refused
    assert refused[0]['ok'] is False and '分析' in refused[0]['error']
    assert 'Do not send it again' in refused[1]['error'], refused[1]['error']


def test_retry_reruns_the_last_turn_without_a_second_user_message(client, fake_ai, clean_ai):
    response = _chat(client, text='try this again')
    conversation_id = response.get_json()['events'][0]['conversation_id']
    retried = client.post('/api/ai/retry?stream=0', json={'conversation_id': conversation_id, 'api_key': 'secret-key'})
    assert retried.status_code == 200, retried.get_json()
    types = [event['type'] for event in retried.get_json()['events']]
    assert 'text' in types and 'done' in types
    detail = client.get('/api/ai/conversations/' + conversation_id).get_json()
    assert sum(1 for message in detail['messages'] if message['role'] == 'user') == 1


class ManyQuestionsProvider(FakeProvider):
    """Asks one question too many, or two questions with the same id."""

    def __init__(self, provider_id: str, questions: list):
        super().__init__(provider_id)
        self._questions = questions

    def stream(self, request):
        yield {
            'type': 'tool_call',
            'id': 'call_q',
            'name': 'ask_user_question',
            'arguments': {'questions': self._questions},
        }
        yield {'type': 'done', 'stop_reason': 'tool_calls'}


def _turn_errors(data: dict) -> list[str]:
    """The reason a turn refused, whether the API answered as an event stream or as one refusal."""
    if isinstance(data.get('events'), list):
        return [str(event.get('error') or '') for event in data['events'] if event.get('type') == 'error']
    return [str(data.get('error') or '')]


def test_a_question_card_over_the_limit_is_refused_by_name(client, monkeypatch, clean_ai):
    """The old code kept the first five SILENTLY, so a sixth question (and its answer) never existed.

    The limit is now 10; an eleventh is still refused by name rather than dropped.
    """
    from ai.providers import PROVIDERS

    questions = [{'id': f'q{i}', 'question': f'question {i}', 'options': [{'label': 'yes'}]} for i in range(11)]
    monkeypatch.setitem(PROVIDERS, 'fake_many_q', ManyQuestionsProvider('fake_many_q', questions))
    data = _chat(client, provider='fake_many_q', model='fake-model', text='ask me').get_json()
    errors = _turn_errors(data)
    assert errors, data
    assert '10' in errors[0], errors[0]


def test_two_questions_with_one_id_are_refused(client, monkeypatch, clean_ai):
    from ai.providers import PROVIDERS

    questions = [
        {'id': 'same', 'question': 'first', 'options': [{'label': 'a'}]},
        {'id': 'same', 'question': 'second', 'options': [{'label': 'b'}]},
    ]
    monkeypatch.setitem(PROVIDERS, 'fake_dup_q', ManyQuestionsProvider('fake_dup_q', questions))
    data = _chat(client, provider='fake_dup_q', model='fake-model', text='ask me').get_json()
    errors = _turn_errors(data)
    assert errors and 'same' in errors[0], data


def test_a_question_with_no_text_is_refused(client, monkeypatch, clean_ai):
    from ai.providers import PROVIDERS

    questions = [{'id': 'blank', 'question': '   ', 'options': [{'label': 'a'}]}]
    monkeypatch.setitem(PROVIDERS, 'fake_blank_q', ManyQuestionsProvider('fake_blank_q', questions))
    data = _chat(client, provider='fake_blank_q', model='fake-model', text='ask me').get_json()
    errors = _turn_errors(data)
    assert errors and '1' in errors[0], data


def test_a_resumed_turn_does_not_seed_a_second_skill_row(client, fake_ai, clean_ai):
    """Answering a question resumes the turn through `_loop`, which restarted `rounds` at zero and
    seeded another “skill” row into the SAME turn — the transcript showed the skill twice."""
    response = _chat(client, provider='fake_ask', model='fake-model', text='which?')
    events = response.get_json()['events']
    meta = next(event for event in events if event['type'] == 'meta')
    question = next(event for event in events if event['type'] == 'question')
    answer = {
        'conversation_id': meta['conversation_id'],
        'message_id': question['message_id'],
        'question_id': question['question_id'],
        'answers': [{'id': 'scope', 'selected': ['Dataset A']}],
        'api_key': 'secret-key',
    }
    assert client.post('/api/ai/answer?stream=0', json=answer).status_code == 200
    stored = client.get('/api/ai/conversations/' + meta['conversation_id']).get_json()
    skills = [
        block
        for message in stored['messages']
        if message['role'] == 'assistant'
        for block in message.get('blocks') or []
        if block.get('type') == 'skill'
    ]
    assert len(skills) == 1, skills
