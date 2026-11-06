"""The environment and component routes behind the 设置 → 环境与组件 panel.

The panel is a view of the same catalogue and probe the installer uses. Nothing here downloads on a
GET: a click starts a background job and the panel polls, because a 1.5 GB archive is not an HTTP
request any browser should hold open.

The catalogue is the bundled one; a release may later point the app at a newer catalogue with a
setting, and the only change here is which path is passed to :func:`load_catalog`.
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from api.http import _json_body
from i18n import t
from services.components import jobs
from services.components.catalog import Catalog, CatalogError, load_catalog
from services.components.install import InstallError, remove_component
from services.components.manifest import Manifest, ManifestError
from services.components.paths import components_root
from services.components.probe import environment

bp = Blueprint('components', __name__)


def _catalog() -> Catalog:
    return Catalog(load_catalog())


def _rows(catalog: Catalog) -> list[dict]:
    try:
        installed = Manifest(components_root()).load().installed()
    except ManifestError:
        installed = {}
    rows = []
    for component in catalog.components.values():
        record = installed.get(component.id) or {}
        asset = component.asset()
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
                'downloadable': asset is not None,
                'installed': record.get('version') or '',
                'path': record.get('path') or '',
                'update': bool(record.get('version') and record.get('version') != component.version),
            }
        )
    return rows


@bp.route('/api/environment', methods=['GET'])
def get_environment():
    """One row per capability: ok / degraded / missing / unknown, with a reason key."""
    return jsonify({'ok': True, **environment()})


@bp.route('/api/components', methods=['GET'])
def get_components():
    try:
        catalog = _catalog()
    except CatalogError as exc:
        return jsonify({'ok': False, 'error': t('components.catalogFailed', err=str(exc))}), 500
    return jsonify({'ok': True, 'components': _rows(catalog)})


@bp.route('/api/components/install', methods=['POST'])
def install_component():
    payload = _json_body()
    if payload is None:
        return jsonify({'ok': False, 'error': t('api.bodyNotObject')}), 400
    component_id = str(payload.get('id') or '').strip()
    try:
        catalog = _catalog()
        catalog.get(component_id)
    except CatalogError as exc:
        return jsonify({'ok': False, 'error': t('components.unknown', component=component_id, err=str(exc))}), 400
    job = jobs.start(catalog, component_id, components_root())
    return jsonify({'ok': True, 'job': job, 'message': t('components.installStarted', component=component_id)})


@bp.route('/api/components/jobs/<job_id>', methods=['GET'])
def get_job(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        return jsonify({'ok': False, 'error': t('components.jobMissing')}), 404
    return jsonify({'ok': True, 'job': job})


@bp.route('/api/components/jobs/<job_id>/cancel', methods=['POST'])
def cancel_job(job_id: str):
    if jobs.get(job_id) is None:
        return jsonify({'ok': False, 'error': t('components.jobMissing')}), 404
    jobs.cancel(job_id)
    return jsonify({'ok': True})


@bp.route('/api/components/remove', methods=['POST'])
def remove():
    payload = _json_body()
    if payload is None:
        return jsonify({'ok': False, 'error': t('api.bodyNotObject')}), 400
    component_id = str(payload.get('id') or '').strip()
    try:
        removed = remove_component(components_root(), component_id)
    except InstallError as exc:
        return jsonify({'ok': False, 'error': t('components.removeFailed', component=component_id, err=str(exc))}), 400
    return jsonify({'ok': True, 'removed': removed})
