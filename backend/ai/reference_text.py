"""Bounded text for the workspace's ``@`` references.

The framework owns the reference budget and the picker merge; this module owns what each product
object looks like when it is named: a dataset's shape and three rows, a run's verdicts and console
tail, a saved workflow's node map, an export file's head, and a capability skill's body. Every
reader is bounded here as well, because a reference is also stored on the user's row for replay.
"""

from __future__ import annotations

import json

from runtime import paths, stores

#: Enough shape for the model to decide the next call; a deeper read is the matching tool.
PREVIEW_ROWS = 3
HEAD_CHARS = 4000


def dataset(dataset_id: str) -> str:
    """The columns, total and a few rows — never the whole table."""
    frame = stores.get_dataset_store().get(dataset_id)
    if frame is None:
        return ''
    columns = [str(column) for column in list(frame.columns)[:24]]
    rows = frame.head(PREVIEW_ROWS).fillna('').to_dict('records')
    table = '\n'.join(' | '.join(str(row.get(column, ''))[:60] for column in columns) for row in rows)
    return f'数据集 {dataset_id}（共 {len(frame)} 行，列：{", ".join(columns)}）\n前 {len(rows)} 行：\n{table}'


def run(run_id: str) -> str:
    """A run record, its node verdicts and a short console tail."""
    store = stores.get_run_store()
    found = store.get_run(run_id)
    if not found:
        return ''
    lines = [
        f'运行 {found.get("workflow_name") or run_id}（{run_id}）',
        f'状态：{found.get("status") or ""}；'
        f'开始：{found.get("started_at") or ""}；结束：{found.get("finished_at") or ""}',
    ]
    try:
        for node_id, node in list(store.node_statuses(run_id).items())[:20]:
            error = str(node.get('error') or '')
            lines.append(
                f'- {node_id}: {node.get("status") or ""}，{node.get("row_count") or 0} 行'
                + (f'，错误：{error[:200]}' if error else '')
            )
        rows = store.read_log(run_id, limit=20).get('rows') or []
        if rows:
            lines.append('控制台尾部：')
            lines.extend(f'{row.get("level") or ""} {str(row.get("line") or "")[:200]}' for row in rows)
    except Exception as exc:  # a run whose tables are gone is still a named run
        lines.append(f'（明细不可读：{str(exc)[:120]}）')
    return '\n'.join(lines)


def workflow(name: str) -> str:
    """The node map and wires, so the model can read a saved canvas without reloading it."""
    manager = stores.get_workflow_manager()
    data = manager.load(name)
    if not data:
        return ''
    nodes = data.get('nodes') or []
    if isinstance(nodes, dict):
        nodes = list(nodes.values())
    lines = [f'工作流 {name}（{len(nodes)} 个节点，文件可直接用 apply_workflow 改后重载）：']
    for node in nodes[:24]:
        if not isinstance(node, dict):
            continue
        title = str(node.get('title') or node.get('id') or '')
        params = node.get('params') if isinstance(node.get('params'), dict) else {}
        shown = json.dumps(params, ensure_ascii=False)
        if len(shown) > 300:
            shown = shown[:300] + '…'
        lines.append(f'- {title} [{node.get("type") or ""}] {shown}')
    wires = data.get('connections') or []
    if wires:
        lines.append('连线：' + '、'.join(f'{w.get("from")}→{w.get("to")}' for w in wires[:30] if isinstance(w, dict)))
    return '\n'.join(lines)


def export(name: str) -> str:
    """A bounded head of one export file in this account's export directory."""
    from services.exports.browser import resolve_export_file

    candidate = resolve_export_file(paths.active().export_dir, name)
    if not candidate:
        return ''
    try:
        with open(candidate, encoding='utf-8', errors='replace') as handle:
            head = handle.read(HEAD_CHARS)
    except OSError:
        return ''
    return f'导出文件 {name} 的前 {len(head)} 个字符：\n{head}'


def skill(skill_id: str) -> str:
    """A capability skill's L2 body, rendered from its manifest now."""
    from ai import knowledge

    try:
        return str(knowledge.load(skill_id)['markdown'])
    except Exception:  # an unknown skill is an unresolved reference, not a failed turn
        return ''
