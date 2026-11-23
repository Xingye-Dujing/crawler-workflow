"""The product facts and documentation search the AI workspace reads.

The framework's context builder owns the three layers (facts, live context, memories) and their
budgets; this module supplies only the product half: the generated project map and a keyword search
over the repository's own docs. Imports stay lazy so the AI page can boot even when a heavy optional
module (torch, matplotlib) is unavailable.
"""

import json
import os
import re
from pathlib import Path

from core.config import Config

SECRET = re.compile(r'(sk-[A-Za-z0-9_-]{8,}|oc_sk_[A-Za-z0-9_-]{8,}|Bearer\s+[A-Za-z0-9._-]{8,})')
CJK = re.compile(r'[\u3400-\u9fff]')
DOC_ROOTS = (
    'README.md',
    'AGENTS.md',
    'docs/ARCHITECTURE.md',
    'docs/analysis.md',
    'docs/crawler_rules.md',
    'docs/frontend_modules.md',
    'docs/capabilities/',
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


def redact_with_count(text: str) -> tuple[str, int]:
    """Redact secrets and report how many were removed.

    The count is data for the inspector, not a log line: a turn whose context was scrubbed must be
    able to SAY so, or the user reads a silence as "the model saw everything". Nothing about the
    matched value is kept — only the number and, at the call site, which source it came from.
    """
    return SECRET.subn('[redacted]', str(text or ''))


def redact(text: str) -> str:
    return redact_with_count(text)[0]


def _clip(text: str, limit: int) -> str:
    text = str(text or '')
    return text if len(text) <= limit else text[:limit] + '\n…'


def project_facts() -> str:
    """A compact, generated map of the product."""
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
        from capabilities_kernel import knowledge

        lines.append('## 能力技能')
        lines.append('用 skill_catalog 检索、skill_load 读全文；每个能力都有前置/步骤/模板/失败/验收七段。')
        lines.extend(knowledge.prompt_lines(limit=40))
    except Exception:  # a partial install must not take the whole context down
        pass
    try:
        from ai import recipes as product_recipes

        lines.append('## 配方')
        for recipe in product_recipes.catalog():
            steps = ' → '.join(f'{step["id"]}:{step["tool"]}' for step in recipe['steps'])
            lines.append(f'- {recipe["id"]}（{recipe["title"]}）：{steps}')
        lines.append('用 recipe_start 开始，recipe_skip 只记录用户主动跳步。')
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


def safe_filename(name: str) -> str:
    cleaned = re.sub(r'[^\w.\- ]+', '_', os.path.basename(str(name or 'file')))
    return cleaned[:120] or 'file'


def json_dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)
