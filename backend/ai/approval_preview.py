"""What an approval card shows about the call it is asking to allow.

``request_approval`` carries a one-sentence ``summary`` the model wrote about its own intent. The
user, however, is being asked to allow an act on their own machine, so the card also shows the thing
itself: the resolved path, the command that would run, or the lines a write would change.

This module only DESCRIBES — it never writes. A description that cannot be produced (an escaping
path, a cloud host, an unreadable file) is reported in ``error`` with the same named sentence the
tool will answer with: failing to explain a call must never fail the turn that asked for it.
"""

from __future__ import annotations

import contextlib
import difflib
import json
import os

from ai.errors import AIError

#: Diff lines one card shows before the rest is counted and reported. A card is a review, not a pager.
MAX_DIFF_LINES = 400
#: One fact's text. A path or a command fits; a whole file does not.
MAX_FACT_CHARS = 1000


def preview(tool: str, args: dict | None) -> dict:
    """``{tool, kind, facts, diff, exists, changed, truncated, error}`` for one approval card."""
    detail = args if isinstance(args, dict) else {}
    name = str(tool or '')
    builder = _BUILDERS.get(name)
    return builder(name, detail) if builder else _frame(name, 'unknown', _plain_facts(detail))


def _frame(
    tool: str,
    kind: str,
    facts: list,
    *,
    diff: list | None = None,
    exists: bool = False,
    changed: bool = False,
    truncated: bool = False,
    error: str = '',
) -> dict:
    return {
        'tool': tool,
        'kind': kind,
        'facts': [{'key': str(key), 'value': str(value)[:MAX_FACT_CHARS]} for key, value in facts],
        'diff': diff or [],
        'exists': bool(exists),
        'changed': bool(changed),
        'truncated': bool(truncated),
        'error': str(error or ''),
    }


def _plain_facts(detail: dict) -> list:
    """An approval tool we do not know yet still shows its arguments, never an empty card."""
    rows = []
    for key, value in detail.items():
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        rows.append((key, value))
    return rows


def _write(tool: str, detail: dict) -> dict:
    from ai import workspace

    relative = str(detail.get('path') or '')
    content = str(detail.get('content') or '')
    facts = [('path', relative)]
    try:
        target = workspace.resolve(relative)
    except AIError as exc:
        return _frame(tool, 'write', facts, error=exc.localized())
    except OSError as exc:
        return _frame(tool, 'write', facts, error=str(exc)[:160])
    facts.append(('target', target))
    exists = os.path.isfile(target)
    try:
        size = os.path.getsize(target) if exists else 0
    except OSError:
        size = 0
    if exists:
        facts.append(('bytes_before', size))
    facts.append(('bytes_after', len(content.encode('utf-8'))))
    diff, truncated, computed = _diff(relative, content, exists, size)
    return _frame(
        tool,
        'write',
        facts,
        diff=diff,
        exists=exists,
        # An unreadable/oversized file cannot be compared, but the write still REPLACES it: show
        # that as a change rather than claiming the two sides matched.
        changed=(not exists) or (not computed) or bool(diff),
        truncated=truncated,
    )


def _diff(relative: str, content: str, exists: bool, size: int) -> tuple[list, bool, bool]:
    """``(lines, truncated, computed)``. ``computed=False`` means "sizes only, no body"."""
    from ai import workspace

    if size > workspace.MAX_READ_BYTES or len(content) > workspace.MAX_READ_BYTES:
        return [], False, False
    old = ''
    if exists:
        try:
            old = workspace.read_text(relative, max_bytes=workspace.MAX_READ_BYTES)['content']
        except (AIError, OSError):
            return [], False, False
    name = relative or 'file'
    lines = list(
        difflib.unified_diff(
            old.splitlines(),
            content.splitlines(),
            fromfile='a/' + name,
            tofile='b/' + name,
            lineterm='',
            n=3,
        )
    )
    return lines[:MAX_DIFF_LINES], len(lines) > MAX_DIFF_LINES, True


def _command(tool: str, detail: dict) -> dict:
    from ai import workspace

    facts = [('command', str(detail.get('command') or ''))]
    cwd = str(detail.get('cwd') or '')
    if cwd:
        # Show exactly what was proposed; the tool itself refuses an escaping cwd BY NAME.
        with contextlib.suppress(AIError, OSError):
            cwd = workspace.resolve(cwd)
    facts.append(('cwd', cwd or workspace.describe().get('folder') or ''))
    facts.append(('timeout', str(detail.get('timeout') or '')))
    return _frame(tool, 'command', facts, changed=True)


def _import(tool: str, detail: dict) -> dict:
    from ai import workspace

    relative = str(detail.get('path') or '')
    facts = [('path', relative), ('name', str(detail.get('name') or ''))]
    error = ''
    try:
        target = workspace.resolve(relative, must_exist=True)
        facts.append(('target', target))
        facts.append(('bytes', os.path.getsize(target)))
    except AIError as exc:
        error = exc.localized()
    except OSError as exc:
        error = str(exc)[:160]
    return _frame(tool, 'import', facts, changed=True, error=error)


def _rerun(tool: str, detail: dict) -> dict:
    facts = [
        ('run_id', str(detail.get('run_id') or '')),
        ('node_id', str(detail.get('node_id') or '')),
        ('workflow', str(detail.get('workflow_name') or '')),
    ]
    return _frame(tool, 'rerun', facts, changed=True)


#: One entry per tool that ``tools.APPROVAL_TOOLS`` may ask about. A new mutating tool adds its
#: describer here and nowhere else; an unknown one falls back to its raw arguments.
_BUILDERS = {
    'workspace_write': _write,
    'run_cmd': _command,
    'workspace_import': _import,
    'rerun_node': _rerun,
}
