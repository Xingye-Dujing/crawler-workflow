"""Generate the derived capability artifacts from the manifests.

One manifest feeds several surfaces, and a surface that is generated once and never checked is
worse than a hand-written one: it looks authoritative after the declaration moved. So ``check()``
re-renders every artifact in memory and compares bytes; the completeness gate runs it, and
``tools/gen_capabilities.py --check`` is the same answer from the command line.

The six artifacts:

1. ``backend/capabilities_kernel/generated/catalog.json`` — the machine catalogue **and** the
   capability × check test matrix.
2. ``backend/capabilities_kernel/generated/openapi.json`` — the API schema for ``/api/node-types``
   and each capability's parameter schema.
3. ``backend/capabilities_kernel/generated/ai_tools.json`` — the AI-facing vocabulary (summary,
   steps, examples, failures); P4/P6 turn it into skills/tools.
4. ``backend/capabilities_kernel/generated/capability-schema.json`` — the browser form catalogue.
5. ``backend/static/js/node-types-fallback.js`` — the same catalogue as a script a cold page loads
   before ``node-types.js`` answers, so the canvas never keeps a hand-written copy of the types.
6. ``docs/capabilities/index.md`` — the human index of every capability.

Rendering is deterministic: manifests in registry order, JSON without sorting by key (the dataclass
field order is the contract), LF newlines on every platform so a Windows checkout and a Linux CI
runner compare the same bytes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from capabilities_kernel import knowledge, registry
from capabilities_kernel.manifest import KINDS
from services.charts.registry import chart_profiles

ROOT = Path(__file__).resolve().parents[2]
GENERATED = 'backend/capabilities_kernel/generated'

#: What a capability's generated test-matrix row enumerates. The gate reads the matrix; ``doctor``
#: computes the same dimensions live.
MATRIX_CHECKS = (
    'structure',
    'executor',
    'port_hooks',
    'validators',
    'preflight',
    'postcheck',
    'docs',
    'contracts',
    'title_keys',
)

#: Artifact path → renderer name. A new artifact is one entry plus one function.
OUTPUTS = {
    f'{GENERATED}/catalog.json': 'catalog',
    f'{GENERATED}/openapi.json': 'openapi',
    f'{GENERATED}/ai_tools.json': 'ai_tools',
    f'{GENERATED}/capability-schema.json': 'frontend_schema',
    'backend/static/js/node-types-fallback.js': 'frontend_catalogue',
    'docs/capabilities/index.md': 'docs_index',
}


def _manifests():
    found = []
    for kind in KINDS:
        found.extend(registry.manifests(kind))
    return found


def _json(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + '\n'


def _catalog_payload() -> dict:
    capabilities = []
    matrix = []
    for manifest in _manifests():
        capabilities.append(
            {
                'kind': manifest.identity.kind,
                'id': manifest.identity.id,
                'digest': manifest.digest(),
                'manifest': manifest.as_dict(),
            },
        )
        matrix.append(
            {
                'kind': manifest.identity.kind,
                'id': manifest.identity.id,
                'checks': list(MATRIX_CHECKS),
                'contract_tests': list(manifest.tests.contracts),
                'docs': manifest.docs.page,
            },
        )
    return {
        'api_version': registry.API_VERSION,
        'generated_by': 'tools/gen_capabilities.py',
        'capabilities': capabilities,
        'matrix': matrix,
    }


def _node_schema(manifest) -> dict:
    properties = {spec.name: spec.schema() for spec in manifest.params}
    required = [spec.name for spec in manifest.params if spec.required]
    out: dict = {'type': 'object', 'properties': properties, 'additionalProperties': True}
    if required:
        out['required'] = required
    return out


def _openapi_payload() -> dict:
    schemas = {
        'NodeType': {
            'type': 'object',
            'required': ['type', 'labelKey', 'category', 'rows', 'quiet'],
            'properties': {
                'type': {'type': 'string'},
                'labelKey': {'type': 'string'},
                'category': {'type': 'string'},
                'rows': {'type': 'string', 'enum': ['table', 'pdf', 'none']},
                'quiet': {'type': 'boolean'},
                'defaults': {'type': ['object', 'null'], 'additionalProperties': True},
                'defaultsFrom': {'type': 'string'},
            },
        },
        'ChartField': {
            'type': 'object',
            'required': ['name', 'role', 'required'],
            'properties': {
                'name': {'type': 'string'},
                'role': {
                    'type': 'string',
                    'enum': [
                        'category',
                        'category2',
                        'value',
                        'coordinate',
                        'source',
                        'target',
                        'text',
                        'geo',
                        'list',
                        'label',
                        'column',
                    ],
                },
                'required': {'type': 'boolean'},
                'labelKey': {'type': 'string'},
                'placeholder': {'type': 'string'},
                'placeholderKey': {'type': 'string'},
                'hintKey': {'type': 'string'},
                'control': {'type': 'string'},
            },
        },
        'ChartProfile': {
            'type': 'object',
            'required': ['key', 'family', 'echartsOnly', 'latexBuildable', 'fields'],
            'properties': {
                'key': {'type': 'string'},
                'family': {'type': 'string', 'enum': ['console', 'biblio']},
                'echartsOnly': {'type': 'boolean'},
                'latexBuildable': {'type': 'boolean'},
                'tokenize': {'type': 'boolean'},
                'labelKey': {'type': 'string'},
                'hintKey': {'type': 'string'},
                'defaults': {'type': 'object', 'additionalProperties': True},
                'fields': {'type': 'array', 'items': {'$ref': '#/components/schemas/ChartField'}},
                'controls': {'type': 'array', 'items': {'type': 'string'}},
            },
        },
        'NodeTypesResponse': {
            'type': 'object',
            'required': ['ok', 'types', 'charts'],
            'properties': {
                'ok': {'type': 'boolean'},
                'types': {'type': 'array', 'items': {'$ref': '#/components/schemas/NodeType'}},
                'charts': {'type': 'array', 'items': {'$ref': '#/components/schemas/ChartProfile'}},
            },
        },
    }
    for manifest in _manifests():
        if manifest.identity.kind in ('node', 'operator'):
            schemas[f'NodeParams.{manifest.identity.id}'] = _node_schema(manifest)
    return {
        'openapi': '3.1.0',
        'info': {
            'title': '采析绘 capabilities',
            'version': str(registry.API_VERSION),
            'description': 'Generated from capabilities_kernel manifests by tools/gen_capabilities.py.',
        },
        'paths': {
            '/api/node-types': {
                'get': {
                    'summary': 'Every node type, its word, shape and seed parameters',
                    'responses': {
                        '200': {
                            'description': 'The catalogue the canvas reads',
                            'content': {
                                'application/json': {
                                    'schema': {'$ref': '#/components/schemas/NodeTypesResponse'},
                                },
                            },
                        },
                    },
                },
            },
        },
        'components': {'schemas': schemas},
    }


def _ai_payload() -> dict:
    tools = []
    for manifest in _manifests():
        if not (manifest.ai.summary or manifest.ai.steps or manifest.ai.examples):
            continue
        tools.append(
            {
                'capability': f'{manifest.identity.kind}:{manifest.identity.id}',
                'tool': manifest.ai.tool,
                'summary': manifest.ai.summary,
                'steps': list(manifest.ai.steps),
                'examples': list(manifest.ai.examples),
                'failures': list(manifest.ai.failures),
                'params': _node_schema(manifest) if manifest.identity.kind in ('node', 'operator') else {},
                'emit_columns': manifest.ports.emit_columns,
                'read_columns': manifest.ports.read_columns,
            },
        )
    return {
        'api_version': registry.API_VERSION,
        'generated_by': 'tools/gen_capabilities.py',
        'tools': tools,
    }


def _frontend_nodes() -> list[dict]:
    """One entry per node manifest — the projection the API and the cold-page script share."""
    return registry.node_schema_entries()


def _frontend_charts() -> list[dict]:
    """The chart registry's browser projection — the visualize node's parameter domain.

    The settings panel draws one box per declared field, so which chart reads x/y/value and which
    box is required is served, not hand-kept in JavaScript beside the Python table.
    """
    return chart_profiles()


def _frontend_schema() -> str:
    """The form catalogue as data. P2 moves it into a page module when a page actually loads it.

    It deliberately does not live under ``static/js`` yet: the frontend gate refuses a JS module no
    page loads, and a generated module nobody reads would be dead code with a freshness test.
    """
    return _json({'apiVersion': registry.API_VERSION, 'nodes': _frontend_nodes(), 'charts': _frontend_charts()})


def _frontend_catalogue_js() -> str:
    """The same node catalogue as a script: the cold-page fallback the page loads before the fetch.

    A generated file beats a hand-written list in ``canvas.js``: the fallback and the served answer
    cannot drift, and adding a node type edits no frontend file.
    """
    payload = json.dumps(
        {'ok': True, 'types': _frontend_nodes(), 'charts': _frontend_charts()},
        ensure_ascii=False,
        indent=2,
    )
    return (
        '/* Generated by tools/gen_capabilities.py from backend/capabilities_kernel/ — do not edit. */\n'
        f'window.NODE_TYPE_CATALOGUE = {payload};\n'
    )


def _operator_page(manifest) -> str:
    """One operator's documentation page: the contract, the shape, and where its skill is."""
    ident = manifest.identity
    reads = manifest.reads
    writes = manifest.writes
    lines = [
        f'# {ident.id}（{ident.category}）',
        '',
        '> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。',
        f'> 技能正文：`{manifest.docs.skill}`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。',
        '',
        manifest.ai.summary or ident.description,
        '',
        '## 何时使用',
        '',
        ident.when_to_use or '（未声明）',
        '',
    ]
    if manifest.ai.when_not_to_use:
        lines += ['不要用于：', '']
        lines += [f'- {item}' for item in manifest.ai.when_not_to_use]
        lines.append('')
    lines += ['## 参数', '', '| 参数 | 类型 | 默认 | 必填 | 可选值 |', '|---|---|---|---|---|']
    for spec in manifest.params:
        allowed = ', '.join(str(value) for value in spec.enum) if spec.enum else ''
        default = '' if spec.default in ('', None) else f'`{spec.default}`'
        lines.append(f'| `{spec.name}` | {spec.type} | {default} | {"是" if spec.required else ""} | {allowed} |')
    lines += ['', '## 读取的列', '']
    facts = []
    if reads.one:
        facts.append('必须存在的一列：' + '、'.join(f'`{name}`' for name in reads.one))
    if reads.some:
        facts.append('可选列子集（留空=全部）：' + '、'.join(f'`{name}`' for name in reads.some))
    if reads.nonblank:
        facts.append('不可为空：' + '、'.join(f'`{name}`' for name in reads.nonblank))
    if reads.mapping:
        facts.append('需要 `mapping`（旧列 → 新列）。')
    if reads.two_table_keys:
        facts.append('两张表的连接键：' + '、'.join(f'`{name}`' for name in reads.two_table_keys))
    lines += [f'- {item}' for item in facts] or ['- 不读取具名列。']
    lines += ['', '## 输出形状', '']
    mode = writes.mode
    if mode == 'replace':
        lines.append('新表，列固定：' + '、'.join(f'`{column}`' for column in writes.columns) + '。')
    elif mode == 'add':
        lines.append('保留上游列，追加清单声明的列。')
    elif mode == 'dynamic':
        lines.append('新表，列名来自本步参数。')
    elif mode == 'select':
        lines.append('只保留指定的列，顺序即参数顺序。')
    elif mode == 'unknown':
        lines.append('输出列依赖数据，需从运行结果读取。')
    else:
        lines.append('行被过滤或重排，列不变。')
    lines.append('')
    if manifest.needs_llm:
        lines += ['## 模型', '', '本步需要运行中的 LLM；没有可用模型时按名拒绝，不会静默换模型。', '']
    lines += ['## 契约测试', '']
    lines += [f'- `{path}`' for path in manifest.tests.contracts]
    return '\n'.join(lines).rstrip() + '\n'


