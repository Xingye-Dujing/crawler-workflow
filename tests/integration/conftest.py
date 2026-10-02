"""Shared plumbing for the device-tier tests (real Chrome, real Ollama).

Everything in this directory additionally opts into network via pytest-socket's
``enable_socket`` marker (set per-file), because the root pytest.ini runs the
fast suite with sockets disabled.

One thing this file owns that is worth reading before trusting a green run: the
*skip-or-fail* policy below. Skipping an unavailable device is right by default and
dangerous in exactly one situation — the run that MEANT to exercise this tier.
"""

import contextlib
import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures'

#: Set this to make an unavailable BROWSER fail this tier instead of skipping it.
#:
#: Skipping is the right default — a laptop without Chrome should still run everything else.
#: But it is also the most dangerous shape in this suite, because `-m integration` against a
#: machine whose chromedriver cannot start prints "99 skipped" and the run still reads green.
#: The closure rule ("nothing deselected and nothing skipped") then cannot be checked by
#: eye: the same number also means "this tier never ran". Measured — the whole UI-layout
#: file skipped on this machine, and only a hand-run with wider access showed all 99
#: passing. So a run that MEANS to exercise the tier sets this, and the session probe far
#: below fails before any test can pass for the wrong reason.
REQUIRE_BROWSER_ENV = 'CRAWLER_REQUIRE_BROWSER'
#: The same switch for the daemon: :func:`ollama_host` skips when nothing answers the port.
REQUIRE_OLLAMA_ENV = 'CRAWLER_REQUIRE_OLLAMA'


def _flag(name: str) -> bool:
    """``as_bool`` for the environment: blank is off, and so is every spelling of no."""
    return str(os.environ.get(name) or '').strip().lower() in {'1', 'true', 'yes', 'on'}


def unavailable(reason: str, flag: str) -> None:
    """Skip a device precondition, or FAIL when the tier was explicitly requested."""
    if _flag(flag):
        pytest.fail(f'{reason} — {flag} is set, so an unavailable device is an error, never a silent skip')
    pytest.skip(reason)


@pytest.fixture(scope='session', autouse=True)
def the_device_the_tier_asked_for_really_starts():
    """Prove the browser can start, once, when the operator asked for that guarantee.

    Autouse and session-scoped so it runs before the first device case and only when a flag
    is set: without one, the per-file skips behave exactly as they did and a developer
    without Chrome is not slowed down by a probe they did not ask for.

    The probe has to START a driver rather than check that a binary exists — the failure
    this exists for is a chromedriver that launches and then crashes, which a path check
    reports as present.

    There is no early ``return`` on the quiet path on purpose: this is a generator fixture,
    and returning before the first ``yield`` is not "do nothing", it is a ``StopIteration``
    that pytest reports as "did not yield a value" — which turned every case in the tier
    into an ERROR while the flag was off. Measured, not guessed.
    """
    if _flag(REQUIRE_BROWSER_ENV):
        from crawlers.wechat import WechatCrawler

        try:
            crawler = WechatCrawler(headless=True)
        except Exception as e:
            pytest.fail(f'{REQUIRE_BROWSER_ENV} is set, but Chrome/chromedriver cannot start: {type(e).__name__}: {e}')
        with contextlib.suppress(Exception):
            crawler.close()
    yield


@pytest.fixture(scope='session')
def wechat_article_url() -> str:
    """file:// URL of a minimal WeChat-article DOM shaped exactly like the
    real pages WechatCrawler scrapes (#activity-name, .rich_media_content…)."""
    return (FIXTURES / 'html' / 'wechat_article.html').as_uri()


@pytest.fixture(scope='session')
def ollama_host() -> str:
    """First reachable Ollama daemon address, or skip the whole live test.

    Probed over /api/tags rather than trusting the settings default: a laptop
    with the daemon stopped should skip, not fail — unless the run asked for the daemon
    by setting ``CRAWLER_REQUIRE_OLLAMA``, which is the same switch the browser has.
    """
    import requests

    from config import Config

    host = (Config.OLLAMA_HOST or 'http://localhost:11434').rstrip('/')
    try:
        resp = requests.get(host + '/api/tags', timeout=5)
        resp.raise_for_status()
    except Exception as e:  # any failure means "not reachable" — skip, don't fail
        unavailable(f'Ollama daemon not reachable at {host}: {e}', REQUIRE_OLLAMA_ENV)
    if not (resp.json().get('models') or []):
        unavailable(f'Ollama at {host} has no pulled models', REQUIRE_OLLAMA_ENV)
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
    unavailable('the daemon has no chat-capable model pulled', REQUIRE_OLLAMA_ENV)
    return ''  # unreachable; keeps the annotation honest
