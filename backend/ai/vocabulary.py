"""The legal vocabulary of 采析绘, generated from the registries the app itself trusts.

An assistant that writes a workflow, an analysis plan or a chart proposal must use the names this
product actually understands. A model that invents ``节点类型: 分析`` (a DISPLAY word) or a chart
key the registry does not hold produces a canvas of blank boxes and a plan no panel can run — the
server was refusing those drafts only after the fact. This module gives the model the same table
the engine, the chart registry and the capability matrix use, so the first draft is already legal.

Nothing here is hand-maintained twice: node types and their seed params come from
``nodes/catalog.py`` + ``nodes/defaults.py``, analysis operators and the parameters each one
requires from ``services.analysis.contracts.STEP_PARAMS``, chart types from
``services.charts.registry.SPECS`` and platform modes/fields from ``capabilities.registry``.
A registry change therefore changes the prompt in the same commit.
"""

from __future__ import annotations

import json
from functools import lru_cache

#: Facts a workflow file is expected to carry, and the wire shape the canvas loads.
WORKFLOW_SHAPE = {
    'nodes': [{'id': 'n1', 'type': '<node type>', 'x': 80, 'y': 120, 'title': '', 'params': {}}],
    'connections': [{'from': 'n1', 'to': 'n2'}],
    'settings': {'mode': 'serial', 'headless': True, 'disabledTypes': []},
    'view': {'x': 0, 'y': 0, 'zoom': 1},
}

RULES = (
    '工作流文件格式（唯一的合法形状）：\n'
    '- 顶层是 JSON 对象：nodes（数组，至少一个）、connections（数组）、settings（对象，可省）、view（对象，可省）。\n'
    '- 每个 node：id（字符串，文件内唯一，只能用字母/数字/下划线/短横线）、type（必须是下列节点类型之一，'
    '不能用中文显示名）、x/y（数字，画布坐标）、title（可省）、params（对象；键必须是该类型声明的参数）。\n'
    '- 每条 connection 只有 from 和 to 两个键，值是节点 id；图必须无环，且每条线的两端都必须在 nodes 里。\n'
    '- settings.mode 只能是 serial 或 parallel；headless 是布尔；disabledTypes 是该画布里关掉的类型数组。\n'
    '- 节点坐标只要不重叠即可；建议从左到右每列 260px、每行 160px。\n'
    '- 名称：要固定工作流名时，加一个 type="name" 且 params.workflow_name 的节点。\n'
    '- 数据源节点（source）的 params 由平台与模式决定（见下方平台字段），不要写别的键。\n'
    '- upload 节点必须带 dataset_id（本账号已有数据集），否则改为 source 节点。\n'
    '- 可视化节点（visualize）的 chart_type 必须来自下方图表清单；分析节点（analysis）的 operation '
    '必须来自下方算子清单，并带上该算子要求的参数键。\n'
)


def _node_defaults() -> dict:
    from nodes.defaults import NODE_DEFAULTS

    return NODE_DEFAULTS


def node_catalog() -> list[dict]:
    """Every node type with the parameters a new node starts with."""
    from nodes.catalog import PLUGINS

    defaults = _node_defaults()
    rows = []
    for plugin in PLUGINS.values():
        params = defaults.get(plugin.type)
        rows.append(
            {
                'type': plugin.type,
                'category': plugin.category,
                'rows': plugin.rows,
                'params': dict(params) if params else {},
                'params_from': 'capabilities' if plugin.type == 'source' else '',
                'label_key': plugin.label_key,
            }
        )
    return rows


def workflow_schema() -> dict:
    return {'shape': WORKFLOW_SHAPE, 'rules': RULES, 'nodes': node_catalog()}


def platform_matrix() -> list[dict]:
    """Platforms, their runnable modes and the fields each mode requires, with defaults."""
    import capabilities.registry as capabilities

    payload = capabilities.as_dict()
    rows = []
    for platform in payload.get('platforms', []):
        modes = []
        for mode in platform.get('modes') or []:
            if not isinstance(mode, dict) or not mode.get('key'):
                continue
            fields = []
            for field in mode.get('fields') or []:
                if not isinstance(field, dict) or not field.get('key'):
                    continue
                item = {'key': field['key'], 'control': field.get('control') or 'text'}
                if field.get('default') not in (None, ''):
                    item['default'] = field['default']
                if field.get('required'):
                    item['required'] = True
                if field.get('options'):
                    item['options'] = [
                        str(option.get('value') if isinstance(option, dict) else option) for option in field['options']
                    ][:20]
                fields.append(item)
            modes.append(
                {
                    'key': mode['key'],
                    'rows': mode.get('rows') or '',
                    'needs_session': bool(mode.get('needsSession')),
                    'engines': list(mode.get('engines') or []),
                    'fields': fields,
                }
            )
        rows.append({'platform': platform.get('platform') or '', 'modes': modes})
    return rows


