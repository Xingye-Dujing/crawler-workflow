"""Build the committed world basemap: ``backend/static/geo/world.json``.

Source: Natural Earth 1:110m Admin 0 — Countries (``ne_110m_admin_0_countries.geojson``),
which is **public domain** (no attribution requirement, no share-alike, commercial use fine):
https://www.naturalearthdata.com/downloads/110m-cultural-vectors/110m-admin-0-countries/

Why the file is committed rather than fetched at run time: this is a local research tool whose
figures have to render on an offline machine, and the existing China basemap already depends on a
third-party CDN — a second one, on the critical path of every country map, is one network outage
from a blank figure.

What the build does, and why:

* **keeps four properties** (``name`` / ``zh`` / ``iso`` / ``alt``) and drops the other ninety-odd.
  The map needs a region key, a Chinese name, a join code and the source's own alternate spellings;
  the rest is 600 KB of census and GDP numbers nobody reads.
* **rounds coordinates to 2 decimals** (~1 km). A choropleth of country co-authorship is read at
  a metre scale nowhere; the file goes from 838 KB to a few hundred.
* **folds Taiwan into China** and drops it as a region. Natural Earth records Taiwan as
  ``TYPE: Sovereign country`` with ``NAME_ZH: 中华民国``; a figure from this app is pasted into
  Chinese-language research, and the basemap the same app already uses for China (DataV / 高德)
  draws Taiwan as part of China. The fold is a coordinate concatenation — a MultiPolygon may hold
  disjoint parts, so no polygon arithmetic is involved and nothing is redrawn.
* **keeps Natural Earth's other defacto splits** (Greenland separate from Denmark, Northern Cyprus
  separate) because those are how bibliometric country fields actually arrive (WoS lists Greenland
  under its own code). A fold is a claim, and a claim needs a reason that survives the reader.
* **fills the small states 1:110m omits from 1:50m** — Singapore, Bahrain, Qatar, Malta, Mauritius,
  Fiji and about sixty others. They publish research, and a country map that cannot draw one tells
  the reader it produced nothing. Taking only the missing regions keeps the asset a fifth of the
  size of an all-50m file for the same coverage.

Run it only when the upstream files change::

    .venv/Scripts/python.exe tools/build_world_geojson.py \
        scratchpad/ne_110m_admin_0_countries.geojson scratchpad/ne_50m_admin_0_countries.geojson

Both sources download from ``https://fastly.jsdelivr.net/gh/nvkelso/natural-earth-vector@master/geojson/``
(``raw.githubusercontent.com`` is reset on some networks).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / 'backend' / 'static' / 'geo' / 'world.json'

#: Region codes the basemap must not carry as their own country. Each entry names the reason the
#: figure would be wrong rather than merely inconvenient.
FOLDS = {
    # ISO_A3 -> the region that absorbs its geometry AND its data value. All three arrive as their
    # own region somewhere in the two sources: Taiwan at 1:110m, Hong Kong and Macau only at 1:50m,
    # so the fold runs after the small-state fill or the extra file would undo it.
    'TWN': 'CHN',
    'HKG': 'CHN',
    'MAC': 'CHN',
}

PRECISION = 2

#: A second ring of a region smaller than this (diagonal, degrees) is dropped. At 1:50m, Canada,
#: Russia, Norway, Indonesia and Denmark each carry hundreds of Arctic and island rings that no
#: country-level choropleth can see, and they are more than half the file. A region's LARGEST ring
#: is always kept, so a small island STATE — Singapore, Malta, Bahrain — survives untouched; only
#: the extra slivers of a big country go.
MIN_EXTRA_RING_DEGREES = 0.6

SOURCE = 'Natural Earth 1:110m Admin 0 — Countries (public domain)'

#: Natural Earth's "no data" marker. Two Admin-0 rows carry it in ``ISO_A3`` while their
#: ``ADM0_A3`` is a real code — Norway and **France** — so reading the first column blindly
#: keyed both of them to the same placeholder and the dedupe below deleted France from the map.
NO_CODE = ('', '-99', 'N/A', 'None', 'nan')


#: Extra spellings kept per region. Natural Earth's short ``NAME`` is not what every export emits
#: (``Antigua and Barb.`` against ``Antigua and Barbuda``, ``Côte d'Ivoire`` against
#: ``Ivory Coast``), and carrying the source's own long/formal names here means the join table
#: holds the differences that no column covers rather than a copy of the world's gazetteer.
ALT_COLUMNS = ('NAME_LONG', 'NAME_CIAWF', 'FORMAL_EN', 'FORMAL_FR', 'NAME_SORT', 'NAME_ALT')


def _alts(props: dict, name: str) -> list:
    seen: list[str] = []
    for column in ALT_COLUMNS:
        value = str(props.get(column) or '').strip()
        if value and value != name and value not in seen:
            seen.append(value)
    return seen


def _code(props: dict) -> str:
    for column in ('ISO_A3', 'ADM0_A3', 'SU_A3'):
        value = str(props.get(column) or '').strip()
        if value and value not in NO_CODE:
            return value
    return ''


def _round(geometry: dict) -> dict:
    def walk(part):
        if isinstance(part[0], list):
            return [walk(item) for item in part]
        return [round(float(x), PRECISION) for x in part]

    geometry = dict(geometry)
    geometry['coordinates'] = walk(geometry['coordinates'])
    return geometry


def _polygons(geometry: dict) -> list:
    """A region's rings as a list of polygons, so Polygon and MultiPolygon concatenate cleanly."""
    if geometry['type'] == 'MultiPolygon':
        return list(geometry['coordinates'])
    if geometry['type'] == 'Polygon':
        return [geometry['coordinates']]
    raise ValueError(f'unsupported geometry: {geometry["type"]}')


