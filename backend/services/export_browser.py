"""Reading side of ``EXPORT_DIR``: list, download, delete.

Exports have always been write-only — a run produced files under
``data/exports`` and the only way to find them was to open a file manager. That
is a strange shape for a tool whose whole output IS files, so this is the reader:
a bounded listing the panel can sort, a download that can only name a file that
is really there, and a delete that can only remove one file at a time.

Path safety is the point of doing this in one place rather than three
endpoints. Every entry point takes a *name*, never a path, and resolves it
through :func:`resolve_export_file`, which rejects separators, traversal and
anything that lands outside the export directory after resolution. A browser
that sends ``..\\..\\config.py`` gets a 404, not the repository's source.

Nothing here deletes on a clock (that is housekeeping's job) and nothing here
walks subdirectories: exports are flat by construction, and a recursive delete
is the kind of convenience that eventually removes something the user meant to
keep.
"""

import logging
import os

from i18n import t
from utils.helpers import sanitize_filename

logger = logging.getLogger(__name__)

#: Refused extensions. The panel can show the file but must not hand back a
#: script or an executable with a content type that a browser might act on.
UNSAFE_DOWNLOADS = ('.py', '.js', '.html', '.htm', '.exe', '.bat', '.cmd', '.sh', '.dll')

#: A listing this long stops being useful and starts being a memory problem;
#: the caller pages by narrowing the prefix instead.
MAX_ENTRIES = 500

#: Recognised kinds, so the panel can label a row without parsing the name.
KINDS = {
    '.csv': 'csv',
    '.json': 'json',
    '.xlsx': 'excel',
    '.xls': 'excel',
    '.txt': 'text',
    '.md': 'markdown',
    '.png': 'image',
    '.html': 'report',
    '.htm': 'report',
}

#: The report writer's own prefix. A name outside it is not a report, whatever
#: its extension claims — see :func:`resolve_report_path`.
REPORT_PREFIX = 'report-'


def resolve_report_path(export_dir: str, name: str) -> str:
    """One generated report's resolved path, or '' when it is not one.

    ``.html`` is on the refused-to-download list on purpose: a file the browser
    renders in this app's origin can read this app's pages. A report is still
    worth showing, so it gets its own door instead of the general one — only a
    name this product's own writer produces resolves, and the route that serves
    it sends a Content-Security-Policy that forbids script. Anything else — a
    stray page dropped into the folder, another user's file — answers as it would
    for a path outside the directory: nothing found.
    """
    cleaned = sanitize_filename(name)
    if not cleaned.startswith(REPORT_PREFIX):
        return ''
    if os.path.splitext(cleaned)[1].lower() not in ('.html', '.htm'):
        return ''
    path = resolve_export_file(export_dir, cleaned)
    return path if os.path.splitext(path)[1].lower() in ('.html', '.htm') else ''


def list_exports(export_dir: str, limit: int = MAX_ENTRIES) -> list:
    """Every file in *export_dir*, newest first, with size and mtime.

    Unreadable entries are skipped rather than failing the listing: one file
    locked by Excel must not empty the panel.
    """
    if not export_dir or not os.path.isdir(export_dir):
        return []
    entries = []
    with os.scandir(export_dir) as handles:
        for entry in handles:
            try:
                if not entry.is_file(follow_symlinks=False):
                    continue
                stat = entry.stat()
            except OSError:
                continue
            extension = os.path.splitext(entry.name)[1].lower()
            entries.append(
                {
                    'name': entry.name,
                    'size': stat.st_size,
                    'mtime': int(stat.st_mtime),
                    'kind': KINDS.get(extension, 'other'),
                    'downloadable': extension not in UNSAFE_DOWNLOADS,
                }
            )
    entries.sort(key=lambda row: (row['mtime'], row['name']), reverse=True)
    return entries[: max(1, min(int(limit or MAX_ENTRIES), MAX_ENTRIES))]


def resolve_export_file(export_dir: str, name: str) -> str:
    """The absolute path of export file *name*, or '' when it is not one.

    Three separate reasons a name can be bad and they all answer the same way:
    empty. A caller that distinguishes "not found" from "not allowed" would be
    handing out a directory oracle, so both cases return '' and the endpoints
    both answer 404.
    """
    cleaned = sanitize_filename(name)
    if not cleaned or not export_dir:
        return ''
    root = os.path.realpath(export_dir)
    candidate = os.path.realpath(os.path.join(root, cleaned))
    if candidate == root or not candidate.startswith(root + os.sep):
        return ''
    if not os.path.isfile(candidate):
        return ''
    return candidate


def is_downloadable(path: str) -> bool:
    """Whether a resolved export path may be handed to a browser."""
    return os.path.splitext(path)[1].lower() not in UNSAFE_DOWNLOADS


def resolve_download_path(export_dir: str, name: str) -> str:
    """Like :func:`resolve_export_file`, and additionally refuses the kinds the
    listing already marks ``downloadable: False``.

    The flag has to be enforced here rather than trusted from the panel: a
    listing that says "not downloadable" while ``?name=`` still returns the file
    is a rule that only exists in the UI, and the UI is the part an attacker
    edits. Deletion keeps using :func:`resolve_export_file` — removing a stray
    script from the export folder is legitimate, serving it is not.
    """
    path = resolve_export_file(export_dir, name)
    if not path or not is_downloadable(path):
        return ''
    return path


def delete_export_file(export_dir: str, name: str) -> bool:
    """Remove ONE export file. True when it is gone afterwards.

    A missing file is not an error to report as success-with-nothing: the caller
    asked for a state, and after this returns the state holds.
    """
    path = resolve_export_file(export_dir, name)
    if not path:
        return False
    try:
        os.remove(path)
    except OSError as e:
        logger.warning(t('misc.exportDeleteFailed', name=name, err=e))
        return not os.path.exists(path)
    return not os.path.exists(path)


def export_usage(export_dir: str) -> dict:
    """Totals for the panel header, from the same listing it displays."""
    rows = list_exports(export_dir)
    return {'files': len(rows), 'bytes': sum(int(row['size'] or 0) for row in rows)}
