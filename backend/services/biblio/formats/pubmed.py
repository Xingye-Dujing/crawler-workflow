"""PubMed exports: the Medline text file and the CSV summary.

No XML reader lives here. The evidence is the two files a user can actually download from
the site — a ``.txt`` Medline set and a ``.csv`` summary — and a format nobody has ever
exported here would be a claim the app makes and the user cannot satisfy. Adding XML later
means a real file and tests over it, never a fixture written from a specification.
"""

import re

from services.biblio.formats.base import FormatSpec
from services.biblio.formats.common import (
    cell,
    countries,
    frame_has_groups,
    frame_of,
    header_has_groups,
    make_row,
    split_keywords,
    year_of,
)

ID = 'PubMed'
LABEL = 'PubMed'


def detect(text: str) -> bool:
    value = str(text or '')
    if re.search(r'(?m)^PMID-\s+\d+', value) and re.search(r'(?m)^TI\s{2}-', value):
        return True
    return header_has_groups(value, _CSV_GROUPS)


# ─── Medline text (the site's "Text" download, also .nbib) ─────

_MEDLINE_TAG = re.compile(r'^([A-Z]{2,4})\s*-\s?(.*)$')


def _medline_records(text: str) -> list[dict[str, list[str]]]:
    records: list[dict[str, list[str]]] = []
    fields: dict[str, list[str]] = {}
    current: str | None = None

    def flush():
        nonlocal fields, current
        if fields:
            records.append(fields)
        fields = {}
        current = None

    for raw in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        if not raw.strip():
            if fields:
                flush()
            continue
        match = _MEDLINE_TAG.match(raw)
        if match:
            tag, value = match.group(1), match.group(2).strip()
            fields.setdefault(tag, []).append(value)
            current = tag
            continue
        if current:
            fields[current][-1] = f'{fields[current][-1]} {raw.strip()}'.strip()
    if fields:
        flush()
    return records


def _first_field(fields: dict[str, list[str]], *tags: str) -> str:
    for tag in tags:
        for value in fields.get(tag) or []:
            if str(value).strip():
                return str(value).strip()
    return ''


def _all_fields(fields: dict[str, list[str]], *tags: str) -> str:
    values: list[str] = []
    for tag in tags:
        values += [str(value).strip() for value in fields.get(tag) or [] if str(value).strip()]
    return ';'.join(values)


def parse_medline(text: str) -> tuple[list[dict], int]:
    rows: list[dict] = []
    skipped = 0
    for fields in _medline_records(text):
        title = _first_field(fields, 'TI')
        if not title:
            skipped += 1
            continue
        doi = ''
        for value in fields.get('LID') or fields.get('AID') or []:
            if '[doi]' in str(value).lower():
                doi = re.sub(r'\s*\[doi\]\s*$', '', str(value), flags=re.IGNORECASE).strip()
                break
        affiliations = ';'.join(fields.get('AD') or [])
        rows.append(
            make_row(
                title=title,
                # FAU is the full-name list and AU the abbreviated one — the same people twice.
                # Concatenating them, as this line once did, doubles every author node.
                authors=_all_fields(fields, 'FAU') or _all_fields(fields, 'AU'),
                affiliations=affiliations,
                journal=_first_field(fields, 'JT', 'TA'),
                year=year_of(_first_field(fields, 'DP', 'DEP')),
                volume=_first_field(fields, 'VI'),
                issue=_first_field(fields, 'IP'),
                page_start=_first_field(fields, 'PG'),
                keywords=_all_fields(fields, 'OT', 'MH'),
                abstract=' '.join(fields.get('AB') or []),
                doi=doi,
                fmt=ID,
                country=countries(affiliations),
                funding=_all_fields(fields, 'GR'),
                doctype=_all_fields(fields, 'PT'),
                language=_first_field(fields, 'LA'),
            )
        )
    return rows, skipped


# ─── CSV summary export ─────────────────────────────────────────
#
# One row per citation: ``PMID,Title,Authors,Citation,First Author,Journal/Book,
# Publication Year,Create Date,PMCID,NIHMS ID,DOI``. Volume, issue and pages exist only
# inside the free ``Citation`` string, so they are read out of it and left blank when it
# does not carry them.

_CSV_GROUPS = (
    ('PMID',),
    ('Title',),
    # Dimensions exports a PMID column too, so only the two strings that are PubMed's own
    # citation summary may answer the third group. A signature loose enough to accept
    # ``Authors`` steals the Dimensions download and reads it with four columns filled.
    ('Citation', 'Journal/Book'),
)
#: ``AAPS J. 2021 Jan 5;23(1):14. doi: …`` — the volume, issue and pages.
_CITE_BLOCK = re.compile(r';\s*(?P<volume>\d+)\s*\((?P<issue>[^)]{1,16})\)\s*:\s*(?P<pages>[^\s.;]{1,40})')


def detect_frame(frame) -> bool:
    return frame_has_groups(frame, _CSV_GROUPS)


def _csv_authors(value: str) -> str:
    """``Majumder J, Minko T.`` -> two authors.

    The CSV separates authors with a comma and puts no comma inside a name, the opposite
    of the WoS/RIS convention the shared splitter expects, so the split happens here
    instead of widening that helper and changing every other format.
    """
    names = [part.strip().rstrip('.') for part in str(value or '').split(',') if part.strip()]
    return ';'.join(dict.fromkeys(names))


def parse_frame(frame) -> tuple[list[dict], int]:
    rows: list[dict] = []
    skipped = 0
    for _, source in frame.iterrows():
        title = cell(source, 'Title')
        if not title:
            skipped += 1
            continue
        citation = cell(source, 'Citation')
        match = _CITE_BLOCK.search(citation)
        rows.append(
            make_row(
                title=title,
                authors=_csv_authors(cell(source, 'Authors')),
                affiliations='',
                journal=cell(source, 'Journal/Book', 'Journal'),
                year=year_of(cell(source, 'Publication Year', 'Year') or citation),
                volume=(match.group('volume') if match else '') or cell(source, 'Volume'),
                issue=(match.group('issue') if match else '') or cell(source, 'Issue'),
                page_start=(match.group('pages') if match else '') or cell(source, 'Pages'),
                keywords=split_keywords(cell(source, 'Keywords', 'MeSH Terms')),
                abstract=cell(source, 'Abstract'),
                refs=[],
                doi=cell(source, 'DOI'),
                fmt=ID,
                country=countries(cell(source, 'Affiliations', 'Countries')),
                doctype=cell(source, 'Resource Type', 'Publication Type'),
                language=cell(source, 'Language'),
            )
        )
    return rows, skipped


def parse(text: str) -> tuple[list[dict], int]:
    value = str(text or '')
    if header_has_groups(value, _CSV_GROUPS):
        return parse_frame(frame_of(value))
    return parse_medline(value)


SPEC = FormatSpec(
    id=ID,
    label=LABEL,
    extensions=('.txt', '.nbib', '.csv'),
    capabilities=frozenset(
        (
            'abstract',
            'keywords',
            'country',
            'doi',
            'doctype',
            'language',
            'funding',
        )
    ),
    detect=detect,
    parse=parse,
    detect_frame=detect_frame,
    parse_frame=parse_frame,
)
