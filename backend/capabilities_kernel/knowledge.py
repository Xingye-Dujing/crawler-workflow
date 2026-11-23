"""The capability skill: one L1 catalogue, one L2 body, both derived from the manifest.

A skill used to be a long document beside the code, so its parameter table drifted from the
manifest the first time a default changed. Here the manifest is the only declaration: ``catalog()``
projects the words a router selects on (~100 tokens per skill), and ``render()`` builds the
seven-section body with the parameter table re-read from ``manifest.params``. The AI tools
(``skill_catalog``/``skill_load``) and the generated documentation page call these two functions,
so a loaded skill and a published page cannot disagree.

The module imports only the kernel and the standard library: the AI page loads it on the context
path, and a capability skill must not drag pandas or Flask there.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable

from capabilities_kernel import registry
from capabilities_kernel.manifest import KINDS, Manifest

#: The tools a skill tells the model to act with, by kind. A capability owns its skill, not a tool:
#: the node is reached through the workflow tools every turn already has. This is generic kernel
#: vocabulary, not a per-capability fact.
KIND_TOOLS = {
    'node': ('workflow_schema', 'apply_workflow', 'workflow_validate'),
}

_WORD = re.compile(r'[A-Za-z0-9_]{3,}')
_CJK = re.compile(r'[\u3400-\u9fff]{2,}')


def skill_id(manifest: Manifest) -> str:
    """The stable address of a capability skill: ``<kind>.<id>``."""
    return f'{manifest.identity.kind}.{manifest.identity.id}'


def _terms(query: str) -> set[str]:
    terms = {word.lower() for word in _WORD.findall(query or '')}
    for run in _CJK.findall(query or ''):
        terms.update(run[index : index + 2] for index in range(len(run) - 1))
    return terms


def _haystack(manifest: Manifest) -> str:
    identity = manifest.identity
    parts = [
        skill_id(manifest),
        identity.category,
        identity.description,
        identity.when_to_use,
        manifest.ai.summary,
        *manifest.ai.when_not_to_use,
    ]
    return '\n'.join(part for part in parts if part).lower()


def _score(manifest: Manifest, terms: set[str]) -> int:
    haystack = _haystack(manifest)
    return sum(haystack.count(term) for term in terms)


def l1(manifest: Manifest) -> dict:
    """The level-1 record: what a router or the project context needs, nothing more."""
    identity = manifest.identity
    return {
        'id': skill_id(manifest),
        'kind': identity.kind,
        'capability': identity.id,
        'category': identity.category,
        'title_key': identity.title_key,
        'summary': manifest.ai.summary or identity.description,
        'when_to_use': identity.when_to_use,
        'when_not_to_use': list(manifest.ai.when_not_to_use),
        'docs': manifest.docs.page,
    }


def l2(manifest: Manifest) -> dict:
    """The level-2 record: the seven sections plus the fresh parameter projection."""
    return {
        'prerequisites': list(manifest.ai.prerequisites),
        'steps': list(manifest.ai.steps),
        'examples': list(manifest.ai.examples),
        'template': manifest.ai.template,
        'failures': list(manifest.ai.failures),
        'acceptance': list(manifest.ai.acceptance),
        'params': [
            {
                'name': spec.name,
                'type': spec.type,
                'default': spec.default,
                'required': spec.required,
                'enum': list(spec.enum),
                'minimum': spec.minimum,
                'maximum': spec.maximum,
                'label_key': spec.label_key,
            }
            for spec in manifest.params
        ],
        'ports': {
            'rows': manifest.ports.rows,
            'inputs': manifest.ports.inputs,
            'emit_columns': manifest.ports.emit_columns,
            'read_columns': manifest.ports.read_columns,
        },
        'tools': list(KIND_TOOLS.get(manifest.identity.kind, ())),
        'docs': manifest.docs.page,
        'contracts': list(manifest.tests.contracts),
    }


def find(identifier: str, kind: str = '') -> Manifest | None:
    """Resolve ``<kind>.<id>`` (or a bare id when *kind* is given); ``None`` when it does not exist."""
    text = str(identifier or '').strip()
    kinds = (kind,) if kind else KINDS
    for candidate in kinds:
        for manifest in registry.manifests(candidate):
            if text == skill_id(manifest) or text == manifest.identity.id:
                return manifest
    return None


def catalog(kind: str = '', query: str = '', limit: int = 0) -> list[dict]:
    """The L1 catalogue, filtered by kind and scored by *query*; an unknown kind raises ``ValueError``.

    Scoring is the same cheap keyword overlap ``docs_search`` uses, so the workspace works with no
    embedding model. A query that matches nothing returns an empty list; the caller says so.
    """
    if kind and kind not in KINDS:
        raise ValueError(f'unknown capability kind {kind!r}; known kinds: {", ".join(KINDS)}')
    kinds = (kind,) if kind else KINDS
    terms = _terms(query)
    rows: list[tuple[int, dict]] = []
    for candidate in kinds:
        for manifest in registry.manifests(candidate):
            score = _score(manifest, terms) if terms else 1
            if score:
                rows.append((score, l1(manifest)))
    rows.sort(key=lambda item: (-item[0], item[1]['id']))
    found = [row for _score_value, row in rows]
    if limit and limit > 0:
        return found[:limit]
    return found


def prompt_lines(limit: int = 40) -> list[str]:
    """One line per skill for the project context: the L1 catalogue, bounded and stable."""
    lines = []
    for kind in KINDS:
        for manifest in registry.manifests(kind)[:limit]:
            lines.append(f'- {skill_id(manifest)}: {manifest.ai.summary or manifest.identity.description}')
    return lines


def _bullets(items: Iterable[str]) -> list[str]:
    return [f'- {item}' for item in items] or ['- (none declared)']


def _numbered(items: Iterable[str]) -> list[str]:
    return [f'{index}. {item}' for index, item in enumerate(items, start=1)] or ['1. (none declared)']


def _params_table(manifest: Manifest) -> list[str]:
    if not manifest.params:
        return ['This capability takes no declared parameters.']
    lines = ['| name | type | default | required | allowed |', '|---|---|---|---|---|']
    for spec in manifest.params:
        allowed = ', '.join(str(value) for value in spec.enum) if spec.enum else ''
        default = '' if spec.default in ('', None) else f'`{spec.default}`'
        lines.append(f'| `{spec.name}` | {spec.type} | {default} | {"yes" if spec.required else ""} | {allowed} |')
    return lines


def render(manifest: Manifest, title: str = '') -> str:
    """The seven-section skill body, with the parameter table read from the manifest now.

    *title* is the localized display word the caller supplies; the kernel keeps no translation
    table. Every heading is present even when a section is empty, so a reader (or a gate) sees a
    missing section instead of a body that silently omits it.
    """
    identity = manifest.identity
    heading = f'# {skill_id(manifest)}'
    if title:
        heading += f' — {title}'
    tools = KIND_TOOLS.get(identity.kind, ())
    lines = [heading, '', manifest.ai.summary or identity.description, '']
    lines += ['## When to use', '', identity.when_to_use or '(not declared)', '']
    if manifest.ai.when_not_to_use:
        lines += ['Do not use it when:', '']
        lines += _bullets(manifest.ai.when_not_to_use)
        lines.append('')
    lines += ['## Prerequisites', '']
    lines += _bullets(manifest.ai.prerequisites)
    lines += ['', '## Steps', '']
    lines += _numbered(manifest.ai.steps)
    lines += ['', '## Examples', '']
    for example in manifest.ai.examples:
        lines += ['```json', json.dumps(example, ensure_ascii=False, indent=2), '```', '']
    if manifest.ai.template:
        lines += [
            '## Template JSON',
            '',
            '```json',
            json.dumps(manifest.ai.template, ensure_ascii=False, indent=2),
            '```',
            '',
        ]
    lines += ['## Parameters', '']
    lines += _params_table(manifest)
    lines += ['', '## Failure modes', '']
    lines += _bullets(manifest.ai.failures)
    lines += ['', '## Acceptance', '']
    lines += _bullets(manifest.ai.acceptance)
    lines += ['', '## Reach it', '']
    if tools:
        lines.append('Tools: ' + ', '.join(f'`{tool}`' for tool in tools))
    if manifest.docs.page:
        lines.append(f'Documentation: `{manifest.docs.page}`')
    if manifest.docs.skill:
        lines.append(f'Skill page: `{manifest.docs.skill}`')
    if manifest.tests.contracts:
        lines.append('Contract tests: ' + ', '.join(f'`{path}`' for path in manifest.tests.contracts))
    return '\n'.join(lines).rstrip() + '\n'
