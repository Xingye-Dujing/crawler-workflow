"""Find model manifests at call time: the operator may add one while the server is running.

Versioned manifests live in ``tools/model_manifests/``; local additions and downloaded checkpoints
live in ``data/models/<id>/model.json``. Every path is resolved against the application root, never
a module constant, so a test with its own ``CRAWLER_DATA_ROOT`` sees only its own overrides. A
malformed manifest refuses by name instead of disappearing -- silence would present a broken model
as "nothing configured".
"""

import json
import os

from core.config import BASE_DIR
from runtime import paths

from services.models.manifest import ModelManifest, from_legacy, read_manifest_file


class ManifestFileError(ValueError):
    """A manifest file exists but cannot be interpreted."""


def manifest_roots() -> tuple[str, ...]:
    return (
        os.path.join(BASE_DIR, 'tools', 'model_manifests'),
        paths.models_manifest_dir(),
        os.path.join(BASE_DIR, 'bert_models'),
    )


def _manifest_files(root: str) -> list[str]:
    """Flat ``<id>.json`` and nested ``<id>/model.json`` are both legal manifest layouts."""
    if not os.path.isdir(root):
        return []
    found = []
    for child in sorted(os.scandir(root), key=lambda entry: entry.name):
        if child.is_file() and child.name.endswith('.json'):
            found.append(child.path)
        elif child.is_dir():
            candidate = os.path.join(child.path, 'model.json')
            if os.path.isfile(candidate):
                found.append(candidate)
    return found


def load() -> list[ModelManifest]:
    """Declared manifests first (operator preference), then legacy rows in registry order."""
    models = []
    seen: set[str] = set()
    for root in manifest_roots():
        for manifest_path in _manifest_files(root):
            try:
                manifest = read_manifest_file(manifest_path, base_dir=BASE_DIR)
            except (OSError, ValueError) as exc:
                raise ManifestFileError(f'{manifest_path}: {exc}') from exc
            if manifest.id in seen:
                raise ManifestFileError(f'{manifest_path}: duplicate model id {manifest.id!r}')
            seen.add(manifest.id)
            models.append(manifest)
    for row in _legacy_rows_raw():
        manifest = from_legacy(row)
        if manifest is not None and manifest.id not in seen:
            seen.add(manifest.id)
            models.append(manifest)
    return models


def _legacy_rows_raw() -> list[dict]:
    try:
        with open(paths.model_registry_json(), encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict) and str(row.get('path') or '').strip()]
