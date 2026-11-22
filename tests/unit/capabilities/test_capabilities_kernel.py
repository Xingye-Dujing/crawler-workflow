"""The kernel's own contract: discovery, refusals, ordering and the stable hash.

The registry is the one reader of ``capabilities_kernel/<kind>/``. Its promises are the kind that
fail silently when broken — a duplicate silently wins for whoever imported first, a manifest for
another api_version is reinterpreted field-by-field, a digest that changes without a declaration
change makes every freshness gate useless. So each promise is a named refusal here, and the
duplicate/id/version cases run against a temporary tree instead of writing into the checkout.
"""

import sys
import types
from dataclasses import replace

import pytest
from capabilities_kernel import registry
from capabilities_kernel.manifest import API_VERSION

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _fresh_registry():
    registry.reset_for_tests()
    yield
    registry.reset_for_tests()


def _tokenize():
    manifest = registry.manifest_for_node('tokenize')
    assert manifest is not None, 'the pilot manifest is not discoverable'
    return manifest


class TestDiscovery:
    def test_the_pilot_is_discovered_without_a_second_list(self):
        assert [manifest.identity.id for manifest in registry.manifests('node')] == [
            'name',
            'source',
            'upload',
            'resume',
            'comment',
            'process',
            'python',
            'analysis',
            'tokenize',
            'biblio',
            'verify',
            'fuse',
            'accumulate',
            'visualize',
            'compile',
            'output',
        ]

    def test_an_unknown_kind_is_refused_by_name(self):
        with pytest.raises(registry.ManifestError, match='unknown capability kind'):
            registry.describe('moonbase')

    def test_a_flat_module_and_a_package_with_the_same_id_are_refused(self, monkeypatch, tmp_path):
        twenty = tmp_path / 'nodes' / 'tokenize'
        twenty.mkdir(parents=True)
        (twenty / 'manifest.py').write_text('MANIFEST = None\n', encoding='utf-8')
        (tmp_path / 'nodes' / 'tokenize.py').write_text('MANIFEST = None\n', encoding='utf-8')
        monkeypatch.setattr(registry, 'KERNEL_ROOT', tmp_path)
        with pytest.raises(registry.ManifestError, match='declared twice'):
            registry.describe('node')

    def test_a_directory_without_a_manifest_is_not_a_capability(self, monkeypatch, tmp_path):
        (tmp_path / 'nodes' / 'notes').mkdir(parents=True)
        (tmp_path / 'nodes' / 'notes' / 'readme.txt').write_text('x', encoding='utf-8')
        monkeypatch.setattr(registry, 'KERNEL_ROOT', tmp_path)
        assert registry.describe('node') == {}


class TestRefusals:
    def _fake_import(self, monkeypatch, manifest):
        monkeypatch.setattr(registry, '_import', lambda _module: manifest)

    def test_a_manifest_for_another_api_version_is_refused(self, monkeypatch):
        self._fake_import(monkeypatch, replace(_tokenize(), api_version=API_VERSION + 1))
        with pytest.raises(registry.ManifestError, match='api_version'):
            registry._load('node', 'tokenize', 'fake')

    def test_a_manifest_under_the_wrong_kind_tree_is_refused(self, monkeypatch):
        manifest = _tokenize()
        self._fake_import(monkeypatch, replace(manifest, identity=replace(manifest.identity, kind='chart')))
        with pytest.raises(registry.ManifestError, match='kind'):
            registry._load('node', 'tokenize', 'fake')

    def test_a_manifest_whose_id_is_not_its_directory_is_refused(self, monkeypatch):
        manifest = _tokenize()
        self._fake_import(monkeypatch, replace(manifest, identity=replace(manifest.identity, id='tokenizer')))
        with pytest.raises(registry.ManifestError, match='declares id'):
            registry._load('node', 'tokenize', 'fake')

    def test_an_incomplete_manifest_is_refused_with_its_sections(self, monkeypatch):
        manifest = _tokenize()
        self._fake_import(monkeypatch, replace(manifest, execution=replace(manifest.execution, handler='')))
        with pytest.raises(registry.ManifestError, match='execution.handler'):
            registry._load('node', 'tokenize', 'fake')

    def test_a_module_without_a_manifest_is_named(self, monkeypatch):
        monkeypatch.setitem(sys.modules, 'fake_capability', types.ModuleType('fake_capability'))
        with pytest.raises(registry.ManifestError, match='MANIFEST'):
            registry._import('fake_capability')

    def test_a_handler_reference_needs_both_halves_and_an_attribute(self):
        with pytest.raises(registry.ManifestError, match='module:function'):
            registry.resolve('nodes.executors.tokenize')
        with pytest.raises(registry.ManifestError, match='no .*nope'):
            registry.resolve('nodes.executors.tokenize:nope')


class TestProjections:
    def test_the_node_entry_is_the_manifest_identity(self):
        manifest = _tokenize()
        entry = next(item for item in registry.node_entries() if item['type'] == 'tokenize')
        assert entry['label_key'] == manifest.identity.title_key
        assert entry['category'] == manifest.identity.category
        assert entry['rows'] == manifest.ports.rows
        assert entry['quiet'] is manifest.execution.quiet
        assert entry['order'] == manifest.identity.order

    def test_the_seed_parameters_are_the_manifest_defaults(self):
        manifest = _tokenize()
        assert registry.node_defaults()['tokenize'] == manifest.defaults()
        assert manifest.defaults() == {'text_column': '', 'top_n': '', 'output_mode': 'word_freq'}

    def test_defaults_are_copies_not_the_manifest(self):
        manifest = _tokenize()
        seeds = manifest.defaults()
        seeds['text_column'] = 'mutated'
        assert manifest.defaults()['text_column'] == '', 'a caller edited the declaration itself'


class TestDigest:
    def test_the_digest_is_stable_and_content_addressed(self):
        manifest = _tokenize()
        assert manifest.digest() == _tokenize().digest()
        assert len(manifest.digest()) == 64
        changed = replace(
            manifest,
            params=(replace(manifest.params[0], default='正文'),) + manifest.params[1:],
        )
        assert changed.digest() != manifest.digest(), 'a changed default must change the hash'