def _operator_docs() -> dict[Path, str]:
    """One documentation page per operator, beside its generated skill page."""
    return {
        ROOT / manifest.docs.page: _operator_page(manifest)
        for manifest in registry.manifests('operator')
        if manifest.docs.page
    }


def _chart_page(manifest) -> str:
    """One chart type's documentation page: its fields, its shape and where its skill is."""
    ident = manifest.identity
    lines = [
        f'# {ident.id}（{manifest.family}）',
        '',
        '> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/charts/` 的清单生成，请勿手改。',
        f'> 技能正文：`{manifest.docs.skill}`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。',
        '',
        manifest.ai.summary or ident.description,
        '',
        '## 何时使用',
        '',
        ident.when_to_use or '（未声明）',
        '',
    ]
    if manifest.ai.when_not_to_use:
        lines += ['不要用于：', '']
        lines += [f'- {item}' for item in manifest.ai.when_not_to_use]
        lines.append('')
    lines += ['## 字段', '', '| 字段 | 角色 | 必填 | 默认列 | 控件 |', '|---|---|---|---|---|']
    defaults = dict(manifest.defaults)
    for field in manifest.fields:
        default = f'`{defaults[field.name]}`' if field.name in defaults else ''
        required = '是' if field.required else (f'当 {field.required_when} 已填' if field.required_when else '')
        lines.append(f'| `{field.name}` | {field.role} | {required} | {default} | {field.control} |')
    if not manifest.fields:
        lines.append('| — | — | — | — | — |')
    lines += ['', '## 输出形状', '', 'ECharts/matplotlib 图（可另出 LaTeX 图/表），不是一张数据表。', '']
    lines += ['## 引擎', '']
    lines.append('- 仅 ECharts' if manifest.echarts_only else '- ECharts 与 matplotlib 都能画')
    lines.append('- 有 LaTeX 孪生图/表' if manifest.latex_buildable else '- 没有 LaTeX 孪生图（只出现在一致性矩阵）')
    if manifest.reads:
        lines.append('- 文献列：' + '、'.join(f'`{column}`' for column in manifest.reads))
    lines.append('')
    lines += ['## 契约测试', '']
    lines += [f'- `{path}`' for path in manifest.tests.contracts]
    return '\n'.join(lines).rstrip() + '\n'


