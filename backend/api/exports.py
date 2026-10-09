"""导出文件 Blueprint — the ``/api/export/*`` cluster, split out of ``app.py``.

The export folder's writer and browser: ``/api/export/save`` writes a table out in any
format, and ``/api/exports/{list,download,delete,clear}`` read and manage what is there.
Every helper it needs is already reachable without importing ``app`` — the file operations
live in ``services.export_browser`` (imported lazily, as before), the request coercions in
``api.http``, the dataframe resolution in ``api.resolution``, the lock ledger in
``services.lock_store``, the format writers in ``services.exporter`` and the run-in-flight
check in ``state.execution_state``. Paths and behaviour are unchanged.
"""

import logging
import os

from flask import Blueprint, jsonify, request
from state import execution_state
from stores import get_run_store

from api.http import _bad_body, _bad_param, _json_body, _safe_int
from api.resolution import _resolve_payload_dataframe
from config import Config
from i18n import t
from services import lock_store
from services.exporter import DataExporter, UnsupportedFormatError
from utils.helpers import sanitize_filename

logger = logging.getLogger(__name__)

bp = Blueprint('exports', __name__)


def _delete_export_names(names) -> dict:
    """Delete a set of export files by name, one at a time, and keep the run ledger honest.

    Locked (「固定」) files are SKIPPED, never removed — the same rule ``/clear`` and ``/delete``
    already honour, so a pinned artefact outlives every bulk clear. A name already gone from disk
    counts as ``missing`` but still drops its ledger row, because the whole point of the ledger is
    to describe files that exist; a row pointing at nothing would make 智能清除 promise to delete
    what is already gone. Deletion always goes through the export browser's resolver (refuses
    traversal / outside-``EXPORT_DIR``), so a ledger row can never become a path oracle.
    """
    from services.export_browser import delete_export_file

    store = get_run_store()
    counts = {'removed': 0, 'skipped_locked': 0, 'missing': 0}
    for name in names:
        clean = os.path.basename(str(name or ''))
        if not clean:
            continue
        if lock_store.is_locked('exports', clean):
            counts['skipped_locked'] += 1
            continue
        if delete_export_file(Config.EXPORT_DIR, clean):
            counts['removed'] += 1
        else:
            counts['missing'] += 1
        store.forget_file(clean)
    return counts


@bp.route('/api/export/save', methods=['POST'])
def export_dataset():
    """Save any dataset (uploaded, pasted, cleaned, or a workflow result)
    to disk in the requested format — independent of a workflow's Save node."""
    data = _json_body()
    if data is None:
        return _bad_body()
    df, error = _resolve_payload_dataframe(data)
    if error is not None:
        return error

    # The exporter calls ``fmt.lower()`` and ``os.path.splitext(filename)`` on
    # what it is handed, so a number in either field raised AttributeError — a
    # 500 for a value the caller could simply have left out. The name is cleaned
    # *before* the format is inferred from its extension, so both calls below see
    # a real string.
    raw_format = data.get('format')
    if raw_format is not None and not isinstance(raw_format, str):
        return _bad_param('format')
    filename = sanitize_filename(data.get('filename', 'export.csv'))
    fmt = raw_format.strip() if isinstance(raw_format, str) else ''
    fmt = fmt or DataExporter.infer_format(filename)
    filename = DataExporter.normalize_filename(filename, fmt)
    filepath = os.path.join(Config.EXPORT_DIR, filename)
    try:
        text_column = data.get('text_column')
        result = DataExporter.save(
            df, filepath, fmt=fmt, text_column=text_column if isinstance(text_column, str) else None
        )
    except UnsupportedFormatError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except (TypeError, ValueError) as e:
        # A writer that cannot handle the frame's contents (an unhashable cell in
        # a json export) is still a request the caller can fix.
        return jsonify({'ok': False, 'error': str(e)}), 400
    except OSError as e:
        logger.exception(t('misc.export_failed'))
        return jsonify({'ok': False, 'error': str(e)}), 500
    return jsonify({'ok': True, **result})


@bp.route('/api/exports/list', methods=['GET'])
def exports_list():
    """Every export file, newest first, with the totals for the panel header."""
    from services.export_browser import export_usage, list_exports

    limit = _safe_int(request.args.get('limit'), 200, minimum=1, maximum=500)
    rows = list_exports(Config.EXPORT_DIR, limit=limit)
    usage = export_usage(Config.EXPORT_DIR)
    return jsonify({'ok': True, 'exports': rows, 'directory': Config.EXPORT_DIR, **usage})


@bp.route('/api/exports/download', methods=['GET'])
def exports_download():
    """Send one export file by name — never by path.

    An unresolvable name answers 404 the same way whether it was traversal or
    simply absent, because distinguishing them would turn this route into an
    oracle for what exists outside the export directory.
    """
    from flask import send_file

    from services.export_browser import resolve_download_path

    path = resolve_download_path(Config.EXPORT_DIR, request.args.get('name', ''))
    if not path:
        return jsonify({'ok': False, 'error': t('api.exportNotFound', name=request.args.get('name', ''))}), 404
    return send_file(path, as_attachment=True, download_name=os.path.basename(path))


