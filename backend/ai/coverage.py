"""The capability → AI-entry matrix, generated from the registries that actually run.

A new node type, platform mode, analysis operator, chart type or tool is added in ONE place. The
assistant can only use it if some entry reaches it: the generated schema/catalog tools, a skill's
tool list, or the universal set. This module reads those registries and reports any cell with no
entry — the product gap behind "the AI does not know it can do X", named instead of guessed.

The gate (``tests/unit/gates/test_ai_coverage.py``) refuses a missing cell, so adding a capability
without an entry fails CI rather than waiting for a user to notice.
"""

from __future__ import annotations


def _family(entry: str, expected, covered) -> dict:
    expected = {str(item) for item in expected if str(item)}
    covered = {str(item) for item in covered if str(item)}
    missing = sorted(expected - covered)
    return {
        'entry': entry,
        'total': len(expected),
        'covered': len(expected) - len(missing),
        'missing': missing,
    }


def audit() -> dict:
    """Every family with its totals, the entry that reaches it, and the missing names."""
    import capabilities.registry as capabilities
    from nodes.catalog import NODE_TYPES

    from ai import vocabulary

    schema = vocabulary.workflow_schema()
    node_types = {str(row.get('type') or '') for row in schema.get('nodes') or ()}
    matrix = vocabulary.platform_matrix()
    platform_modes = {
        f'{row.get("platform")}/{mode.get("key")}'
        for row in matrix
        for mode in row.get('modes') or ()
        if row.get('platform') and mode.get('key')
    }
    advertised = capabilities.as_dict()
    advertised_modes = {
        f'{platform.get("platform")}/{mode.get("key")}'
        for platform in advertised.get('platforms') or ()
        for mode in platform.get('modes') or ()
        if platform.get('platform') and mode.get('key')
    }
    analysis_ops = {str(row.get('operation') or '') for row in vocabulary.analysis_catalog()}
    chart_types = {str(row.get('chart_type') or '') for row in vocabulary.chart_catalog()}

    from services.analysis.ops import OPS
    from services.charts.registry import SPECS

    families = {
        'workflow_nodes': _family('workflow_schema', NODE_TYPES, node_types),
        'platform_modes': _family('capabilities', advertised_modes, platform_modes),
        'analysis_ops': _family('analysis_catalog', OPS, analysis_ops),
        'chart_types': _family('chart_catalog', {spec.key for spec in SPECS}, chart_types),
    }

    from ai import skills
    from ai.agent import FILE_TOOLS, UNIVERSAL_TOOLS
    from ai.tools import TOOLS

    reachable = set(UNIVERSAL_TOOLS) | set(FILE_TOOLS)
    for skill in skills.all_skills().values():
        reachable.update(skill.tools)
    tool_names = {name for name, spec in TOOLS.items() if spec.builtin and not spec.control}
    families['tools'] = _family('skill tools + universal', tool_names, reachable)

    missing = {name: family['missing'] for name, family in families.items() if family['missing']}
    return {
        'ok': not missing,
        'families': families,
        'missing': missing,
        'totals': {
            'capabilities': sum(family['total'] for family in families.values()),
            'missing': sum(len(rows) for rows in missing.values()),
        },
    }
