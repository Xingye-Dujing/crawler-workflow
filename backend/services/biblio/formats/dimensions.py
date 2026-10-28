"""Dimensions CSV export.

The download's first row is not a header: Dimensions writes its copyright notice there,
so a reader that takes line 1 as column names sees one long sentence and 34 unnamed
columns. The banner is dropped in :func:`services.biblio.formats.common.frame_of`.

Column names below are the ones the publication export really writes (``PubYear``,
``Pagination``, ``MeSH terms``, ``Times cited``, ``Fields of Research (ANZSRC 2020)``);
there is no ``Language`` and no ``Countries`` column in it, so those stay empty instead
of being invented from another field.
"""

from services.biblio.formats.base import FormatSpec
from services.biblio.formats.common import (
    countries,
    frame_cell,
    frame_has_groups,
    frame_of,
    header_has_groups,
    make_row,
    references_from_field,
    split_authors,
    split_keywords,
    year_of,
)
from services.biblio.refs import structured_references

ID = 'Dimensions'
LABEL = 'Dimensions'
#: A publication id or a title, plus a column that only a Dimensions export writes.
#: ``Source title`` was in here and it is not unique: Lens uses the same label, and the
#: first registry entry to answer wins, so the Lens demo came back labelled Dimensions.
_GROUPS = (
    ('Publication ID', 'Title'),
    ('Dimensions URL', 'Source Linkout'),
)
_AFFILIATIONS = ('Authors Affiliations', 'Authors (Raw Affiliation)', 'Author Affiliations', 'Affiliations')
_CATEGORIES = ('Fields of Research (ANZSRC 2020)', 'Fields of Research', 'Field of Research', 'Fields of Study')


def detect(value: str) -> bool:
    return header_has_groups(value, _GROUPS)


def detect_frame(frame) -> bool:
    return frame_has_groups(frame, _GROUPS)


def parse_frame(frame) -> tuple[list[dict], int]:
    rows: list[dict] = []
    skipped = 0
    for _, source in frame.iterrows():
        title = frame_cell(source, frame, 'Title')
        if not title:
            skipped += 1
            continue
        refs = references_from_field(frame_cell(source, frame, 'References'))
        affiliations = frame_cell(source, frame, *_AFFILIATIONS)
        # The publication export has no country column. ``Authors Affiliations`` keeps only
        # institution names; the city and country live in ``Authors (Raw Affiliation)``,
        # so the country is read from that column rather than from the one we store.
        nation = frame_cell(source, frame, 'Countries', 'Country') or countries(
            frame_cell(source, frame, 'Authors (Raw Affiliation)')
        )
        rows.append(
            make_row(
                title=title,
                authors=split_authors(frame_cell(source, frame, 'Authors')),
                affiliations=affiliations,
                journal=frame_cell(source, frame, 'Source title'),
                year=year_of(frame_cell(source, frame, 'PubYear', 'Publication Year', 'Year')),
                volume=frame_cell(source, frame, 'Volume'),
                issue=frame_cell(source, frame, 'Issue'),
                page_start=frame_cell(source, frame, 'Pagination', 'Pages', 'Page start'),
                page_end=frame_cell(source, frame, 'Page end'),
                keywords=split_keywords(frame_cell(source, frame, 'Keywords', 'MeSH terms')),
                abstract=frame_cell(source, frame, 'Abstract'),
                refs=refs,
                structured_refs=structured_references(refs),
                doi=frame_cell(source, frame, 'DOI'),
                fmt=ID,
                country=countries(nation) if nation else '',
                category=frame_cell(source, frame, *_CATEGORIES),
                tc=frame_cell(source, frame, 'Times cited', 'Citation count'),
                funding=frame_cell(source, frame, 'Funding', 'Funding Details'),
                doctype=frame_cell(source, frame, 'Publication Type', 'Document Type'),
                language=frame_cell(source, frame, 'Language'),
            )
        )
    return rows, skipped


def parse(value: str) -> tuple[list[dict], int]:
    return parse_frame(frame_of(value))


SPEC = FormatSpec(
    id=ID,
    label=LABEL,
    extensions=('.csv',),
    capabilities=frozenset(
        (
            'refs',
            'tc',
            'categories',
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
