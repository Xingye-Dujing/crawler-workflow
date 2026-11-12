"""The environment and component routes behind the 设置 → 环境与组件 panel.

The panel is a view of the same catalogue and probe the installer uses. Nothing here downloads on a
GET: a click starts a background job and the panel polls, because a 1.5 GB archive is not an HTTP
request any browser should hold open.

The catalogue is the bundled one; a release may later point the app at a newer catalogue with a
setting, and the only change here is which path is passed to :func:`load_catalog`.
"""

from __future__ import annotations

from contextlib import suppress

from flask import Blueprint, jsonify
from runtime.state import any_run_live

from api.auth import is_admin
from api.http import _json_body
from i18n import t
from services.accounts.service import accounts_mode
from services.components import jobs
from services.components.catalog import Catalog, CatalogError, load_catalog
from services.components.install import InstallError, remove_component
from services.components.manifest import Manifest, ManifestError
from services.components.paths import install_root
from services.components.probe import environment

bp = Blueprint('components', __name__)


def _admin_refusal():
    """Why this caller may not change what is installed on this machine.

    ``install_root()`` is one tree shared by every account (the launch path exports it into
    ``CHROME_PATH``/``CIXI_DRIVER_PATH``/``CIXI_NODE_BIN`` for all of them), so installing or
    removing a component rewrites what every account's next run spawns — the same machine-level
    write ``/api/settings`` and ``/api/lexicon`` guard with 403. The panel hides the buttons;
    hiding is cosmetic, the 403 is the permission.
    """
    if accounts_mode() and not is_admin():
        return jsonify({'ok': False, 'error': t('accounts.adminRequired')}), 403
    return None


def _admin() -> bool:
    return not accounts_mode() or is_admin()


def _catalog() -> Catalog:
    return Catalog(load_catalog())


def _rows(catalog: Catalog) -> list[dict]:
    manifest = Manifest(install_root())
    # An unreadable manifest means "nothing is known to be installed"; it must not blank the whole
    # panel, and the environment report already names the broken file.
    with suppress(ManifestError):
        manifest.load()
    # A component's folder is a host path — the same fingerprint ``/api/settings`` blanks for a
    # non-administrator. The panel only needs it to show where a thing lives, which is the
    # operator's business, so an ordinary account gets the same answer as the settings panel.
    show_paths = _admin()
    rows = []
    for component in catalog.components.values():
        record = manifest.get(component.id) or {}
        target = manifest.path_of(component.id)
        asset = component.asset()
        # The running application cannot replace itself (its own files are open), so a new build is
        # the online installer's job — it moves the old folder to app.previous for a rollback.
        downloadable = asset is not None and component.id != 'app'
        # A record whose folder is gone is not an installation: the version is what the manifest
        # says, the installation is what exists on disk.
        installed_version = str(record.get('version') or '') if target else ''
        rows.append(
            {
                'id': component.id,
                'version': component.version,
                'label': component.label,
                'summary': component.summary,
                'default': component.default,
                'kind': component.kind,
                'requires': list(component.requires),
                'provides': list(component.provides),
                'license': component.license,
                'homepage': component.homepage,
                'notes': component.notes,
                'size': asset.size if asset else 0,
                'downloadable': downloadable,
                'installed': installed_version,
                'path': (record.get('path') or '') if show_paths else '',
                'update': bool(installed_version and installed_version != component.version),
            }
        )
    return rows


@bp.route('/api/environment', methods=['GET'])
def get_environment():
    """One row per capability: ok / degraded / missing / unknown, with a reason key."""
    report = environment()
    if not _admin():
        # ``root`` and the reason parameters carry absolute host paths (the configured
        # chromedriver, xelatex, CatBus entry). The panel needs the STATE and the reason key,
        # not the layout of this machine.
        report['root'] = ''
        for capability in report.get('capabilities', []):
            params = capability.get('reason_params')
            if isinstance(params, dict):
                capability['reason_params'] = {
                    key: value
                    for key, value in params.items()
                    if key not in ('path', 'chrome', 'driver', 'entry', 'node')
                }
    return jsonify({'ok': True, **report})


@bp.route('/api/components', methods=['GET'])
def get_components():
    try:
        catalog = _catalog()
    except CatalogError as exc:
        return jsonify({'ok': False, 'error': t('components.catalogFailed', err=str(exc))}), 500
    return jsonify({'ok': True, 'components': _rows(catalog)})


@bp.route('/api/components/install', methods=['POST'])
def install_component():
    refusal = _admin_refusal()
    if refusal is not None:
        return refusal
    if any_run_live():
        # A download unpacks over the very chromedriver/Node/xelatex a live crawl is spawning.
        return jsonify({'ok': False, 'error': t('components.installBusy')}), 409
    payload = _json_body()
    if payload is None:
        return jsonify({'ok': False, 'error': t('api.bodyNotObject')}), 400
    component_id = str(payload.get('id') or '').strip()
    try:
        catalog = _catalog()
        component = catalog.get(component_id)
    except CatalogError as exc:
        return jsonify({'ok': False, 'error': t('components.unknown', component=component_id, err=str(exc))}), 400
    if component_id == 'app':
        return jsonify({'ok': False, 'error': t('components.appNotSelfInstallable')}), 400
    if component.asset() is None:
        return (
            jsonify({'ok': False, 'error': t('components.notDownloadable', component=component_id)}),
            400,
        )
    job = jobs.start(catalog, component_id, install_root())
    return jsonify({'ok': True, 'job': job, 'message': t('components.installStarted', component=component_id)})


@bp.route('/api/components/jobs/<job_id>', methods=['GET'])
def get_job(job_id: str):
    # The install/remove/cancel doors are admin-only; the poll is the fourth door to the same
    # machine-level operation and used to be the one without a check (it also carries the
    # install path in ``error``/``path``).
    refusal = _admin_refusal()
    if refusal is not None:
        return refusal
    job = jobs.get(job_id)
    if job is None:
        return jsonify({'ok': False, 'error': t('components.jobMissing')}), 404
    return jsonify({'ok': True, 'job': job})


@bp.route('/api/components/jobs/<job_id>/cancel', methods=['POST'])
def cancel_job(job_id: str):
    refusal = _admin_refusal()
    if refusal is not None:
        return refusal
    if jobs.get(job_id) is None:
        return jsonify({'ok': False, 'error': t('components.jobMissing')}), 404
    jobs.cancel(job_id)
    return jsonify({'ok': True})


@bp.route('/api/components/remove', methods=['POST'])
def remove():
    refusal = _admin_refusal()
    if refusal is not None:
        return refusal
    if any_run_live():
        return jsonify({'ok': False, 'error': t('components.installBusy')}), 409
    payload = _json_body()
    if payload is None:
        return jsonify({'ok': False, 'error': t('api.bodyNotObject')}), 400
    component_id = str(payload.get('id') or '').strip()
    try:
        removed = remove_component(install_root(), component_id)
    except InstallError as exc:
        return jsonify({'ok': False, 'error': t('components.removeFailed', component=component_id, err=str(exc))}), 400
    return jsonify({'ok': True, 'removed': removed})
