"""One platform, declared once and projected into the crawl matrix.

``capabilities/platforms/<id>.py`` became ``capabilities_kernel/platforms/<id>/manifest.py``: the
modes and fields are the same value types, and ``capabilities.platforms.CAPABILITIES`` is now the
tree's projection in panel order. These cases hold the declaration and the runtime matrix together.
"""

import pytest
from capabilities import platforms
from capabilities import registry as matrix
from capabilities_kernel import registry

pytestmark = pytest.mark.unit

MANIFESTS = registry.manifests('platform')
IDS = [manifest.identity.id for manifest in MANIFESTS]


class TestEveryPlatformIsDeclaredOnce:
    def test_the_tree_is_not_empty(self):
        assert MANIFESTS, 'the platform tree discovered nothing — every case below would pass over nothing'

    def test_the_matrix_is_the_projection_in_panel_order(self):
        assert matrix.CAPABILITIES is platforms.CAPABILITIES
        assert tuple(cap.platform for cap in matrix.CAPABILITIES) == tuple(IDS)
        assert matrix.platform_ids() == tuple(IDS)
        assert [manifest.identity.order for manifest in MANIFESTS] == sorted(
            manifest.identity.order for manifest in MANIFESTS
        )

    def test_every_manifest_is_whole(self):
        for manifest in MANIFESTS:
            assert manifest.problems() == [], manifest.identity.id

    def test_every_region_is_one_of_the_two_networks(self):
        assert {manifest.region for manifest in MANIFESTS} <= set(matrix.REGIONS)

    def test_every_crawler_is_the_declared_class(self):
        for manifest in MANIFESTS:
            crawler = registry.resolve(manifest.execution.handler)
            assert isinstance(crawler, type), manifest.execution.handler
            assert str(getattr(crawler, 'platform', manifest.platform)) == manifest.platform


class TestTheModesSayWhatThePanelNeeds:
    def test_every_mode_has_a_unique_key_and_a_handler(self):
        for manifest in MANIFESTS:
            keys = [mode.key for mode in manifest.modes]
            assert keys and len(keys) == len(set(keys)), manifest.platform
            for mode in manifest.modes:
                assert mode.handler, f'{manifest.platform}.{mode.key}'

    def test_the_declares_collects_vocabulary_is_the_shared_one(self):
        from capabilities_kernel.platform import COLLECT_KINDS

        assert set(COLLECT_KINDS) == set(matrix.COLLECT_KINDS)
        for manifest in MANIFESTS:
            for mode in manifest.modes:
                assert mode.collects in COLLECT_KINDS, f'{manifest.platform}.{mode.key}'

    def test_a_platforms_first_mode_is_the_one_the_panel_starts_on(self):
        for manifest in MANIFESTS:
            first = matrix.mode_for(manifest.platform, '')
            assert first is manifest.modes[0], manifest.platform


class TestTheDeclaredSkillTeachesTheDeclaredCrawl:
    @pytest.mark.parametrize('manifest', MANIFESTS, ids=IDS)
    def test_the_template_is_a_source_node_for_this_platform(self, manifest):
        params = manifest.ai.template['params']
        assert manifest.ai.template['type'] == 'source'
        assert params['platform'] == manifest.platform
        assert params.get('collect') in manifest.mode_keys

    @pytest.mark.parametrize('manifest', MANIFESTS, ids=IDS)
    def test_the_seven_sections_are_present(self, manifest):
        for value in (
            manifest.ai.summary,
            manifest.ai.prerequisites,
            manifest.ai.steps,
            manifest.ai.examples,
            manifest.ai.failures,
            manifest.ai.acceptance,
        ):
            assert value

    def test_the_generated_pages_live_under_the_platform_trees(self):
        for manifest in MANIFESTS:
            assert manifest.docs.page == f'docs/capabilities/platforms/{manifest.platform}.md'
            assert manifest.docs.skill == f'docs/capabilities/skills/platforms/{manifest.platform}.md'
