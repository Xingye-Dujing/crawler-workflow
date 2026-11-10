"""The release feed, as the installer's source for the application package.

The online installer used to embed the application's URL, size and digest in its own catalogue. That
made every release require a rebuilt installer, and an installer downloaded in March could only ever
install March's build. ``version.json`` — the same file the installed application reads to find its
own update — already names the current package per platform with its digest, so the installer reads
it at install time instead. One feed, one set of hashes, one installer that keeps installing the
newest build until the *components* it pins itself change.

The feed only ever answers with bytes it can verify: an entry without an ``https`` URL, a 64-character
SHA-256, a positive size or a runnable archive is a named refusal. A failed feed never falls back to a
build pinned in the catalogue — installing a version nobody asked for is the guess this project
refuses, and it is worse than saying what is missing.

Standard library only, like :mod:`catalog` and :mod:`fetch`: the bootstrap installer imports it
before the application exists.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from services.components.catalog import (
    Catalog,
    CatalogError,
    Component,
    fetch_catalog,
    validate_asset,
)

FEED_SCHEMA = 1
#: A release feed's version is the build number the application also compares (``2026.11.11.1``).
_VERSION = re.compile(r'^\d+(?:\.\d+)+$')
#: Which feed keys say "this is the download", kept apart from the installer's own knobs.
_BYTES = ('urls', 'parts', 'sha256', 'size')


class FeedError(CatalogError):
    """The release feed could not name a package this installer can use; the sentence names the URL."""


def resolve(catalog: Catalog, *, timeout: float = 20.0, load: Callable[..., dict] | None = None) -> dict[str, str]:
    """Replace every ``feed`` asset in ``catalog`` with the package the feed names right now.

    Returns ``{component_id: version}`` for what was resolved. Nothing is written until every entry
    has been read and validated, so a refused feed leaves the catalogue exactly as it was — a
    half-resolved catalogue would mix this release's application with last release's knobs.
    """
    fetch = load or fetch_catalog
    payloads: dict[tuple[str, ...], dict] = {}
    pending: list[tuple[Component, str, dict]] = []
    versions: dict[str, str] = {}
    for component in catalog.components.values():
        for key, raw in list(component.platforms.items()):
            urls = _urls_of(raw)
            if not urls:
                continue
            if urls not in payloads:
                payloads[urls] = _read(urls, fetch, timeout)
            payload = payloads[urls]
            version = str(payload.get('version') or '').strip()
            if not _VERSION.match(version):
                raise FeedError(f'{urls[0]}: the feed version {version!r} is not a build number')
            pending.append((component, key, _merge(component.id, key, raw, _entry(payload, key, urls))))
            versions[component.id] = version
    for component, key, merged in pending:
        component.platforms[key] = merged
        component.version = versions[component.id]
    return versions


def _urls_of(raw: dict) -> tuple[str, ...]:
    feed = raw.get('feed')
    return tuple(str(url) for url in feed) if isinstance(feed, list) else ()


def _read(urls: tuple[str, ...], fetch: Callable[..., dict], timeout: float) -> dict:
    """The first mirror that answers with a usable feed; otherwise one sentence naming each try."""
    errors: list[str] = []
    for url in urls:
        try:
            payload = fetch(url, timeout=timeout)
        except CatalogError as exc:
            errors.append(f'{url}: {exc}')
            continue
        except OSError as exc:
            errors.append(f'{url}: {exc}')
            continue
        if not isinstance(payload, dict):
            errors.append(f'{url}: the feed is not a JSON object')
            continue
        if payload.get('schema') != FEED_SCHEMA:
            errors.append(f'{url}: unsupported feed schema {payload.get("schema")!r}')
            continue
        if not isinstance(payload.get('platforms'), dict) or not payload['platforms']:
            errors.append(f'{url}: the feed names no platform')
            continue
        return payload
    raise FeedError('the release feed could not be read: ' + '; '.join(errors))


def _entry(payload: dict, key: str, urls: tuple[str, ...]) -> dict:
    """This OS/CPU key's download, with a plain ``darwin`` entry as the fallback (as ``asset()`` does)."""
    platforms = payload['platforms']
    raw = platforms.get(key)
    if not isinstance(raw, dict) and key.startswith('darwin-'):
        raw = platforms.get('darwin')
    if not isinstance(raw, dict):
        raise FeedError(f'{urls[0]}: the feed has no package for {key}')
    entry = dict(raw)
    # ``version.json`` names one file as ``url``; the catalogue's shape is a list of mirrors.
    single = entry.pop('url', '')
    if single and not entry.get('urls'):
        entry['urls'] = [single]
    size = entry.get('size')
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise FeedError(f'{urls[0]}: the {key} package has no usable size')
    return entry


def _merge(component_id: str, key: str, pinned: dict, fed: dict) -> dict:
    """The feed's bytes with the catalogue's install knobs; refuse a shape that disagrees."""
    archive = str(pinned.get('archive') or 'zip')
    if str(fed.get('archive') or archive) != archive:
        raise FeedError(
            f'{component_id}/{key}: the feed ships {fed.get("archive")!r}, this installer expects {archive!r}'
        )
    merged = {name: value for name, value in pinned.items() if name != 'feed'}
    merged.update({name: fed[name] for name in _BYTES if name in fed})
    merged['archive'] = archive
    try:
        validate_asset(component_id, key, merged)
    except CatalogError as exc:
        raise FeedError(f'{component_id}/{key}: the feed entry is unusable: {exc}') from exc
    return merged
