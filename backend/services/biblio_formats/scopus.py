"""Scopus CSV export."""

from services.biblio_formats.base import FormatSpec
from services.biblio_formats.common import (
    countries,
    frame_cell,
    frame_of,
    has_columns,
    header_has,
    make_row,
    references_from_field,
    split_authors,
    split_keywords,
    year_of,
)
from services.biblio_refs import structured_references

ID = 'Scopus'
LABEL = 'Scopus'
_REQUIRED = ('title',)
_ANY = ('eid', 'scopus')


def detect(text: str) -> bool:
    return header_has(text, _REQUIRED, _ANY)


def detect_frame(frame) -> bool:
    return has_columns(frame, _REQUIRED, _ANY)


def parse_frame(frame) -> tuple[list[dict], int]:
    rows: list[dict] = []
    skipped = 0
    for _, source in frame.iterrows():
        title = frame_cell(source, frame, 'Title')
        if not title:
            skipped += 1
            continue
        refs = references_from_field(frame_cell(source, frame, 'References'))
        rows.append(
            make_row(
                title=title,
                authors=split_authors(frame_cell(source, frame, 'Author full names', 'Authors')),
                affiliations=frame_cell(source, frame, 'Affiliations', 'Authors with affiliations'),
                journal=frame_cell(source, frame, 'Source title'),
                year=year_of(frame_cell(source, frame, 'Year')),
                volume=frame_cell(source, frame, 'Volume'),
                issue=frame_cell(source, frame, 'Issue'),
                page_start=frame_cell(source, frame, 'Page start'),
                page_end=frame_cell(source, frame, 'Page end'),
                keywords=split_keywords(
                    ';'.join(
                        part
                        for part in (
                            frame_cell(source, frame, 'Author Keywords'),
                            frame_cell(source, frame, 'Index Keywords'),
                        )
                        if part
                    )
                ),
                abstract=frame_cell(source, frame, 'Abstract'),
                refs=refs,
                structured_refs=structured_references(refs),
                doi=frame_cell(source, frame, 'DOI'),
                fmt=ID,
                country=countries(frame_cell(source, frame, 'Affiliations')),
                tc=frame_cell(source, frame, 'Citation count'),
                funding=';'.join(
                    part
                    for part in (
                        frame_cell(source, frame, 'Funding Details'),
                        frame_cell(source, frame, 'Funding Text 1'),
                    )
                    if part
                ),
                doctype=frame_cell(source, frame, 'Document Type'),
                language=frame_cell(source, frame, 'Language of original document'),
            )
        )
    return rows, skipped


def parse(text: str) -> tuple[list[dict], int]:
    return parse_frame(frame_of(text))


SPEC = FormatSpec(
    id=ID,
    label=LABEL,
    extensions=('.csv',),
    capabilities=frozenset(
        (
            'refs',
            'tc',
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
    frame_only=False,
)
