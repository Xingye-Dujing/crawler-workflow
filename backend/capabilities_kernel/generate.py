"""Generate the derived capability artifacts from the manifests.

One manifest feeds several surfaces, and a surface that is generated once and never checked is
worse than a hand-written one: it looks authoritative after the declaration moved. So ``check()``
re-renders every artifact in memory and compares bytes; the completeness gate runs it, and
``tools/gen_capabilities.py --check`` is the same answer from the command line.

The five artifacts (P1):

1. ``backend/capabilities_kernel/generated/catalog.json`` — the machine catalogue **and** the
   capability × check test matrix.
2. ``backend/capabilities_kernel/generated/openapi.json`` — the API schema for ``/api/node-types``
   and each capability's parameter schema.
3. ``backend/capabilities_kernel/generated/ai_tools.json`` — the AI-facing vocabulary (summary,
   steps, examples, failures); P4/P6 turn it into skills/tools.
4. ``backend/static/js/capability-schema.generated.js`` — the browser form catalogue (P2 renderer).
5. ``docs/capabilities/index.md`` — the human index of every capability.

Rendering is deterministic: manifests in registry order, JSON without sorting by key (the dataclass
field order is the contract), LF newlines on every platform so a Windows checkout and a Linux CI
runner compare the same bytes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from capabilities_kernel import registry
from capabilities_kernel.manifest import KINDS

ROOT = Path(__file__).resolve().parents[2]
GENERATED = 'backend/capabilities_kernel/generated'

#: What a capability's generated test-matrix row enumerates. The gate reads the matrix; ``doctor``
#: computes the same dimensions live.
MATRIX_CHECKS = ('structure', 'executor', 'port_hooks', 'docs', 'contracts', 'title_keys')

#: Artifact path → renderer name. A new artifact is one entry plus one function.
OUTPUTS = {
    f'{GENERATED}/catalog.json': 'catalog',
    f'{GENERATED}/openapi.json': 'openapi',
    f'{GENERATED}/ai_tools.json': 'ai_tools',
    'backend/static/js/capability-schema.generated.js': 'frontend_schema',
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
        'NodeTypesResponse': {
            'type': 'object',
            'required': ['ok', 'types'],
            'properties': {
                'ok': {'type': 'boolean'},
                'types': {'type': 'array', 'items': {'$ref': '#/components/schemas/NodeType'}},
            },
        },
    }
    for manifest in _manifests():
        if manifest.identity.kind == 'node':
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
                'params': _node_schema(manifest) if manifest.identity.kind == 'node' else {},
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
    nodes = []
    for manifest in _manifests():
        if manifest.identity.kind != 'node':
            continue
        nodes.append(
            {
                'type': manifest.identity.id,
                'labelKey': manifest.identity.title_key,
                'category': manifest.identity.category,
                'order': manifest.identity.order,
                'params': [
                    {
                        'name': spec.name,
                        'type': spec.type,
                        'default': spec.default,
                        'required': spec.required,
                        'enum': list(spec.enum),
                        'minimum': spec.minimum,
                        'maximum': spec.maximum,
                        'widget': spec.widget,
                        'placeholder': spec.placeholder,
                    }
                    for spec in manifest.params
                ],
                'rules': [
                    {
                        'kind': rule.kind,
                        'code': rule.code,
                        'messageKey': rule.message_key,
                        'param': rule.param,
                        'severity': rule.severity,
                    }
                    for rule in manifest.rules
                ],
                'ports': {
                    'rows': manifest.ports.rows,
                    'inputs': manifest.ports.inputs,
                    'emitColumns': manifest.ports.emit_columns,
                    'readColumns': manifest.ports.read_columns,
                },
                'ui': {'form': manifest.ui.form, 'customRenderer': manifest.ui.custom_renderer},
            },
        )
    return nodes


def _frontend_schema() -> str:
    body = _json({'apiVersion': registry.API_VERSION, 'nodes': _frontend_nodes()})
    return (
        '/* Generated by tools/gen_capabilities.py from capabilities_kernel manifests.\n'
        '   Do not edit by hand: run `python tools/gen_capabilities.py` and commit the result.\n'
        '   P2 reads this for the schema form; until then the page fetches /api/node-types. */\n'
        f'window.CapabilitySchema = {body};\n'
    )


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
        lines += [f'## {kind}', '', '| id | 标题键 | 分组 | 文档 | 契约测试 | digest |', '|---|---|---|---|---|---|']
        for manifest in manifests:
            page = manifest.docs.page
            link = f'[{page}](../{page.removeprefix("docs/")})' if page else ''
            contracts = '<br>'.join(f'`{path}`' for path in manifest.tests.contracts) or ''
            digest = manifest.digest()[:12]
            ident = manifest.identity
            lines.append(f'| {ident.id} | `{ident.title_key}` | {ident.category} | {link} | {contracts} | `{digest}` |')
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


def render() -> dict[Path, str]:
    """Every artifact's path and exact bytes, rendered from the current manifests."""
    rendered = {
        f'{GENERATED}/catalog.json': _json(_catalog_payload()),
        f'{GENERATED}/openapi.json': _json(_openapi_payload()),
        f'{GENERATED}/ai_tools.json': _json(_ai_payload()),
        'backend/static/js/capability-schema.generated.js': _frontend_schema(),
        'docs/capabilities/index.md': _docs_index(),
    }
    return {ROOT / relative: text for relative, text in rendered.items()}


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
