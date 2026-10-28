"""Lens scholarly-works CSV export.

The column names below are the ones this download really writes (``Lens ID``, ``Author/s``,
``Issue Number``, ``Fields of Study``, ``MeSH Terms``, ``Citing Works Count``), read off the
export in ``samples/``. Two things it does *not* carry decide what cannot be built from it,
and both are stated rather than worked around:

* ``References`` is a list of **Lens record ids** (``002-341-399-981-03X; …``), not citation
  text. Putting those in the reference column would draw a co-citation network whose nodes are
  opaque numbers and would fill the structured-citation JSON with empty author/title fields —
  a well-formed table with the wrong meaning. So ``refs`` is not declared and the column is
  not read; the export guide names WoS/Scopus for citation networks.
* There is no affiliation or address column: ``Author/s`` holds names only, and ``Source
  Country`` is where the *journal* sits, not where the authors do. Mapping it to 国家 would
  answer a different question than the author/institution networks ask, so country is not
  declared either.
"""

from services.biblio.formats.base import FormatSpec
from services.biblio.formats.common import (
    frame_cell,
    frame_has_groups,
    frame_of,
    header_has_groups,
    make_row,
    split_authors,
    split_keywords,
    year_of,
)

ID = 'Lens'
LABEL = 'Lens'
#: ``Lens ID`` names the vendor, and the second group separates the scholarly collection from
#: the patent one, which shares ``Lens ID`` and ``Title`` but writes neither of these columns.
#: A signature that only required the id would claim the patent export and draw applicants as
#: authors — :mod:`services.biblio.formats.unsupported` exists for exactly that file.
_GROUPS = (
    ('Lens ID',),
    ('Citing Works Count', 'Fields of Study'),
    ('Title',),
)


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
        keywords = ';'.join(
            part
            for part in (
                frame_cell(source, frame, 'Keywords'),
                frame_cell(source, frame, 'MeSH Terms'),
            )
            if part
        )
        rows.append(
            make_row(
                title=title,
                authors=split_authors(frame_cell(source, frame, 'Author/s', 'Authors')),
                journal=frame_cell(source, frame, 'Source Title'),
                year=year_of(frame_cell(source, frame, 'Publication Year', 'Date Published')),
                volume=frame_cell(source, frame, 'Volume'),
                issue=frame_cell(source, frame, 'Issue Number', 'Issue'),
                page_start=frame_cell(source, frame, 'Start Page'),
                page_end=frame_cell(source, frame, 'End Page'),
                keywords=split_keywords(keywords),
                abstract=frame_cell(source, frame, 'Abstract'),
                doi=frame_cell(source, frame, 'DOI'),
                fmt=ID,
                category=frame_cell(source, frame, 'Fields of Study'),
                tc=frame_cell(source, frame, 'Citing Works Count'),
                funding=frame_cell(source, frame, 'Funding'),
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
            'tc',
            'categories',
            'abstract',
            'keywords',
            'doi',
            'doctype',
            'funding',
        )
    ),
    detect=detect,
    parse=parse,
    detect_frame=detect_frame,
    parse_frame=parse_frame,
)
