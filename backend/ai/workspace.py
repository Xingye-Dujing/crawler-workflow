"""The user's own machine, as the AI workspace may touch it.

A harness is only useful if it can reach the place the work happens: a folder the user picked, the
checkout's root (web build) or the install root (desktop build). This module is the ONE door for
that, and it decides five things the model may not decide for itself:

1. **Which root.** ``folder`` is the working folder the user chose (stored per account in
   ``ai.db``); ``app_root`` is the server's own tree — the repository on a web build, the install
   directory on a desktop build. A cloud host has neither and refuses by name.
2. **Where a path may go.** Everything is resolved under a root; ``..``, absolute paths and
   symlinks that escape it are refused by name, never silently clamped.
3. **What a command may be.** ``run_cmd`` is not a shell: no piping, no redirection, no chaining,
   an allow-list of executables, a timeout and a bounded capture. It exists so the assistant can
   run ``python script.py`` or ``git status`` in the user's folder — not to administer the box.
4. **What a file becomes.** ``import_table`` turns a local CSV/JSON/Excel/bibliographic export into
   a dataset through the SAME parser the upload panel uses, so columns and row counts agree.
5. **What the model is told.** ``snapshot`` is a small, bounded description of the folder for the
   context section — names and sizes, never file bodies.

The sandbox is honest: a command runs with the user's own permissions. The boundary is the
allow-list and the working directory, and the prompt says so.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from core.config import Config
from core.procs import popen_kwargs

from ai import store
from ai.errors import AIError

#: The working folder the user picked, per account. ``''`` means "not chosen yet".
PREF_KEY = 'workspace.folder'
#: A file read through a tool. Big enough for a script or a CSV head, small enough to be context.
MAX_READ_BYTES = 200_000
#: Command output kept per stream; the rest is dropped and REPORTED as dropped.
MAX_CAPTURE = 20_000
MAX_TIMEOUT = 600
#: Executables a command may name. Read/inspect/build tools only; no shells, no package installers
#: that rewrite the machine, no process managers.
ALLOWED_COMMANDS = frozenset(
    {
        'python',
        'python3',
        'py',
        'pip',
        'pip3',
        'uv',
        'git',
        'node',
        'npm',
        'npx',
        'pnpm',
        'yarn',
        'ruff',
        'pytest',
        'dir',
        'ls',
        'cat',
        'type',
        'head',
        'tail',
        'more',
        'find',
        'grep',
        'rg',
        'where',
        'which',
        'echo',
        'pwd',
        'cd',
        'mkdir',
        'wc',
        'sort',
        'diff',
        'tar',
        'unzip',
        'curl',
        'wget',
    }
)
#: Characters that would mean "a shell", which this is deliberately not.
SHELL_META = ('|', '&', '>', '<', ';', '`', '$(')


def _cloud() -> bool:
    return bool(Config.CLOUD_MODE)


def app_root() -> str:
    """The server's own tree: repository root (web) or install root (desktop)."""
    if _cloud():
        return ''
    from ai import environment

    if environment.kind() == 'desktop':
        return os.path.dirname(os.path.abspath(sys.executable))
    return environment.code_root()


def folder() -> str:
    """The working folder this account chose, or ``''``."""
    return store.get_pref(PREF_KEY, '')


def _exists(path: str) -> bool:
    try:
        return bool(path) and os.path.isdir(path)
    except OSError:
        return False


def describe() -> dict:
    root = folder()
    app = app_root()
    return {
        'folder': root,
        'folder_name': os.path.basename(root.rstrip('\\/')) if root else '',
        'folder_exists': _exists(root),
        'app_root': app,
        'app_name': os.path.basename(app.rstrip('\\/')) if app else '',
        'cloud': _cloud(),
        'can_write': bool(root) and _exists(root),
        'allowed_commands': sorted(ALLOWED_COMMANDS),
    }


def set_folder(path: str) -> dict:
    """Make *path* this account's working folder. Only an existing directory is accepted."""
    if _cloud():
        raise AIError('ai.workspaceCloud', kind='capability')
    raw = os.path.expanduser(str(path or '').strip())
    if not raw:
        store.set_pref(PREF_KEY, '')
        return describe()
    if not os.path.isabs(raw):
        raise AIError('ai.workspaceNotAbsolute', kind='bad_request', path=raw)
    resolved = os.path.realpath(raw)
    if not os.path.isdir(resolved):
        raise AIError('ai.workspaceNotFound', kind='not_found', path=raw)
    store.set_pref(PREF_KEY, resolved)
    return describe()


