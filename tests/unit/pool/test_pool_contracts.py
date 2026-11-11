"""The pool's contracts with the rest of the app: the sentinel, the fingerprint, the gate.

Three seams where a small mistake costs paid-for data or a silent refusal:

* the account selector has to OFFER the sentinel without losing the concrete logins;
* the node fingerprint has to keep "pool mode" distinct from a fixed login (a different
  session and device is a different crawl) while folding a blank/default login as before;
* validation has to answer the pool's question, not look for a cookie file named ``@pool``.
"""

import ast
from pathlib import Path

import pytest
from runtime import paths
from sessions.cookies import CookieManager

from services.pool import store

pytestmark = pytest.mark.unit

BACKEND = Path(__file__).resolve().parents[3] / 'backend'


class _Scope:
    def __init__(self, cookie_dir):
        self.cookie_dir = cookie_dir


@pytest.fixture(autouse=True)
def scope(tmp_path, monkeypatch):
    cookie_dir = tmp_path / 'cookies'
    cookie_dir.mkdir()
    monkeypatch.setattr(paths, 'active', lambda: _Scope(str(cookie_dir)))
    monkeypatch.setattr(store, 'db_path', lambda: str(tmp_path / 'pool.db'))
    yield CookieManager(str(cookie_dir))


def test_the_account_selector_offers_the_pool_without_hiding_logins(scope, monkeypatch, client):
    import api.capabilities as endpoint

    scope.save('weibo', [{'name': 'SUB', 'value': 'v', 'domain': '.weibo.com'}], 'work')
    monkeypatch.setattr(endpoint, 'pool_enabled', lambda: True)
    payload = client.get('/api/capabilities').get_json()
    weibo = [p for p in payload['platforms'] if p['platform'] == 'weibo'][0]
    fields = [f for mode in weibo['modes'] for f in mode['fields'] if f['key'] == 'account']
    assert fields, 'weibo has no account field to check'
    for field in fields:
        values = [option['value'] for option in field['options']]
        assert values[0] == '@pool', values
        assert 'work' in values, values
        # A node added now still starts on a real login: opting into rotation is a choice,
        # never a default the user did not make.
        assert field['default'] == 'work', field['default']


def test_with_the_feature_off_the_selector_is_unchanged(scope, monkeypatch, client):
    import api.capabilities as endpoint

    monkeypatch.setattr(endpoint, 'pool_enabled', lambda: False)
    payload = client.get('/api/capabilities').get_json()
    weibo = [p for p in payload['platforms'] if p['platform'] == 'weibo'][0]
    for mode in weibo['modes']:
        for field in mode['fields']:
            if field['key'] == 'account':
                assert all(option['value'] != '@pool' for option in field['options'])


def test_the_fingerprint_keeps_pool_mode_distinct_and_still_folds_blank(scope):
    from services.runs.store.identity import stable_params

    assert stable_params({'account': '@pool', 'keyword': 'x'})['account'] == '@pool'
    assert 'account' not in stable_params({'account': 'default', 'keyword': 'x'})
    assert 'account' not in stable_params({'account': '', 'keyword': 'x'})


def test_validation_asks_the_pool_not_for_a_file_named_pool(scope):
    from engine.workflow import _account_session_errors

    empty = _account_session_errors(['weibo'], {'account': '@pool'}, '源 #1')
    assert len(empty) == 1 and '源 #1' in empty[0]

    scope.save('weibo', [{'name': 'SUB', 'value': 'v', 'domain': '.weibo.com'}], 'work')
    assert _account_session_errors(['weibo'], {'account': '@pool'}, '源 #1') == []


def test_the_pool_package_does_not_import_crawlers():
    """``nodes → pool → sessions`` is the direction; a reverse import would make the module
    unusable from the validator without dragging Selenium into it."""
    for path in (BACKEND / 'services' / 'pool').glob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or '']
            else:
                continue
            for name in names:
                assert not name.startswith('crawlers'), f'{path.name} imports {name}'


def test_the_browser_takes_the_exit_arguments(scope):
    from crawlers.core import browser

    options = browser.build_options(True, None, False, proxy_args=['--proxy-server=http://10.0.0.1:8080'])
    assert '--proxy-server=http://10.0.0.1:8080' in options.arguments
