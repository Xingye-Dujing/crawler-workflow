"""Regenerate the component catalogue's digests when publishing a new build.

Run this on the machine that built the artifacts, then upload the files and commit the catalogue.
It never downloads anything: the point is that the SHA-256 describes the exact bytes you are about
to publish, not a URL that might change.

    python tools/release_components.py --component chrome=build/chrome-win64.zip \
        --url chrome=https://registry.npmmirror.com/.../chrome-win64.zip --out catalog.json

A component may carry several platform assets now (``win32`` and two Mac architectures), and one
Windows zip must never overwrite a Mac digest. ``ID=path`` therefore updates the CURRENT machine's
asset; name another one explicitly with ``ID:PLATFORM=path`` (for example
``chrome:darwin-arm64=build/chrome-mac-arm64.zip``). ``--check`` validates the catalogue and prints
the total download size without writing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / 'backend' / 'services' / 'components' / 'default_catalog.json'


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _pairs(values: list[str]) -> dict[tuple[str, str], str]:
    """``ID=value`` or ``ID:PLATFORM=value``, keyed so two platforms cannot overwrite each other."""
    result: dict[tuple[str, str], str] = {}
    for value in values:
        key, _, payload = value.partition('=')
        component_id, _, platform_key = key.partition(':')
        if not component_id or not payload:
            raise SystemExit(f'expected id=path or id:platform=path, got {value!r}')
        result[(component_id, platform_key)] = payload
    return result


def _updates(updates: dict[str, str], platform_key: str, fallback: str) -> str:
    """The value for one asset: an explicit platform, else this machine's own, else nothing."""
    if platform_key in updates:
        return updates[platform_key]
    if '' in updates and platform_key == fallback:
        return updates['']
    return ''


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--catalog', default=str(DEFAULT))
    parser.add_argument('--out', default='')
    parser.add_argument('--component', action='append', default=[], metavar='ID[:PLATFORM]=PATH')
    parser.add_argument('--url', action='append', default=[], metavar='ID[:PLATFORM]=URL')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)

    sys.path.insert(0, str(ROOT / 'backend'))
    from core.machine import platform_asset_key

    catalog_path = Path(args.catalog)
    payload = json.loads(catalog_path.read_text(encoding='utf-8'))
    files = _pairs(args.component)
    urls = _pairs(args.url)
    own = platform_asset_key()

    for component_id, raw in (payload.get('components') or {}).items():
        component_files = {key: value for (cid, key), value in files.items() if cid == component_id}
        component_urls = {key: value for (cid, key), value in urls.items() if cid == component_id}
        if files and component_id not in {cid for cid, _ in files} and not args.check:
            continue
        for platform_key, asset in (raw.get('platforms') or {}).items():
            path_text = _updates(component_files, platform_key, own)
            url_text = _updates(component_urls, platform_key, own)
            if not path_text and not url_text:
                continue
            if asset.get('feed'):
                # The application's bytes are named by version.json, which the installer and the
                # running app both read. A second pinned copy here would be the number that goes
                # stale, and the catalogue refuses an asset that pins both.
                raise SystemExit(
                    f'{component_id}:{platform_key} is read from the release feed; update version.json instead'
                )
            if path_text:
                path = Path(path_text)
                if not path.is_file():
                    raise SystemExit(f'missing file for {component_id}:{platform_key}: {path}')
                asset['sha256'] = sha256(path)
                asset['size'] = path.stat().st_size
            if url_text:
                asset['urls'] = [url_text]
                asset.pop('parts', None)
        if files and component_id in {cid for cid, _ in files}:
            unknown = {
                platform_key
                for platform_key in component_files
                if platform_key and platform_key not in (raw.get('platforms') or {})
            }
            if unknown:
                raise SystemExit(f'{component_id} has no asset for {", ".join(sorted(unknown))}')

    total = 0
    for raw in (payload.get('components') or {}).values():
        for asset in (raw.get('platforms') or {}).values():
            total += int(asset.get('size') or 0)
    if args.check:
        print(f'catalog ok: {len(payload.get("components") or {})} components, {total / 1024**3:.2f} GB total')
        return 0

    out = Path(args.out or catalog_path)
    tmp = out.with_name(out.name + '.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(out)
    print(f'wrote {out} ({total / 1024**3:.2f} GB across all platforms)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
