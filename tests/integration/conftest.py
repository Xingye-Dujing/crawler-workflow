"""Shared plumbing for the device-tier tests (real Chrome, real Ollama).

Everything in this directory additionally opts into network via pytest-socket's
``enable_socket`` marker (set per-file), because the root pytest.ini runs the
fast suite with sockets disabled.
"""
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures'


@pytest.fixture(scope='session')
def wechat_article_url() -> str:
    """file:// URL of a minimal WeChat-article DOM shaped exactly like the
    real pages WechatCrawler scrapes (#activity-name, .rich_media_content…)."""
    return (FIXTURES / 'html' / 'wechat_article.html').as_uri()


@pytest.fixture(scope='session')
def ollama_host() -> str:
    """First reachable Ollama daemon address, or skip the whole live test.

    Probed over /api/tags rather than trusting the settings default: a laptop
    with the daemon stopped should skip, not fail.
    """
    import requests

    from config import Config

    host = (Config.OLLAMA_HOST or 'http://localhost:11434').rstrip('/')
    try:
        resp = requests.get(host + '/api/tags', timeout=5)
        resp.raise_for_status()
    except Exception as e:  # any failure means "not reachable" — skip, don't fail
        pytest.skip(f'Ollama daemon not reachable at {host}: {e}')
    if not (resp.json().get('models') or []):
        pytest.skip(f'Ollama at {host} has no pulled models')
    return host


@pytest.fixture(scope='session')
def ollama_chat_model(ollama_host) -> str:
    """A pulled, chat-capable model tag (embedding models cannot chat)."""
    import requests

    from config import Config

    models = requests.get(ollama_host + '/api/tags', timeout=5).json().get('models', [])
    tags = [
        str(m.get('name') or m.get('model'))
        for m in models
        if 'embed' not in str(m.get('name') or m.get('model') or '').lower()
    ]
    configured = Config.OLLAMA_MODEL
    if configured in tags:
        return configured
    if tags:
        return tags[0]
    pytest.skip('no chat-capable model pulled')
    return ''  # unreachable; keeps the annotation honest
