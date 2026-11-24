"""Every capability appears on every surface that serves its kind — and no surface invents one.

A capability used to be declared once per surface: an operator in ``OPS`` and again in a chart's
column contract, a platform in the matrix and again in the AI's vocabulary, a node in the catalogue
and again in the generated page. The manifests fixed the declaration; this gate fixes the *delivery*:
for each kind it names the surfaces that must serve it, and fails in both directions — a capability
missing from a surface, and a surface offering an id the tree does not declare.

One test per (kind, surface) pair, so the failure names the surface and the ids.
"""

import json
from pathlib import Path

import pytest
from capabilities_kernel import generate, knowledge, registry
from capabilities_kernel.manifest import KINDS

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]

#: The surfaces each kind must reach. ``runtime`` is what the server serves today, ``api`` what a
#: browser asks for, ``generated`` the committed artifacts, ``ai`` what the assistant can select and
#: read, ``docs`` the pages a reader opens.
SURFACES: dict[str, tuple[str, ...]] = {
    'node': (
        'runtime:node-types',
        'generated:frontend-schema',
        'openapi:params',
        'generated:catalog',
        'generated:ai-tools',
        'ai:skill-catalog',
        'ai:vocabulary',
        'mcp:capabilities',
        'cli:capabilities',
        'docs:page',
        'docs:skill',
    ),
    'operator': (
        'runtime:ops',
        'openapi:params',
        'generated:catalog',
        'generated:ai-tools',
        'ai:skill-catalog',
        'ai:vocabulary',
        'mcp:capabilities',
        'cli:capabilities',
        'docs:page',
        'docs:skill',
    ),
    'chart': (
        'runtime:charts',
        'api:chart-profiles',
        'generated:frontend-schema',
        'openapi:params',
        'generated:catalog',
        'generated:ai-tools',
        'ai:skill-catalog',
        'ai:vocabulary',
        'mcp:capabilities',
        'cli:capabilities',
        'docs:page',
        'docs:skill',
    ),
    'platform': (
        'runtime:platforms',
        'openapi:params',
        'generated:catalog',
        'generated:ai-tools',
        'ai:skill-catalog',
        'ai:vocabulary',
        'mcp:capabilities',
        'cli:capabilities',
        'docs:page',
        'docs:skill',
    ),
}

_OPENAPI_PREFIX = {
    'node': 'NodeParams.',
    'operator': 'OperatorParams.',
    'chart': 'ChartFields.',
    'platform': 'PlatformModes.',
}


def _generated(relative: str) -> dict:
    return json.loads(generate.render()[generate.ROOT / relative])


def _declared(kind: str) -> set[str]:
    return {manifest.identity.id for manifest in registry.manifests(kind)}


def _offered(surface: str, kind: str) -> set[str]:
    """The ids one surface offers for *kind*. Imported lazily: this gate must stay cheap per case."""
    if surface == 'runtime:node-types':
        return {row['type'] for row in registry.node_schema_entries()}
    if surface == 'runtime:ops':
        from services.analysis.ops import OPS

        return set(OPS)
    if surface == 'runtime:charts':
        from services.charts.registry import CHART_TYPES

        return set(CHART_TYPES)
    if surface == 'runtime:platforms':
        from capabilities import registry as matrix

        return set(matrix.platform_ids())
    if surface == 'api:chart-profiles':
        from services.charts.registry import chart_profiles

        return {row['key'] for row in chart_profiles()}
    if surface == 'generated:frontend-schema':
        payload = _generated('backend/capabilities_kernel/generated/capability-schema.json')
        key = 'nodes' if kind == 'node' else 'charts'
        id_key = 'type' if kind == 'node' else 'key'
        return {row[id_key] for row in payload.get(key) or []}
    if surface == 'openapi:params':
        prefix = _OPENAPI_PREFIX[kind]
        payload = _generated('backend/capabilities_kernel/generated/openapi.json')
        return {name[len(prefix) :] for name in payload['components']['schemas'] if name.startswith(prefix)}
    if surface == 'generated:catalog':
        payload = _generated('backend/capabilities_kernel/generated/catalog.json')
        return {row['id'] for row in payload['capabilities'] if row['kind'] == kind}
    if surface == 'generated:ai-tools':
        payload = _generated('backend/capabilities_kernel/generated/ai_tools.json')
        prefix = f'{kind}:'
        return {row['capability'][len(prefix) :] for row in payload['tools'] if row['capability'].startswith(prefix)}
    if surface == 'ai:skill-catalog':
        return {row['capability'] for row in knowledge.catalog(kind)}
    if surface == 'mcp:capabilities':
        from services.mcp import capabilities_list

        return {row['capability'] for row in capabilities_list(kind=kind)['skills']}
    if surface == 'cli:capabilities':
        from services.capability_cli import listed

        return {row['capability'] for row in listed(kind=kind)}
    if surface == 'ai:vocabulary':
        from ai import vocabulary

        handlers = {
            'node': lambda: vocabulary.node_catalog(),
            'operator': lambda: vocabulary.analysis_catalog(),
            'chart': lambda: vocabulary.chart_catalog(),
            'platform': lambda: vocabulary.platform_matrix(),
        }
        rows = handlers[kind]()
        id_key = {'node': 'type', 'operator': 'operation', 'chart': 'chart_type', 'platform': 'platform'}[kind]
        offered = {row[id_key] for row in rows}
        if kind == 'platform':
            # The vocabulary also lists the platforms only the CatBus adapter serves; those are the
            # adapter's capabilities, not this tree's, so the reverse check must not call them extra.
            from capabilities.catbus import CATBUS_ONLY_PLATFORMS

            offered -= set(CATBUS_ONLY_PLATFORMS)
        return offered
    if surface in ('docs:page', 'docs:skill'):
        relative = f'docs/capabilities/{kind}s' if surface == 'docs:page' else f'docs/capabilities/skills/{kind}s'
        return {path.stem for path in (REPO / relative).glob('*.md') if path.stem != 'index'}
    raise AssertionError(f'unknown surface {surface!r} in this gate')


PAIRS = [(kind, surface) for kind in KINDS for surface in SURFACES.get(kind, ())]
PAIR_IDS = [f'{kind}<-{surface}' for kind, surface in PAIRS]


class TestEveryCapabilityReachesEverySurface:
    @pytest.mark.parametrize('kind, surface', PAIRS, ids=PAIR_IDS)
    def test_no_capability_is_missing_from_a_surface(self, kind, surface):
        missing = _declared(kind) - _offered(surface, kind)
        assert not missing, f'{surface} does not serve {kind}: {sorted(missing)}'

    @pytest.mark.parametrize('kind, surface', PAIRS, ids=PAIR_IDS)
    def test_no_surface_offers_a_capability_the_tree_does_not_declare(self, kind, surface):
        extra = _offered(surface, kind) - _declared(kind)
        assert not extra, f'{surface} offers undeclared {kind}: {sorted(extra)}'

    def test_every_kind_this_gate_knows_is_one_the_kernel_declares(self):
        assert set(SURFACES) <= set(KINDS)
        for kind in KINDS:
            if registry.manifests(kind):
                assert SURFACES.get(kind), f'the gate names no surface for kind {kind!r}'
