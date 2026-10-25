"""Reusable node templates: the picker's list, full reads, save and delete.

The template is validated in ``services.reusable_store`` (types, wiring, one terminal,
one input meaning per slot), so a fragment that cannot be expanded is refused before it
is ever offered to a canvas. No endpoint executes a template.
"""

from flask import Blueprint, jsonify, request

from api.http import _bad_body, _bad_param, _json_body
from i18n import t
from services.reusable_store import (
    TemplateCorruptError,
    delete_template,
    get_template,
    list_templates,
    rename_template,
    save_template,
)

bp = Blueprint('reusable', __name__)


@bp.route('/api/reusable', methods=['GET'])
def reusable_list():
    return jsonify({'ok': True, 'templates': list_templates()})


@bp.route('/api/reusable/get', methods=['GET'])
def reusable_get():
    template_id = str(request.args.get('id') or '')
    try:
        template = get_template(template_id)
    except TemplateCorruptError:
        return jsonify({'ok': False, 'error': t('reusable.corrupt', id=template_id)}), 409
    if template is None:
        return jsonify({'ok': False, 'error': t('reusable.missing', id=template_id or '(empty)')}), 404
    return jsonify({'ok': True, 'template': template})


@bp.route('/api/reusable/save', methods=['POST'])
def reusable_save():
    data = _json_body()
    if data is None:
        return _bad_body()
    if data.get('name') is not None and not isinstance(data.get('name'), str):
        return _bad_param('name')
    if data.get('id') is not None and not isinstance(data.get('id'), str):
        return _bad_param('id')
    try:
        template = save_template(data)
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    return jsonify({'ok': True, 'template': template})


@bp.route('/api/reusable/rename', methods=['POST'])
def reusable_rename():
    data = _json_body()
    if data is None:
        return _bad_body()
    template_id = data.get('id')
    name = data.get('name')
    if not isinstance(template_id, str):
        return _bad_param('id')
    if not isinstance(name, str):
        return _bad_param('name')
    try:
        template = rename_template(template_id, name)
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    if template is None:
        return jsonify({'ok': False, 'error': t('reusable.missing', id=template_id or '(empty)')}), 404
    return jsonify({'ok': True, 'template': template})


@bp.route('/api/reusable/delete', methods=['POST'])
def reusable_delete():
    data = _json_body()
    if data is None:
        return _bad_body()
    template_id = data.get('id')
    if not isinstance(template_id, str):
        return _bad_param('id')
    return jsonify({'ok': True, 'deleted': delete_template(template_id)})
