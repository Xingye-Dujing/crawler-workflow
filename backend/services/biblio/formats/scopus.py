"""Scopus CSV export.

The download follows the browser's language: the same "Download" button writes
``文献标题/年份/来源出版物名称/施引文献/参考文献`` for a Chinese UI and ``Title/Source
title/Cited by/References`` for an English one. Both spellings are candidates for every
field, because a signature that only knows one refuses the real file the user has. The
English names are not stable either — the count column has shipped as both ``Citation
count`` and ``Cited by``, and the article number as both ``Article number`` and
``Art. No.`` — so a measured file adds candidates rather than replacing them.
"""

import re

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
    text,
    year_of,
)
from services.biblio.refs import structured_references

ID = 'Scopus'
LABEL = 'Scopus'
#: One group per piece of evidence: a title column, plus something only a Scopus
#: download carries (its accession id or the database-name column).
_GROUPS = (
    ('Title', '文献标题'),
    ('EID', 'Scopus', '来源出版物'),
)
#: Scopus appends the author's identifier to each name: ``Selby, Christina N. (57952067000)``.
#: Left in, the same person is a different node in a WoS/Scopus fusion.
_AUTHOR_ID = re.compile(r'\s*\((?:\d{4}-\d{4}-\d{4}[\dXx]|orcid:[^)]+|\d{9,12}[a-z]?)\)\s*$', re.IGNORECASE)


def detect(value: str) -> bool:
    return header_has_groups(value, _GROUPS)


def detect_frame(frame) -> bool:
    return frame_has_groups(frame, _GROUPS)


def _authors(value: str) -> str:
    """``Author full names`` minus the identifier each name carries."""
    names = [_AUTHOR_ID.sub('', part).strip() for part in text(value).split(';')]
    return split_authors(';'.join(name for name in names if name))


def parse_frame(frame) -> tuple[list[dict], int]:
    rows: list[dict] = []
    skipped = 0
    for _, source in frame.iterrows():
        title = frame_cell(source, frame, 'Title', '文献标题')
        if not title:
            skipped += 1
            continue
        refs = references_from_field(frame_cell(source, frame, 'References', '参考文献'))
        page_start = frame_cell(source, frame, 'Page start', '起始页码')
        # An article-number journal writes no page range: Scopus puts the paper's
        # number where the pages would be, and 论文编号 is that number.
        page_end = frame_cell(source, frame, 'Page end', '结束页码')
        if not page_start:
            page_start = frame_cell(source, frame, 'Article number', 'Art. No.', '论文编号')
        keywords = ';'.join(
            part
            for part in (
                frame_cell(source, frame, 'Author Keywords', '作者关键字'),
                frame_cell(source, frame, 'Index Keywords', '索引关键字'),
            )
            if part
        )
        rows.append(
            make_row(
                title=title,
                authors=_authors(frame_cell(source, frame, 'Author full names', 'Authors', '作者')),
                affiliations=frame_cell(source, frame, 'Affiliations', 'Authors with affiliations', '作者单位'),
                # `来源出版物` alone is the database name (its value is literally "Scopus"),
                # so only the title column may answer for the journal.
                journal=frame_cell(source, frame, 'Source title', '来源出版物名称'),
                year=year_of(frame_cell(source, frame, 'Year', '年份')),
                volume=frame_cell(source, frame, 'Volume', '卷'),
                issue=frame_cell(source, frame, 'Issue', '期'),
                page_start=page_start,
                page_end=page_end,
                keywords=split_keywords(keywords),
                abstract=frame_cell(source, frame, 'Abstract', '摘要'),
                refs=refs,
                structured_refs=structured_references(refs),
                doi=frame_cell(source, frame, 'DOI'),
                fmt=ID,
                country=countries(frame_cell(source, frame, 'Affiliations', 'Authors with affiliations', '作者单位')),
                tc=frame_cell(source, frame, 'Citation count', 'Cited by', '施引文献'),
                funding=';'.join(
                    part
                    for part in (
                        frame_cell(source, frame, 'Funding Details', '资助详情'),
                        frame_cell(source, frame, 'Funding Texts', 'Funding Text 1'),
                    )
                    if part
                ),
                doctype=frame_cell(source, frame, 'Document Type', '文献类型'),
                language=frame_cell(source, frame, 'Language of original document', '语言'),
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
