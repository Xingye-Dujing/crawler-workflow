"""The declarative rule evaluator and the node-specific validator seam (P1/P2).

``static_problems`` answers what a manifest can refuse WITHOUT touching data: a required parameter,
an enum, an input/output shape. A rule cannot express every check — a save node's PDF parents, a
compile node's LaTeX sources — so a manifest may also name ``module:function`` validators that live
with the capability. Both halves return data (``code``/``message_key``/``context``), never a
sentence: the console and the canvas badge word it from ``i18n``.

A validator that raises or returns a malformed problem becomes a named
``engine.validator_failed`` problem instead of a 500 from ``/api/workflow/diagnostics``: the plugin
bug stays visible, and the canvas keeps its other badges. A problem may carry a mechanical ``fix``
(``{'set': {param: value}}``) that the settings panel applies in one click; preflight (a sample of
upstream rows) and data-contract checks build on the same entry shape.
"""

from __future__ import annotations

from dataclasses import dataclass

from capabilities_kernel import registry as kernel_registry
from nodes.context import node_params
from nodes.labels import node_label


@dataclass(frozen=True)
class ValidationContext:
    """The graph facts a node-specific validator may read — never the executor's run context."""

    node_id: str
    label: str
    nodes: dict
    connections: list
    data_inputs: frozenset[str]

    def node(self, node_id: str) -> dict:
        return self.nodes.get(str(node_id)) or {}

    def parent_ids(self) -> list[str]:
        return [str(conn.get('from')) for conn in self.connections if str(conn.get('to')) == self.node_id]

    def label_of(self, node_id: str) -> str:
        return node_label(self.node(node_id), str(node_id))

    def has_data_input(self) -> bool:
        return self.node_id in self.data_inputs

    def has_incoming(self) -> bool:
        return any(str(conn.get('to')) == self.node_id for conn in self.connections)

    def has_output(self) -> bool:
        return any(str(conn.get('from')) == self.node_id for conn in self.connections)


def _blank(value) -> bool:
    return not str(value if value is not None else '').strip()


def _problem(rule, *, param: str = '', context: dict | None = None) -> dict:
    found = {
        'code': rule.code,
        'message_key': rule.message_key,
        'severity': rule.severity,
        'param': param or rule.param,
        'context': dict(context or {}),
    }
    return found


def _default_fix(manifest, rule) -> dict | None:
    """A declared default is the fix for an off-list value — never a guessed option.

    Only a rule whose parameter has a non-blank default offers one: resetting a select to the
    value the manifest itself starts a node with is mechanical, while inventing an option the
    table does not name is exactly the guess this project refuses.
    """
    if rule.kind != 'enum_param':
        return None
    spec = manifest.param(rule.param)
    default = getattr(spec, 'default', None)
    if _blank(default):
        return None
    return {'set': {rule.param: default}}


def _failed(reference: str, reason: Exception) -> dict:
    return {
        'code': 'engine.validator_failed',
        'message_key': 'engine.validator_failed',
        'severity': 'error',
        'param': '',
        'context': {'ref': reference, 'err': str(reason)[:300]},
        'fix': None,
    }


def _normalize(item, reference: str) -> tuple[dict | None, str]:
    if not isinstance(item, dict):
        return None, f'{reference} returned {type(item).__name__}, not an object'
    code = str(item.get('code') or '')
    message_key = str(item.get('message_key') or '')
    severity = str(item.get('severity') or 'error')
    if not code or not message_key:
        return None, f'{reference} returned a problem without code/message_key'
    if severity not in ('error', 'warning'):
        return None, f'{reference} returned severity {severity!r}'
    context = item.get('context') or {}
    if not isinstance(context, dict):
        return None, f'{reference} returned a non-object context'
    fix, reason = _normalize_fix(item.get('fix'), reference)
    if reason:
        return None, reason
    return {
        'code': code,
        'message_key': message_key,
        'severity': severity,
        'param': str(item.get('param') or ''),
        'context': dict(context),
        'fix': fix,
    }, ''


def _normalize_fix(fix, reference: str) -> tuple[dict | None, str]:
    """``{'set': {param: value}}`` or nothing; a malformed fix is a named plugin failure.

    A fix is a mechanical edit the settings panel may apply in one click. It may only set TOP-LEVEL
    node parameters (the panel's ``updateParam`` writes those), and it must name at least one: a
    button that changes nothing is worse than no button.
    """
    if fix is None:
        return None, ''
    if not isinstance(fix, dict):
        return None, f'{reference} returned a {type(fix).__name__} fix, not an object'
    changes = fix.get('set')
    if not isinstance(changes, dict) or not changes:
        return None, f'{reference} returned a fix without a non-empty "set"'
    if not all(isinstance(key, str) and key.strip() for key in changes):
        return None, f'{reference} returned a fix whose parameter name is not a non-empty string'
    return {'set': dict(changes)}, ''


def static_problems(
    manifest,
    node: dict,
    *,
    has_input: bool = True,
    has_incoming: bool = False,
    has_output: bool = True,
) -> list[dict]:
    """Every declared static problem for *node*, in manifest order.

    Missing parameters are judged against the manifest's own defaults first: a box the schema fills
    is not missing to the user. ``has_input`` is a DATA input (a name node's metadata-only wire is
    not one); ``has_incoming`` is any wire, for the name node's "must sit at the head" rule.
    """
    params = node_params(node)
    effective = manifest.defaults()
    effective.update(params)
    found: list[dict] = []
    for rule in manifest.rules:
        if rule.kind == 'required_param':
            if _blank(effective.get(rule.param)):
                found.append(_problem(rule))
        elif rule.kind == 'enum_param':
            value = effective.get(rule.param)
            if _blank(value):
                continue  # a required rule owns the blank case; an optional blank is not a bad option
            spec = manifest.param(rule.param)
            allowed = tuple(spec.enum) if spec is not None else ()
            if value not in allowed:
                found.append(
                    _problem(rule, context={'value': value, 'allowed': ', '.join(str(item) for item in allowed)}),
                )
                fix = _default_fix(manifest, rule)
                if fix:
                    found[-1]['fix'] = fix
        elif rule.kind in ('upstream_required', 'no_input', 'requires_output'):
            triggered = (
                (rule.kind == 'upstream_required' and not has_input)
                or (rule.kind == 'no_input' and has_incoming)
                or (rule.kind == 'requires_output' and not has_output)
            )
            if triggered:
                found.append(_problem(rule))
    return found


def validation_problems(manifest, node: dict, context: ValidationContext) -> list[dict]:
    """Static rules plus every declared validator, each failure named rather than raised."""
    found = static_problems(
        manifest,
        node,
        has_input=context.has_data_input(),
        has_incoming=context.has_incoming(),
        has_output=context.has_output(),
    )
    for reference in manifest.validators:
        try:
            handler = kernel_registry.resolve(reference)
            produced = handler(node, context)
        except Exception as exc:  # a plugin bug is reported, not allowed to 500 diagnostics
            found.append(_failed(reference, exc))
            continue
        if not isinstance(produced, (list, tuple)):
            found.append(_failed(reference, ValueError(f'returned {type(produced).__name__}, not a list')))
            continue
        for item in produced:
            normalized, reason = _normalize(item, reference)
            if normalized is None:
                found.append(_failed(reference, ValueError(reason)))
            else:
                found.append(normalized)
    return found
