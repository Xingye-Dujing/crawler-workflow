"""Every capability manifest is whole, importable and answerable on the boot path.

The registry refuses a duplicate or a structurally broken manifest at read time; this gate adds the
facts that need the file system and the message catalogue: the executor exists, the declared port
hooks resolve, the documented page and contract test are real, the capability's word exists in both
browser languages, and a manifest module imports nothing heavy or upward. Those are exactly the
questions a new capability used to leave to a reviewer, and the gate is generic: a manifest added
tomorrow is covered the day it lands, with no edit here.
"""

import ast
import re
import sys
from pathlib import Path

import pytest
from capabilities_kernel import generate, registry
from capabilities_kernel.manifest import KINDS
from frontend_catalogue import catalog_keys

from engine.workflow import WorkflowEngine

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

    def test_the_declared_validators_resolve(self, manifest):
        for reference in manifest.validators:
            assert callable(registry.resolve(reference)), reference

    def test_the_declared_preflight_resolves(self, manifest):
        """A preflight is optional, but a declared one must be a callable ``module:function``:
        a typo would silently skip every data check the capability claims."""
        if manifest.preflight:
            assert callable(registry.resolve(manifest.preflight)), manifest.preflight

    def test_the_declared_postcheck_resolves(self, manifest):
        """The after-run check is optional too, and the same typo would silence it."""
        if manifest.postcheck:
            assert callable(registry.resolve(manifest.postcheck)), manifest.postcheck

    def test_the_documented_page_and_contract_tests_exist(self, manifest):
        if manifest.docs.page:
            assert (REPO / manifest.docs.page).is_file(), manifest.docs.page
        if manifest.docs.skill:
            assert (REPO / manifest.docs.skill).is_file(), manifest.docs.skill
        for relative in manifest.tests.contracts:
            assert (REPO / relative).is_file(), relative

    def test_the_capability_has_a_word_in_both_languages(self, manifest):
        tables = catalog_keys()
        missing = [lang for lang in ('en', 'zh') if manifest.identity.title_key not in tables[lang]]
        assert missing == [], f'{manifest.identity.title_key} missing from {missing}'

    def test_every_form_word_exists_in_both_languages(self, manifest):
        """A schema form draws labels/hints from the manifest: an untranslated key would print
        itself as the field label in one language."""
        tables = catalog_keys()
        keys = [manifest.ui.hint_key] if manifest.ui.hint_key else []
        for spec in manifest.params:
            keys.extend(key for key in (spec.label_key, spec.placeholder_key, spec.description_key) if key)
        missing = [f'{key} missing from {lang}' for key in keys for lang in ('en', 'zh') if key not in tables[lang]]
        assert missing == []

    def test_the_digest_is_a_sha256(self, manifest):
        digest = manifest.digest()
        assert len(digest) == 64 and set(digest) <= set('0123456789abcdef')


def _manifest_modules():
    schema = KERNEL / 'manifest.py'
    return sorted(path for path in KERNEL.rglob('manifest.py') if path != schema and '__pycache__' not in path.parts)


class TestTheFrontendKnowsEveryCustomForm:
    """ADR-002's "UI renderer 是否存在": a custom form names a renderer the browser registers.

    The panel refuses an unknown id at open time, which is the right runtime behaviour — but a
    capability that ships without its form would only be discovered by the user who opens it. The
    ids are registered by ``registerSettingsRenderer('<id>', …)`` in the shipped JS, so the gate
    asks that exact set.
    """

    REGISTERED = re.compile(r"registerSettingsRenderer\(\s*'([a-z0-9_]+)'")

    def test_every_custom_renderer_is_registered_in_the_shipped_javascript(self):
        sources = (BACKEND / 'static' / 'js').rglob('*.js')
        registered = {
            identifier
            for path in sources
            for identifier in self.REGISTERED.findall(path.read_text(encoding='utf-8', errors='replace'))
        }
        assert registered, 'the scan found no registered settings renderer at all'
        missing = {
            manifest.ui.custom_renderer
            for manifest in MANIFESTS
            if manifest.ui.form == 'custom' and manifest.ui.custom_renderer not in registered
        }
        assert not missing, f'custom settings renderers nobody registers: {sorted(missing)}'


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

    def test_the_generated_artifact_set_is_the_declared_set_plus_skill_pages(self):
        """Six fixed artifacts, plus one page per capability skill under their own tree.

        The skill pages are derived from the same manifest section the ``skill_load`` tool renders,
        so they are generated rather than hand-kept; every extra path must live under that tree, so a
        typo cannot quietly add a document somewhere nobody reviews.
        """
        rendered = {path.relative_to(REPO).as_posix() for path in generate.render()}
        fixed = {
            'backend/capabilities_kernel/generated/catalog.json',
            'backend/capabilities_kernel/generated/openapi.json',
            'backend/capabilities_kernel/generated/ai_tools.json',
            'backend/capabilities_kernel/generated/capability-schema.json',
            'backend/static/js/node-types-fallback.js',
            'docs/capabilities/index.md',
        }
        assert fixed <= rendered
        extra = rendered - fixed
        assert extra, 'no capability skill page was rendered'
        assert all(path.startswith('docs/capabilities/skills/') for path in extra), sorted(extra)


class TestTheTrainingTemplateIsAccepted:
    """A skill's template is offered to the model as something to send back, so the engine must
    accept it: a template that names an illegal option teaches the model a call the server refuses.
    """

    @pytest.mark.parametrize('manifest', MANIFESTS, ids=IDS)
    def test_the_template_produces_no_parameter_or_matrix_refusal(self, manifest):
        template = dict(manifest.ai.template)
        template.setdefault('id', 'a')
        codes = [entry for entry in WorkflowEngine({'nodes': [template], 'connections': []}).validate_detailed()]
        wrong = [
            entry['code']
            for entry in codes
            if entry.get('param')
            or any(word in entry['code'] for word in ('unknown', 'bad', 'missing'))
            or entry['code'] == 'engine.source'
        ]
        assert wrong == [], f'{manifest.identity.id} template is refused: {wrong}'
