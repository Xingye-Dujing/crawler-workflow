"""Regenerate the component catalogue's digests when publishing a new build.

Run this on the machine that built the artifacts, then upload the files and commit the catalogue.
It never downloads anything: the point is that the SHA-256 describes the exact bytes you are about
to publish, not a URL that might change.

    python tools/release_components.py --component chrome=build/chrome-win64.zip \
        --url chrome=https://registry.npmmirror.com/.../chrome-win64.zip --out catalog.json

``--check`` validates the catalogue and prints the total download size without writing.
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


def _pairs(values: list[str]) -> dict[str, str]:
    result = {}
    for value in values:
        key, _, path = value.partition('=')
        if not key or not path:
            raise SystemExit(f'expected id=path, got {value!r}')
        result[key] = path
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--catalog', default=str(DEFAULT))
    parser.add_argument('--out', default='')
    parser.add_argument('--component', action='append', default=[], metavar='ID=PATH')
    parser.add_argument('--url', action='append', default=[], metavar='ID=URL')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)

    catalog_path = Path(args.catalog)
    payload = json.loads(catalog_path.read_text(encoding='utf-8'))
    files = _pairs(args.component)
    urls = _pairs(args.url)

    for component_id, raw in (payload.get('components') or {}).items():
        for _platform, asset in (raw.get('platforms') or {}).items():
            if files and component_id not in files and not args.check:
                continue
            if component_id in files:
                path = Path(files[component_id])
                if not path.is_file():
                    raise SystemExit(f'missing file for {component_id}: {path}')
                asset['sha256'] = sha256(path)
                asset['size'] = path.stat().st_size
                if component_id in urls:
                    asset['urls'] = [urls[component_id]]
                    asset.pop('parts', None)
            elif component_id in urls:
                asset['urls'] = [urls[component_id]]
                asset.pop('parts', None)

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
