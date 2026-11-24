"""One run, one export folder.

The export directory used to be flat: a run's files were distinguishable only by the ledger. A
group is the folder a run owns, named ``{workflow}_{YYYY-MM-DD_HH-MM-SS}``, and this module is the
ONE place that names, creates and resolves it. Download/delete/list, the writer and the AI workspace
mount all ask here, so a name can never become a path oracle in one endpoint while another is safe.

A name is always a single path segment. ``group`` and ``name`` are validated separately, then the
resolved real path must still live under ``export_dir/<group>``.
"""

from __future__ import annotations

import os
import re
import time

from core.refs import sanitize_filename

MANUAL_GROUP = '_手动导出'
LEGACY_GROUP = '_历史产物'
GROUP_BYTES = 80
_STAMP = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$')


def _safe_segment(value: str, limit: int = 200) -> str:
    return sanitize_filename(str(value or ''), truncate=False)[:limit].strip(' .')


def group_name(workflow_name: str, started_at: str, export_dir: str, *, attempts: int = 1000) -> str:
    """A readable, collision-free folder name; the time is the run's own start, not today's clock."""
    stamp = str(started_at or '')
    when = stamp.replace('T', '_').replace(':', '-') if _STAMP.match(stamp) else time.strftime('%Y-%m-%d_%H-%M-%S')
    base = _safe_segment(workflow_name or '未命名运行', GROUP_BYTES) or '未命名运行'
    candidate = f'{base}_{when}'
    n = 1
    while os.path.exists(os.path.join(export_dir, candidate)):
        n += 1
        if n > attempts:
            raise OSError(f'cannot allocate export group under {export_dir}')
        candidate = f'{base}_{when}-{n}'
    return candidate


def resolve_group_dir(export_dir: str, group: str, *, must_exist: bool = False) -> str:
    """The resolved directory for *group*, or '' when the name is not one safe segment."""
    clean = _safe_segment(group, 200)
    if not clean or clean != str(group or '').strip() or clean in ('.', '..'):
        return ''
    root = os.path.realpath(export_dir)
    candidate = os.path.realpath(os.path.join(root, clean))
    if candidate == root or not candidate.startswith(root + os.sep):
        return ''
    if must_exist and not os.path.isdir(candidate):
        return ''
    return candidate


def ensure_group(export_dir: str, group: str) -> str:
    path = resolve_group_dir(export_dir, group)
    if not path:
        raise ValueError(f'invalid export group: {group!r}')
    os.makedirs(path, exist_ok=True)
    return path


def resolve_member(export_dir: str, group: str, name: str) -> str:
    """One file inside one group, or '' for traversal/absolute/missing."""
    directory = resolve_group_dir(export_dir, group, must_exist=True)
    if not directory:
        return ''
    clean = _safe_segment(name, 240)
    if not clean or clean != os.path.basename(str(name or '')) or clean in ('.', '..'):
        return ''
    candidate = os.path.realpath(os.path.join(directory, clean))
    if not candidate.startswith(directory + os.sep) or not os.path.isfile(candidate):
        return ''
    return candidate


def _root_files(export_dir: str, limit: int = 500) -> list[dict]:
    if not export_dir or not os.path.isdir(export_dir):
        return []
    rows = []
    with os.scandir(export_dir) as handles:
        for entry in handles:
            try:
                if not entry.is_file(follow_symlinks=False):
                    continue
                stat = entry.stat()
            except OSError:
                continue
            rows.append({'name': entry.name, 'size': stat.st_size, 'mtime': int(stat.st_mtime)})
    rows.sort(key=lambda row: (row['mtime'], row['name']), reverse=True)
    return rows[: max(1, int(limit or 500))]


def build_tree(export_dir: str, ledger: list[dict], limit: int = 500) -> list[dict]:
    """Groups for the panel, newest first. The run record is the group's identity.

    A run with no ``export_group`` (or a stray file at the root) is shown under the legacy group;
    the one-time migration moves those files into a real folder. The frontend never infers this.
    """
    seen: set[str] = set()
    groups: list[dict] = []
    for run in ledger or ():
        group = str(run.get('export_group') or LEGACY_GROUP)
        if group in seen:
            continue
        seen.add(group)
        files = list_group(export_dir, group, limit) if group != LEGACY_GROUP else _root_files(export_dir, limit)
        if group == LEGACY_GROUP and not files:
            files = list_group(export_dir, group, limit)
        if not files:
            continue
        groups.append(
            {
                'id': group,
                'label': group,
                'kind': 'run',
                'run_id': str(run.get('run_id') or ''),
                'workflow_name': str(run.get('workflow_name') or ''),
                'created_at': str(run.get('started_at') or ''),
                'files': files,
            }
        )
    manual = list_group(export_dir, MANUAL_GROUP)
    if manual:
        groups.append(
            {
                'id': MANUAL_GROUP,
                'label': MANUAL_GROUP,
                'kind': 'manual',
                'run_id': '',
                'workflow_name': '',
                'created_at': '',
                'files': manual,
            }
        )
    return groups


def list_group(export_dir: str, group: str, limit: int = 500) -> list[dict]:
    directory = resolve_group_dir(export_dir, group, must_exist=True)
    if not directory:
        return []
    rows = []
    with os.scandir(directory) as handles:
        for entry in handles:
            try:
                if not entry.is_file(follow_symlinks=False):
                    continue
                stat = entry.stat()
            except OSError:
                continue
            rows.append({'name': entry.name, 'size': stat.st_size, 'mtime': int(stat.st_mtime)})
    rows.sort(key=lambda row: (row['mtime'], row['name']), reverse=True)
    return rows[: max(1, int(limit or 500))]
