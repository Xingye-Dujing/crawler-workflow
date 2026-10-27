"""Shared plumbing for the device-tier tests (real Chrome, real Ollama).

Everything in this directory additionally opts into network via pytest-socket's
``enable_socket`` marker (set per-file), because the root pytest.ini runs the
fast suite with sockets disabled.

One thing this file owns that is worth reading before trusting a green run: the
*skip-or-fail* policy below. Skipping an unavailable device is right by default and
dangerous in exactly one situation — the run that MEANT to exercise this tier.
"""

import contextlib
from pathlib import Path

import pytest
from device_policy import REQUIRE_BROWSER_ENV, REQUIRE_OLLAMA_ENV, unavailable
from device_policy import flag_set as _flag

FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures'

#: The skip-or-fail policy lives in ``tests/device_policy.py`` so a device case can import it too —
#: ``import conftest`` would bind to whichever of this repo's four conftest files loaded first, which
#: is how a "shared" rule ends up private. The names above are this file's own uses of that one policy.


#: Did THIS session select a case that needs a device? See :func:`pytest_collection_modifyitems`.
#: A dict rather than a global because the tests tier has no business re-binding module state
#: to answer one question about collection.
_selection = {'device_requested': False}


def pytest_collection_modifyitems(items):
    """Notice whether the selected run contains a device case at all.

    Without this, the probe below fires for *any* file in this directory once
    ``CRAWLER_REQUIRE_BROWSER`` is set — including the several here that are marked ``unit`` and drive
    a fake driver in under a second (``test_weibo_crawler.py``: 66 cases, 0.93 s). Measured: such a
    run answered ``Chrome/chromedriver cannot start: SocketBlockedError`` — a false claim that the
    device tier is broken, raised by a session that never asked for a device. And AGENTS tells the
    reader to override the marker filter to run one device case, so the documented way in was the way
    that broke.
    """
    _selection['device_requested'] = any(
        item.get_closest_marker('integration') or item.get_closest_marker('live_ollama') for item in items
    )


@pytest.fixture(scope='session', autouse=True)
def the_device_the_tier_asked_for_really_starts():
    """Prove the browser can start, once, when the operator asked for that guarantee.

    Autouse and session-scoped so it runs before the first device case and only when a flag
    is set: without one, the per-file skips behave exactly as they did and a developer
    without Chrome is not slowed down by a probe they did not ask for. It also stays quiet
    when the selected items contain no device case, which is what
    :func:`pytest_collection_modifyitems` exists to notice.

    The probe has to START a driver rather than check that a binary exists — the failure
    this exists for is a chromedriver that launches and then crashes, which a path check
    reports as present.

    There is no early ``return`` on the quiet path on purpose: this is a generator fixture,
    and returning before the first ``yield`` is not "do nothing", it is a ``StopIteration``
    that pytest reports as "did not yield a value" — which turned every case in the tier
    into an ERROR while the flag was off. Measured, not guessed.
    """
    if _selection['device_requested'] and _flag(REQUIRE_BROWSER_ENV):
        from crawlers.platforms.wechat.crawler import WechatCrawler

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
    from core.config import Config

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
    from core.config import Config

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
