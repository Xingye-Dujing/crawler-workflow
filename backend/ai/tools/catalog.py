"""The catalogue tools: what this build can do, read from the registries that own the answers.

Every tool here is read-only and cheap: the capability→AI-entry matrix, the two-level capability
skill catalogue, the CatBus toolchain probe, and the chart/analysis registries with their column
contracts. None of them inspects a path or guesses a capability — each asks the one registry that
already knows.
"""

from ai.errors import AIError
from ai.tools.shared import _int_arg
from ai.types import ToolSpec


def tool_ai_coverage(_args: dict, _ctx: dict) -> dict:
    """The generated capability→entry matrix. A missing cell is a product gap, not a prompt issue."""
    from ai import coverage

    return coverage.audit()


def tool_capability_catalog(args: dict, _ctx: dict) -> dict:
    """The level-1 capability-skill catalogue: words to select on, not bodies."""
    from ai import knowledge

    return knowledge.catalog(
        kind=str(args.get('kind') or ''),
        query=str(args.get('query') or ''),
        limit=_int_arg(args.get('limit'), 30, 1, 200),
    )


def tool_capability_load(args: dict, _ctx: dict) -> dict:
    """The level-2 body of one capability skill, with its parameter table rendered fresh."""
    from ai import knowledge

    skill = str(args.get('skill_id') or '').strip()
    if not skill:
        raise AIError('ai.skillUnknown', kind='bad_request', skill='')
    return knowledge.load(skill)


def tool_catbus_status(_args: dict, _ctx: dict) -> dict:
    """Report the CatBus toolchain the app itself would use — one detector, two run modes.

    The adapter half comes from the SAME :func:`services.ingest.catbus.probe` the canvas backend
    uses, and the direct-command half from :func:`services.ingest.catbus.direct_cli_status`, which
    applies the same component-source rule. No PATH probe or path precedence is repeated here. The
    verdict is a server answer; the model never inspects paths itself or installs anything.
    """
    from services.ingest import catbus as bridge

    info = bridge.probe()
    status: dict = {
        'available': info.available,
        'reason_key': info.reason_key,
        'node': info.node,
        'node_version': info.node_version,
        'entry': info.entry,
        'platforms': list(info.platforms)[:30],
    }
    if not info.available:
        from i18n import t

        status['message'] = t(info.reason_key, **info.reason_params)
    # The direct CLI facts are the bridge's shared answer, not a second detection here.
    status.update(bridge.direct_cli_status(info.entry, info.node))
    local = status['local_cli']
    if not status['available']:
        status['hint'] = 'The canvas backend is unavailable — report the named reason; do not install.'
    elif status['cli_ok']:
        status['hint'] = 'Both paths are ready: the canvas second backend and direct AI catbus commands.'
    elif local:
        status['hint'] = (
            f'No global catbus CLI, but a local build exists at {local}. Ask the user whether to use '
            'this local build or to install the global CLI (npm i -g catbus-cli). Never install first.'
        )
    else:
        status['hint'] = (
            'No global catbus CLI and no local build found. Ask the user whether to install the global '
            'CLI (npm i -g catbus-cli) or point CATBUS_HOME at a checkout. Never install without consent.'
        )
    return status


def tool_chart_catalog(_args: dict, _ctx: dict) -> dict:
    from ai import vocabulary
    from services.charts.registry import SPECS

    return {
        'charts': [
            {
                'key': spec.key,
                'family': spec.family,
                'reads': list(spec.reads),
                'echarts_only': spec.echarts_only,
                'latex_buildable': spec.latex_buildable,
            }
            for spec in SPECS
        ],
        'contracts': vocabulary.chart_catalog(),
    }


def tool_analysis_catalog(_args: dict, _ctx: dict) -> dict:
    from ai import vocabulary
    from services.analysis.ops import OPS

    return {'ops': sorted(OPS), 'count': len(OPS), 'contracts': vocabulary.analysis_catalog()}


#: ``(spec, …)`` in the order the model reads them; ``ai.tools.TOOLS`` merges every domain's tuple.
TOOLS = (
    ToolSpec(
        'ai_coverage',
        'Read the generated capability→AI-entry matrix: workflow nodes, platform modes, analysis '
        'operators, chart types and tools, each with the entry that reaches it and any gap.',
        {'type': 'object', 'properties': {}},
        handler=tool_ai_coverage,
    ),
    ToolSpec(
        'capability_catalog',
        'List the capability documentation (level 1: id, category, one-sentence summary, when to use and '
        'when not to). Pass query to search and kind to narrow (node/operator/chart/platform/tool/skill). '
        'Load one body with capability_load before acting on a capability you are not sure about.',
        {
            'type': 'object',
            'properties': {
                'kind': {'type': 'string'},
                'query': {'type': 'string'},
                'limit': {'type': 'integer'},
            },
        },
        handler=tool_capability_catalog,
    ),
    ToolSpec(
        'capability_load',
        'Read one capability skill in full (level 2): prerequisites, ordered steps, examples, a template '
        'JSON, the parameters re-read from the live manifest, named refusals and acceptance. Refuses an '
        'unknown id by name.',
        {
            'type': 'object',
            'properties': {'skill_id': {'type': 'string'}},
            'required': ['skill_id'],
        },
        handler=tool_capability_load,
    ),
    ToolSpec(
        'catbus_status',
        'Detect the local CatBus toolchain read-only: the 采析绘 adapter (Node + capabilities) and the '
        'global catbus CLI. Call this before deciding how to crawl; it never installs anything.',
        {'type': 'object', 'properties': {}},
        handler=tool_catbus_status,
    ),
    ToolSpec(
        'chart_catalog',
        'Read the chart registry and each chart’s required columns.',
        {'type': 'object', 'properties': {}},
        handler=tool_chart_catalog,
    ),
    ToolSpec(
        'analysis_catalog',
        'Read every analysis operator the pipeline knows.',
        {'type': 'object', 'properties': {}},
        handler=tool_analysis_catalog,
    ),
)
