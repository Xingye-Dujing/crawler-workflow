"""One chart type, declared once and projected into every surface that draws or validates it.

``services.charts.registry`` used to hold the chart table; it now projects
``capabilities_kernel/charts/<id>/manifest.py``. These cases hold the declaration and the runtime
registries together: a chart whose builder vanished, whose template cannot be validated, or whose
fields disagree with the form is refused here first.
"""

import pytest
from capabilities_kernel import registry
from capabilities_kernel.chart import FAMILIES

from services.charts import registry as charts

pytestmark = pytest.mark.unit

MANIFESTS = registry.manifests('chart')
IDS = [manifest.identity.id for manifest in MANIFESTS]


class TestEveryChartTypeIsDeclaredOnce:
    def test_the_tree_is_not_empty(self):
        assert MANIFESTS, 'the chart tree discovered nothing — every case below would pass over nothing'

    def test_the_registry_is_the_projection_in_panel_order(self):
        assert tuple(spec.key for spec in charts.SPECS) == tuple(IDS)
        assert tuple(IDS) == charts.CHART_TYPES
        assert [spec.identity.order for spec in MANIFESTS] == sorted(spec.identity.order for spec in MANIFESTS)

    def test_every_manifest_is_whole(self):
        for manifest in MANIFESTS:
            assert manifest.problems() == [], manifest.identity.id

    def test_every_family_is_declared(self):
        assert {manifest.family for manifest in MANIFESTS} <= set(FAMILIES)

    def test_a_console_builder_is_the_registered_builder(self):
        from services.charts.options import BUILDERS

        for manifest in MANIFESTS:
            if manifest.family != 'console':
                continue
            builder = registry.resolve(manifest.execution.handler)
            assert builder is BUILDERS[manifest.key], manifest.key

    def test_a_bibliometric_builder_is_the_registered_view(self):
        from services.biblio.charts import BUILDERS as BIBLIO_BUILDERS

        for manifest in MANIFESTS:
            if manifest.family != 'biblio':
                continue
            assert registry.resolve(manifest.execution.handler) is BIBLIO_BUILDERS[manifest.key], manifest.key


class TestTheDeclaredChartTeachesItsOwnContract:
    @pytest.mark.parametrize('manifest', MANIFESTS, ids=IDS)
    def test_the_template_satisfies_the_declared_fields(self, manifest):
        params = dict(manifest.ai.template['params'])
        assert params.pop('chart_type') == manifest.key
        assert charts.chart_problems(manifest.key, params) == []

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

    def test_the_generated_pages_live_under_the_chart_trees(self):
        for manifest in MANIFESTS:
            assert manifest.docs.page == f'docs/capabilities/charts/{manifest.key}.md'
            assert manifest.docs.skill == f'docs/capabilities/skills/charts/{manifest.key}.md'
