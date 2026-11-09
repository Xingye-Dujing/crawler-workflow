"""Installing one catalogue component into an installation root, atomically.

The layout is the contract the launcher and the app read:

.. code-block:: text

    <root>/app/...                       the application itself (one current copy)
    <root>/components/<id>/<version>/    everything else (current + previous kept)
    <root>/install-manifest.json         what was installed and from where

``install_as: app`` is special only in that there is one app folder rather than a version family:
the previous copy is moved aside, so a failed update leaves a rollback one rename away. Every other
component is versioned, which is what makes a rollback and pruning possible without redownloading.

Nothing here knows a Windows path. Extraction and archive names are POSIX inside the archive; the
only OS-specific part is which asset the catalogue supplied.
"""

from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from core.machine import platform_name

from services.components.archive import ArchiveError, safe_extract
from services.components.catalog import Asset, Catalog, Component
from services.components.fetch import DownloadError, download_asset
from services.components.manifest import Manifest, ManifestError

Progress = Callable[[int, int], None]
Cancel = Callable[[], bool]
Extract = Callable[[Path, Path, str, str], None]
ARCHIVE_SUFFIXES = {'zip': '.zip', 'tar.gz': '.tar.gz'}


class InstallError(Exception):
    """An installation that stopped; the message names the component and the step."""


def _verify_payload(payload: Path, verify: tuple[str, ...]) -> None:
    missing = [name for name in verify if not (payload / name).exists()]
    if missing:
        raise InstallError(f'the archive does not contain {", ".join(missing)}')


def _payload_ok(target: Path, verify: tuple[str, ...]) -> bool:
    return target.exists() and all((target / name).exists() for name in verify)


def _replace(target: Path, staging: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    os.replace(staging, target)


def _drop_empty(path: Path) -> None:
    """Remove a scratch directory that is empty again; never a folder with anything in it."""
    with suppress(OSError):
        path.rmdir()


def _platform_extract(archive: Path, staging: Path, archive_type: str, strip_prefix: str) -> None:
    """Unpack the way the target OS must: ditto/tar on macOS, the portable extractor elsewhere.

    A macOS ``.app`` loses its framework symlinks and executable bits under the portable
    extractor, so the platform's own tool is not an optimization — it is the only way the payload
    can run. See :mod:`services.components.macos`.
    """
    if platform_name() == 'darwin':
        from services.components.macos import extract_native

        extract_native(archive, staging, archive_type=archive_type, strip_prefix=strip_prefix)
        return
    safe_extract(archive, staging, archive_type=archive_type, strip_prefix=strip_prefix)


def install_component(
    catalog: Catalog,
    component_id: str,
    root: str | Path,
    *,
    system: str | None = None,
    progress: Progress | None = None,
    cancel: Cancel | None = None,
    allow_insecure: bool = False,
    keep_versions: int = 2,
    extract: Extract | None = None,
) -> Path:
    """Download, verify, extract and register one component; return its installed path."""
    component: Component = catalog.get(component_id)
    asset: Asset | None = component.asset(system)
    if asset is None:
        raise InstallError(f'{component_id} has no asset for {platform_name(system)}')
    base = Path(root)
    manifest = Manifest(base).load()
    for required in component.requires:
        if manifest.get(required) is None:
            raise InstallError(f'{component_id} needs {required}, which is not installed')

    suffix = ARCHIVE_SUFFIXES.get(asset.archive)
    if suffix is None:
        # A DMG carries a signed .app bundle and is mounted, not extracted; the desktop installer
        # owns that step. Saying so beats a KeyError from a component manager that never could.
        raise InstallError(f'{component_id}: {asset.archive} bundles are installed by the desktop installer')
    cache = base / '.cache' / f'{component_id}-{component.version}{suffix}'
    staging = base / '.staging' / f'{component_id}-{component.version}-{uuid.uuid4().hex[:8]}'
    try:
        archive = download_asset(asset, cache, progress=progress, cancel=cancel, allow_insecure=allow_insecure)
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True, exist_ok=True)
        try:
            (extract or _platform_extract)(archive, staging, asset.archive, asset.strip_prefix)
        except ArchiveError as exc:
            raise InstallError(f'cannot extract {component_id}: {exc}') from exc
        _verify_payload(staging, asset.verify)

        target = base / 'app' if asset.install_as == 'app' else base / 'components' / component_id / component.version
        # The app always lives in one folder, so "the file is there" cannot mean "this version is
        # there": a version bump would download the new build and then throw it away. Every other
        # component's folder name carries its version, which is why only the app compares versions.
        if asset.install_as == 'app':
            recorded = str((manifest.get(component_id) or {}).get('version') or '')
            already_installed = _payload_ok(target, asset.verify) and recorded == component.version
        else:
            already_installed = _payload_ok(target, asset.verify)
        if already_installed:
            shutil.rmtree(staging)
        elif asset.install_as == 'app':
            previous = base / 'app.previous'
            if target.exists():
                if previous.exists():
                    shutil.rmtree(previous)
                os.replace(target, previous)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            _replace(target, staging)
        manifest.record(component_id, component.version, target, asset.sha256, _source(asset))
        manifest.save()
        if asset.install_as != 'app':
            manifest.prune(component_id, keep=keep_versions)
        cache.unlink(missing_ok=True)
        _drop_empty(staging.parent)
        _drop_empty(cache.parent)
        return target
    except (InstallError, DownloadError, ManifestError, OSError):
        shutil.rmtree(staging, ignore_errors=True)
        _drop_empty(staging.parent)
        raise


def verify_component(catalog: Catalog, component_id: str, root: str | Path, *, system: str | None = None) -> Path:
    """Check an installed component's payload still exists; raise a named error when it does not."""
    component = catalog.get(component_id)
    asset = component.asset(system)
    if asset is None:
        raise InstallError(f'{component_id} has no asset for {platform_name(system)}')
    manifest = Manifest(root).load()
    path = manifest.path_of(component_id)
    if path is None:
        raise InstallError(f'{component_id} is not installed')
    _verify_payload(path, asset.verify)
    return path


def remove_component(root: str | Path, component_id: str) -> bool:
    """Delete a component family and its manifest row. The application itself is not removable.

    The bytes go first and the record second: a Chrome directory can hold a running browser, and a
    removal that deleted the record but left the folder would report "not installed" while the disk
    still holds it — and the next install would have to fight the leftover.
    """
    if component_id == 'app':
        raise InstallError('the application is removed by the uninstaller, not the component manager')
    base = Path(root)
    family = base / 'components' / component_id
    manifest = Manifest(base).load()
    had_record = manifest.get(component_id) is not None
    existed = family.exists()
    if existed:
        try:
            shutil.rmtree(family)
        except OSError as exc:
            raise InstallError(f'cannot delete {family}: {exc}') from exc
    manifest.remove(component_id)
    manifest.save()
    return had_record or existed


def _source(asset: Asset) -> str:
    if asset.parts:
        return asset.parts[0].url
    return asset.urls[0] if asset.urls else ''