def _root(kind: str = 'folder') -> str:
    root = folder() if kind == 'folder' else app_root()
    if _cloud():
        raise AIError('ai.workspaceCloud', kind='capability')
    if not root:
        raise (
            AIError('ai.workspaceNoApp', kind='capability')
            if kind == 'app'
            else AIError('ai.workspaceMissing', kind='capability')
        )
    if not _exists(root):
        raise AIError('ai.workspaceGone', kind='not_found', path=root)
    return os.path.realpath(root)


def resolve(relative: str, *, kind: str = 'folder', must_exist: bool = False) -> str:
    """An absolute path inside *kind*'s root, or a refusal that names why not."""
    root = _root(kind)
    rel = str(relative or '').strip().replace('\\', '/')
    while rel.startswith('./'):
        rel = rel[2:]
    if rel.startswith('/') or rel.startswith('~') or (len(rel) > 1 and rel[1] == ':'):
        raise AIError('ai.workspaceOutside', kind='bad_request', path=relative)
    if any(part == '..' for part in rel.split('/')):
        raise AIError('ai.workspaceOutside', kind='bad_request', path=relative)
    target = os.path.realpath(os.path.join(root, rel))
    if target != root and not target.startswith(root + os.sep):
        raise AIError('ai.workspaceOutside', kind='bad_request', path=relative)
    if must_exist and not os.path.exists(target):
        raise AIError('ai.workspaceFileMissing', kind='not_found', path=relative)
    return target


def _relative(path: str, kind: str = 'folder') -> str:
    root = _root(kind)
    return os.path.relpath(path, root).replace('\\', '/')


def browse(path: str = '') -> dict:
    """Directories and files one level down, for the folder picker.

    ``path`` may be absolute (a picker walks the real filesystem) or empty (start at the current
    folder, else the user's home). Only a cloud host is refused: a server has no user machine.
    """
    if _cloud():
        raise AIError('ai.workspaceCloud', kind='capability')
    raw = os.path.expanduser(str(path or '').strip()) or folder() or str(Path.home())
    if not os.path.isabs(raw):
        raw = os.path.join(folder() or str(Path.home()), raw)
    current = os.path.realpath(raw)
    if not os.path.isdir(current):
        raise AIError('ai.workspaceNotFound', kind='not_found', path=raw)
    entries = []
    try:
        with os.scandir(current) as scan:
            for item in scan:
                if len(entries) >= 300:
                    break
                if item.name.startswith('.'):
                    continue
                try:
                    is_dir = item.is_dir()
                except OSError:
                    continue
                entries.append({'name': item.name, 'path': os.path.join(current, item.name), 'dir': is_dir})
    except OSError as exc:
        raise AIError('ai.workspaceUnreadable', kind='error', path=current, detail=str(exc)[:160]) from exc
    entries.sort(key=lambda row: (not row['dir'], row['name'].lower()))
    parent = os.path.dirname(current)
    return {
        'path': current,
        'parent': parent if parent and parent != current else '',
        'entries': entries,
        'home': str(Path.home()),
        'folder': folder(),
    }


def snapshot(limit: int = 40) -> str:
    """A short description of the working folder for the context section."""
    root = folder()
    if not root:
        return ''
    if not _exists(root):
        return f'## 工作文件夹\n{root}（已不存在，请让用户重新选择）'
    lines = [f'## 工作文件夹\n{root}']
    try:
        with os.scandir(root) as scan:
            items = sorted(scan, key=lambda item: (not item.is_dir(), item.name.lower()))[:limit]
        for item in items:
            if item.name.startswith('.'):
                continue
            try:
                size = '' if item.is_dir() else f'，{item.stat().st_size} 字节'
            except OSError:
                size = ''
            lines.append(f'- {item.name}{"/" if item.is_dir() else ""}{size}')
            if not item.is_dir():
                continue
            # One level down, names only: enough for the model to know what it may read without
            # paying for a full tree on every turn.
            try:
                with os.scandir(item.path) as inner:
                    children = sorted(inner, key=lambda child: (not child.is_dir(), child.name.lower()))[:8]
                names = [
                    child.name + ('/' if child.is_dir() else '') for child in children if not child.name.startswith('.')
                ]
            except OSError:
                names = []
            if names:
                lines.append('  - ' + '、'.join(names))
    except OSError as exc:
        lines.append(f'（无法读取：{str(exc)[:120]}）')
    return '\n'.join(lines)