def _chart_docs() -> dict[Path, str]:
    """One documentation page per chart type, beside its generated skill page."""
    return {
        ROOT / manifest.docs.page: _chart_page(manifest)
        for manifest in registry.manifests('chart')
        if manifest.docs.page
    }


def _docs_index() -> str:
    lines = [
        '# 能力目录（自动生成）',
        '',
        '> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/` 的清单生成，请勿手改。',
        '> 机器可读版本：`backend/capabilities_kernel/generated/catalog.json`。',
        '',
    ]
    for kind in KINDS:
        manifests = [manifest for manifest in _manifests() if manifest.identity.kind == kind]
        if not manifests:
            continue
        lines += [
            f'## {kind}',
            '',
            '| id | 标题键 | 分组 | 文档 | 技能 | 契约测试 | digest |',
            '|---|---|---|---|---|---|---|',
        ]
        for manifest in manifests:
            page = manifest.docs.page
            link = f'[{page}](../{page.removeprefix("docs/")})' if page else ''
            skill_link = f'[技能](skills/{kind}s/{manifest.identity.id}.md)'
            contracts = '<br>'.join(f'`{path}`' for path in manifest.tests.contracts) or ''
            digest = manifest.digest()[:12]
            ident = manifest.identity
            lines.append(
                f'| {ident.id} | `{ident.title_key}` | {ident.category} | {link} | {skill_link} | '
                f'{contracts} | `{digest}` |',
            )
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


