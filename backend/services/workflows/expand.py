"""Expand reusable nodes into a runnable child graph on the server.

The browser expands on Run too, but a scheduled task is started from the **saved file**,
where a reusable node is still one group (that is what makes it reopenable). This is the
same expansion rule in Python: namespaced child ids (``<group>__<child>``), internal wires
copied, external incoming wires assigned to the template's ordered input slots, external
outgoing wires fed from its single output. A group that cannot be expanded is a named
refusal, never a run over a silently incomplete graph.

The two implementations are deliberately kept in lock-step by tests, not shared across the
language boundary: the JS harness pins its mapping and the Python tests pin this one with
the same edge expectations.
"""

from i18n import t
from services.workflows.reusable import ALLOWED_TYPES


def _name_of(node: dict) -> str:
    params = node.get('params') or {}
    return str(params.get('template_name') or node.get('title') or node.get('id') or '')


def expand_reusable_workflow(workflow: dict) -> tuple[dict, str]:
    """Return ``(expanded_workflow, error)``; a workflow without groups is returned as-is."""
    if not isinstance(workflow, dict):
        return {}, t('reusable.invalid')
    nodes = workflow.get('nodes')
    if not isinstance(nodes, list):
        return {}, t('reusable.invalid')
    groups = {str(n.get('id')): n for n in nodes if isinstance(n, dict) and n.get('type') == 'reusable'}
    if not groups:
        return workflow, ''

    connections = workflow.get('connections')
    if not isinstance(connections, list):
        connections = []

    enabled = {}
    inner_out = {}
    expanded_nodes = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        nid = str(node.get('id') or '')
        if node.get('type') != 'reusable':
            expanded_nodes.append(node)
            continue
        params = node.get('params') or {}
        if params.get('enabled') is False:
            continue
        enabled[nid] = node
        template = params.get('template') or {}
        inner_nodes = template.get('nodes') if isinstance(template, dict) else None
        outputs = template.get('outputs') if isinstance(template, dict) else None
        if not isinstance(inner_nodes, list) or not inner_nodes or not isinstance(outputs, list) or len(outputs) != 1:
            return {}, t('reusable.noTemplateForRun', name=_name_of(node))
        by_id = {}
        for inner in inner_nodes:
            if not isinstance(inner, dict):
                return {}, t('reusable.badTemplate', name=_name_of(node))
            inner_id = str(inner.get('id') or '')
            inner_type = str(inner.get('type') or '')
            if not inner_id or inner_id in by_id or inner_type not in ALLOWED_TYPES:
                return {}, t('reusable.badTemplate', name=_name_of(node))
            namespaced = f'{nid}__{inner_id}'
            by_id[inner_id] = namespaced
            inner_params = inner.get('params') if isinstance(inner.get('params'), dict) else {}
            expanded_nodes.append(
                {
                    'id': namespaced,
                    'type': inner_type,
                    'title': str(inner.get('title') or ''),
                    'platform': inner_params.get('platform'),
                    'params': inner_params,
                    'operation': inner_params.get('operation'),
                    'x': inner.get('x') or 0,
                    'y': inner.get('y') or 0,
                    'folded': False,
                }
            )
        out = str(outputs[0])
        if out not in by_id:
            return {}, t('reusable.noTemplateForRun', name=_name_of(node))
        inner_out[nid] = by_id[out]

    expanded_connections = []
    for node_id in enabled:
        template = (enabled[node_id].get('params') or {}).get('template') or {}
        by_id = {
            str(inner.get('id')): f'{node_id}__{inner.get("id")}'
            for inner in (template.get('nodes') or [])
            if isinstance(inner, dict)
        }
        inner_connections = template.get('connections') or []
        if not isinstance(inner_connections, list):
            return {}, t('reusable.badTemplate', name=_name_of(enabled[node_id]))
        for conn in inner_connections:
            if not isinstance(conn, dict):
                return {}, t('reusable.badTemplate', name=_name_of(enabled[node_id]))
            left = str(conn.get('from') or '')
            right = str(conn.get('to') or '')
            if left in by_id and right in by_id:
                expanded_connections.append({'from': by_id[left], 'to': by_id[right]})

    for conn in connections:
        if not isinstance(conn, dict):
            continue
        left = str(conn.get('from') or '')
        right = str(conn.get('to') or '')
        if left not in groups and right not in groups:
            expanded_connections.append({'from': left, 'to': right})

    for group_id, group in enabled.items():
        template = (group.get('params') or {}).get('template') or {}
        inputs = template.get('inputs') if isinstance(template, dict) else []
        inputs = inputs if isinstance(inputs, list) else []
        incoming = [conn for conn in connections if isinstance(conn, dict) and str(conn.get('to')) == group_id]
        if len(incoming) > len(inputs):
            return {}, t('reusable.tooManyInputs', name=_name_of(group))
        if len(incoming) < len(inputs):
            return {}, t('reusable.missingInputs', name=_name_of(group), n=len(inputs), wired=len(incoming))
        for index, conn in enumerate(incoming):
            source = str(conn.get('from') or '')
            if source in groups:
                source = inner_out.get(source, '')
            if not source:
                return {}, t('reusable.missingInputs', name=_name_of(group), n=len(inputs), wired=len(incoming))
            expanded_connections.append({'from': source, 'to': f'{group_id}__{inputs[index]}'})

    for conn in connections:
        if not isinstance(conn, dict):
            continue
        left = str(conn.get('from') or '')
        right = str(conn.get('to') or '')
        if left in enabled and right not in groups:
            output = inner_out.get(left)
            if not output:
                return {}, t('reusable.noTemplateForRun', name=_name_of(enabled[left]))
            expanded_connections.append({'from': output, 'to': right})

    expanded = dict(workflow)
    expanded['nodes'] = expanded_nodes
    expanded['connections'] = expanded_connections
    return expanded, ''
