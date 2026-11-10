"""The component catalogue: what the online installer may download, and where from.

This module is deliberately dependency-free (standard library only) because the *bootstrap*
installer imports it before the application exists, while the running app imports it from
``backend/``. Nothing here knows a Windows path: a component carries one asset table per operating
system, and the caller asks for its own system. That is the same rule ``core.machine`` follows for
Chrome, Node and CatBus.

A catalogue is data; every check here answers a question the rest of the code depends on:

- ``schema`` is the version of this shape, so an older installer refuses a newer manifest instead of
  guessing at fields it does not know;
- every archive has a SHA-256 (except a ``manual`` component, which is a documentation entry, not a
  download), because a mirror is not trusted merely for being a mirror;
- a ``parts`` asset is several files that are concatenated before verification — Gitee caps one
  attachment at 100 MB, so the no-VPN route needs that shape;
- a ``feed`` asset names no bytes at all: its URL, size and digest are read at install time from the
  release feed (:mod:`services.components.feed`), which is what lets one installer install every
  future build instead of only the one it was compiled against. A feed asset may not also pin bytes,
  or two sources would disagree about which build is being installed;
- ``verify`` names the files that must exist after extraction: a download that unpacks into the
  wrong folder is not an installation, and this turns that into a named failure.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.machine import platform_asset_key

SCHEMA = 1
CATALOG_NAME = 'default_catalog.json'
MAX_CATALOG_BYTES = 4 * 1024 * 1024
_ALLOWED_ARCHIVES = ('zip', 'tar.gz', 'dmg')
_ALLOWED_KINDS = ('archive', 'manual')


class CatalogError(Exception):
    """A catalogue that cannot be trusted, with a sentence naming the exact field."""


def default_catalog_path() -> Path:
    """The catalogue bundled with the application (and with the bootstrap installer)."""
    return Path(__file__).with_name(CATALOG_NAME)


def fetch_catalog(url: str, timeout: float = 20.0) -> dict:
    """Download a catalogue over HTTPS and return its mapping.

    HTTPS is required: the whole point of the digest is that the bytes came from the expected
    place, and a plain-HTTP manifest can be rewritten in transit together with its digests.
    """
    if not str(url or '').lower().startswith('https://'):
        raise CatalogError('catalog url must be https')
    request = urllib.request.Request(url, headers={'User-Agent': 'CaiXiHui-installer'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(MAX_CATALOG_BYTES + 1)
    if len(raw) > MAX_CATALOG_BYTES:
        raise CatalogError('catalog is too large')
    try:
        payload = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as exc:
        raise CatalogError(f'catalog is not UTF-8 JSON: {exc}') from exc
    return payload


def load_catalog(path: str | Path | None = None) -> dict:
    """Read a catalogue from disk and validate it; the default is the bundled one."""
    source = Path(path) if path else default_catalog_path()
    try:
        raw = source.read_text(encoding='utf-8')
    except OSError as exc:
        raise CatalogError(f'cannot read catalog {source}: {exc}') from exc
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise CatalogError(f'catalog is not JSON: {exc}') from exc
    validate_catalog(payload)
    return payload


@dataclass(frozen=True)
class Part:
    url: str
    sha256: str
    size: int


@dataclass(frozen=True)
class Asset:
    """One operating system's downloadable shape for a component."""

    urls: tuple[str, ...]
    parts: tuple[Part, ...]
    sha256: str
    size: int
    archive: str
    strip_prefix: str
    install_as: str
    verify: tuple[str, ...]
    #: Release-feed URLs this asset's bytes come from, empty for a pinned asset. A non-empty value
    #: with no urls/parts means "not resolved yet": nothing may be downloaded until it is.
    feed: tuple[str, ...] = ()


