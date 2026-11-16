"""Files API and standalone Search / Fetch, with a scripted HTTP tier. No network."""

import io
import json

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
