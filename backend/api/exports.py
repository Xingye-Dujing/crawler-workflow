"""导出文件 Blueprint — the ``/api/exports/*`` cluster, split out of ``app.py``.

The export folder's browser: list / download / delete / clear. Every helper it needs is
already reachable without importing ``app`` — the file operations live in
``services.export_browser`` (imported lazily, as before), the request coercions in
``api.http``, the lock ledger in ``services.lock_store``, and the run-in-flight check in
``state.execution_state``. Paths and behaviour are unchanged.
"""

import logging
import os

from flask import Blueprint, jsonify, request
from state import execution_state

from api.http import _bad_body, _bad_param, _json_body, _safe_int
from config import Config
from i18n import t
from services import lock_store

logger = logging.getLogger(__name__)

bp = Blueprint('exports', __name__)


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
        if removed == before:
            break
    left = len(list_exports(Config.EXPORT_DIR))
    logger.warning(t('exports.cleared', n=removed))
    return jsonify({'ok': True, 'removed': removed, 'left': left})
