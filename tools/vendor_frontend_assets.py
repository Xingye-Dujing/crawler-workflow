"""Vendor the front-end's third-party bundles into the repository.

Why this exists: the desktop build is supposed to work by double-clicking one exe, but the canvas
pulled ECharts, its GL and word-cloud extensions, the China basemap and the UI webfont from four
different CDN hosts. On a machine without internet — or behind a network that resets one of those
hosts, which this project has already measured for ``raw.githubusercontent.com`` — the figure area
rendered as an empty box and the page carried a different typeface, with nothing on screen naming
the cause. Every asset the UI needs to draw is now a file the app serves itself.

The pins are deliberate. Downloading "whatever upstream says today" into a shipped product would
mean a third party can change what our users' screens execute, and a broken build would look like
our bug. Each asset therefore carries the SHA-256 of the bytes that were reviewed; a changed
upstream file is a named failure here and a red test (``tests/unit/test_vendored_assets.py``), and
updating one is an edit with a diff, not an accident.

Usage::

    python tools/vendor_frontend_assets.py            # fetch, verify the pins, write the files
    python tools/vendor_frontend_assets.py --check    # verify what is on disk, offline

Regenerating after a deliberate version bump: edit the URL and the ``sha256`` in the same place
(this tool prints the hash it saw when a pin mismatches), then re-run and commit both.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATIC = REPO / 'backend' / 'static'
VENDOR = STATIC / 'vendor'
FONT_DIR = VENDOR / 'fonts'
PROVENANCE = VENDOR / 'PROVENANCE.txt'

#: Google hands out ``.woff2`` only to a client it recognises as modern; a bare urllib UA is
#: served a TTF-only stylesheet, so the vendored CSS would not match what browsers get.
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'

CDN = 'https://cdn.jsdmirror.com/npm'


# ─── Pinned assets ──────────────────────────────────────────────


@dataclass(frozen=True)
class Asset:
    """One file that ships inside the app, with what it was taken from and what it must hash to."""

    rel: str
    url: str
    sha256: str
    min_bytes: int
    license_note: str


ASSETS: tuple[Asset, ...] = (
    Asset(
        rel='vendor/echarts.min.js',
        url=f'{CDN}/echarts@5.4.3/dist/echarts.min.js',
        sha256='1156429a16a38cb8604dcc6518c19406d4226142d908f8edd2e3531443c54d19',
        min_bytes=900_000,
        license_note='Apache-2.0 (ASF banner is carried inline in the file)',
    ),
    Asset(
        rel='vendor/echarts-gl.min.js',
        url=f'{CDN}/echarts-gl@2.0.9/dist/echarts-gl.min.js',
        sha256='bfba1b87b8c3c06e5c7ed7741002586c747b00e4efdaa92077d15c2dc721bda0',
        min_bytes=500_000,
        license_note='BSD-3-Clause (Copyright (c) 2017, Baidu Inc.), see vendor/LICENSE.echarts-gl.txt',
    ),
    Asset(
        rel='vendor/echarts-wordcloud.min.js',
        url=f'{CDN}/echarts-wordcloud@2.1.0/dist/echarts-wordcloud.min.js',
        sha256='7b6f0d55971d9de5913120c7ce6342f3551efd00b4a1df8a50f08385bb25f155',
        min_bytes=10_000,
        license_note='ISC (declared in the package manifest; the bundle names its own LICENSE.txt)',
    ),
    Asset(
        rel='vendor/LICENSE.echarts-gl.txt',
        url=f'{CDN}/echarts-gl@2.0.9/LICENSE',
        sha256='55ea01207028f76d844678511f29fc800f8a1e67a8a0fe80470128677847ad32',
        min_bytes=1_000,
        license_note='the upstream license text, redistributed with the bundle',
    ),
    Asset(
        rel='geo/china.json',
        url='https://geo.datav.aliyun.com/areas_v3/bound/100000_full.json',
        sha256='99adfeded5223848bbe37a0a12f8023e11ee12161c7800521c27db42fdeac275',
        min_bytes=300_000,
        license_note='Alibaba Cloud DataV.GeoAtlas administrative boundaries (province-level, '
        'nine-dash line included); stored byte-for-byte as served',
    ),
)

FONT_CSS_URL = (
    'https://fonts.googleapis.com/css2?family=Literata:ital,opsz,wght@'
    '0,7..72,300;0,7..72,400;0,7..72,500;0,7..72,600;0,7..72,700;1,7..72,400&display=swap'
)
FONT_LICENSE = 'SIL Open Font License 1.1 (Literata, Red Hat / Google Fonts)'

#: ``<style>`` markers and the CSS block shape Google emits, parsed rather than hand-copied so an
#: upstream weight change cannot quietly drop a face we render with.
_BLOCK = re.compile(
    r'/\* (?P<subset>[a-z-]+) \*/\s*'
    r'@font-face \{[^}]*?font-style:\s*(?P<style>normal|italic);[^}]*?'
    r'font-weight:\s*(?P<weight>\d+);[^}]*?src:\s*url\((?P<url>[^)]+)\)[^}]*?'
    r'unicode-range:\s*(?P<range>[^;]+);',
    re.S,
)


# ─── Fetch and verify ───────────────────────────────────────────


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _pin_check(rel: str, payload: bytes, expected: str, min_bytes: int) -> str:
    """'' when the bytes are the reviewed ones; otherwise a sentence naming path, size and hashes."""
    if len(payload) < min_bytes:
        return f'{rel}: {len(payload)} bytes, expected at least {min_bytes}'
    seen = _sha256(payload)
    if seen != expected:
        return f'{rel}: sha256 {seen} does not match the pinned {expected}'
    return ''


# ─── Fonts ──────────────────────────────────────────────────────


def parse_font_css(css: str) -> list[tuple[str, str, str, str]]:
    """(subset, style, weight, url) for every ``@font-face`` block Google's stylesheet declares."""
    return [
        (match.group('subset'), match.group('style'), match.group('weight'), match.group('url'))
        for match in _BLOCK.finditer(css)
    ]


