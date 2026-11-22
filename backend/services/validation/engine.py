"""The declarative rule evaluator (P1: static rules only).

``static_problems`` answers what a manifest can refuse WITHOUT touching data or a live crawl. Each
problem is data — ``{code, message_key, severity, param, context}`` — never a sentence: the console
and the canvas badge word it from ``i18n``, so the same rule cannot say two different things in two
surfaces. Preflight (a sample of upstream rows), ``fix`` suggestions and data-contract checks join
this engine in P3; they will be additional rule kinds, not additional callers.
"""

from __future__ import annotations

from nodes.context import node_params


def _blank(value) -> bool:
    return not str(value if value is not None else '').strip()


def _problem(rule, *, param: str = '', context: dict | None = None) -> dict:
    return {
        'code': rule.code,
        'message_key': rule.message_key,
        'severity': rule.severity,
        'param': param or rule.param,
        'context': dict(context or {}),
    }


def static_problems(manifest, node: dict, *, has_input: bool = True) -> list[dict]:
    """Every declared static problem for *node*, in manifest order.

    Missing parameters are judged against the manifest's own defaults first: a box the schema fills
    is not missing to the user. ``has_input`` answers ``upstream_required``; the caller owns what
    "has input" means (the engine excludes a name node's metadata-only wire).
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
        elif rule.kind == 'upstream_required' and not has_input:
            found.append(_problem(rule))
    return found
