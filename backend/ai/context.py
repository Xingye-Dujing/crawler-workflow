"""What the model may read, and the one place that decides how much of it fits.

Three layers, always in this order:

1. **Project facts** — generated from the registries the app already trusts, never a second
   hand-written list. Stable across turns, so DeepSeek's prefix cache can hit it.
2. **Live context** — the saved canvas draft, dataset profile, run status and console tail. The
   browser may send ids or an unsaved draft; the server re-reads every saved fact itself.
3. **Conversation memory** — user-approved notes, retrieved docs and the current question.

Everything is measured before it is sent. A budget cut is reported in ``meta`` and shown in the
context inspector; the model is never quietly fed a different project.
"""

import json
import os
import re
from pathlib import Path

from core.config import Config
from runtime import paths
from runtime.settings import get_setting

from ai import store

SECRET = re.compile(r'(sk-[A-Za-z0-9_-]{8,}|oc_sk_[A-Za-z0-9_-]{8,}|Bearer\s+[A-Za-z0-9._-]{8,})')
CJK = re.compile(r'[\u3400-\u9fff]')
DOC_ROOTS = (
    'README.md',
    'AGENTS.md',
    'docs/ARCHITECTURE.md',
    'docs/analysis.md',
    'docs/crawler_rules.md',
    'docs/frontend_modules.md',
    # The authoritative CatBus skill (copied from catbus/.claude/skills/catbus). A directory root
    # expands to every .md under it, so the catbus skill can read the one platform/workflow file it
    # needs without a second hand-written index here.
    'docs/catbus/',
)


