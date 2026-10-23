"""EndNote tagged (Refer) export."""

import re
from collections import defaultdict

from services.biblio_formats.base import FormatSpec
from services.biblio_formats.common import make_row, references_from_field, split_authors, split_keywords, year_of
from services.biblio_refs import structured_references

ID = 'EndNote'
LABEL = 'EndNote'
_TAG = re.compile(r'^(%[0-9A-Za-z@+\-])\s*(.*)$')


def detect(text: str) -> bool:
    return bool(re.search(r'(?m)^%0\s+\S', text))


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
            if tag == '%0' and fields:
                flush()
            fields[tag].append(value)
            current = tag
            continue
        if current and raw.strip():
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


def _all(fields: dict[str, list[str]], *tags: str) -> str:
    values: list[str] = []
    for tag in tags:
        values += [str(value).strip() for value in fields.get(tag) or [] if str(value).strip()]
    return ';'.join(values)


def parse(text: str) -> tuple[list[dict], int]:
    rows: list[dict] = []
    skipped = 0
    for fields in _blocks(text):
        title = _first(fields, '%T')
        if not title:
            skipped += 1
            continue
        notes = [str(value).strip() for value in fields.get('%Z') or [] if str(value).strip()]
        refs: list[str] = []
        for note in notes:
            if re.search(r'\[\d+\]', note):
                refs += references_from_field(note)
        rows.append(
            make_row(
                title=title,
                authors=split_authors(_all(fields, '%A')),
                affiliations=_all(fields, '%+'),
                journal=_first(fields, '%J', '%B'),
                year=year_of(_first(fields, '%D', '%8')),
                volume=_first(fields, '%V'),
                issue=_first(fields, '%N'),
                page_start=_first(fields, '%P'),
                keywords=split_keywords(_all(fields, '%K')),
                abstract=_first(fields, '%X'),
                refs=refs,
                structured_refs=structured_references(refs),
                doi=_first(fields, '%R'),
                fmt=ID,
                tc=_first(fields, '%TC'),
                funding=_first(fields, '%FU', '%FX'),
                doctype=_first(fields, '%0'),
                language=_first(fields, '%G'),
            )
        )
    return rows, skipped


SPEC = FormatSpec(
    id=ID,
    label=LABEL,
    extensions=('.enw', '.txt'),
    capabilities=frozenset(
        (
            'refs',
            'abstract',
            'keywords',
            'doi',
            'doctype',
            'language',
        )
    ),
    detect=detect,
    parse=parse,
)
