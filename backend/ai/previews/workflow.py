"""Workflow-draft preview: what each proposed node would do to the current canvas.

The validator already decided the draft is loadable and runnable. This preview only makes its
shape legible: which nodes are new, which would overwrite an existing id, and which existing nodes
the draft would leave alone. The client applies a SELECTION by merging it into the live canvas —
never by replacing the whole canvas — so an unselected node is left exactly as the user had it.
"""

from nodes.labels import node_label

from ai.previews.base import Preview, PreviewItem, register
from i18n import t


def _ids(workflow: dict | None) -> set[str]:
    nodes = (workflow or {}).get('nodes') or []
    return {str(node.get('id') or '') for node in nodes if isinstance(node, dict) and node.get('id')}


def _detail(node: dict) -> str:
    params = node.get('params') if isinstance(node.get('params'), dict) else {}
    parts = [str(node.get('type') or '')]
    for key in ('operation', 'mode', 'backend', 'platform'):
        value = str(params.get(key) or node.get(key) or '').strip()
        if value:
            parts.append(value)
    return ' · '.join(part for part in parts if part)


def _preview(payload: dict, current: dict | None = None) -> Preview:
    nodes = [node for node in (payload.get('nodes') or []) if isinstance(node, dict)]
    current_ids = _ids(current)
    items: list[PreviewItem] = []
    for node in nodes:
        nid = str(node.get('id') or '')
        overwrite = nid in current_ids
        items.append(
            PreviewItem(
                id=nid,
                label=f'{t("ai.preview.change") if overwrite else t("ai.preview.add")} · {node_label(node, nid)}',
                detail=_detail(node),
                action='change' if overwrite else 'add',
                selectable=True,
                checked=True,
            )
        )
    kept = sorted(current_ids - {str(node.get('id') or '') for node in nodes})
    items.extend(
        PreviewItem(id=f'keep:{nid}', label=f'{t("ai.preview.keep")} · {nid}', action='keep', selectable=False)
        for nid in kept
    )
    warnings: list[str] = []
    if kept and (payload.get('connections') or (current or {}).get('connections')):
        warnings.append(t('ai.preview.mergeNote'))
    return Preview(
        kind=str(payload.get('kind') or 'workflow_draft'),
        title=t('ai.preview.title'),
        summary=t('ai.preview.nodeSummary', n=len(nodes)),
        items=items,
        warnings=warnings,
    )


register('workflow', _preview)
register('workflow_draft', _preview)