def font_face_names(faces: list[tuple[str, str, str, str]]) -> dict[str, str]:
    """One local name per remote URL.

    Google's stylesheet declares the same bytes under every weight it is asked for — the first
    draft of this tool named a file per ``@font-face`` block and shipped 42 files of 2 MB where 14
    files of 556 KB carry the same glyphs. A name is therefore keyed on (style, subset): the two
    things that actually distinguish the bytes.
    """
    names: dict[str, str] = {}
    claimed: dict[tuple[str, str], str] = {}
    for subset, style, _weight, url in faces:
        key = (style, subset)
        if claimed.setdefault(key, url) != url:
            raise SystemExit(
                f'font face {style}/{subset} is declared twice with different files '
                f'({claimed[key]} vs {url}); a name per (style, subset) would be ambiguous'
            )
        names.setdefault(url, f'literata-{style}-{subset}.woff2')
    return names


def build_font_css(css: str, hashes: dict[str, str]) -> tuple[str, dict[str, bytes]]:
    """Rewrite the stylesheet onto local file names and return it with the files it now points at.

    Names are readable (``literata-normal-latin.woff2``) because an opaque ``or3yQ6P12…`` stem is
    not evidence of what a file is, and this tree is inspected by a person when a font breaks.
    The ``unicode-range`` line is kept verbatim: it is the reason two subsets of one style are
    different files, and dropping it would make the browser load every face for every glyph.
    """
    names = font_face_names(parse_font_css(css))
    files: dict[str, bytes] = {}
    rewritten = css
    for url, name in names.items():
        digest = hashes.get(url)
        if digest is None:
            raise SystemExit(f'font face {name} has no recorded bytes for {url}')
        files[name] = base64.b64decode(digest)
        rewritten = rewritten.replace(url, name)
    leftover = re.findall(r'https?://\S*\.woff2', rewritten)
    if leftover:
        raise SystemExit(f'font stylesheet still points off-box: {leftover[0]}')
    return rewritten, files


# ─── Invariants on the China basemap ────────────────────────────


