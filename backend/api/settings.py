"""Runtime settings Blueprint — ``/api/settings`` and its schema/export/import/preset routes.

The values live in ``data/settings.json`` (``runtime.settings``), and the declaration
they are validated against lives in ``runtime.settings_schema``. The panel renders
itself from ``GET /api/settings/schema`` instead of keeping a second list of fields,
so a setting cannot exist in the store yet be missing from the page.

Who may do what:

* an administrator may read everything and may write, export, import and apply a preset;
* any other signed-in account may READ the values its own runs live under, but not
  change them — one account must not be able to move every other account's
  chromedriver, browser or proxy. Machine paths are hidden from a non-administrator
  because they are a fingerprint of the host, not something its runs need.
"""

from flask import Blueprint, jsonify, request
from runtime.settings import (
    all_settings,
    apply_preset,
    export_payload,
    import_payload,
    preset_state,
    restore_preset,
    save_settings,
    schema_payload,
)
from runtime.settings_schema import MACHINE_KEYS

from api.auth import is_admin
from api.http import _bad_body, _json_body
from i18n import t
from services.accounts.service import accounts_mode
from services.components import source as component_source

bp = Blueprint('settings', __name__)

#: Kept as a name older code/tests import; the authority is the schema.
_MACHINE_PATH_KEYS = MACHINE_KEYS


def _is_admin() -> bool:
    """Whether this caller may mutate machine-wide settings."""
    return not accounts_mode() or is_admin()


def _visible(values: dict, admin: bool) -> dict:
    """The settings as this caller may see them: everything for an admin, no host paths otherwise."""
    if admin or not isinstance(values, dict):
        return dict(values)
    return {key: ('' if key in _MACHINE_PATH_KEYS else value) for key, value in values.items()}


def _refuse_write():
    return jsonify({'ok': False, 'error': t('accounts.adminRequired')}), 403


@bp.route('/api/settings', methods=['GET'])
def get_runtime_settings():
    admin = _is_admin()
    return jsonify(
        {
            'ok': True,
            'settings': _visible(all_settings(), admin),
            # Told, not inferred: the panel disables its fields rather than letting the user
            # fill one in and meet a 403 at save time.
            'read_only': not admin,
            'preset': preset_state(),
        }
    )


@bp.route('/api/settings/schema', methods=['GET'])
def get_settings_schema():
    """The declaration the panel renders: groups, field metadata and preset ids.

    A machine-local default (the configured driver/CatBus/xelatex path) is part of the host's
    fingerprint, and ``MACHINE_KEYS``' own contract says it is never visible to a non-admin.
    The values endpoint already hides it; the schema leaked the same path through ``default``.
    """
    schema = schema_payload()
    if not _is_admin():
        for field in schema.get('settings', []):
            if field.get('key') in MACHINE_KEYS:
                field['default'] = ''
    schema['installer_available'] = component_source.installer_available()
    return jsonify({'ok': True, 'schema': schema, 'read_only': not _is_admin()})


@bp.route('/api/settings', methods=['POST'])
def set_runtime_settings():
    if not _is_admin():
        return _refuse_write()
    data = _json_body()
    if data is None:
        return _bad_body()
    patch = data.get('settings') if isinstance(data.get('settings'), dict) else data
    values, warnings = save_settings(patch or {})
    return jsonify({'ok': True, 'settings': values, 'warnings': warnings, 'preset': preset_state()})


@bp.route('/api/settings/export', methods=['GET'])
def export_settings():
    """Download a settings package. Machine paths need an explicit opt-in."""
    if not _is_admin():
        return _refuse_write()
    include_machine = str(request.args.get('include_machine') or '').strip().lower() in ('1', 'true', 'yes', 'on')
    payload = export_payload(include_machine=include_machine)
    response = jsonify(payload)
    stamp = payload.get('exported_at', '')[:19].replace(':', '').replace('-', '').replace('T', '-')
    response.headers['Content-Disposition'] = f'attachment; filename="crawler-settings-{stamp or "export"}.json"'
    return response


@bp.route('/api/settings/import', methods=['POST'])
def import_settings():
    """Validate (and, unless ``dry_run``, apply) a settings package.

    ``dry_run`` is the default the panel uses first: it shows the diff and warnings
    before anything is written. ``mode='replace'`` needs ``confirm_replace`` so a
    mistyped package cannot silently reset an unrelated setting.
    """
    if not _is_admin():
        return _refuse_write()
    data = _json_body()
    if data is None:
        return _bad_body()
    payload = data.get('payload') if isinstance(data.get('payload'), dict) else data
    mode = str(data.get('mode') or 'merge').strip().lower()
    if mode == 'replace' and data.get('confirm_replace') is not True:
        return jsonify({'ok': False, 'error': t('set.importConfirmReplace')}), 400
    result = import_payload(
        payload,
        mode=mode,
        include_machine=bool(data.get('include_machine')),
        dry_run=bool(data.get('dry_run')),
    )
    status = 200 if result.get('ok') else 400
    return jsonify(result), status


@bp.route('/api/settings/preset', methods=['POST'])
def set_settings_preset():
    """Apply or restore a named preset (慢速采集) as one atomic step."""
    if not _is_admin():
        return _refuse_write()
    data = _json_body()
    if data is None:
        return _bad_body()
    action = str(data.get('action') or 'apply').strip().lower()
    warnings: list = []
    if action == 'restore':
        values, warnings = restore_preset()
        ok = True
    elif action == 'apply':
        try:
            values, warnings = apply_preset(str(data.get('preset') or 'slow'))
        except KeyError as exc:
            return jsonify({'ok': False, 'error': str(exc.args[0] if exc.args else exc)}), 400
        ok = True
    else:
        return jsonify({'ok': False, 'error': t('set.presetBadAction', action=action)}), 400
    return jsonify({'ok': ok, 'settings': _visible(values, True), 'warnings': warnings, 'preset': preset_state()})