def _skill_docs() -> dict[Path, str]:
    """One page per capability skill plus its catalogue.

    The page is rendered by the same ``knowledge.render`` the ``skill_load`` tool calls, so the
    published body and the body a model reads are one derivation. A reader can also find them
    through ``docs_search`` because ``docs/capabilities/`` is a document root.
    """
    pages: dict[Path, str] = {}
    index = [
        '# 能力技能目录（自动生成）',
        '',
        '> 由 `tools/gen_capabilities.py` 从清单的第七段生成，请勿手改。',
        '> 运行时由 `capabilities_kernel.knowledge` 直接渲染同一份清单，页面不会比接口旧。',
        '',
        '| 技能 | 分组 | 一句话 | 何时使用 |',
        '|---|---|---|---|',
    ]
    for manifest in _manifests():
        ident = manifest.identity
        address = knowledge.skill_id(manifest)
        relative = manifest.docs.skill
        pages[ROOT / relative] = knowledge.render(manifest)
        index.append(
            f'| [{address}]({ident.kind}s/{ident.id}.md) | {ident.category} | '
            f'{manifest.ai.summary or ident.description} | {ident.when_to_use} |',
        )
    index.append('')
    pages[ROOT / 'docs/capabilities/skills/index.md'] = '\n'.join(index)
    return pages


def render() -> dict[Path, str]:
    """Every artifact's path and exact bytes, rendered from the current manifests."""
    renderers = {
        'catalog': lambda: _json(_catalog_payload()),
        'openapi': lambda: _json(_openapi_payload()),
        'ai_tools': lambda: _json(_ai_payload()),
        'frontend_schema': _frontend_schema,
        'frontend_catalogue': _frontend_catalogue_js,
        'docs_index': _docs_index,
    }
    return (
        {ROOT / relative: renderers[name]() for relative, name in OUTPUTS.items()}
        | _skill_docs()
        | _operator_docs()
        | _chart_docs()
    )


def write() -> list[Path]:
    written = []
    for path, text in render().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8', newline='\n')
        written.append(path)
    return written


def check() -> list[str]:
    """Artifacts whose committed bytes differ from the manifests; empty means fresh."""
    stale = []
    for path, text in render().items():
        relative = path.relative_to(ROOT).as_posix()
        if not path.is_file():
            stale.append(f'{relative}: missing')
        elif path.read_bytes() != text.encode('utf-8'):
            stale.append(f'{relative}: stale')
    return stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Render the capability artifacts from their manifests.')
    parser.add_argument('--check', action='store_true', help='compare instead of write; exit 1 when stale')
    args = parser.parse_args(argv)
    if args.check:
        stale = check()
        for line in stale:
            print(line)
        return 1 if stale else 0
    for path in write():
        print(f'wrote {path.relative_to(ROOT).as_posix()}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