def list_dir(relative: str = '', *, kind: str = 'folder', limit: int = 200) -> dict:
    target = resolve(relative, kind=kind, must_exist=True)
    if not os.path.isdir(target):
        raise AIError('ai.workspaceNotDir', kind='bad_request', path=relative)
    rows = []
    try:
        with os.scandir(target) as scan:
            for item in scan:
                if len(rows) >= max(1, min(limit, 500)):
                    break
                try:
                    is_dir = item.is_dir()
                    size = item.stat().st_size
                except OSError:
                    is_dir, size = False, 0
                rows.append({'name': item.name, 'dir': is_dir, 'size': size})
    except OSError as exc:
        raise AIError('ai.workspaceUnreadable', kind='error', path=relative, detail=str(exc)[:160]) from exc
    rows.sort(key=lambda row: (not row['dir'], row['name'].lower()))
    return {'root': _root(kind), 'path': relative, 'entries': rows}


def read_text(relative: str, *, kind: str = 'folder', max_bytes: int = MAX_READ_BYTES) -> dict:
    target = resolve(relative, kind=kind, must_exist=True)
    if not os.path.isfile(target):
        raise AIError('ai.workspaceNotFile', kind='bad_request', path=relative)
    size = os.path.getsize(target)
    with open(target, 'rb') as handle:
        raw = handle.read(max(1, min(max_bytes, MAX_READ_BYTES)))
    text = _decode(raw)
    return {
        'path': relative,
        'bytes': size,
        'truncated': size > len(raw),
        'content': text,
    }


def write_text(relative: str, content: str, *, kind: str = 'folder') -> dict:
    if kind != 'folder':
        raise AIError('ai.workspaceReadOnly', kind='bad_request', path=relative)
    target = resolve(relative, kind=kind, must_exist=False)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, 'w', encoding='utf-8', newline='') as handle:
        handle.write(str(content or ''))
    return {'path': relative, 'bytes': os.path.getsize(target)}


def _decode(raw: bytes) -> str:
    for codec in ('utf-8', 'gb18030'):
        try:
            return raw.decode(codec)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', 'replace')


def _split(command: str) -> list[str]:
    text = str(command or '').strip()
    if not text:
        raise AIError('ai.cmdEmpty', kind='bad_request')
    for meta in SHELL_META:
        if meta in text:
            raise AIError('ai.cmdShellRefused', kind='bad_request', detail=meta)
    try:
        parts = shlex.split(text, posix=os.name != 'nt')
    except ValueError as exc:
        raise AIError('ai.cmdUnparsable', kind='bad_request', detail=str(exc)[:120]) from exc
    return [part.strip('"').strip("'") if os.name == 'nt' else part for part in parts if part]


