"""A workflow artifact must be LEGAL before it is offered as something the canvas can load.

The auto skill lets the model propose a workflow. A model that writes display words as node types
(``"type": "分析"`` / ``"可视化"``) or a sentence where ``params`` belongs produced a canvas of
blank boxes, and every ``/api/workflow/diagnostics`` call then raised
``AttributeError: 'str' object has no attribute 'get'``. The vocabulary belongs to the server, so
the check does too: the engine's own node types, ``params`` as an object, wires that name nodes
that exist. A draft that fails is REFUSED BY NAME with the offending node — never half-applied.
"""

from __future__ import annotations

import os

from engine.workflow import NODE_TYPES

#: A workflow artifact carries its graph under one of these keys.
GRAPH_KEYS = ('nodes',)
WIRE_KEYS = ('connections', 'edges')


def _ids(nodes: list) -> list[str]:
    return [str(node.get('id') or '') for node in nodes if isinstance(node, dict)]


def problems(payload: dict) -> list[str]:
    """Every reason this draft cannot be loaded, in the order a reader would fix them."""
    if not isinstance(payload, dict):
        return ['the draft is not an object']
    nodes = payload.get('nodes')
    if not isinstance(nodes, list) or not nodes:
        return ['the draft has no node list']
    out: list[str] = []
    seen: set[str] = set()
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            out.append(f'node #{index + 1} is not an object')
            continue
        node_id = str(node.get('id') or '')
        if not node_id:
            out.append(f'node #{index + 1} has no id')
        elif node_id in seen:
            out.append(f'id «{node_id}» is used twice')
        seen.add(node_id)
        node_type = str(node.get('type') or '')
        if not node_type:
            out.append(f'node {node_id or index + 1} has no type')
        elif node_type not in NODE_TYPES:
            allowed = ', '.join(sorted(NODE_TYPES))
            out.append(
                f'node {node_id or index + 1} uses type «{node_type}», which is not a node type (use one of: {allowed})'
            )
        if 'params' in node and not isinstance(node.get('params'), dict):
            out.append(f'node {node_id or index + 1} has params that are not an object')
    for key in WIRE_KEYS:
        wires = payload.get(key)
        if wires is None:
            continue
        if not isinstance(wires, list):
            out.append(f'«{key}» is not a list')
            continue
        for index, wire in enumerate(wires):
            if not isinstance(wire, dict):
                out.append(f'{key} #{index + 1} is not an object')
                continue
            for end in ('from', 'to'):
                target = str(wire.get(end) or '')
                if target and target not in seen:
                    out.append(f'{key} #{index + 1} names «{target}», which is not a node id')
    return out


def validate(payload: dict) -> dict:
    """Structural legality **and** the engine's own run-time validation, in one answer.

    ``problems`` catches what makes the canvas blank (unknown type, params that are not an object,
    a wire to nowhere). ``WorkflowEngine.validate`` catches what makes the RUN refuse — a source
    mode the platform does not have, a missing required field, a cycle. A draft the model presents
    is checked against both, so "it loaded" and "it can run" are one question.
    """
    structural = problems(payload)
    if structural:
        return {'ok': False, 'structural': structural, 'engine': []}
    engine_problems: list[str] = []
    try:
        from engine.workflow import WorkflowEngine

        engine_problems = [str(item) for item in WorkflowEngine(payload).validate()]
    except Exception as exc:  # a malformed file must answer, not 500
        engine_problems = [f'the engine could not read the draft: {str(exc)[:200]}']
    return {'ok': not engine_problems, 'structural': [], 'engine': engine_problems}


def save(payload: dict, name: str = '') -> dict:
    """Write a legal draft into this account's workflow folder under a free name.

    The file is what the canvas's own "open" reads, so an applied draft is also a saved workflow —
    not a second, private shape. A name that already exists gets a suffix instead of overwriting the
    user's own canvas.
    """
    from runtime.stores import get_workflow_manager

    manager = get_workflow_manager()
    base = manager.clean_name(str(name or '').strip() or 'AI 工作流')
    taken = {str(item).casefold() for item in manager.list_workflows()}
    candidate = base
    suffix = 2
    # The TAIL is reserved before the length cap, exactly like ``manager.duplicate`` and the
    # project-bundle importer do it: comparing an UNCLEANED ``base (2)`` against cleaned names
    # never matched a 60-character stem, the loop exited, ``clean_name`` cut the tail off, and the
    # save then overwrote the user's own canvas under the name it was supposed to avoid.
    while candidate.casefold() in taken or os.path.exists(manager.path_for(candidate)):
        tail = f' ({suffix})'
        room = max(1, manager.MAX_NAME_LENGTH - len(tail))
        candidate = manager.clean_name(f'{base[:room]}{tail}')
        suffix += 1
    path = manager.save(candidate, payload)
    return {'name': candidate, 'path': path}
