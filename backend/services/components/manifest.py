"""What is actually installed: one JSON file beside the components, never a database.

The manifest is the only record the app trusts when it decides which Chrome, Node or CatBus to use.
It must therefore be written atomically (a half-written JSON beside a working install is worse than
no record at all) and it must never contain a path outside its own root: an archive that escapes its
directory is a security failure, not a configuration.

The file lives at ``<root>/install-manifest.json`` and paths inside it are relative to ``<root>``
with forward slashes, so moving the whole installation to another drive keeps working.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from core.atomic import replace as atomic_replace

SCHEMA = 1
MANIFEST_NAME = 'install-manifest.json'


class ManifestError(Exception):
    """A manifest that cannot be used, with the field that is wrong."""


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(text, encoding='utf-8')
    atomic_replace(temporary, path)


def _relative(root: Path, path: Path) -> str:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ManifestError(f'path escapes the install root: {path}') from exc
    return relative.as_posix()


class Manifest:
    """Read/write helpers for one installation root."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.path = self.root / MANIFEST_NAME
        self._data: dict[str, Any] = {'schema': SCHEMA, 'components': {}}

    def load(self) -> Manifest:
        if not self.path.exists():
            self._data = {'schema': SCHEMA, 'components': {}}
            return self
        try:
            payload = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise ManifestError(f'cannot read {self.path}: {exc}') from exc
        if not isinstance(payload, dict) or payload.get('schema') != SCHEMA:
            raise ManifestError(f'unsupported manifest schema in {self.path}')
        components = payload.get('components')
        if not isinstance(components, dict):
            raise ManifestError(f'manifest components must be an object: {self.path}')
        self._data = payload
        return self

    def save(self) -> None:
        payload = {**self._data, 'schema': SCHEMA, 'updated_at': _now()}
        _atomic_write(self.path, json.dumps(payload, ensure_ascii=False, indent=2) + '\n')

    def installed(self) -> dict[str, dict]:
        return dict(self._data.get('components') or {})

    def get(self, component_id: str) -> dict | None:
        return self.installed().get(component_id)

    def path_of(self, component_id: str) -> Path | None:
        record = self.get(component_id)
        if not record:
            return None
        path = self.root / str(record.get('path') or '')
        return path if path.exists() else None

    def record(self, component_id: str, version: str, path: Path, sha256: str, source: str) -> None:
        self._data.setdefault('components', {})[component_id] = {
            'version': version,
            'path': _relative(self.root, path),
            'sha256': sha256,
            'source': source,
            'installed_at': _now(),
        }

    def remove(self, component_id: str) -> bool:
        components = self._data.setdefault('components', {})
        return components.pop(component_id, None) is not None

    def prune(self, component_id: str, keep: int = 2) -> list[Path]:
        """Delete older version directories for one component, keeping the newest ``keep``.

        The manifest only names the current version, so pruning is driven by directory mtimes:
        the order the user installed them is the order that makes a rollback useful.
        """
        base = self.root / 'components' / component_id
        if not base.is_dir():
            return []
        versions = sorted(
            (item for item in base.iterdir() if item.is_dir()), key=lambda item: item.stat().st_mtime, reverse=True
        )
        removed: list[Path] = []
        for stale in versions[max(1, keep) :]:
            shutil.rmtree(stale, ignore_errors=True)
            removed.append(stale)
        return removed


def _now() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
