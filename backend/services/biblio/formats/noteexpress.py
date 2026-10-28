"""NoteExpress ``.net`` export — the format CNKI labels 「NoteExpress 下载」.

Tagged like EndNote's ``.enw`` but with brace-quoted keys, one per line:

    {Reference Type}: Journal Article
    {Title}: …
    {Author}: 常世亮;常世恺;吴衍卓

A record is closed by a repeat of a leading key, the same rule the EndNote reader uses.
``{Pages}`` arrives as one range (``64-67``); ``{ISBN/ISSN}`` carries both identifiers in
one field, so it is not pretended to be a DOI. ``{Database Provider}`` names where the
records came from (CNKI writes 中国知网 here) and is kept out of the table: the ``格式``
column answers which *format* was read, not which database paid for it.
"""

import re

from services.biblio.formats.base import FormatSpec
from services.biblio.formats.common import countries, make_row, split_authors, split_keywords, year_of

ID = 'NoteExpress'
LABEL = 'NoteExpress'
_KEY = re.compile(r'^\s*\{([^}]{1,40})\}\s*:\s*(.*)$')
#: A key that opens a record. CNKI writes ``{Reference Type}`` first, but a plain
#: NoteExpress library export may start at the title, so both close the previous record.
_START_KEYS = frozenset({'reference type', 'title'})


def detect(text: str) -> bool:
    value = str(text or '')
    return bool(re.search(r'(?m)^\s*\{Reference Type\}\s*:', value)) and bool(
        re.search(r'(?m)^\s*\{Title\}\s*:', value)
    )


def _records(text: str) -> list[dict[str, list[str]]]:
    records: list[dict[str, list[str]]] = []
    fields: dict[str, list[str]] = {}
    current: str | None = None
    for raw in str(text or '').replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        line = raw.strip()
        if not line:
            continue
        match = _KEY.match(line)
        if not match:
            # An untagged line continues the previous value: abstracts wrap freely.
            if current and fields.get(current):
                fields[current][-1] = f'{fields[current][-1]} {line}'.strip()
            continue
        key, value = match.group(1).strip(), match.group(2).strip()
        if key.lower() in _START_KEYS and any(item.lower() == 'title' for item in fields):
            records.append(fields)
            fields = {}
            current = None
        fields.setdefault(key, []).append(value)
        current = key
    if fields:
        records.append(fields)
    return records


def _value(fields: dict, *names: str) -> str:
    lowered = {str(key).lower(): values for key, values in fields.items()}
    for name in names:
        for value in lowered.get(name.lower()) or []:
            text_value = str(value or '').strip()
            if text_value:
                return text_value
    return ''


def parse(text: str) -> tuple[list[dict], int]:
    rows: list[dict] = []
    skipped = 0
    for fields in _records(text):
        title = _value(fields, 'Title')
        if not title:
            skipped += 1
            continue
        affiliations = _value(fields, 'Author Address', 'Addresses')
        rows.append(
            make_row(
                title=title,
                authors=split_authors(_value(fields, 'Author', 'Authors')),
                affiliations=affiliations,
                journal=_value(fields, 'Journal', 'Periodical', 'Secondary Title'),
                year=year_of(_value(fields, 'Year', 'Date')),
                volume=_value(fields, 'Volume'),
                issue=_value(fields, 'Issue', 'Number'),
                page_start=_value(fields, 'Pages', 'Page'),
                keywords=split_keywords(_value(fields, 'Keywords', 'Key Words')),
                abstract=_value(fields, 'Abstract'),
                refs=[],
                doi=_value(fields, 'DOI'),
                fmt=ID,
                country=countries(affiliations),
                doctype=_value(fields, 'Reference Type', 'Type of Work'),
                funding=_value(fields, 'Funding', 'Grant'),
            )
        )
    return rows, skipped


SPEC = FormatSpec(
    id=ID,
    label=LABEL,
    extensions=('.net', '.txt'),
    capabilities=frozenset(('abstract', 'keywords', 'country', 'doi', 'doctype', 'funding')),
    detect=detect,
    parse=parse,
)
