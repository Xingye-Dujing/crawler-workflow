"""Shared normalization helpers for the bibliographic format registry."""

import csv
import io
import math
import re

import pandas as pd

from services.biblio.formats.countries import countries_in
from services.biblio.importer import _join_authors, _join_list, _row
from services.biblio.refs import parse_reference, references_json, structured_references

_CELL_SPLIT = re.compile(r'[;；]+')
_YEAR = re.compile(r'(?:19|20)\d{2}')


def text(value) -> str:
    if value is None:
        return ''
    if isinstance(value, float) and math.isnan(value):
        return ''
    return str(value).strip()


def int_value(value, default=''):
    raw = text(value).replace(',', '').replace(' ', '')
    if not raw:
        return default
    match = re.search(r'-?\d+', raw)
    return int(match.group(0)) if match else default


def year_of(value):
    match = _YEAR.search(text(value))
    return int(match.group(0)) if match else ''


def split_keywords(value) -> str:
    return _join_list(text(value))


def split_authors(value) -> str:
    return _join_authors(text(value))


def split_affiliations(value) -> str:
    return _join_list(text(value), _CELL_SPLIT)


def pages(start, end='') -> str:
    first, last = text(start), text(end)
    if first and last and first != last:
        return f'{first}-{last}'
    return first or last


def references_from_field(value) -> list[str]:
    """Split a free-form citation field into one entry per cited work.

    Scopus and Dimensions use ``;`` between references while a title may itself
    contain ``;``. A split is therefore accepted only when the following text
    starts a new author-year block; otherwise the original field stays one
    reference rather than becoming fragments.
    """
    raw = text(value)
    if not raw:
        return []
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) > 1:
        return lines
    parts = re.split(r';\s*(?=[A-Z][^;]{0,240}?,\s*(?:19|20)\d{2})', raw)
    if len(parts) == 1:
        parts = [part for part in raw.split(';') if part.strip()]
    return [part.strip() for part in parts if part.strip()]


def refs_payload(raw_refs: list[str], structured: list[dict] | None = None) -> tuple[str, str]:
    """The raw reference text and the canonical structured JSON."""
    parsed = structured if structured is not None else structured_references(raw_refs)
    return '\n'.join(raw_refs), references_json(parsed)


def make_row(
    *,
    title,
    authors='',
    affiliations='',
    journal='',
    year='',
    volume='',
    issue='',
    page_start='',
    page_end='',
    keywords='',
    abstract='',
    refs: list[str] | None = None,
    structured_refs: list[dict] | None = None,
    doi='',
    fmt,
    country='',
    category='',
    tc='',
    usage='',
    usage2013='',
    funding='',
    doctype='',
    language='',
) -> dict:
    refs = list(refs or [])
    return _row(
        title=str(title or ''),
        authors=str(authors or ''),
        affiliations=str(affiliations or ''),
        journal=str(journal or ''),
        year=year,
        volume=str(volume or ''),
        issue=str(issue or ''),
        pages=pages(page_start, page_end),
        keywords=str(keywords or ''),
        abstract=str(abstract or ''),
        refs=refs,
        doi=str(doi or ''),
        fmt=fmt,
        country=str(country or ''),
        category=str(category or ''),
        tc=int_value(tc),
        usage=int_value(usage),
        usage2013=int_value(usage2013),
        funding=str(funding or ''),
        doctype=str(doctype or ''),
        language=str(language or ''),
        citations=structured_refs if structured_refs is not None else structured_references(refs),
    )


def header_of(text_value: str) -> list[str]:
    """The first CSV line's column names, with a BOM removed."""
    for line in data_lines(text_value):
        try:
            row = next(csv.reader([line]))
        except csv.Error:
            return []
        return [cell.strip().lstrip('\ufeff').strip('"\'') for cell in row]
    return []


#: A vendor preamble written as the first CSV row instead of a comment.
_PROVENANCE = re.compile(r'^["\ufeff]?\s*(?:about the data|exported on|downloaded from)\b', re.I)


def data_lines(text_value: str) -> list[str]:
    """The CSV lines a reader should parse, with a leading provenance banner dropped.

    Dimensions writes its copyright notice as the first row of the download, so pandas
    reads that sentence as the column names and every format signature then fails on a
    real file while passing the synthetic one. Only *leading* banner lines are dropped;
    the notice never appears mid-table, and dropping a row that is not a banner would
    shift a real header off, so the check stays anchored to the phrases above.
    """
    lines = [
        line for line in str(text_value or '').replace('\r\n', '\n').replace('\r', '\n').split('\n') if line.strip()
    ]
    while lines and _PROVENANCE.match(lines[0]):
        lines.pop(0)
    return lines


def frame_of(text_value: str) -> pd.DataFrame:
    """Read a bibliographic CSV without letting pandas invent nulls."""
    lines = data_lines(text_value)
    header = header_of(text_value)
    delimiter = ','
    if header and header.count(';') > header.count(','):
        delimiter = ';'
    return pd.read_csv(
        io.StringIO('\n'.join(lines)),
        sep=delimiter,
        dtype=str,
        keep_default_na=False,
        na_values=[],
        engine='python',
    )


def _norm(name: str) -> str:
    return re.sub(r'[\s_\-]+', ' ', str(name or '').strip().lower())


def column_of(frame: pd.DataFrame, *names: str) -> str | None:
    """The real column matching the first candidate name, case/space insensitive."""
    lookup = {_norm(column): column for column in frame.columns}
    for name in names:
        found = lookup.get(_norm(name))
        if found is not None:
            return found
    return None


def cell(row, *names: str) -> str:
    for name in names:
        if name in row:
            value = text(row.get(name))
            if value:
                return value
    return ''


def frame_cell(row, frame: pd.DataFrame, *names: str) -> str:
    column = column_of(frame, *names)
    return text(row.get(column)) if column else ''


def has_columns(frame: pd.DataFrame, required: tuple[str, ...], any_of: tuple[str, ...] = ()) -> bool:
    names = {_norm(column) for column in frame.columns}
    if not all(_norm(name) in names for name in required):
        return False
    return not any_of or any(_norm(name) in names for name in any_of)


def header_has(text_value: str, required: tuple[str, ...], any_of: tuple[str, ...] = ()) -> bool:
    names = {_norm(name) for name in header_of(text_value)}
    if not all(_norm(name) in names for name in required):
        return False
    return not any_of or any(_norm(name) in names for name in any_of)


def countries(value: str) -> str:
    return ';'.join(countries_in(value))


def _has_groups(names: set[str], groups: tuple[tuple[str, ...], ...]) -> bool:
    """Every group answered by at least one column name.

    Exports rename their columns by locale — the same Scopus download writes
    ``文献标题`` where the English one writes ``Title`` — so a signature built from one
    required name refuses a real file and passes the synthetic one. "this name or that
    one", per group, is the honest shape.
    """
    return all(any(_norm(candidate) in names for candidate in group) for group in groups)


def frame_has_groups(frame: pd.DataFrame, groups: tuple[tuple[str, ...], ...]) -> bool:
    return _has_groups({_norm(column) for column in frame.columns}, groups)


def header_has_groups(text_value: str, groups: tuple[tuple[str, ...], ...]) -> bool:
    return _has_groups({_norm(name) for name in header_of(text_value)}, groups)


def parse_ref(value: str) -> dict | None:
    return parse_reference(value)
