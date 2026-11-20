"""HTTP plugin tools validate every redirect hop, not just the URL in the manifest."""

import types

import pytest

pytestmark = pytest.mark.unit


def _isolated(monkeypatch):
    """Register a tool against throwaway tables so the pack leaves no process-wide contribution."""
    from ai import plugins

    monkeypatch.setattr(plugins, 'tools', types.SimpleNamespace(TOOLS={}))
    monkeypatch.setattr(plugins, 'HOST', types.SimpleNamespace(get=lambda *args: None, register=lambda *args: None))
    monkeypatch.setattr(plugins, 'scopes', types.SimpleNamespace(claim=lambda *args: None))
    return plugins


def _tool(plugins):
    return plugins._http_tool(
        {
            'name': 'redirect_probe',
            'description': 'probe',
            'url': 'https://allowed.example.com/start',
            'allowed_hosts': ['allowed.example.com'],
            'method': 'GET',
        },
        'test.redirect',
    )


class _Response:
    def __init__(self, status_code=200, location=None, text='ok'):
        self.status_code = status_code
        self.headers = {'Location': location} if location else {}
        self.text = text


def test_a_redirect_to_a_disallowed_host_is_refused_and_never_fetched(monkeypatch):
    from ai.errors import AIError

    plugins = _isolated(monkeypatch)
    handler = _tool(plugins).handler
    fetched = []

    def fake_get(url, **kwargs):
        fetched.append(url)
        assert kwargs.get('allow_redirects') is False, 'requests must not follow the hop for us'
        if len(fetched) == 1:
            return _Response(302, 'http://127.0.0.1:8080/secret')
        raise AssertionError('the disallowed redirect target was fetched: ' + url)

    monkeypatch.setattr(plugins.requests, 'get', fake_get)
    with pytest.raises(AIError) as refusal:
        handler({}, {})
    assert refusal.value.key == 'ai.toolRefused'
    # The first (allowed) URL was requested; the internal Location never was.
    assert fetched == ['https://allowed.example.com/start'], fetched


def test_a_relative_redirect_to_an_allowed_host_is_followed(monkeypatch):
    plugins = _isolated(monkeypatch)
    handler = _tool(plugins).handler
    fetched = []

    def fake_get(url, **kwargs):
        fetched.append(url)
        assert kwargs.get('allow_redirects') is False
        if len(fetched) == 1:
            return _Response(302, '/final')
        return _Response(200, text='done')

    monkeypatch.setattr(plugins.requests, 'get', fake_get)
    result = handler({}, {})
    assert fetched == ['https://allowed.example.com/start', 'https://allowed.example.com/final'], fetched
    assert result == {'status': 200, 'body': 'done', 'truncated': False}


def test_a_redirect_loop_is_capped(monkeypatch):
    from ai.errors import AIError

    plugins = _isolated(monkeypatch)
    handler = _tool(plugins).handler
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return _Response(302, '/loop')

    monkeypatch.setattr(plugins.requests, 'get', fake_get)
    with pytest.raises(AIError) as refusal:
        handler({}, {})
    assert refusal.value.key == 'ai.toolRefused'
    assert len(calls) == plugins._MAX_REDIRECTS + 1, calls
