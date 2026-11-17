"""Files API and standalone Search / Fetch, with a scripted HTTP tier. No network."""

import hashlib
import io
import json
import os

import pytest

pytestmark = pytest.mark.api


class FakeResponse:
    def __init__(self, status: int, payload: dict):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload


@pytest.fixture
def ai_conversation(client):
    response = client.post(
        '/api/ai/conversations', json={'provider': 'deepseek', 'model': 'deepseek-flash', 'skill': 'project'}
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()['conversation']['id']


def test_files_upload_uses_purpose_before_file_and_returns_public_metadata(client, ai_conversation, monkeypatch):
    from ai import files

    seen = {}

    def fake_post(url, **kwargs):
        seen['url'] = url
        seen['files'] = kwargs['files']
        return FakeResponse(200, {'id': 'file-api-1', 'filename': 'note.txt', 'bytes': 5, 'purpose': 'user_data'})

    monkeypatch.setattr(files.requests, 'post', fake_post)
    response = client.post(
        '/api/ai/files',
        data={
            'file': (io.BytesIO(b'hello'), 'note.txt'),
            'conversation_id': ai_conversation,
            'provider': 'deepseek',
            'api_key': 'secret',
        },
        content_type='multipart/form-data',
    )
    assert response.status_code == 200, response.get_json()
    attachment = response.get_json()['attachment']
    assert attachment['file_id'] == 'file-api-1'
    assert 'path' not in attachment and 'sha256' not in attachment
    assert seen['url'].endswith('/files')
    assert seen['files'][0][0] == 'purpose'
    assert seen['files'][1][0] == 'file'
    listed = client.get('/api/ai/conversations/' + ai_conversation + '/files').get_json()
    assert listed['attachments'][0]['id'] == attachment['id']
    client.delete('/api/ai/conversations/' + ai_conversation)


def test_a_failed_upload_leaves_no_local_copy(client, ai_conversation, monkeypatch):
    from ai import files
    from runtime import paths

    monkeypatch.setattr(
        files.requests,
        'post',
        lambda *args, **kwargs: FakeResponse(401, {'error': 'bad key'}),
    )
    body = b'this upload must not be stored'
    response = client.post(
        '/api/ai/files',
        data={'file': (io.BytesIO(body), 'nope.txt'), 'conversation_id': ai_conversation, 'api_key': 'bad'},
        content_type='multipart/form-data',
    )
    assert response.status_code == 400
    assert response.get_json()['key'] == 'ai.unauthorized'
    digest = hashlib.sha256(body).hexdigest()[:20]
    directory = paths.active().ai_files_dir
    stored = os.listdir(directory) if os.path.isdir(directory) else []
    assert not [name for name in stored if name.startswith(digest)], 'a rejected upload left its local copy behind'


def test_delete_file_calls_the_provider_and_removes_the_row(client, ai_conversation, monkeypatch):
    from ai import files

    monkeypatch.setattr(
        files.requests,
        'post',
        lambda url, **kwargs: FakeResponse(200, {'id': 'file-api-2', 'filename': 'a.md', 'bytes': 1}),
    )
    upload = client.post(
        '/api/ai/files',
        data={'file': (io.BytesIO(b'x'), 'a.md'), 'conversation_id': ai_conversation, 'api_key': 'k'},
        content_type='multipart/form-data',
    ).get_json()['attachment']
    called = []
    monkeypatch.setattr(
        files.requests, 'delete', lambda url, **kwargs: called.append(url) or FakeResponse(200, {'deleted': True})
    )
    response = client.delete('/api/ai/files/' + upload['id'], json={'api_key': 'k'})
    assert response.status_code == 200, response.get_json()
    assert called and called[0].endswith('/files/file-api-2')
    assert client.get('/api/ai/conversations/' + ai_conversation + '/files').get_json()['attachments'] == []
    client.delete('/api/ai/conversations/' + ai_conversation)


def test_standalone_search_and_fetch(client, monkeypatch):
    from ai import files

    def fake_post(url, **kwargs):
        if url.endswith('/v1/tools/search'):
            assert kwargs['json']['query'] == 'DeepSeek'
            return FakeResponse(200, {'results': [{'title': 'one', 'url': 'https://example.com', 'snippet': 's'}]})
        if url.endswith('/v1/tools/fetch'):
            assert kwargs['json']['url'] == 'https://example.com/a'
            return FakeResponse(200, {'title': 'Page', 'content': '# body'})
        raise AssertionError(url)

    monkeypatch.setattr(files.requests, 'post', fake_post)
    search = client.post('/api/ai/search', json={'api_key': 'k', 'query': 'DeepSeek', 'count': 1})
    assert search.status_code == 200 and search.get_json()['results'][0]['title'] == 'one'
    fetch = client.post('/api/ai/fetch', json={'api_key': 'k', 'url': 'https://example.com/a'})
    assert fetch.status_code == 200 and fetch.get_json()['content'] == '# body'


def test_fetch_refuses_credentials_in_the_url_without_an_http_call(client, monkeypatch):
    from ai import files

    called = []
    monkeypatch.setattr(files.requests, 'post', lambda *args, **kwargs: called.append(args))
    response = client.post('/api/ai/fetch', json={'api_key': 'k', 'url': 'https://user:pass@example.com/a'})
    assert response.status_code == 400
    assert response.get_json()['key'] == 'ai.fetchUrl'
    assert called == []


# ─── token budget: a big table is a dataset, not a prompt ───────────────


def _upload_csv(client, conversation_id, name, data, key='secret'):
    return client.post(
        '/api/ai/files',
        data={
            'file': (io.BytesIO(data), name),
            'conversation_id': conversation_id,
            'provider': 'deepseek',
            'api_key': key,
        },
        content_type='multipart/form-data',
    )


def test_a_big_table_is_imported_as_a_dataset_instead_of_being_sent_to_the_model(client, ai_conversation, monkeypatch):
    """The whole point of the token budget: a few thousand rows are read in SLICES by the
    dataset tools, never billed in full on every turn that names the file."""
    from ai import files

    uploads = []
    monkeypatch.setattr(files.requests, 'post', lambda url, **kwargs: uploads.append(url))

    rows = '\n'.join(f'{index},name-{index}' for index in range(4000))
    response = _upload_csv(client, ai_conversation, 'big.csv', ('a,b\n' + rows + '\n').encode())
    body = response.get_json()
    assert response.status_code == 200, body
    assert body.get('dataset'), body
    assert body['dataset']['rows'] == 4000
    assert body['dataset']['columns'] == ['a', 'b']
    assert uploads == [], 'the table was still uploaded to the provider'
    listed = client.get('/api/data/datasets').get_json()['datasets']
    assert any(row['dataset_id'] == body['dataset']['dataset_id'] for row in listed)


def test_a_small_table_still_travels_as_a_file(client, ai_conversation, monkeypatch):
    from ai import files

    def fake_post(url, **kwargs):
        return FakeResponse(200, {'id': 'file-api-small', 'filename': 'small.csv', 'bytes': 30, 'purpose': 'user_data'})

    monkeypatch.setattr(files.requests, 'post', fake_post)
    response = _upload_csv(client, ai_conversation, 'small.csv', b'a,b\n1,2\n3,4\n')
    body = response.get_json()
    assert body.get('attachment'), body
    assert body['attachment']['file_id'] == 'file-api-small'


def test_an_oversized_attachment_is_refused_by_name(client, ai_conversation, monkeypatch):
    from ai import files

    monkeypatch.setattr(files, 'ATTACH_MAX_BYTES', 8)
    response = _upload_csv(client, ai_conversation, 'report.pdf', b'x' * 64)
    body = response.get_json()
    assert response.status_code == 400
    assert 'report.pdf' in body['error']


def test_the_same_bytes_in_a_second_conversation_reuse_the_provider_upload(client, monkeypatch):
    """Uploading one file in two conversations used to send and parse it twice (and bill twice)."""
    from ai import files

    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        return FakeResponse(200, {'id': 'file-api-1', 'filename': 'note.txt', 'bytes': 5, 'purpose': 'user_data'})

    monkeypatch.setattr(files.requests, 'post', fake_post)
    first = client.post(
        '/api/ai/conversations', json={'provider': 'deepseek', 'model': 'deepseek-flash', 'skill': 'project'}
    ).get_json()['conversation']['id']
    second = client.post(
        '/api/ai/conversations', json={'provider': 'deepseek', 'model': 'deepseek-flash', 'skill': 'project'}
    ).get_json()['conversation']['id']

    one = _upload_csv(client, first, 'note.txt', b'hello')
    two = _upload_csv(client, second, 'note.txt', b'hello')
    assert one.status_code == 200 and two.status_code == 200
    assert len(calls) == 1, 'the same bytes were uploaded twice'
    assert one.get_json()['attachment']['file_id'] == two.get_json()['attachment']['file_id']


def test_previous_uploads_and_this_accounts_objects_are_offerable(client, ai_conversation):
    response = client.get('/api/ai/references')
    body = response.get_json()
    assert body['ok'] is True
    kinds = {row['kind'] for row in body['references']}
    assert kinds <= {'dataset', 'export', 'workflow', 'file'}
    filtered = client.get('/api/ai/references', query_string={'q': 'zzz-nothing-matches'}).get_json()
    assert filtered['references'] == []
