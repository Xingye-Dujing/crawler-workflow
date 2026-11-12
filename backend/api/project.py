"""Project bundles: download one zip, upload one zip.

The packaging logic lives in ``services.workflows.bundle``; this module resolves "which
workflows", moves the file, and turns a named refusal into a 4xx. Export is a GET
because it changes nothing; import is a multipart POST because the bundle is a file,
not JSON. Neither route executes a workflow.

Import runs OFF the request thread (:mod:`services.reports.jobs`). A bundle may unpack into
hundreds of MiB of datasets, and the request thread is the one that serves every other panel: a
minute of blocking there looked like a hung server, and a reverse proxy could cut the reply while
the import kept writing. The upload is copied to a temp file first — the request's own stream is
closed when the response is sent — and the worker deletes it in ``finally``.
"""

import contextlib
import io
import os
import shutil
import tempfile
import threading

from flask import Blueprint, jsonify, request, send_file

from i18n import t
from services.reports import jobs
from services.workflows.bundle import build_bundle, import_bundle
from services.workflows.manager import WorkflowManager

bp = Blueprint('project', __name__)

#: Two bundles at once could pick the same "name (2)" for one workflow: the name search reads the
#: directory and then saves. The job registry allows two workers, so the write phase takes this lock.
_IMPORT_LOCK = threading.Lock()


def _discard(path: str) -> None:
    with contextlib.suppress(OSError):
        os.unlink(path)


def _import_work(path: str):
    """The job body: unpack the temp file, answer the JSON the synchronous route used to return."""

    def work() -> tuple[int, dict]:
        try:
            with _IMPORT_LOCK, open(path, 'rb') as bundle:
                summary = import_bundle(bundle, workflow_manager=WorkflowManager())
        except ValueError as e:
            return 400, {'ok': False, 'error': str(e)}
        finally:
            _discard(path)
        return 200, {'ok': True, 'summary': summary}

    return work


@bp.route('/api/project/export', methods=['GET'])
def export_project():
    manager = WorkflowManager()
    all_workflows = str(request.args.get('all') or '').strip().lower() in ('1', 'true', 'yes')
    workflow = str(request.args.get('workflow') or '').strip()
    names = manager.list_workflows() if all_workflows else ([workflow] if workflow else [])
    try:
        payload, filename, warnings = build_bundle(names, workflow_manager=manager)
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    response = send_file(
        io.BytesIO(payload),
        mimetype='application/zip',
        as_attachment=True,
        download_name=filename,
    )
    response.headers['X-Project-Warnings'] = str(len(warnings))
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.route('/api/project/import', methods=['POST'])
def import_project():
    upload = request.files.get('file')
    if upload is None or not str(getattr(upload, 'filename', '') or ''):
        return jsonify({'ok': False, 'error': t('project.noFile')}), 400
    descriptor, path = tempfile.mkstemp(prefix='cixi-project-', suffix='.zip')
    try:
        with os.fdopen(descriptor, 'wb') as target:
            shutil.copyfileobj(upload.stream, target, 1024 * 1024)
    except OSError:
        _discard(path)
        raise
    try:
        job = jobs.start('project_import', _import_work(path))
    except BaseException:
        # ``jobs.start`` re-raises a thread that could not start; the worker's own ``finally`` never
        # ran, so the temp file would stay behind unseen.
        _discard(path)
        raise
    if job is None:
        _discard(path)
        return jsonify({'ok': False, 'error': t('project.importBusy')}), 409
    return jsonify({'ok': True, 'job': job}), 202
