"""@ references: name something this account already has instead of uploading it again.

A reference is resolved SERVER-side. The browser sends ids it got from its own picker; this module
reads the account's stores and renders a BOUNDED text block (or hands back an uploaded file's
``file_id``), so the model never receives a filesystem path and never receives a whole table — the
same budget the context builder applies to project facts.
"""

from __future__ import annotations

import json

from runtime import paths, stores

from ai import store

#: Kinds the composer's picker offers, in the order it lists them.
KINDS = ('dataset', 'export', 'workflow', 'run', 'file')
#: A turn may name at most this many things; the text budget below is what actually binds.
MAX_REFS = 20
MAX_CHARS = 8000
TOTAL_CHARS = 60000


def _dataset_preview(dataset_id: str) -> dict:
    frame = stores.get_dataset_store().get(dataset_id)
    if frame is None:
        return {}
    columns = [str(column) for column in list(frame.columns)[:24]]
    rows = frame.head(3).fillna('').to_dict('records')
    return {'columns': columns, 'rows': rows, 'total': int(len(frame))}


def options(query: str = '') -> list[dict]:
    """Everything the picker can offer, newest first, filtered by a case-insensitive substring."""
    needle = str(query or '').strip().lower()
    out: list[dict] = []

    for row in stores.get_dataset_store().list_datasets(limit=60):
        out.append(
            {
                'kind': 'dataset',
                'id': str(row.get('dataset_id') or ''),
                'label': str(row.get('name') or row.get('dataset_id') or ''),
                'detail': f'{int(row.get("row_count") or 0)} 行',
            }
        )

    from services.exports.browser import list_exports

    for row in list_exports(paths.active().export_dir, limit=60):
        out.append(
            {
                'kind': 'export',
                'id': str(row.get('name') or ''),
                'label': str(row.get('name') or ''),
                'detail': f'{int(row.get("size") or 0) // 1024} KB',
            }
        )

    from services.workflows.manager import WorkflowManager

    manager = WorkflowManager()
    for row in manager.describe():
        out.append(
            {
                'kind': 'workflow',
                'id': str(row.get('name') or ''),
                'label': str(row.get('name') or ''),
                'detail': f'{int(row.get("nodes") or 0)} 节点',
            }
        )

    for row in stores.get_run_store().run_ledger()[:40]:
        out.append(
            {
                'kind': 'run',
                'id': str(row.get('id') or ''),
                'label': str(row.get('workflow_name') or row.get('id') or ''),
                'detail': f'{row.get("status") or ""} · {row.get("row_count") or 0} 行',
            }
        )

    for row in store.list_attachments_everywhere(limit=60):
        out.append(
            {
                'kind': 'file',
                'id': str(row.get('id') or ''),
                'label': str(row.get('name') or ''),
                'detail': str(row.get('purpose') or ''),
            }
        )

    if needle:
        out = [
            row
            for row in out
            if needle in row['label'].lower() or needle in row['kind'].lower() or needle in row['id'].lower()
        ]
    return out[:80]


def _export_text(name: str) -> str:
    """A bounded head of an export file: the model needs its shape, not its bytes.

    The id is client input, so it goes through the SAME name-only resolver the download route
    uses. ``Path(base) / name`` discarded the base for an absolute name and followed ``..`` for
    a relative one, which let a turn read any file the account could reach and store its first
    characters in ``context_text`` forever.
    """
    from services.exports.browser import resolve_export_file

    candidate = resolve_export_file(paths.active().export_dir, name)
    if not candidate:
        # A name the export directory does not hold is refused by name, never guessed at.
        return f'导出文件 {name}：在本账号的导出目录中找不到。'
    try:
        with open(candidate, encoding='utf-8', errors='replace') as handle:
            head = handle.read(MAX_CHARS)
    except OSError as exc:
        return f'导出文件 {name}：读取失败（{exc}）。'
    return f'导出文件 {name} 的前 {len(head)} 个字符：\n{head}'


def _workflow_text(name: str) -> str:
    from services.workflows.manager import WorkflowManager

    manager = WorkflowManager()
    data = manager.load(name)
    if not data:
        return f'工作流 {name}：找不到这个文件。'
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


def _run_text(run_id: str) -> str:
    """A run record + its node verdicts + a SHORT console tail, for @-referencing a run.

    Token policy: the tail is 20 lines, each capped, and the whole block is clipped by the caller's
    reference budget. A deeper look is the `run_console` tool (bounded, paged by `limit`).
    """
    run_store = stores.get_run_store()
    run = run_store.get_run(run_id)
    if not run:
        return f'运行 {run_id}：找不到。'
    lines = [
        f'运行 {run.get("workflow_name") or run_id}（{run_id}）',
        f'状态：{run.get("status") or ""}；开始：{run.get("started_at") or ""}；结束：{run.get("finished_at") or ""}',
    ]
    try:
        statuses = run_store.node_statuses(run_id)
        for node_id, node in list(statuses.items())[:20]:
            error = str(node.get('error') or '')
            lines.append(
                f'- {node_id}: {node.get("status") or ""}，{node.get("row_count") or 0} 行'
                + (f'，错误：{error[:200]}' if error else '')
            )
        rows = run_store.read_log(run_id, limit=20).get('rows') or []
        if rows:
            lines.append('控制台尾部：')
            lines.extend(f'{row.get("level") or ""} {str(row.get("line") or "")[:200]}' for row in rows)
    except Exception as exc:  # a run whose tables are gone is still a named run
        lines.append(f'（明细不可读：{str(exc)[:120]}）')
    return '\n'.join(lines)


def resolve(refs: list) -> tuple[str, list[dict]]:
    """Render the named references: ``(text for the turn, rows that travel as attachments)``."""
    parts: list[str] = []
    files: list[dict] = []
    used = 0
    for ref in (refs or [])[:MAX_REFS]:
        if not isinstance(ref, dict):
            continue
        kind = str(ref.get('kind') or '')
        ident = str(ref.get('id') or '').strip()
        if kind not in KINDS or not ident:
            continue
        if kind == 'dataset':
            info = _dataset_preview(ident)
            if not info:
                parts.append(f'数据集 {ident}：找不到。')
                continue
            table = '\n'.join(
                ' | '.join(str(row.get(column, ''))[:60] for column in info['columns']) for row in info['rows']
            )
            text = (
                f'数据集 {ident}（共 {info["total"]} 行，列：{", ".join(info["columns"])}）'
                f'\n前 {len(info["rows"])} 行：\n{table}'
            )
        elif kind == 'export':
            text = _export_text(ident)
        elif kind == 'workflow':
            text = _workflow_text(ident)
        elif kind == 'run':
            text = _run_text(ident)
        else:
            row = store.get_attachment(ident)
            if row is None:
                parts.append(f'文件 {ident}：找不到。')
                continue
            files.append(row)
            # A local-only upload has no provider file id; the agent sends its extracted text.
            text = f'文件 {row.get("name") or ident}（随本轮一起发送）'
        text = text[:MAX_CHARS]
        if used + len(text) > TOTAL_CHARS:
            parts.append('（其余引用因长度上限未展开）')
            break
        used += len(text)
        parts.append(text)
    if not parts:
        return '', files
    return '<cai_xi_hui_references>\n' + '\n\n'.join(parts) + '\n</cai_xi_hui_references>', files
