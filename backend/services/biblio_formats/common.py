"""Shared normalization helpers for the bibliographic format registry."""

import csv
import io
import re

import pandas as pd

from services.biblio_formats.countries import countries_in
from services.biblio_import import _join_authors, _join_list, _row
from services.biblio_refs import parse_reference, references_json, structured_references

_CELL_SPLIT = re.compile(r'[;；]+')
_YEAR = re.compile(r'(?:19|20)\d{2}')


def text(value) -> str:
    if value is None:
        return ''
    if isinstance(value, float) and value != value:  # NaN
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
    for line in str(text_value or '').splitlines():
        if not line.strip():
            continue
        try:
            row = next(csv.reader([line]))
        except csv.Error:
            return []
        return [cell.strip().lstrip('\ufeff').strip('"\'') for cell in row]
    return []


def frame_of(text_value: str) -> pd.DataFrame:
    """Read a bibliographic CSV without letting pandas invent nulls."""
    header = header_of(text_value)
    delimiter = ','
    if header and header.count(';') > header.count(','):
        delimiter = ';'
    return pd.read_csv(
        io.StringIO(str(text_value or '')),
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


def parse_ref(value: str) -> dict | None:
    return parse_reference(value)