@dataclass
class Component:
    """One catalogue entry. Mutable because a feed asset rewrites it (see ``feed.resolve``)."""

    id: str
    version: str
    kind: str
    label: str
    summary: str
    provides: tuple[str, ...]
    requires: tuple[str, ...]
    default: bool
    license: str
    homepage: str
    notes: str
    platforms: dict[str, dict]

    def _entry(self, system: str | None = None) -> dict | None:
        """This OS's platform entry, falling back from ``darwin-<cpu>`` to a plain ``darwin``."""
        key = str(system or platform_asset_key())
        raw = self.platforms.get(key)
        if not raw and key.startswith('darwin-'):
            raw = self.platforms.get('darwin')
        return raw or None

    def feed_urls(self, system: str | None = None) -> tuple[str, ...]:
        """The release feed this OS's asset is read from; ``()`` when the bytes are pinned here."""
        raw = self._entry(system) or {}
        feed = raw.get('feed')
        return tuple(str(url) for url in feed) if isinstance(feed, list) else ()

    def asset(self, system: str | None = None) -> Asset | None:
        """This OS's asset, or ``None`` when the component is documentation or ships for another OS.

        ``system`` may be an OS name (``darwin``) or an OS+CPU key (``darwin-arm64``); the default
        is the running machine's full key, so a Mac downloads the archive its CPU can run. A
        hand-written single-architecture ``darwin`` entry still works as the fallback.

        An unresolved ``feed`` entry is also ``None``: the feed names the file, so a caller that has
        not resolved it has nothing to download and must say so rather than fetch a stale build.
        """
        if self.kind == 'manual':
            return None
        raw = self._entry(system)
        if not raw:
            return None
        urls = tuple(str(url) for url in raw.get('urls') or ())
        parts = tuple(
            Part(str(p['url']), str(p.get('sha256') or ''), int(p.get('size') or 0)) for p in raw.get('parts') or ()
        )
        feed = self.feed_urls(system)
        if feed and not urls and not parts:
            return None
        return Asset(
            urls=urls,
            parts=parts,
            sha256=str(raw.get('sha256') or ''),
            size=int(raw.get('size') or 0),
            archive=str(raw.get('archive') or 'zip'),
            strip_prefix=str(raw.get('strip_prefix') or ''),
            install_as=str(raw.get('install_as') or 'component'),
            verify=tuple(str(name) for name in raw.get('verify') or ()),
            feed=feed,
        )


class Catalog:
    """A validated catalogue with lookups the installer and the API share."""

    def __init__(self, payload: dict):
        validate_catalog(payload)
        self.raw = payload
        self.generated_at = str(payload.get('generated_at') or '')
        self.components: dict[str, Component] = {}
        for component_id, raw in (payload.get('components') or {}).items():
            self.components[component_id] = Component(
                id=component_id,
                version=str(raw.get('version') or ''),
                kind=str(raw.get('kind') or 'archive'),
                label=str(raw.get('label') or component_id),
                summary=str(raw.get('summary') or ''),
                provides=tuple(str(item) for item in raw.get('provides') or ()),
                requires=tuple(str(item) for item in raw.get('requires') or ()),
                default=bool(raw.get('default', True)),
                license=str(raw.get('license') or ''),
                homepage=str(raw.get('homepage') or ''),
                notes=str(raw.get('notes') or ''),
                platforms=dict(raw.get('platforms') or {}),
            )

    def get(self, component_id: str) -> Component:
        try:
            return self.components[component_id]
        except KeyError as exc:
            raise CatalogError(f'unknown component {component_id!r}') from exc

    def downloadable(self, system: str | None = None) -> dict[str, Component]:
        """Components that actually have an asset for this OS/CPU key, in catalogue order."""
        return {key: item for key, item in self.components.items() if item.asset(system) is not None}

    def defaults(self, system: str | None = None) -> list[str]:
        return [key for key, item in self.downloadable(system).items() if item.default]