def analysis_catalog() -> list[dict]:
    """Every operator with the parameters it cannot run without."""
    from services.analysis.contracts import STEP_PARAMS
    from services.analysis.ops import OPS

    rows = []
    for name in sorted(OPS):
        contract = STEP_PARAMS.get(name) or {}
        required = [str(column) for column in contract.get('one') or ()]
        some = [str(column) for column in contract.get('some') or ()]
        nonblank = [str(column) for column in contract.get('nonblank') or ()]
        enums = {key: list(value[1]) for key, value in (contract.get('enums') or {}).items()}
        rows.append(
            {
                'operation': name,
                'needs_column': required,
                'needs_any_of_columns': some,
                'needs_value': nonblank,
                'allowed': enums,
                'needs_mapping': bool(contract.get('mapping')),
            }
        )
    return rows


def chart_catalog() -> list[dict]:
    from services.charts.registry import SPECS

    return [
        {
            'chart_type': spec.key,
            'family': spec.family,
            'required_columns': list(spec.reads),
            'no_x_axis': spec.no_x,
            # The boxes this chart wants, so the AI can name a chart's fields instead of
            # guessing at x/y for a heatmap or a sangley. Derived from the one declaration.
            'fields': [{'name': field.name, 'role': field.role, 'required': field.required} for field in spec.fields],
        }
        for spec in SPECS
    ]


@lru_cache(maxsize=1)
def prompt_block() -> str:
    """The full legal vocabulary, as one stable block for the system prompt.

    Stable is deliberate: this text sits in the prompt prefix, so DeepSeek's prefix cache hits on
    it turn after turn. It is generated once per process and never mixes per-account facts; the
    live canvas and datasets arrive in the context section instead.
    """
    lines = [
        '# 采析绘的合法词汇（服务端注册表生成，生成任何工作流/分析/图表前必须遵守）',
        RULES,
        '## 节点类型与参数种子',
    ]
    for node in node_catalog():
        params = node['params']
        if params:
            seed = ', '.join(f'{key}={json.dumps(value, ensure_ascii=False)}' for key, value in params.items())
        elif node['params_from']:
            seed = '（由平台与模式决定，见下方平台字段）'
        else:
            seed = '（无参数）'
        lines.append(f'- {node["type"]}（{node["category"]}，产出 {node["rows"]}）：{seed}')
    lines.append('')
    lines.append('## 采集平台 / 模式 / 必填字段（source 节点的 params）')
    for platform in platform_matrix():
        modes = []
        for mode in platform['modes']:
            required = [field['key'] for field in mode['fields'] if field.get('required')]
            optional = [field['key'] for field in mode['fields'] if not field.get('required')]
            label = mode['key']
            if required:
                label += '（必填 ' + '/'.join(required) + '）'
            if optional:
                label += '（可选 ' + '/'.join(optional[:10]) + '）'
            if mode['needs_session']:
                label += ' [需登录]'
            if mode['engines']:
                label += ' [引擎 ' + '/'.join(mode['engines']) + ']'
            modes.append(label)
        lines.append(f'- {platform["platform"]}：' + ('；'.join(modes) if modes else '当前没有可用模式'))
    lines.append('')
    lines.append('## 分析算子（analysis 节点的 params.operation 与参数键）')
    for op in analysis_catalog():
        facts = []
        if op['needs_column']:
            facts.append('列 ' + '/'.join(op['needs_column']))
        if op['needs_any_of_columns']:
            facts.append('可选列 ' + '/'.join(op['needs_any_of_columns']))
        if op['needs_value']:
            facts.append('必填 ' + '/'.join(op['needs_value']))
        if op['allowed']:
            facts.append('可选值 ' + '；'.join(f'{key}={"|".join(values)}' for key, values in op['allowed'].items()))
        if op['needs_mapping']:
            facts.append('需要 mapping（旧列->新列）')
        lines.append(f'- {op["operation"]}：' + ('；'.join(facts) if facts else '无额外参数'))
    lines.append('')
    lines.append('## 本地模型（调用 models_catalog 获取实时可用性与实测指标）')
    from services.models import catalog as model_catalog

    for model in model_catalog.all_models():
        use = '、'.join(model.use_for[:2]) or model.desc[:40]
        outputs = ' / '.join(model.outputs) or '按任务'
        lines.append(f'- {model.id}：任务 {model.task}，族 {model.family}，输出 {outputs}；适用 {use}')
    lines.append('')
    lines.append('## 图表类型（visualize 节点的 params.chart_type）')
    console = [row for row in chart_catalog() if row['family'] == 'console']
    biblio = [row for row in chart_catalog() if row['family'] == 'biblio']
    lines.append('- 通用：' + ', '.join(row['chart_type'] for row in console))
    for row in biblio:
        reads = '/'.join(row['required_columns'])
        lines.append(f'- 文献图 {row["chart_type"]}：必需列 {reads}')
    return '\n'.join(lines)