def estimate_tokens(text: str) -> int:
    """A deliberately cheap estimate: CJK runs near one token per character, Latin near four."""
    if not text:
        return 0
    cjk = len(CJK.findall(text))
    return max(1, cjk + (len(text) - cjk) // 4)


def redact(text: str) -> str:
    return SECRET.sub('[redacted]', str(text or ''))


def _clip(text: str, limit: int) -> str:
    text = str(text or '')
    return text if len(text) <= limit else text[:limit] + '\n…'


def project_facts() -> str:
    """A compact, generated map of the product. Imports stay lazy so the AI page can boot even
    when a heavy optional module (torch, matplotlib) is unavailable."""
    lines = [
        '# 采析绘项目事实',
        '产品：Flask + 无构建 vanilla JS；采集 9 个社交平台与 CNKI 导出；工作流画布；文本清洗、分析与可视化。',
        '数据根：每次调用 runtime.paths.active() 解析；运行、数据集、会话都按账号隔离。',
        '规则：缺失的列、未知模式、未知 provider/skill 必须按名字拒绝；不能静默降级。',
    ]
    try:
        from nodes.catalog import PLUGINS

        lines.append('## 节点')
        for plugin in PLUGINS.values():
            lines.append(f'- {plugin.type}：显示名键 {plugin.label_key}，分类 {plugin.category}')
    except Exception:  # a partial install must not take the whole context down
        pass
    try:
        import capabilities.registry as capabilities

        payload = capabilities.as_dict()
        lines.append('## 采集平台')
        for platform in payload.get('platforms', []):
            modes = platform.get('modes') or []
            names = [str(mode.get('key') or '') for mode in modes if isinstance(mode, dict) and mode.get('key')]
            engines = sorted(
                {
                    str(engine.get('key') or '')
                    for engine in platform.get('engines') or []
                    if isinstance(engine, dict) and engine.get('available') and engine.get('key')
                }
            )
            session_modes = sum(1 for mode in modes if isinstance(mode, dict) and mode.get('needsSession'))
            # Only facts that exist: the old line joined `mode` keys that this payload stopped
            # carrying, so every platform printed as a row of empty commas.
            facts = []
            if names:
                facts.append('模式 ' + '/'.join(names))
            else:
                facts.append('当前没有可用模式')
            facts.append('引擎 ' + '/'.join(engines) if engines else '引擎不可用')
            if session_modes:
                facts.append(f'其中 {session_modes} 个模式需要登录')
            lines.append(f'- {platform.get("platform") or "?"}：' + '；'.join(facts))
    except Exception:
        pass
    try:
        from services.analysis.ops import OPS

        lines.append('## 分析算子')
        lines.append(', '.join(sorted(OPS)))
    except Exception:
        pass
    try:
        from services.charts.registry import SPECS

        lines.append('## 图表类型')
        lines.append(', '.join(spec.key for spec in SPECS))
    except Exception:
        pass
    return '\n'.join(lines)


def _doc_files(root: Path) -> list[tuple[str, Path]]:
    """Resolve DOC_ROOTS to files. A trailing ``/`` means “every markdown under this directory”."""
    files: list[tuple[str, Path]] = []
    for relative in DOC_ROOTS:
        path = root / relative
        if relative.endswith('/'):
            if path.is_dir():
                for child in sorted(path.rglob('*.md')):
                    files.append((f'{relative}{child.relative_to(path).as_posix()}', child))
            continue
        if path.is_file():
            files.append((relative, path))
    return files


def _doc_chunks() -> list[tuple[str, str]]:
    chunks = []
    root = Path(Config.ROOT_DIR) if hasattr(Config, 'ROOT_DIR') else Path(__file__).resolve().parents[2]
    for relative, path in _doc_files(root):
        text = path.read_text(encoding='utf-8', errors='replace')
        current_title = relative
        current = []
        for line in text.splitlines():
            if line.startswith('#'):
                if current:
                    chunks.append((current_title, '\n'.join(current).strip()))
                current_title = line.lstrip('#').strip() or relative
                current = []
            else:
                current.append(line)
        if current:
            chunks.append((current_title, '\n'.join(current).strip()))
    return [(title, body) for title, body in chunks if body]


def docs_search(query: str, limit: int = 3) -> list[dict]:
    """A small keyword retriever over the repository's own docs.

    No embedding model is required: the workspace must work on a machine whose only model is the
    remote API. Chinese search uses overlapping bigrams so a sentence containing 采集/评论 still
    scores a section headed 评论采集.
    """
    terms = {term.lower() for term in re.findall(r'[A-Za-z0-9_]{3,}', query or '')}
    for run in re.findall(r'[\u3400-\u9fff]{2,}', query or ''):
        terms.update(run[i : i + 2] for i in range(len(run) - 1))
    if not terms:
        return []
    scored = []
    for title, body in _doc_chunks():
        haystack = (title + '\n' + body).lower()
        score = sum(haystack.count(term) for term in terms)
        if score:
            scored.append((score, title, body))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [{'title': title, 'text': _clip(body, 2400)} for _score, title, body in scored[:limit]]


def _canvas_context(canvas: dict) -> str:
    nodes = canvas.get('nodes') or []
    connections = canvas.get('connections') or canvas.get('edges') or []
    if not isinstance(nodes, list) or not isinstance(connections, list):
        return ''
    lines = [
        f'## 当前画布（{"未保存草稿" if canvas.get("unsaved") else "画布"}）',
        f'节点 {len(nodes)}，连线 {len(connections)}',
    ]
    selected = canvas.get('selectedNode') or canvas.get('selected_node')
    for node in nodes[:40]:
        if not isinstance(node, dict):
            continue
        params = node.get('params') or {}
        keys = ', '.join(sorted(params)[:12]) if isinstance(params, dict) else ''
        mark = '*' if selected and node.get('id') == selected else '-'
        lines.append(f'{mark} {node.get("type") or "?"} #{node.get("id") or "?"} {node.get("title") or ""} [{keys}]')
    return '\n'.join(lines)


def _dataset_context(dataset_id: str, scope: str) -> str:
    if not dataset_id:
        return ''
    try:
        from runtime.stores import get_dataset_store

        frame = get_dataset_store().get(dataset_id)
        meta = get_dataset_store().meta(dataset_id) or {}
    except Exception:
        return ''
    if frame is None:
        return ''
    sample_n = 6 if scope == 'summary' else 20
    lines = [
        f'## 数据集 {dataset_id}',
        f'名称：{meta.get("name") or ""}；行数：{len(frame)}；列数：{len(frame.columns)}',
        '列：' + ', '.join(f'{column}（{frame[column].dtype}）' for column in frame.columns),
        '缺失：'
        + ', '.join(
            f'{column}={int(frame[column].isna().sum())}' for column in frame.columns if frame[column].isna().any()
        ),
        '样本（前几行，值已截断）：',
        _clip(frame.head(sample_n).to_json(orient='records', force_ascii=False), 5000),
    ]
    return '\n'.join(lines)


def _run_context(run_id: str, scope: str) -> str:
    if not run_id:
        return ''
    try:
        from runtime.stores import get_run_store

        run_store = get_run_store()
        run = run_store.get_run(run_id)
        statuses = run_store.node_statuses(run_id)
        log = run_store.read_log(run_id, limit=50 if scope == 'summary' else 150)
    except Exception:
        return ''
    if not run:
        return ''
    lines = [
        f'## 运行 {run_id}',
        f'状态：{run.get("status")}；工作流：{run.get("workflow_name") or ""}；'
        f'模型：{run.get("llm_provider")}/{run.get("llm_model")}',
        '节点：',
    ]
    for node_id, node in list(statuses.items())[:40]:
        lines.append(
            f'- {node_id}: {node.get("status")}，{node.get("row_count") or 0} 行'
            + (f'，错误：{_clip(node.get("error") or "", 300)}' if node.get('error') else '')
        )
    rows = log.get('rows') or []
    if rows:
        lines.append('控制台尾部：')
        lines.extend(
            f'{row.get("ts") or ""} {row.get("level") or ""} {_clip(row.get("line") or "", 240)}' for row in rows
        )
    return '\n'.join(lines)


#: How many confirmed memories one turn carries. The rest stay visible in the studio; the count is
#: reported in ``context_meta.memories`` so a cut is a fact, not a silence.
MEMORY_CONTEXT_LIMIT = 20


def _memory_context() -> tuple[str, dict]:
    """The user-confirmed memories, newest first, plus how many did not fit.

    The heading is added by ``build_context`` like every other section: returning one here produced
    a second ``## 项目记忆`` inside the first, which read as two sections and made the inspector's
    character count disagree with what the model saw.
    """
    try:
        memories = store.list_memories()
    except Exception:
        return '', {'total': 0, 'shown': 0, 'omitted': 0}
    shown = memories[:MEMORY_CONTEXT_LIMIT]
    text = '\n'.join(f'- {item["text"]}' for item in shown)
    return text, {'total': len(memories), 'shown': len(shown), 'omitted': max(0, len(memories) - len(shown))}


def build_context(query: str, payload: dict | None = None) -> tuple[str, dict]:
    """Return ``(context_text, meta)``. ``meta`` is what the inspector renders."""
    payload = payload or {}
    scope = str(get_setting('ai_context_scope') or 'summary')
    if payload.get('scope') in ('off', 'summary', 'full'):
        scope = str(payload['scope'])
    if scope == 'off':
        return '', {
            'scope': 'off',
            'items': [],
            'chars': 0,
            'tokens': 0,
            'omitted': [],
            'memories': {'total': 0, 'shown': 0, 'omitted': 0},
        }
    parts: list[tuple[str, str]] = []
    memories_meta: dict = {'total': 0, 'shown': 0, 'omitted': 0}
    if scope in ('summary', 'full'):
        parts.append(('项目事实', project_facts()))
        memory_text, memories_meta = _memory_context()
        parts.append(('项目记忆', memory_text))
    canvas = payload.get('canvas') if isinstance(payload.get('canvas'), dict) else None
    if canvas:
        parts.append(('画布', _canvas_context(canvas)))
    try:
        from ai import workspace

        folder = workspace.snapshot()
    except Exception:  # a store that cannot open must not take the whole context down
        folder = ''
    if folder:
        parts.append(('工作文件夹', folder))
    if payload.get('dataset_id'):
        parts.append(('数据集', _dataset_context(str(payload['dataset_id']), scope)))
    if payload.get('run_id'):
        parts.append(('运行', _run_context(str(payload['run_id']), scope)))
    if scope == 'full':
        for index, doc in enumerate(docs_search(query, limit=3), 1):
            parts.append((f'文档 {index}：{doc["title"]}', doc['text']))
    budget = max(2000, int(get_setting('ai_max_context_chars') or 120000))
    kept: list[str] = []
    items: list[dict] = []
    omitted: list[str] = []
    used = 0
    for title, text in parts:
        text = redact(text)
        if not text:
            continue
        remaining = budget - used
        if remaining <= 200:
            omitted.append(title)
            continue
        clipped = text if len(text) <= remaining else text[:remaining] + '\n…'
        kept.append(f'## {title}\n{clipped}')
        items.append({'title': title, 'chars': len(clipped), 'truncated': len(clipped) < len(text)})
        used += len(clipped)
    joined = '\n\n'.join(kept)
    return joined, {
        'scope': scope,
        'items': items,
        'chars': len(joined),
        'tokens': estimate_tokens(joined),
        'omitted': omitted,
        'budget': budget,
        'memories': memories_meta,
    }


def context_preview(query: str, payload: dict | None = None) -> dict:
    text, meta = build_context(query, payload)
    return {'ok': True, 'context': text, 'meta': meta}


def for_replay(text: str) -> tuple[str, dict]:
    """Clamp the block a turn will carry for the REST of the conversation.

    The block is stored on the user's own row and replayed with that row forever (that is what lets
    the provider's prefix cache hit across turns — a message whose bytes change invalidates
    everything after it). "Forever" is why its size matters: a 120,000-character context repeated
    over twenty turns is a window nobody has. The cap keeps it bounded, and what it drops is
    reported (``replay_truncated``) and still reachable through the read tools.
    """
    value = str(text or '')
    limit = max(1000, int(get_setting('ai_context_replay_chars') or 16000))
    meta = {'replay_limit': limit, 'replay_chars': min(len(value), limit), 'replay_truncated': len(value) > limit}
    if not meta['replay_truncated']:
        return value, meta
    note = f'\n…[context cut at {limit} chars for replay; read the rest with a tool]'
    return value[:limit] + note, meta


def ensure_dirs() -> None:
    paths.active().ensure()


def safe_filename(name: str) -> str:
    cleaned = re.sub(r'[^\w.\- ]+', '_', os.path.basename(str(name or 'file')))
    return cleaned[:120] or 'file'


def json_dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)
