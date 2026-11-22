"""Every capability manifest is whole, importable and answerable on the boot path.

The registry refuses a duplicate or a structurally broken manifest at read time; this gate adds the
facts that need the file system and the message catalogue: the executor exists, the declared port
hooks resolve, the documented page and contract test are real, the capability's word exists in both
browser languages, and a manifest module imports nothing heavy or upward. Those are exactly the
questions a new capability used to leave to a reviewer, and the gate is generic: a manifest added
tomorrow is covered the day it lands, with no edit here.
"""

import ast
import sys
from pathlib import Path

import pytest
from capabilities_kernel import generate, registry
from capabilities_kernel.manifest import KINDS
from frontend_catalogue import catalog_keys

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / 'backend'
KERNEL = BACKEND / 'capabilities_kernel'
STDLIB = set(sys.stdlib_module_names)


def _manifests():
    found = []
    for kind in KINDS:
        found.extend(registry.manifests(kind))
    assert found, 'the kernel discovered no capability at all — this gate would pass over nothing'
    return found


MANIFESTS = _manifests()
IDS = [f'{manifest.identity.kind}:{manifest.identity.id}' for manifest in MANIFESTS]


@pytest.mark.parametrize('manifest', MANIFESTS, ids=IDS)
class TestAManifestIsWhole:
    def test_the_structural_sections_are_complete(self, manifest):
        assert manifest.problems() == []

    def test_the_executor_is_a_callable_the_registry_can_import(self, manifest):
        handler = registry.resolve(manifest.execution.handler)
        assert callable(handler), f'{manifest.execution.handler} is not callable'

    def test_the_declared_port_hooks_resolve(self, manifest):
        for reference in (manifest.ports.emit_columns, manifest.ports.read_columns):
            if reference:
                assert callable(registry.resolve(reference)), reference

    def test_the_documented_page_and_contract_tests_exist(self, manifest):
        if manifest.docs.page:
            assert (REPO / manifest.docs.page).is_file(), manifest.docs.page
        for relative in manifest.tests.contracts:
            assert (REPO / relative).is_file(), relative

    def test_the_capability_has_a_word_in_both_languages(self, manifest):
        tables = catalog_keys()
        missing = [lang for lang in ('en', 'zh') if manifest.identity.title_key not in tables[lang]]
        assert missing == [], f'{manifest.identity.title_key} missing from {missing}'

    def test_the_digest_is_a_sha256(self, manifest):
        digest = manifest.digest()
        assert len(digest) == 64 and set(digest) <= set('0123456789abcdef')


def _manifest_modules():
    schema = KERNEL / 'manifest.py'
    return sorted(path for path in KERNEL.rglob('manifest.py') if path != schema and '__pycache__' not in path.parts)


class TestManifestsStayLight:
    def test_the_scan_sees_every_manifest(self):
        assert len(_manifest_modules()) == len(MANIFESTS)

    def test_no_manifest_imports_a_domain_layer_or_a_heavy_library(self):
        """``nodes.catalog`` imports manifests while parsing a DAG; pandas here would cost every start."""
        offenders = []
        for path in _manifest_modules():
            tree = ast.parse(path.read_text(encoding='utf-8'), str(path))
            for node in tree.body:
                if isinstance(node, ast.Import):
                    roots = {alias.name.split('.')[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    roots = {node.module.split('.')[0]}
                else:
                    continue
                for root in roots:
                    if root in STDLIB or root == 'capabilities_kernel':
                        continue
                    offenders.append(f'{path.relative_to(BACKEND).as_posix()}: imports {root}')
        assert offenders == [], 'a manifest reached outside the kernel: ' + '; '.join(offenders)


class TestTheGeneratedArtifactsAreCurrent:
    def test_no_committed_artifact_is_stale(self):
        """A rename that skips the generator must fail here, not in the P2 form."""
        assert generate.check() == [], 'run `python tools/gen_capabilities.py` and commit the result'

    def test_the_generator_renderers_and_the_outputs_table_agree(self):
        assert {path.name for path in generate.render()} == {
            'catalog.json',
            'openapi.json',
            'ai_tools.json',
            'capability-schema.json',
            'index.md',
        }
