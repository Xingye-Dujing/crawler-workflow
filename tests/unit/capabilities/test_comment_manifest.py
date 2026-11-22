"""The comment node's declaration: links are required, and every link's platform needs a login.

The session half is monkeypatched rather than measured: the question is whether the validator
asks ``sessions.preflight`` for every platform a link names, not whether this machine holds a
cookie. A real probe belongs to the device tier.
"""

from pathlib import Path

import pytest
from capabilities_kernel import registry
from nodes.catalog import PLUGINS
from nodes.defaults import NODE_DEFAULTS
from nodes.executors import comment as executor
from sessions import preflight

from engine.workflow import WorkflowEngine

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
ZHIHU = 'https://www.zhihu.com/question/1/answer/2'
WEIBO = 'https://weibo.com/1/abcdef'


def _manifest():
    manifest = registry.manifest_for_node('comment')
    assert manifest is not None
    return manifest


def _codes(params, monkeypatch=None, has_session=True, pool=('total', 'usable')):
    if monkeypatch is not None:
        monkeypatch.setattr(preflight, 'has_session_to_test', lambda *_args, **_kwargs: has_session)

        def _snapshot(_platform):
            return {'total': 1 if pool[0] == 'total' else 0, 'usable': pool[1] == 'usable'}

        monkeypatch.setattr(preflight.pool, 'snapshot', _snapshot)
    workflow = {'nodes': [{'id': 'c', 'type': 'comment', 'params': params}], 'connections': []}
    return [entry['code'] for entry in WorkflowEngine(workflow).validate_detailed() if entry['id'] == 'c']


class TestTheDeclaration:
    def test_the_manifest_is_whole_and_matches_the_catalogue(self):
        manifest = _manifest()
        assert manifest.problems() == []
        plugin = PLUGINS['comment']
        assert (plugin.label_key, plugin.category, plugin.rows) == (
            manifest.identity.title_key,
            manifest.identity.category,
            manifest.ports.rows,
        )
        assert NODE_DEFAULTS['comment'] == manifest.defaults()

    def test_the_handler_and_validator_are_the_executors_own(self):
        manifest = _manifest()
        assert registry.resolve(manifest.execution.handler) is executor.run
        assert registry.resolve(manifest.validators[0]) is executor.validate_node

    def test_the_page_and_contract_exist(self):
        manifest = _manifest()
        assert (REPO / manifest.docs.page).is_file()
        for path in manifest.tests.contracts:
            assert (REPO / path).is_file()


class TestValidation:
    def test_no_links_is_named(self):
        assert _codes({}) == ['engine.comment_no_urls']

    def test_blank_links_are_missing_not_configured(self):
        assert _codes({'urls': '   '}) == ['engine.comment_no_urls']

    def test_a_link_with_a_login_is_clean(self, monkeypatch):
        assert _codes({'urls': ZHIHU}, monkeypatch, has_session=True) == []

    def test_a_link_without_a_login_is_named_for_its_platform(self, monkeypatch):
        codes = _codes({'urls': ZHIHU}, monkeypatch, has_session=False)
        assert codes == ['engine.source_no_cookie_account']

    def test_every_platform_a_link_names_is_asked(self, monkeypatch):
        asked = []

        def _has_session(platform, *_args, **_kwargs):
            asked.append(platform)
            return True

        monkeypatch.setattr(preflight, 'has_session_to_test', _has_session)
        assert _codes({'urls': f'{ZHIHU}\n{WEIBO}'}) == []
        assert asked == ['zhihu', 'weibo'], asked

    def test_a_duplicate_platform_is_asked_once(self, monkeypatch):
        asked = []

        def _has_session(platform, *_args, **_kwargs):
            asked.append(platform)
            return True

        monkeypatch.setattr(preflight, 'has_session_to_test', _has_session)
        assert _codes({'urls': f'{ZHIHU}\n{ZHIHU}'}) == []
        assert asked == ['zhihu'], asked

    def test_a_pool_account_is_asked_about_the_pool_not_a_file(self, monkeypatch):
        assert _codes({'urls': ZHIHU, 'account': '@pool'}, monkeypatch, pool=('empty', 'usable')) == [
            'engine.source_pool_empty'
        ]
        assert _codes({'urls': ZHIHU, 'account': '@pool'}, monkeypatch, pool=('total', 'cooling')) == [
            'engine.source_pool_cooling'
        ]
        assert _codes({'urls': ZHIHU, 'account': '@pool'}, monkeypatch) == []

    def test_a_catbus_node_is_not_asked_about_a_selenium_cookie(self, monkeypatch):
        asked = []
        monkeypatch.setattr(preflight, 'has_session_to_test', lambda platform, *_a, **_k: asked.append(platform))
        params = {'urls': ZHIHU, 'backend': 'catbus'}
        assert _codes(params) == []
        assert asked == []
