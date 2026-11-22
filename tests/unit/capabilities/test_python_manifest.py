"""The Python node's declaration: a saved script id, local-only, no inline code."""

from pathlib import Path

import pytest
from capabilities_kernel import registry
from nodes.catalog import PLUGINS
from nodes.defaults import NODE_DEFAULTS
from nodes.executors import python_node as executor

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]


def _manifest():
    manifest = registry.manifest_for_node('python')
    assert manifest is not None
    return manifest


class TestTheDeclaration:
    def test_the_manifest_is_whole_and_matches_the_catalogue(self):
        manifest = _manifest()
        assert manifest.problems() == []
        plugin = PLUGINS['python']
        assert (plugin.label_key, plugin.category, plugin.rows) == (
            manifest.identity.title_key,
            manifest.identity.category,
            manifest.ports.rows,
        )
        assert NODE_DEFAULTS['python'] == manifest.defaults()

    def test_the_handler_is_the_executors_own_and_no_validation_pretends(self):
        manifest = _manifest()
        assert registry.resolve(manifest.execution.handler) is executor.run
        assert manifest.validators == ()
        assert manifest.rules == ()

    def test_the_page_and_contract_exist(self):
        manifest = _manifest()
        assert (REPO / manifest.docs.page).is_file()
        for path in manifest.tests.contracts:
            assert (REPO / path).is_file()
