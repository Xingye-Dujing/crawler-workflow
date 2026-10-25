"""Web of Science plain-text (tagged) export."""

import re
from collections import defaultdict

from services.biblio_formats.base import FormatSpec
from services.biblio_formats.common import (
    countries,
    frame_cell,
    frame_has_groups,
    frame_of,
    header_has_groups,
    make_row,
    references_from_field,
    split_authors,
    split_keywords,
    structured_references,
    year_of,
)

ID = 'WoS'
LABEL = 'Web of Science'
_TAG = re.compile(r'^([A-Z][A-Z0-9])\s+(.*)$')
_CONTINUATION = re.compile(r'^\s{2,}\S')
#: WoS' Excel / Tab-delimited download: a title column plus something only that table writes.
_TABLE_GROUPS = (
    ('Article Title',),
    ('UT (Unique WOS ID)', 'Source Title', 'Times Cited, All Databases', 'Web of Science Record'),
)


def detect(text: str) -> bool:
    if re.search(r'(?m)^PT\s+\S', text) and re.search(r'(?m)^ER\s*$', text):
        return True
    # A user who opens the Excel export and re-saves it as CSV is the common case, and the
    # upload route recognises formats from the text before it ever builds a frame.
    return header_has_groups(text, _TABLE_GROUPS)


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
    """Parse a WoS download from its text, choosing the reader by the file's shape.

    The upload route recognises formats from the raw text, and a tab-delimited or
    re-saved CSV WoS file answers to that same text — so a reader that only knew the
    two-letter tags would refuse the table it had just claimed.
    """
    if header_has_groups(text, _TABLE_GROUPS):
        return parse_frame(frame_of(text))
    return parse_tagged(text)


def parse_tagged(text: str) -> tuple[list[dict], int]:
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


# ─── Table export (Excel, and a re-saved CSV of the same columns) ────────
#
# WoS' "Excel" download uses the long English labels below — a different document from the
# tagged text, with the same content and extra things the text does not carry: `180 Day Usage
# Count` / `Since 2013 Usage Count` and `Affiliations` arrive as their own columns. Reading only
# the tagged file would refuse the export most users click, since Excel is the button with the
# shortest name. The measured Excel download (thirty records) leaves Cited References, Author
# Keywords, WoS Categories and Funding empty for every row, so a table-only upload cannot answer
# for those networks; the plain-text download of the same records does. A Tab-delimited download
# is not claimed anywhere: no such file has been measured, and its separators are not what the
# CSV reader here is proved on.


def detect_frame(frame) -> bool:
    return frame_has_groups(frame, _TABLE_GROUPS)


def parse_frame(frame) -> tuple[list[dict], int]:
    rows: list[dict] = []
    skipped = 0
    for _, source in frame.iterrows():
        title = frame_cell(source, frame, 'Article Title', 'Book Title', 'Item Title')
        if not title:
            skipped += 1
            continue
        refs = references_from_field(frame_cell(source, frame, 'Cited References'))
        addresses = frame_cell(source, frame, 'Addresses', 'Reprint Addresses')
        affiliations = frame_cell(source, frame, 'Affiliations') or addresses
        rows.append(
            make_row(
                title=title,
                authors=split_authors(frame_cell(source, frame, 'Author Full Names', 'Authors')),
                affiliations=affiliations,
                journal=frame_cell(source, frame, 'Source Title', 'Journal Abbreviation'),
                year=year_of(frame_cell(source, frame, 'Publication Year', 'Publication Date')),
                volume=frame_cell(source, frame, 'Volume'),
                issue=frame_cell(source, frame, 'Issue'),
                page_start=frame_cell(source, frame, 'Start Page', 'Article Number'),
                page_end=frame_cell(source, frame, 'End Page'),
                keywords=split_keywords(
                    ';'.join(
                        part
                        for part in (
                            frame_cell(source, frame, 'Author Keywords'),
                            frame_cell(source, frame, 'Keywords Plus'),
                        )
                        if part
                    )
                ),
                abstract=frame_cell(source, frame, 'Abstract'),
                refs=refs,
                structured_refs=structured_references(refs),
                doi=frame_cell(source, frame, 'DOI'),
                fmt=ID,
                country=countries(addresses or affiliations),
                category=frame_cell(source, frame, 'WoS Categories', 'Web of Science Categories', 'Research Areas'),
                tc=frame_cell(source, frame, 'Times Cited, All Databases', 'Times Cited, WoS Core'),
                usage=frame_cell(source, frame, '180 Day Usage Count'),
                usage2013=frame_cell(source, frame, 'Since 2013 Usage Count'),
                funding=';'.join(
                    part
                    for part in (
                        frame_cell(source, frame, 'Funding Text', 'Funding Text 1'),
                        frame_cell(source, frame, 'Funding Orgs', 'Funding Name Preferred'),
                    )
                    if part
                ),
                doctype=frame_cell(source, frame, 'Document Type'),
                language=frame_cell(source, frame, 'Language', 'Language of Text'),
            )
        )
    return rows, skipped


SPEC = FormatSpec(
    id=ID,
    label=LABEL,
    extensions=('.txt', '.xls', '.xlsx'),
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
    detect_frame=detect_frame,
    parse_frame=parse_frame,
)
