"""Web of Science plain-text (tagged) export."""

import re
from collections import defaultdict

from services.biblio_formats.base import FormatSpec
from services.biblio_formats.common import countries, make_row, split_authors, split_keywords, year_of

ID = 'WoS'
LABEL = 'Web of Science'
_TAG = re.compile(r'^([A-Z][A-Z0-9])\s+(.*)$')
_CONTINUATION = re.compile(r'^\s{2,}\S')


def detect(text: str) -> bool:
    return bool(re.search(r'(?m)^PT\s+\S', text) and re.search(r'(?m)^ER\s*$', text))


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
            tag, value = match.group(1), match.group(2).strip()
            if tag == 'ER':
                flush()
                continue
            if tag == 'PT' and fields:
                flush()
            fields[tag].append(value)
            current = tag
            continue
        if current and _CONTINUATION.match(raw):
            value = raw.strip()
            if not value:
                continue
            if current in ('AU', 'AF', 'C1', 'CR'):
                # WoS indents every author, address and cited reference with
                # three spaces. They are list items, not wrapped lines; merging
                # them would fuse authors and collapse separate references.
                fields[current].append(value)
            else:
                fields[current][-1] = f'{fields[current][-1]} {value}'.strip()
    if fields:
        flush()
    return records


def _first(fields: dict[str, list[str]], *tags: str) -> str:
    for tag in tags:
        for value in fields.get(tag) or []:
            if str(value).strip():
                return str(value).strip()
    return ''


def _all(fields: dict[str, list[str]], *tags: str) -> str:
    values: list[str] = []
    for tag in tags:
        values += [str(value).strip() for value in fields.get(tag) or [] if str(value).strip()]
    return ';'.join(values)


def parse(text: str) -> tuple[list[dict], int]:
    rows: list[dict] = []
    skipped = 0
    for fields in _blocks(text):
        title = _first(fields, 'TI', 'T1')
        if not title:
            skipped += 1
            continue
        refs = [str(value).strip() for value in fields.get('CR') or [] if str(value).strip()]
        authors = _all(fields, 'AU') or _all(fields, 'AF')
        rows.append(
            make_row(
                title=title,
                authors=split_authors(authors),
                affiliations=';'.join(fields.get('C1') or []),
                journal=_first(fields, 'SO', 'J9', 'JI'),
                year=year_of(_first(fields, 'PY', 'PD', 'DA')),
                volume=_first(fields, 'VL'),
                issue=_first(fields, 'IS'),
                page_start=_first(fields, 'BP'),
                page_end=_first(fields, 'EP'),
                keywords=split_keywords(_all(fields, 'DE', 'ID')),
                abstract=_first(fields, 'AB'),
                refs=refs,
                doi=_first(fields, 'DI', 'DO'),
                fmt=ID,
                country=countries(';'.join(fields.get('C1') or [])),
                category=_all(fields, 'SC', 'WC'),
                tc=_first(fields, 'TC', 'Z9'),
                usage=_first(fields, 'U1'),
                usage2013=_first(fields, 'U2'),
                funding=_all(fields, 'FU', 'FX'),
                doctype=_first(fields, 'DT'),
                language=_first(fields, 'LA'),
            )
        )
    return rows, skipped


SPEC = FormatSpec(
    id=ID,
    label=LABEL,
    extensions=('.txt',),
    capabilities=frozenset(
        (
            'refs',
            'tc',
            'usage',
            'categories',
            'grants',
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