def run_command(command: str, *, cwd: str = '', timeout: int = 120) -> dict:
    """Run one allow-listed executable in the working folder (or the app root) and capture output.

    Not a shell: the arguments are passed as a list, metacharacters are refused, and only the
    binaries in :data:`ALLOWED_COMMANDS` are accepted. ``cwd`` stays inside the chosen root, so a
    command cannot be pointed at another part of the disk.
    """
    if _cloud():
        raise AIError('ai.cmdCloud', kind='capability')
    from ai import environment

    if not environment.capabilities()['user_files']:
        raise AIError('ai.cmdCloud', kind='capability')
    argv = _split(command)
    name = os.path.splitext(os.path.basename(argv[0]))[0].lower()
    if name not in ALLOWED_COMMANDS:
        raise AIError('ai.cmdNotAllowed', kind='capability', command=argv[0])
    workdir = resolve(cwd, kind='folder', must_exist=True) if folder() else _root('app')
    if not os.path.isdir(workdir):
        raise AIError('ai.workspaceNotDir', kind='bad_request', path=cwd)
    limit = max(1, min(int(timeout or 120), MAX_TIMEOUT))
    try:
        proc = subprocess.run(
            argv,
            cwd=workdir,
            capture_output=True,
            timeout=limit,
            check=False,
            **popen_kwargs(),
        )
    except FileNotFoundError as exc:
        raise AIError('ai.cmdMissing', kind='not_found', command=argv[0]) from exc
    except subprocess.TimeoutExpired as exc:
        raise AIError('ai.cmdTimeout', kind='error', seconds=limit) from exc
    stdout = _decode(proc.stdout or b'')
    stderr = _decode(proc.stderr or b'')
    return {
        'command': command,
        'cwd': _relative(workdir) if folder() else workdir,
        'exit_code': proc.returncode,
        'stdout': stdout[-MAX_CAPTURE:],
        'stderr': stderr[-MAX_CAPTURE:],
        'truncated': len(stdout) > MAX_CAPTURE or len(stderr) > MAX_CAPTURE,
    }


def import_table(relative: str, name: str = '') -> dict:
    """A local table file as a dataset, through the upload panel's own parsers."""
    import pandas as pd
    from runtime.stores import _register_dataset

    from services.biblio.importer import BiblioDecodeError, decode_text, parse_bytes, parse_frame, parse_text
    from services.datasets.store import SOURCE_UPLOAD

    target = resolve(relative, kind='folder', must_exist=True)
    if not os.path.isfile(target):
        raise AIError('ai.workspaceNotFile', kind='bad_request', path=relative)
    filename = str(name or os.path.basename(target))
    suffix = os.path.splitext(target)[1].lower()
    with open(target, 'rb') as handle:
        raw = handle.read()
    parsed = None
    try:
        if suffix in ('.csv', '.tsv', '.txt', '.ris', '.bib', '.bibtex', '.enw', '.nbib', '.net'):
            text = decode_text(raw, filename)
            try:
                parsed = parse_text(text) if suffix == '.csv' else None
            except BiblioDecodeError:
                parsed = None
            if parsed is None and suffix not in ('.csv', '.tsv'):
                parsed = parse_bytes(raw, filename)
            if parsed is not None:
                frame = pd.DataFrame(parsed['rows'], columns=parsed['columns'])
            elif suffix in ('.csv', '.tsv'):
                import io

                frame = pd.read_csv(io.StringIO(text), sep='\t' if suffix == '.tsv' else ',')
            else:
                frame = pd.DataFrame({'content': [text]})
        elif suffix in ('.xlsx', '.xls', '.xlsm'):
            book = pd.ExcelFile(target)
            filled = [sheet for sheet in book.sheet_names if not pd.read_excel(book, sheet_name=sheet, nrows=1).empty]
            if len(filled) > 1:
                raise AIError('ai.workspaceMultiSheet', kind='bad_request', name=filename, sheets='、'.join(filled))
            frame = pd.read_excel(
                book, sheet_name=filled[0] if filled else (book.sheet_names[0] if book.sheet_names else 0)
            )
            detected = parse_frame(frame)
            if detected is not None:
                frame = pd.DataFrame(detected['rows'], columns=detected['columns'])
        elif suffix == '.json':
            with open(target, encoding='utf-8') as handle:
                frame = pd.DataFrame(json.load(handle))
        else:
            raise AIError('ai.workspaceUnsupported', kind='capability', name=filename)
    except (ValueError, OSError, UnicodeDecodeError, pd.errors.ParserError, ImportError) as exc:
        raise AIError('ai.workspaceParseFailed', kind='bad_request', name=filename, detail=str(exc)[:200]) from exc
    try:
        dataset_id = _register_dataset(frame, name=filename, source=SOURCE_UPLOAD)
    except ValueError as exc:
        raise AIError('ai.datasetTooBig', kind='bad_request', detail=str(exc)[:200]) from exc
    return {
        'dataset_id': dataset_id,
        'name': filename,
        'rows': int(len(frame)),
        'columns': [str(column) for column in frame.columns],
        'next': 'Use dataset_peek with this dataset_id before analysing it.',
    }
