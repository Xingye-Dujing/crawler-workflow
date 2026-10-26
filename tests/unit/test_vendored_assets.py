"""The front-end's third-party bundles are files this app serves, not things it borrows.

The reason these tests exist: a double-clicked desktop build used to draw NO figure at all on a
machine without network, because ECharts, its two extensions, the China basemap and the UI face were
referenced off four CDN hosts. Nothing in the app failed loudly — the panels were simply empty.
So the gate here is not "the chart looks right", it is "the page asks nothing off this machine", and
the bytes are pinned so a third party cannot change what our users' screens execute without a diff
in this repository.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
STATIC = REPO / 'backend' / 'static'
TOOLS = REPO / 'tools'


def _load(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    # Registered before execution: ``@dataclass`` resolves annotations through
    # ``sys.modules[cls.__module__]``, so a module executed straight off a file path without an
    # entry there dies with ``AttributeError: 'NoneType' object has no attribute '__dict__'``
    # (measured on this file's first run) — and the tool defines a frozen dataclass on purpose.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


TOOL = _load('vendor_frontend_assets', TOOLS / 'vendor_frontend_assets.py')


class TestThePinnedBytesAreTheReviewedOnes:
    """A vendored file that quietly changed upstream is our bug to review, not to absorb."""

    @pytest.mark.parametrize('asset', TOOL.ASSETS, ids=lambda asset: asset.rel)
    def test_each_asset_is_shipped_and_byte_identical(self, asset):
        target = STATIC / asset.rel
        assert target.is_file(), f'{asset.rel} is not in the tree (run tools/vendor_frontend_assets.py)'
        payload = target.read_bytes()
        assert len(payload) >= asset.min_bytes, f'{asset.rel} is truncated'
        assert hashlib.sha256(payload).hexdigest() == asset.sha256, (
            f'{asset.rel} no longer matches the pin: review the new bytes, then update the sha256 '
            f'and the URL together in tools/vendor_frontend_assets.py'
        )

    def test_the_tools_offline_check_passes_on_this_tree(self):
        assert TOOL.verify_on_disk() == []

    def test_provenance_records_every_asset_with_its_license(self):
        text = (STATIC / 'vendor' / 'PROVENANCE.txt').read_text(encoding='utf-8')
        for asset in TOOL.ASSETS:
            assert asset.rel in text, f'{asset.rel} is missing from PROVENANCE.txt'
            assert asset.sha256 in text, f'{asset.rel} has no recorded hash'
        # The webfont and the basemap are redistributed too, so their terms belong in the record.
        assert 'SIL Open Font License' in text
        assert 'DataV.GeoAtlas' in text

    def test_no_font_file_is_shipped_that_the_stylesheet_does_not_use(self):
        """An unreferenced face still ships: the build copies the whole static tree."""
        text = (STATIC / 'vendor' / 'fonts' / 'literata.css').read_text(encoding='utf-8')
        referenced = set(re.findall(r'url\(([^)]+)\)', text))
        on_disk = {path.name for path in (STATIC / 'vendor' / 'fonts').glob('literata-*.woff2')}
        assert referenced == on_disk, f'drift: {sorted(referenced ^ on_disk)}'


class TestThePageAsksNothingOffThisMachine:
    def test_index_html_has_no_external_resource_reference(self):
        html = (STATIC / 'index.html').read_text(encoding='utf-8')
        offenders = re.findall(r'(?:src|href)="(https?://[^"]+)"', html)
        assert offenders == [], f'the page still loads {offenders[0]} from off-box'

    def test_every_root_relative_asset_in_index_html_exists(self):
        html = (STATIC / 'index.html').read_text(encoding='utf-8')
        for path in re.findall(r'(?:src|href)="/([^"]+)"', html):
            assert (STATIC / path).is_file(), f'index.html references /{path}, which is not shipped'

    def test_the_three_chart_bundles_are_loaded_from_the_app_itself(self):
        html = (STATIC / 'index.html').read_text(encoding='utf-8')
        for name in ('echarts.min.js', 'echarts-gl.min.js', 'echarts-wordcloud.min.js'):
            assert f'src="/vendor/{name}"' in html, f'{name} is not served from /vendor'

    def test_the_ui_face_is_declared_locally_and_named_by_the_stylesheet(self):
        css = (STATIC / 'css' / 'style.css').read_text(encoding='utf-8')
        face = (STATIC / 'vendor' / 'fonts' / 'literata.css').read_text(encoding='utf-8')
        assert 'Literata' in css.split('--font:')[1][:80], 'the design token no longer asks for the vendored face'
        assert "'Literata'" in face or 'Literata' in face
        # Basic Latin is the reason the face exists at all (digits and Latin in a Chinese UI).
        assert 'U+0000-00FF' in face, 'the latin subset went missing from the vendored stylesheet'

    def test_the_basemaps_are_read_from_this_apps_own_files(self):
        js = (STATIC / 'js' / 'workflow.js').read_text(encoding='utf-8')
        table = js.split('var urls = {')[1].split('};')[0]
        assert 'http' not in table, f'a basemap is off-box again: {table}'
        assert "'/geo/china.json'" in table
        assert "'/geo/world.json'" in js


class TestTheChinaBasemapIsStillTheMapItClaims:
    """Content facts, not styling: a map that lost a province still renders, and still lies."""

    def test_province_count_and_the_nine_dash_line(self):
        payload = (STATIC / 'geo' / 'china.json').read_bytes()
        assert TOOL.check_china_geojson(payload) == ''

    def test_a_basemap_missing_a_province_names_that_province(self):
        doc = json.loads((STATIC / 'geo' / 'china.json').read_text(encoding='utf-8'))
        dropped = [feature for feature in doc['features'] if (feature.get('properties') or {}).get('name') != '台湾省']
        assert len(dropped) == len(doc['features']) - 1, 'the fixture this test builds is wrong'
        problem = TOOL.check_china_geojson(json.dumps({'features': dropped}).encode('utf-8'))
        # Both facts in one message: which region went missing is the actionable half, and the
        # count is what stops a reader assuming the file is simply a different vintage.
        assert '台湾省' in problem
        assert '33 province-level features, expected 34' in problem

    def test_a_basemap_missing_the_nine_dash_line_is_refused(self):
        doc = json.loads((STATIC / 'geo' / 'china.json').read_text(encoding='utf-8'))
        kept = [
            feature for feature in doc['features'] if str(feature.get('properties', {}).get('adcode')) != '100000_JD'
        ]
        problem = TOOL.check_china_geojson(json.dumps({'features': kept}).encode('utf-8'))
        assert '100000_JD' in problem
