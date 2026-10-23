"""RIS tagged export (Web of Science, Scopus, PubMed, EndNote and many libraries)."""

import re
from collections import defaultdict

from services.biblio_formats.base import FormatSpec
from services.biblio_formats.common import (
    countries,
    make_row,
    references_from_field,
    split_authors,
    split_keywords,
    year_of,
)
from services.biblio_refs import structured_references

ID = 'RIS'
LABEL = 'RIS'
_TAG = re.compile(r'^([A-Z][A-Z0-9])\s{2}-(?:\s(.*))?$')
_TYPES = {
    'JOUR': 'Journal Article',
    'BOOK': 'Book',
    'CHAP': 'Book Chapter',
    'CONF': 'Conference Paper',
    'CPAPER': 'Conference Paper',
    'THES': 'Thesis',
    'RPRT': 'Report',
    'NEWS': 'News',
    'MGZN': 'Magazine Article',
    'GEN': 'Generic',
    'ELEC': 'Electronic Article',
    'UNPB': 'Unpublished Work',
}


def detect(text: str) -> bool:
    return bool(re.search(r'(?m)^TY\s{2}-', text) and re.search(r'(?m)^ER\s{2}-', text))


def _blocks(text: str) -> list[dict[str, list[str]]]:
    records: list[dict[str, list[str]]] = []
    fields: dict[str, list[str]] = defaultdict(list)
    current: str | None = None

    def flush():
        nonlocal fields, current
        if fields:
            records.append(dict(fields))
        fields = defaultdict(list)
        current = None

    for raw in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        match = _TAG.match(raw)
        if match:
            tag, value = match.group(1), (match.group(2) or '').strip()
            if tag == 'ER':
                flush()
                continue
            if tag == 'TY' and fields:
                flush()
            fields[tag].append(value)
            current = tag
            continue
        if not raw.strip():
            continue
        if current:
            fields[current][-1] = f'{fields[current][-1]} {raw.strip()}'.strip()
    if fields:
        flush()
    return records


def _first(fields: dict[str, list[str]], *tags: str) -> str:
    for tag in tags:
        for value in fields.get(tag) or []:
            if str(value).strip():
                return str(value).strip()
    return ''


def _all(fields: dict[str, list[str]], *tags: str) -> list[str]:
    values: list[str] = []
    for tag in tags:
        values += [str(value).strip() for value in fields.get(tag) or [] if str(value).strip()]
    return values


def parse(text: str) -> tuple[list[dict], int]:
    rows: list[dict] = []
    skipped = 0
    for fields in _blocks(text):
        title = _first(fields, 'TI', 'T1', 'CT')
        if not title:
            skipped += 1
            continue
        notes = _all(fields, 'RF', 'N1')
        refs: list[str] = []
        for note in notes:
            refs += references_from_field(note)
        rows.append(
            make_row(
                title=title,
                authors=split_authors(';'.join(_all(fields, 'AU', 'A1'))),
                affiliations=';'.join(_all(fields, 'AD', 'C1')),
                journal=_first(fields, 'JO', 'JF', 'T2', 'JA'),
                year=year_of(_first(fields, 'PY', 'Y1', 'DA')),
                volume=_first(fields, 'VL'),
                issue=_first(fields, 'IS'),
                page_start=_first(fields, 'SP'),
                page_end=_first(fields, 'EP'),
                keywords=split_keywords(';'.join(_all(fields, 'KW'))),
                abstract=_first(fields, 'AB', 'N2'),
                refs=refs,
                structured_refs=structured_references(refs),
                doi=_first(fields, 'DO'),
                fmt=ID,
                country=countries(';'.join(_all(fields, 'AD', 'C1'))),
                tc=_first(fields, 'TC'),
                usage=_first(fields, 'U1'),
                usage2013=_first(fields, 'U2'),
                funding=_first(fields, 'FU', 'FX'),
                doctype=_TYPES.get(_first(fields, 'TY').upper(), _first(fields, 'TY')),
                language=_first(fields, 'LA'),
            )
        )
    return rows, skipped


SPEC = FormatSpec(
    id=ID,
    label=LABEL,
    extensions=('.ris', '.txt'),
    capabilities=frozenset(
        (
            'refs',
            'tc',
            'usage',
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
)
