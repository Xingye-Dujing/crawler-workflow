"""The user's own machine, as the AI panel may look at it.

The working folder itself lives in the framework's workspace (one root per account, one sandbox);
this module owns only what the framework cannot know — the machine's folder picker and the product's
table import:

1. **Which roots exist.** ``volumes`` is the per-OS filesystem table from ``core.machine``.
2. **Where to look.** ``browse`` walks one level of the real filesystem for the panel's picker.
3. **A native choice.** ``pick_folder`` opens the OS dialog and answers the picked path; closing it
   is a decision, not an error.
4. **What a file becomes.** ``import_path`` turns a local CSV/JSON/Excel/bibliographic export into a
   dataset through the SAME parser the upload panel uses, so columns and row counts agree.

A cloud host has no user machine; a shared accounts host has one machine that belongs to the
administrator. Both refuse by name, never silently.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from core import machine
from core.config import Config
from core.procs import popen_kwargs
from runtime import policy

from ai.errors import AIError

#: Command output kept per stream for the native dialog; the rest is dropped.
MAX_CAPTURE = 20_000


def _cloud() -> bool:
    return bool(Config.CLOUD_MODE)


def _refuse_machine() -> None:
    """The one refusal for a door that reads or runs things outside an account's own tree.

    ``CLOUD_MODE`` has no user machine at all; a shared accounts host has one machine that belongs
    to the administrator, not to every signed-in user. Without this second half an ordinary
    account could point the workspace at ``data/users/<other>/`` and read it, or run a command in
    the checkout beside it — the isolation every other machine-level route already enforces.
    """
    if _cloud():
        raise AIError('ai.workspaceCloud', kind='capability')
    if not policy.may_administer_machine():
        raise AIError(policy.machine_refusal_key(), kind='capability')


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
        'catbus',
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


def app_root() -> str:
    """The server's own tree: repository root (web) or install root (desktop)."""
    if _cloud():
        return ''
    from ai import environment

    if environment.kind() == 'desktop':
        return os.path.dirname(os.path.abspath(sys.executable))
    return environment.code_root()


def volumes() -> list[dict]:
    """The filesystem's roots: drives on Windows, mounts elsewhere.

    A picker that only walks DOWN from ``C:\\`` can never leave it: ``dirname('C:\\\\')`` is itself,
    so at the drive root the parent button disappeared and every other disk was unreachable. The
    list itself is the per-OS table in ``core.machine``; this module only refuses the callers it
    may not serve.
    """
    if _cloud() or not policy.may_administer_machine():
        return []
    return machine.filesystem_roots()


def browse(path: str = '', start_folder: str = '') -> dict:
    """Directories and files one level down, for the folder picker.

    ``path`` may be absolute (a picker walks the real filesystem) or empty (start at the account's
    working folder, else the user's home).
    """
    _refuse_machine()
    raw = os.path.expanduser(str(path or '').strip()) or str(start_folder or '') or str(Path.home())
    if not os.path.isabs(raw):
        raw = os.path.join(str(start_folder or '') or str(Path.home()), raw)
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
        'roots': volumes(),
        'home': str(Path.home()),
        'folder': str(start_folder or ''),
    }


def pick_folder(start: str = '', start_folder: str = '') -> dict:
    """Open the OS's own folder dialog and answer the path the user picked.

    The panel's picker walks one directory at a time; the system dialog can jump anywhere, shows
    mounted disks and remembers recent places. A closed dialog is a decision (``cancelled``), not a
    failure, and a machine with none of the per-OS dialogs is refused by name.
    """
    from i18n import t

    _refuse_machine()
    hint = os.path.expanduser(str(start or '').strip()) or str(start_folder or '') or str(Path.home())
    if not os.path.isdir(hint):
        hint = str(Path.home())
    timeout = 600
    for argv in machine.folder_dialog_commands(hint, t('ai.workspace.pickTitle')):
        try:
            proc = subprocess.run(argv, capture_output=True, timeout=timeout, check=False, **popen_kwargs())
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise AIError('ai.pickUnavailable', kind='capability', detail=str(exc)[:160]) from exc
        except subprocess.TimeoutExpired as exc:
            raise AIError('ai.pickTimeout', kind='error', seconds=timeout) from exc
        # Every one of these dialogs exits non-zero when the user closes it (zenity/kdialog 1,
        # osascript -128); that is a choice, so it is reported, never raised.
        if proc.returncode != 0:
            return {'path': '', 'cancelled': True}
        picked = _decode(proc.stdout or b'').strip().strip('"')
        if not picked:
            return {'path': '', 'cancelled': True}
        resolved = os.path.realpath(picked)
        if not os.path.isdir(resolved):
            raise AIError('ai.workspaceNotFound', kind='not_found', path=picked)
        return {'path': resolved, 'cancelled': False}
    raise AIError('ai.pickUnavailable', kind='capability', detail='no system folder dialog')


def _decode(raw: bytes) -> str:
    """A dialog's output, decoded without assuming the console code page."""
    for encoding in ('utf-8', 'utf-16', 'gbk', 'latin-1'):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode('utf-8', errors='replace')


def import_path(target: str, name: str = '', display: str = '') -> dict:
    """Import an ABSOLUTE path (the framework's workspace already resolved it)."""
    import pandas as pd
    from runtime.stores import _register_dataset

    from services.biblio.importer import BiblioDecodeError, decode_text, parse_bytes, parse_frame, parse_text
    from services.datasets.store import SOURCE_UPLOAD

    if not os.path.isfile(target):
        raise AIError('ai.workspaceNotFile', kind='bad_request', path=display or target)
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
