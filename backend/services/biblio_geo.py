"""Join a bibliometric country name onto the committed world basemap.

The basemap (``backend/static/geo/world.json``, Natural Earth 1:110m, public domain — see
``tools/build_world_geojson.py``) is the authority on which regions exist and what they are called
in each language. This module holds only the OTHER thing: the differences between the vocabularies.

Two name lists meet here and they disagree on purpose:

* ``services/biblio_formats/countries.py`` emits the spellings the exports use
  (``PEOPLES R CHINA`` → ``People's Republic of China``, ``ENGLAND``, ``SOUTH KOREA``);
* Natural Earth emits ``China``, ``United Kingdom``, ``South Korea``, ``Czechia``, ``eSwatini``.

Anything that cannot be resolved is reported, never guessed: a country silently missing from a
choropleth reads as "that country published nothing", which is the opposite of the truth and the
one thing a map must not do quietly.
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

BASEMAP_PATH = Path(__file__).resolve().parents[1] / 'static' / 'geo' / 'world.json'

_PUNCT = re.compile(r'[^0-9a-z\u4e00-\u9fff]+')


def key(value) -> str:
    """A comparison key that survives case, accents, punctuation and double spaces.

    ``Venezuela (Bolivarian Republic of)`` and ``VENEZUELA`` have to meet, as do ``Timor-Leste``
    and ``Timor Leste``. Accents are folded rather than preserved because the two gazetteers
    disagree about them: Natural Earth writes ``Côte d'Ivoire``, the exports write ``Ivory Coast``.
    """
    text = unicodedata.normalize('NFKD', str(value or ''))
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    return _PUNCT.sub(' ', text.strip().lower()).strip()


#: Source spellings the basemap does not carry under that name. Kept short on purpose: the basemap
#: itself resolves everything else, and a test walks the importer's whole country list against it.
BRIDGE = {
    'peoples republic of china': 'CHN',
    'china mainland': 'CHN',
    'mainland china': 'CHN',
    'taiwan province of china': 'CHN',
    'england': 'GBR',
    'scotland': 'GBR',
    'wales': 'GBR',
    'northern ireland': 'GBR',
    'united kingdom of great britain and northern ireland': 'GBR',
    'great britain': 'GBR',
    'uk': 'GBR',
    'usa': 'USA',
    'united states': 'USA',
    'united states of america': 'USA',
    'korea': 'KOR',
    'republic of korea': 'KOR',
    's korea': 'KOR',
    'south korea republic of': 'KOR',
    'north korea': 'PRK',
    'democratic peoples republic of korea': 'PRK',
    'dprk': 'PRK',
    'czech republic': 'CZE',
    'czechia czech republic': 'CZE',
    'russian federation': 'RUS',
    'russia': 'RUS',
    'iran islamic republic of': 'IRN',
    'viet nam': 'VNM',
    'vietnam democratic republic of': 'VNM',
    'myanmar burma': 'MMR',
    'burma': 'MMR',
    'brunei darussalam': 'BRN',
    'dominican republic': 'DOM',
    'falkland islands malvinas': 'FLK',
    'netherlands kingdom of the': 'NLD',
    'palestine state of': 'PSE',
    'west bank and gaza strip': 'PSE',
    'syrian arab republic': 'SYR',
    'united republic of tanzania': 'TZA',
    'tanzania united republic of': 'TZA',
    'timor leste democratic republic of': 'TLS',
    'venezuela bolivarian republic of': 'VEN',
    'swaziland': 'SWZ',
    'eswatini the kingdom of eswatini': 'SWZ',
    'north macedonia republic of': 'MKD',
    'macedonia': 'MKD',
    'republic of korea south korea': 'KOR',
    'lao people s democratic republic': 'LAO',
    'laos': 'LAO',
    'philippines republic of the': 'PHL',
    'poland republic of': 'POL',
    'turkiye': 'TUR',
    'turkey republic of': 'TUR',
    # Chinese short names, which is what a CNKI 地区 column or a crawled table carries.
    '中国': 'CHN',
    '美国': 'USA',
    '英国': 'GBR',
    '俄罗斯': 'RUS',
    '韩国': 'KOR',
    '朝鲜': 'PRK',
    '日本': 'JPN',
    '德国': 'DEU',
    '法国': 'FRA',
    '加拿大': 'CAN',
    '澳大利亚': 'AUS',
    '意大利': 'ITA',
    '西班牙': 'ESP',
    '荷兰': 'NLD',
    '瑞士': 'CHE',
    '瑞典': 'SWE',
    '挪威': 'NOR',
    '丹麦': 'DNK',
    '芬兰': 'FIN',
    '波兰': 'POL',
    '希腊': 'GRC',
    '奥地利': 'AUT',
    '比利时': 'BEL',
    '爱尔兰': 'IRL',
    '葡萄牙': 'PRT',
    '捷克': 'CZE',
    '匈牙利': 'HUN',
    '以色列': 'ISR',
    '土耳其': 'TUR',
    '伊朗': 'IRN',
    '沙特': 'SAU',
    '沙特阿拉伯': 'SAU',
    '印度': 'IND',
    '巴基斯坦': 'PAK',
    '日本国': 'JPN',
    '泰国': 'THA',
    '新加坡': 'SGP',
    '马来西亚': 'MYS',
    '印度尼西亚': 'IDN',
    '印尼': 'IDN',
    '菲律宾': 'PHL',
    '越南': 'VNM',
    '巴西': 'BRA',
    '墨西哥': 'MEX',
    '阿根廷': 'ARG',
    '智利': 'CHL',
    '哥伦比亚': 'COL',
    '秘鲁': 'PER',
    '委内瑞拉': 'VEN',
    '新西兰': 'NZL',
    '南非': 'ZAF',
    '埃及': 'EGY',
    '尼日利亚': 'NGA',
    '肯尼亚': 'KEN',
    '摩洛哥': 'MAR',
    '罗马尼亚': 'ROU',
    '乌克兰': 'UKR',
    '缅甸': 'MMR',
    '柬埔寨': 'KHM',
    '孟加拉国': 'BGD',
    '巴基斯坦伊斯兰共和国': 'PAK',
    '台湾': 'CHN',
    '香港': 'CHN',
    '澳门': 'CHN',
    # Dependencies and territories the basemap does not carry as regions of their own: the map
    # paints them as part of the state that owns them, so that is where their rows belong. Each one
    # is still named in the figure's merge note — a reader who searched this map for Guadeloupe is
    # told where it went rather than finding nothing. Anything Natural Earth DOES draw on its own
    # (Aruba, Curaçao, Sint Maarten, Norfolk Island, Vatican) is resolved by the basemap and is
    # deliberately absent here: a bridge entry would override the region that exists.
    'taiwan': 'CHN',
    'hong kong': 'CHN',
    'macau': 'CHN',
    'macao': 'CHN',
    'ivory coast': 'CIV',
    'cape verde': 'CPV',
    'bonaire': 'NLD',
    'sint eustatius': 'NLD',
    'bouvet island': 'NOR',
    'svalbard and jan mayen': 'NOR',
    'christmas island': 'AUS',
    'cocos islands': 'AUS',
    'french guiana': 'FRA',
    'guadeloupe': 'FRA',
    'martinique': 'FRA',
    'mayotte': 'FRA',
    'reunion': 'FRA',
    'french southern territories': 'ATF',
    'gibraltar': 'GBR',
    'pitcairn': 'PCN',
    'south georgia and the south sandwich islands': 'SGS',
    'tokelau': 'NZL',
    'united states minor outlying islands': 'USA',
}

#: Codes the basemap has folded into another region, so a row that names one still lands on the
#: region that owns its geometry. The merge is reported by the chart, which sees every spelling
#: that arrived for a region — see ``_merges`` there.
FOLDED_INTO = {'TWN': 'CHN', 'HKG': 'CHN', 'MAC': 'CHN'}

#: Read as ``key(...)`` so the table's own spelling cannot drift from the comparison it feeds:
#: ``People's Republic of China`` normalises to ``people s republic of china``, and a literal key
#: written by hand would quietly never match.
BRIDGE = {key(alias): iso for alias, iso in BRIDGE.items()}


@lru_cache(maxsize=1)
def regions() -> dict:
    """ISO code → ``{'name', 'zh', 'alt'}``, read once from the committed basemap."""
    with BASEMAP_PATH.open(encoding='utf-8') as handle:
        payload = json.load(handle)
    return {
        str(feature['properties'].get('iso') or feature['properties']['name']): {
            'name': feature['properties']['name'],
            'zh': feature['properties'].get('zh') or feature['properties']['name'],
            'alt': list(feature['properties'].get('alt') or ()),
        }
        for feature in payload['features']
    }


@lru_cache(maxsize=1)
def _keys() -> dict:
    index = {}
    for iso, region in regions().items():
        for spelling in (region['name'], region['zh'], iso, *region['alt']):
            index.setdefault(key(spelling), iso)
    return index


@lru_cache(maxsize=1)
def _importer_alias():
    """The importer's own normaliser, reused rather than copied.

    ``biblio_formats.countries`` already knows that ``PEOPLES R CHINA``, ``P R CHINA`` and
    ``CHINA MAINLAND`` are one country; a second spelling table here would be a second opinion
    about the same exports, and the two would drift.
    """
    from services.biblio_formats.countries import country_in_affiliation

    return country_in_affiliation


def direct(value) -> str:
    """The basemap's OWN region name for a spelling, with no bridge and no alias table.

    Empty means "the map does not carry this name" — which is how a caller tells a rename
    (``China`` drawn as ``中华人民共和国``) from a fold (``England`` drawn inside ``United Kingdom``).
    The second loses information, and only the second has to be reported.
    """
    probe = key(value)
    return _keys().get(probe, '') if probe else ''


def resolve(value) -> str:
    """The basemap code one country/region spelling means, or ``''`` when nothing matches.

    Nothing is guessed: an unresolved name is counted and named by the caller, because a region
    silently missing from a choropleth reads as "that country published nothing".
    """
    iso = direct(value)
    if not iso:
        for probe in (key(value), key(_importer_alias()(str(value or '')))):
            if probe:
                iso = BRIDGE.get(probe) or _keys().get(probe) or ''
                if iso:
                    break
    while iso in FOLDED_INTO:
        iso = FOLDED_INTO[iso]
    return iso


def display(iso: str, lang: str) -> str:
    """The basemap's own name for a code, in the run's language."""
    region = regions().get(iso)
    if not region:
        return ''
    return region['zh'] if (lang or 'zh') == 'zh' else region['name']


def known(iso: str) -> bool:
    return iso in regions()


def aggregate(rows) -> dict:
    """Sum a node table PER REGION, keeping the spellings that landed there.

    Shared by the ECharts map and its LaTeX figure on purpose: a printed ranking that grouped the
    rows differently from the drawn map would be two answers to one question.

    Returns ``{'regions': [(iso, value, [folded spellings])], 'unknown': [names]}``, ordered by
    value descending then by code. A spelling counts as FOLDED when the basemap did not carry it
    under that name — ``England`` into ``United Kingdom``, ``台湾`` into ``China`` — which is the
    information a reader can lose from a choropleth and cannot recover from it.
    """
    totals: dict[str, float] = {}
    folded: dict[str, list[str]] = {}
    unknown: list[str] = []
    for row in rows:
        name = str(row.get('节点') or '').strip()
        if not name:
            continue
        iso = resolve(name)
        if not iso:
            if name not in unknown:
                unknown.append(name)
            continue
        try:
            value = float(row.get('频次') or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        totals[iso] = totals.get(iso, 0.0) + max(0.0, value)
        if not direct(name):
            seen = folded.setdefault(iso, [])
            if name not in seen:
                seen.append(name)
    ordered = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    return {
        'regions': [(iso, value, folded.get(iso, [])) for iso, value in ordered],
        'unknown': unknown,
    }
