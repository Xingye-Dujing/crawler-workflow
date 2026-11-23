"""Generated artifacts are derived, deterministic and current.

Six fixed artifacts plus one page per capability skill are rendered from the manifests. The failures
this file guards are the quiet ones: an artifact left behind after a parameter rename looks
authoritative, a renderer that sorts dict keys differently on another run makes every freshness check
red, and a form catalogue that no longer parses breaks the P2 form before anyone opens the page.
"""

import json

import pytest
from capabilities_kernel import generate, registry

pytestmark = pytest.mark.unit


def _manifest():
    manifest = registry.manifest_for_node('tokenize')
    assert manifest is not None
    return manifest


class TestTheRenderedSet:
    def test_the_fixed_surfaces_and_the_skill_pages_exist(self):
        rendered = generate.render()
        names = {path.relative_to(generate.ROOT).as_posix() for path in rendered}
        fixed = {
            'backend/capabilities_kernel/generated/catalog.json',
            'backend/capabilities_kernel/generated/openapi.json',
            'backend/capabilities_kernel/generated/ai_tools.json',
            'backend/capabilities_kernel/generated/capability-schema.json',
            'backend/static/js/node-types-fallback.js',
            'docs/capabilities/index.md',
        }
        assert fixed <= names
        extra = names - fixed
        assert extra, 'no capability page was rendered'
        assert all(path.startswith(('docs/capabilities/skills/', 'docs/capabilities/operators/')) for path in extra), (
            sorted(extra)
        )

    def test_rendering_twice_is_byte_identical(self):
        first = {str(path): text for path, text in generate.render().items()}
        second = {str(path): text for path, text in generate.render().items()}
        assert first == second

    def test_no_committed_artifact_is_stale(self):
        assert generate.check() == [], 'run `python tools/gen_capabilities.py` and commit the result'

    def test_the_outputs_table_names_every_renderer(self):
        functions = {
            'catalog': generate._catalog_payload,
            'openapi': generate._openapi_payload,
            'ai_tools': generate._ai_payload,
            'frontend_schema': generate._frontend_schema,
            'frontend_catalogue': generate._frontend_catalogue_js,
            'docs_index': generate._docs_index,
        }
        assert set(generate.OUTPUTS.values()) == set(functions)
        for name, function in functions.items():
            assert callable(function), name


class TestTheArtifactsSayTheSameThing:
    def test_the_catalog_carries_the_manifest_digest(self):
        payload = json.loads(generate.render()[generate.ROOT / 'backend/capabilities_kernel/generated/catalog.json'])
        entry = next(row for row in payload['capabilities'] if row['id'] == 'tokenize')
        assert entry['digest'] == _manifest().digest()
        assert entry['manifest']['identity']['title_key'] == 'nodeType.tokenize'

    def test_the_test_matrix_enumerates_every_check(self):
        payload = json.loads(generate.render()[generate.ROOT / 'backend/capabilities_kernel/generated/catalog.json'])
        row = next(item for item in payload['matrix'] if item['id'] == 'tokenize')
        assert row['checks'] == list(generate.MATRIX_CHECKS)
        assert row['docs'] == 'docs/capabilities/nodes/tokenize.md'
        assert row['contract_tests'] == ['tests/unit/capabilities/test_tokenize_manifest.py']

    def test_openapi_describes_the_catalogue_endpoint_and_the_tokenize_params(self):
        payload = json.loads(generate.render()[generate.ROOT / 'backend/capabilities_kernel/generated/openapi.json'])
        assert payload['openapi'].startswith('3.1')
        assert '/api/node-types' in payload['paths']
        params = payload['components']['schemas']['NodeParams.tokenize']
        assert params['required'] == ['text_column']
        assert params['properties']['output_mode']['enum'] == ['word_freq', 'words_only', 'csv_line']

    def test_the_ai_catalogue_carries_the_example_and_failure_modes(self):
        payload = json.loads(generate.render()[generate.ROOT / 'backend/capabilities_kernel/generated/ai_tools.json'])
        entry = next(row for row in payload['tools'] if row['capability'] == 'node:tokenize')
        assert entry['examples'] == list(_manifest().ai.examples)
        assert entry['emit_columns'] == 'nodes.executors.tokenize:emit_columns'

    def test_the_docs_index_links_the_documented_page(self):
        text = generate.render()[generate.ROOT / 'docs/capabilities/index.md']
        assert '| tokenize |' in text
        assert '(../capabilities/nodes/tokenize.md)' in text
        assert '[技能](skills/nodes/tokenize.md)' in text

    def test_the_skill_page_is_the_body_the_tool_renders(self):
        from capabilities_kernel import knowledge

        manifest = registry.manifest_for_node('tokenize')
        page = generate.render()[generate.ROOT / 'docs/capabilities/skills/nodes/tokenize.md']
        assert page == knowledge.render(manifest)


class TestTheFrontendCatalogue:
    def test_it_is_a_json_catalogue_of_nodes(self):
        text = generate.render()[generate.ROOT / 'backend/capabilities_kernel/generated/capability-schema.json']
        payload = json.loads(text)
        node = next(item for item in payload['nodes'] if item['type'] == 'tokenize')
        assert node['params'][0]['widget'] == 'column'
        assert node['rules'][0]['code'] == 'engine.tokenize_no_column'

    def test_the_cold_page_script_is_loaded_before_the_catalogue_module(self):
        """The generated fallback is a page module now, and it must load before ``node-types.js``
        reads it; a page that loads it later would run the first paint on no catalogue at all."""
        html = (generate.ROOT / 'backend' / 'static' / 'index.html').read_text(encoding='utf-8')
        fallback = html.index('js/node-types-fallback.js')
        module = html.index('js/node-types.js')
        assert fallback < module
        paths = {path.relative_to(generate.ROOT).as_posix() for path in generate.render()}
        assert 'backend/static/js/node-types-fallback.js' in paths