@bp.route('/api/exports/delete', methods=['POST'])
def exports_delete():
    """Delete exactly one export file. No prefixes, no recursion."""
    from services.export_browser import delete_export_file

    data = _json_body()
    if data is None:
        return _bad_body()
    name = data.get('name')
    if not isinstance(name, str) or not name.strip():
        return _bad_param('name')
    if lock_store.is_locked('exports', name.strip()):
        return jsonify({'ok': False, 'error': t('lock.refuse')}), 409
    gone = delete_export_file(Config.EXPORT_DIR, name)
    if gone:
        lock_store.drop('exports', name.strip())
        get_run_store().forget_file(name.strip())
    return jsonify({'ok': gone, 'deleted': gone, 'name': os.path.basename(name.strip())})


@bp.route('/api/exports/clear', methods=['POST'])
def exports_clear():
    """Empty the export folder — the panel's 清空 button.

    One name at a time through :func:`delete_export_file`, over exactly the listing the panel
    shows. That is deliberate: the rules which stop a workflow-authored name from reaching
    outside ``data/exports`` (no sub-directories, no symlink pointing elsewhere, no prefix
    match) are then a single implementation that cannot drift from a second bulk one.

    Refused outright while a run is live — a streaming node is writing part files into this
    very directory, and the panel cannot tell a finished artefact from one still being appended.
    """
    from services.export_browser import delete_export_file, list_exports

    data = _json_body()
    if data is None:
        return _bad_body()
    if data.get('confirm') is not True:
        return jsonify({'ok': False, 'error': t('api.needConfirm')}), 400
    if execution_state['running']:
        return jsonify({'ok': False, 'error': t('exports.clearBusy')}), 409
    removed = 0
    # The listing is capped, so one pass is not necessarily the whole folder: keep going
    # while it shrinks. The loop's exit is "a pass removed nothing", which is the honest
    # answer for a file Excel still holds open — 清空 reports what is left rather than
    # pretending, and cannot spin.
    while True:
        before = removed
        for row in list_exports(Config.EXPORT_DIR):
            if lock_store.is_locked('exports', row['name']):
                # A locked artefact outlives 清空 — the user pinned it on purpose.
                continue
            if delete_export_file(Config.EXPORT_DIR, row['name']):
                removed += 1
                get_run_store().forget_file(row['name'])
        if removed == before:
            break
    left = len(list_exports(Config.EXPORT_DIR))
    logger.warning(t('exports.cleared', n=removed))
    return jsonify({'ok': True, 'removed': removed, 'left': left})


@bp.route('/api/exports/ledger', methods=['GET'])
def exports_ledger():
    """Every run that wrote export files, with its record header and its file list.

    Backs the 智能清除 selectors. Reads the run→files ledger, never the directory scan: only a run
    the ledger knows about can be cleared by record, so the panel offers exactly the actionable set.
    """
    return jsonify({'ok': True, 'ledger': get_run_store().run_ledger()})


def _smart_clear_guards(data):
    """Shared precondition for the two smart-clear routes: a response tuple to return, or None.

    A bulk clear of a run's files while ANY run is live is refused with 409 for the same reason
    ``/clear`` is: a streaming node is writing part files into this very directory and the ledger
    cannot tell the file just flushed from one still being appended. Requiring ``confirm`` keeps the
    door identical to every other destructive bulk action here (400 without it).
    """
    if data is None:
        return _bad_body()
    if data.get('confirm') is not True:
        return jsonify({'ok': False, 'error': t('api.needConfirm')}), 400
    if execution_state['running']:
        return jsonify({'ok': False, 'error': t('exports.clearBusy')}), 409
    return None


@bp.route('/api/exports/clear-run', methods=['POST'])
def exports_clear_run():
    """Remove every file one run wrote, by that run's ledger — 智能清除「按运行」.

    Deletes exactly the recorded names (through the browser's resolver, skipping 固定 files); the
    run record and its checkpointed ROWS are untouched — this clears disk artefacts, not history.
    """
    data = _json_body()
    refusal = _smart_clear_guards(data)
    if refusal is not None:
        return refusal
    run_id = data.get('run_id')
    if not isinstance(run_id, str) or not run_id.strip():
        return _bad_param('run_id')
    store = get_run_store()
    files = store.files_for_run(run_id.strip())
    result = _delete_export_names([f['name'] for f in files])
    result['ok'] = True
    result['run_id'] = run_id.strip()
    result['requested'] = len(files)
    return jsonify(result)


@bp.route('/api/exports/clear-run-parts', methods=['POST'])
def exports_clear_run_parts():
    """Remove only one source node's shards from one run, keeping the merged file — 智能清除「按节点」.

    Scoped to ``(run_id, node_id, kind='part')`` so it can never touch a different run, a different
    node, or the merged/live result the run still needs. This is the routine cleanup after a
    batched crawl: the parts did their job feeding the merge, and now they are just clutter.
    """
    data = _json_body()
    refusal = _smart_clear_guards(data)
    if refusal is not None:
        return refusal
    run_id = data.get('run_id')
    node_id = data.get('node_id')
    if not isinstance(run_id, str) or not run_id.strip():
        return _bad_param('run_id')
    if not isinstance(node_id, str) or not node_id.strip():
        return _bad_param('node_id')
    store = get_run_store()
    files = store.files_for_run(run_id.strip(), node_id=node_id.strip(), kind='part')
    result = _delete_export_names([f['name'] for f in files])
    result['ok'] = True
    result['run_id'] = run_id.strip()
    result['node_id'] = node_id.strip()
    result['requested'] = len(files)
    return jsonify(result)