def check_china_geojson(payload: bytes) -> str:
    """Refuse a basemap that lost a province or the nine-dash line — both are content, not styling.

    The figure this file feeds is a map in a Chinese-language paper; 'the map no longer shows
    Taiwan' or 'the South China Sea line is gone' is a factual defect that no test would otherwise
    notice, because ECharts happily draws a map with fewer features.
    """
    try:
        doc = json.loads(payload.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return f'geo/china.json is not readable JSON: {exc}'
    features = doc.get('features') or []
    provinces = [f for f in features if (f.get('properties') or {}).get('level') == 'province']
    names = {(f.get('properties') or {}).get('name') for f in provinces}
    problems: list[str] = []
    # Which region is gone is said before how many are: "33 of 34" does not tell a reader to go
    # and look at Taiwan, and this file feeds a map in a Chinese-language paper.
    for required in ('台湾省', '香港特别行政区', '澳门特别行政区'):
        if required not in names:
            problems.append(f'geo/china.json lost {required}')
    if len(provinces) != 34:
        problems.append(f'geo/china.json carries {len(provinces)} province-level features, expected 34')
    if not any(str((f.get('properties') or {}).get('adcode')) == '100000_JD' for f in features):
        problems.append('geo/china.json lost the nine-dash line feature (adcode 100000_JD)')
    empty = [str((f.get('properties') or {}).get('adcode')) for f in features if not f.get('geometry')]
    if empty:
        problems.append(f'geo/china.json has a feature with no geometry: {empty[0]}')
    return '; '.join(problems)


# ─── Commands ───────────────────────────────────────────────────


def verify_on_disk() -> list[str]:
    """Every problem with what is already in the tree; empty means the vendored set is intact."""
    problems: list[str] = []
    for asset in ASSETS:
        target = STATIC / asset.rel
        if not target.is_file():
            problems.append(f'{asset.rel}: missing')
            continue
        problems.append(_pin_check(asset.rel, target.read_bytes(), asset.sha256, asset.min_bytes))
        if asset.rel.endswith('china.json'):
            problems.append(check_china_geojson(target.read_bytes()))
    css = FONT_DIR / 'literata.css'
    if not css.is_file():
        problems.append('vendor/fonts/literata.css: missing')
    else:
        text = css.read_text(encoding='utf-8')
        if 'http' in text:
            problems.append('vendor/fonts/literata.css still references a remote file')
        referenced = set(re.findall(r'url\(([^)]+)\)', text))
        for name in sorted(referenced):
            face = FONT_DIR / name
            if not face.is_file():
                problems.append(f'vendor/fonts/{name}: referenced but missing')
            elif face.stat().st_size < 4_000:
                problems.append(f'vendor/fonts/{name}: only {face.stat().st_size} bytes')
        # An unreferenced face still ships: the build copies the whole static tree, so a font the
        # stylesheet stopped naming is dead weight that no other check would ever notice.
        for face in sorted(FONT_DIR.glob('literata-*.woff2')):
            if face.name not in referenced:
                problems.append(f'vendor/fonts/{face.name}: on disk but referenced by nothing')
    return [problem for problem in problems if problem]


def vendor() -> list[str]:
    """Download, pin-check, and write; returns the lines for PROVENANCE.txt."""
    VENDOR.mkdir(parents=True, exist_ok=True)
    (STATIC / 'geo').mkdir(parents=True, exist_ok=True)
    rows: list[str] = []
    for asset in ASSETS:
        payload = _fetch(asset.url)
        problem = _pin_check(asset.rel, payload, asset.sha256, asset.min_bytes)
        if problem:
            raise SystemExit(
                f'{problem}\nUpstream changed. Review the new bytes, then update both the URL and '
                f'the sha256 for {asset.rel} in this file.'
            )
        target = STATIC / asset.rel
        target.write_bytes(payload)
        rows.append(f'{asset.rel}\t{len(payload)} bytes\tsha256 {asset.sha256}\t{asset.license_note}\t{asset.url}')
        print(f'wrote {asset.rel} ({len(payload):,} bytes)')

    css_text = _fetch(FONT_CSS_URL).decode('utf-8')
    faces = parse_font_css(css_text)
    if not faces:
        raise SystemExit('the font stylesheet parsed to zero @font-face blocks — did the URL change?')
    hashes = {}
    for _subset, _style, _weight, url in faces:
        if url in hashes:
            continue
        payload = _fetch(url)
        hashes[url] = base64.b64encode(payload).decode('ascii')
        print(f'fetched {url.rsplit("/", 1)[-1]} ({len(payload):,} bytes)')
    css_local, files = build_font_css(css_text, hashes)
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    (FONT_DIR / 'literata.css').write_text(css_local, encoding='utf-8')
    rows.append(f'vendor/fonts/literata.css\t{len(css_local)} bytes\tgenerated\t{FONT_LICENSE}\t{FONT_CSS_URL}')
    for name, payload in sorted(files.items()):
        digest = _sha256(payload)
        (FONT_DIR / name).write_bytes(payload)
        rows.append(f'vendor/fonts/{name}\t{len(payload)} bytes\tsha256 {digest}\t{FONT_LICENSE}\t{FONT_CSS_URL}')
        print(f'wrote vendor/fonts/{name} ({len(payload):,} bytes)')

    # Drop faces this run no longer names — the first draft left 28 weight-duplicate files behind,
    # and a font nobody references still costs the shipped app its bytes. Only our own naming shape
    # is touched; anything else in that directory belongs to someone else.
    for stale in sorted(FONT_DIR.glob('literata-*.woff2')):
        if stale.name in files:
            continue
        stale.unlink()
        print(f'removed stale vendor/fonts/{stale.name}')

    stamp = datetime.now(UTC).strftime('%Y-%m-%dT%H:%MZ')
    header = (
        'Vendored front-end assets -- regenerated by tools/vendor_frontend_assets.py\n'
        f'Last run: {stamp}\n'
        'Each line: path, size, sha256 (pinned in the tool), license, upstream URL.\n\n'
    )
    PROVENANCE.write_text(header + '\n'.join(rows) + '\n', encoding='utf-8')
    print(f'wrote {PROVENANCE.relative_to(REPO).as_posix()}')
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='verify what is on disk, without network')
    args = parser.parse_args(argv)
    if args.check:
        problems = verify_on_disk()
        for problem in problems:
            print(f'PROBLEM {problem}')
        print(f'vendored assets: {"OK" if not problems else f"{len(problems)} problem(s)"}')
        return 1 if problems else 0
    vendor()
    problems = verify_on_disk()
    for problem in problems:
        print(f'PROBLEM {problem}')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
