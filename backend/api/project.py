"""Project bundles: download one zip, upload one zip.

The packaging logic lives in ``services.workflows.bundle``; this module resolves "which
workflows", moves the file, and turns a named refusal into a 4xx. Export is a GET
because it changes nothing; import is a multipart POST because the bundle is a file,
not JSON. Neither route executes a workflow.
"""

import io

from flask import Blueprint, jsonify, request, send_file

from i18n import t
from services.workflows.bundle import build_bundle, import_bundle
from services.workflows.manager import WorkflowManager

bp = Blueprint('project', __name__)


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
    try:
        summary = import_bundle(upload.stream, workflow_manager=WorkflowManager())
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    return jsonify({'ok': True, 'summary': summary})