def validate_catalog(payload: Any) -> None:
    """Refuse anything this installer would have to guess about. One sentence per defect."""
    if not isinstance(payload, dict):
        raise CatalogError('catalog must be a JSON object')
    if payload.get('schema') != SCHEMA:
        raise CatalogError(f'unsupported catalog schema {payload.get("schema")!r} (expected {SCHEMA})')
    components = payload.get('components')
    if not isinstance(components, dict) or not components:
        raise CatalogError('catalog has no components')
    for component_id, raw in components.items():
        if not isinstance(component_id, str) or not component_id or not component_id.replace('_', '').isalnum():
            raise CatalogError(f'bad component id {component_id!r}')
        if not isinstance(raw, dict):
            raise CatalogError(f'component {component_id} must be an object')
        kind = raw.get('kind', 'archive')
        version = str(raw.get('version') or '')
        platforms = raw.get('platforms')
        feed_platforms = [
            str(system) for system, asset in (platforms or {}).items() if isinstance(asset, dict) and asset.get('feed')
        ]
        if kind != 'manual' and not version and not feed_platforms:
            # A feed-driven component has no version of its own: the feed says which build is
            # current, and pinning a second number here would only be a number that goes stale.
            raise CatalogError(f'component {component_id} has no version')
        if version and (re.search(r'[\\/]', version) or '..' in version):
            # The version becomes a directory name under components/<id>/; a separator or '..' there
            # would install outside the root the manifest is allowed to name.
            raise CatalogError(f'component {component_id} has an unusable version {version!r}')
        if kind not in _ALLOWED_KINDS:
            raise CatalogError(f'component {component_id} has unknown kind {kind!r}')
        if not isinstance(platforms, dict) or not platforms:
            raise CatalogError(f'component {component_id} has no platforms')
        for system, asset in platforms.items():
            validate_asset(component_id, system, asset, kind)


def validate_asset(component_id: str, system: str, asset: Any, kind: str = 'archive') -> None:
    """One platform entry: refuse what a downloader would have to guess about."""
    if not isinstance(asset, dict):
        raise CatalogError(f'{component_id}/{system}: asset must be an object')
    if kind == 'manual':
        return
    archive = asset.get('archive', 'zip')
    if archive not in _ALLOWED_ARCHIVES:
        raise CatalogError(f'{component_id}/{system}: unsupported archive {archive!r}')
    feeds = _feed_urls(component_id, system, asset)
    urls = asset.get('urls') or ()
    parts = asset.get('parts') or ()
    if feeds:
        if urls or parts or asset.get('sha256') or asset.get('size'):
            raise CatalogError(f'{component_id}/{system}: a feed asset must not also pin urls, parts, sha256 or size')
    else:
        if not urls and not parts:
            raise CatalogError(f'{component_id}/{system}: no urls and no parts')
        if urls and parts:
            raise CatalogError(f'{component_id}/{system}: use urls or parts, not both')
        for url in list(urls) + [part.get('url') for part in parts]:
            if not isinstance(url, str) or not url.lower().startswith('https://'):
                raise CatalogError(f'{component_id}/{system}: every url must be https')
        sha = str(asset.get('sha256') or '')
        if not _looks_like_sha256(sha):
            raise CatalogError(f'{component_id}/{system}: sha256 is missing or malformed')
        for part in parts:
            if not _looks_like_sha256(str(part.get('sha256') or '')):
                raise CatalogError(f'{component_id}/{system}: a part has no usable sha256')
    for name in asset.get('verify') or ():
        if not isinstance(name, str) or not name or '..' in name or name.startswith(('/', '\\')):
            raise CatalogError(f'{component_id}/{system}: bad verify entry {name!r}')


def _feed_urls(component_id: str, system: str, asset: dict) -> tuple[str, ...]:
    feed = asset.get('feed')
    if feed is None:
        return ()
    if not isinstance(feed, list) or not feed:
        raise CatalogError(f'{component_id}/{system}: feed must be a non-empty list of https urls')
    for url in feed:
        if not isinstance(url, str) or not url.lower().startswith('https://'):
            raise CatalogError(f'{component_id}/{system}: every feed url must be https')
    return tuple(feed)


def _looks_like_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in '0123456789abcdef' for char in value.lower())
