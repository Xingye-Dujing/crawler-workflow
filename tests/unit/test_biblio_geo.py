"""The world basemap and the country join: every name the importer can emit must reach a region.

The pairing is the fragile part. ``biblio_formats.countries`` normalises an affiliation to the
spellings the exports use; Natural Earth names its regions its own way; and the map can only draw
what BOTH agree on. A name that resolves to nothing disappears from the figure, which reads as
"that country published nothing" — so the whole emitted vocabulary is walked here, not sampled.
"""

import json

import pytest

from services import biblio_geo
from services.biblio_formats import countries as country_table
from services.biblio_geo import BASEMAP_PATH, BRIDGE, display, known, resolve

pytestmark = pytest.mark.unit


class TestTheBasemap:
    def test_the_file_is_a_feature_collection_we_can_draw(self):
        payload = json.loads(BASEMAP_PATH.read_text(encoding='utf-8'))
        assert payload['type'] == 'FeatureCollection'
        assert len(payload['features']) > 150
        for feature in payload['features']:
            assert feature['properties']['name']
            assert feature['properties']['zh']
            assert feature['geometry']['type'] in ('Polygon', 'MultiPolygon')
            assert feature['geometry']['coordinates']

    def test_the_regions_that_a_placeholder_code_once_deleted_are_present(self):
        """Natural Earth leaves ``ISO_A3`` as ``-99`` for Norway and France while ``ADM0_A3`` holds
        the real code; reading the first column blindly keyed both to the same placeholder and the
        dedupe dropped France out of the world."""
        names = {region['name'] for region in biblio_geo.regions().values()}
        assert {'France', 'Norway', 'China', 'United Kingdom', 'United States of America'} <= names

    def test_taiwan_is_not_a_region_of_its_own_and_china_carries_its_geometry(self):
        """The one cartographic claim this file makes, stated as a test so a rebuild cannot lose it
        silently: the app's figures go into Chinese-language research, and the basemap it already
        uses for China draws Taiwan as part of it."""
        codes = set(biblio_geo.regions())
        assert 'TWN' not in codes
        china = biblio_geo.regions()['CHN']
        assert china['name'] == 'China'
        payload = json.loads(BASEMAP_PATH.read_text(encoding='utf-8'))
        polygons = next(
            len(feature['geometry']['coordinates'])
            for feature in payload['features']
            if feature['properties']['iso'] == 'CHN'
        )
        # Mainland, Hainan and Taiwan — a MultiPolygon may hold disjoint parts, so the fold is a
        # concatenation, not a redraw.
        assert polygons >= 3

    def test_the_file_is_small_enough_to_commit(self):
        size = BASEMAP_PATH.stat().st_size
        assert size < 400_000, f'the basemap grew to {size // 1024} KB; re-trim it in the builder'


class TestTheJoin:
    def test_every_country_the_importer_can_emit_reaches_a_region(self):
        """The whole vocabulary, not a sample: a name in this list that resolves to nothing is a
        country that can never appear on a map, and nothing else would notice."""
        emitted = [name for name in country_table._COUNTRIES.splitlines() if name.strip()]
        emitted += sorted(set(country_table._ALIASES.values()))
        unresolved = [name for name in emitted if not resolve(name)]
        assert unresolved == [], f'{len(unresolved)} of {len(emitted)} country names resolve to nothing'

    def test_the_bridge_only_points_at_regions_that_exist(self):
        missing = sorted(f'{alias}→{iso}' for alias, iso in BRIDGE.items() if not known(iso))
        assert missing == [], f'bridge targets missing from the basemap: {missing}'

    @pytest.mark.parametrize(
        ('spelling', 'iso'),
        [
            ('PEOPLES R CHINA', 'CHN'),
            ("People's Republic of China", 'CHN'),
            ('中国', 'CHN'),
            ('USA', 'USA'),
            ('UNITED STATES OF AMERICA', 'USA'),
            ('美国', 'USA'),
            ('ENGLAND', 'GBR'),
            ('Scotland', 'GBR'),
            ('REPUBLIC OF KOREA', 'KOR'),
            ('DEMOCRATIC PEOPLES REPUBLIC OF KOREA', 'PRK'),
            ('RUSSIAN FEDERATION', 'RUS'),
            ('CZECH REP', 'CZE'),
            ('VENEZUELA (BOLIVARIAN REPUBLIC OF)', 'VEN'),
            ('Timor Leste', 'TLS'),
            ('eSwatini', 'SWZ'),
            ('SWAZILAND', 'SWZ'),
            ('Türkiye', 'TUR'),
        ],
    )
    def test_the_spellings_exports_actually_emit(self, spelling, iso):
        assert resolve(spelling) == iso, spelling

    def test_a_region_the_basemap_folds_still_lands_on_its_owner(self):
        """England, Taiwan and 台湾 have no polygon of their own in this basemap. Resolving them to
        the region that owns the geometry is the map's only honest answer — and the chart reports
        every spelling it merged, so the collapse is visible in the figure rather than silent."""
        assert resolve('England') == 'GBR'
        assert resolve('Scotland') == 'GBR'
        assert resolve('Taiwan') == 'CHN'
        assert resolve('台湾') == 'CHN'
        assert resolve('China') == 'CHN'

    def test_an_unknown_name_is_not_guessed(self):
        assert resolve('Atlantis') == ''
        assert resolve('') == ''
        assert resolve(None) == ''
        assert resolve('   ') == ''

    def test_the_map_label_follows_the_run_language(self):
        assert display('CHN', 'zh') == '中华人民共和国'
        assert display('CHN', 'en') == 'China'
        assert display('ZZZ', 'zh') == '', 'an unknown code has no label, and no fake one'