def _diagonal(ring: list) -> float:
    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]
    return ((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2) ** 0.5


def _trim(polygons: list) -> list:
    """Drop a big country's small extra rings, never its main one."""
    if len(polygons) <= 1:
        return polygons
    sizes = sorted(range(len(polygons)), key=lambda index: -_diagonal(polygons[index][0]))
    biggest = sizes[0]
    keep = {index for index in sizes if index == biggest or _diagonal(polygons[index][0]) >= MIN_EXTRA_RING_DEGREES}
    return [polygon for index, polygon in enumerate(polygons) if index in keep]


def build(source: Path, extra: Path | None = None) -> dict:
    raw = json.loads(source.read_text(encoding='utf-8'))
    regions: dict[str, dict] = {}
    order: list[str] = []

    def absorb(feature: dict) -> None:
        props = feature['properties']
        iso = _code(props)
        name = str(props.get('NAME') or '').strip()
        if not name:
            return
        zh = str(props.get('NAME_ZH') or '').strip() or name
        key = iso or name
        if key in regions:
            # Two rows for one code (Natural Earth splits a few by featureclass): keep the first,
            # which is the Admin-0 country row, and never silently double a region.
            return
        regions[key] = {
            'type': 'Feature',
            'properties': {'name': name, 'zh': zh, 'iso': iso, 'alt': _alts(props, name)},
            'polygons': _polygons(_round(feature['geometry'])),
        }
        order.append(key)

    for feature in raw['features']:
        absorb(feature)

    if extra is not None:
        # 1:110m omits 65 small states — Singapore, Bahrain, Qatar, Malta, Mauritius, Fiji — and a
        # country map that cannot draw them tells the reader those countries published nothing.
        # Those regions come from the larger-scale file; the big polygons stay at 110m, so the
        # committed asset is a fifth of the size for the same coverage.
        for feature in json.loads(extra.read_text(encoding='utf-8'))['features']:
            props = feature['properties']
            if (_code(props) or str(props.get('NAME') or '').strip()) in regions:
                continue
            absorb(feature)

    for fold, into in FOLDS.items():
        moved = regions.pop(fold, None)
        target = regions.get(into)
        if target is None:
            raise ValueError(f'fold {fold} -> {into}: target region is not in the source')
        if moved is not None:
            target['polygons'] += moved['polygons']

    features = []
    for key in order:
        region = regions.get(key)
        if region is None:
            continue  # folded into another region above
        polygons = _trim(region.pop('polygons'))
        if len(polygons) == 1:
            region['geometry'] = {'type': 'Polygon', 'coordinates': polygons[0]}
        else:
            region['geometry'] = {'type': 'MultiPolygon', 'coordinates': polygons}
        features.append(region)
    return {'type': 'FeatureCollection', 'name': 'world', 'source': SOURCE, 'features': features}


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print(__doc__)
        return 2
    source = Path(sys.argv[1])
    extra = Path(sys.argv[2]) if len(sys.argv) == 3 else None
    for path in (source, extra):
        if path is not None and not path.is_file():
            print(f'no such source file: {path}')
            return 2
    built = build(source, extra)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # Chinese region names must stay readable in the file, not \uXXXX-escaped: ECharts reads it as
    # UTF-8 and a reviewer has to be able to diff it.
    OUT.write_text(json.dumps(built, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    sizes = OUT.stat().st_size
    print(f'{OUT.relative_to(REPO).as_posix()}: {len(built["features"])} regions, {sizes // 1024} KB')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
