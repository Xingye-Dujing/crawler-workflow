"""BibTeX / BibLaTeX database file."""

import re

from services.biblio.formats.base import FormatSpec
from services.biblio.formats.common import make_row, references_from_field, split_authors, year_of
from services.biblio.refs import structured_references

ID = 'BibTeX'
LABEL = 'BibTeX'
_ENTRY = re.compile(r'@([A-Za-z]+)\s*[({]')
_TYPES = {
    'article': 'Journal Article',
    'book': 'Book',
    'inbook': 'Book Chapter',
    'incollection': 'Book Chapter',
    'inproceedings': 'Conference Paper',
    'conference': 'Conference Paper',
    'proceedings': 'Conference Proceedings',
    'phdthesis': 'Thesis',
    'mastersthesis': 'Thesis',
    'techreport': 'Report',
    'unpublished': 'Unpublished Work',
    'misc': 'Miscellaneous',
}


def detect(text: str) -> bool:
    return bool(
        re.search(
            r'(?m)^\s*@(article|book|inbook|incollection|inproceedings|conference|phdthesis|mastersthesis|techreport|unpublished|misc)\s*[({]',
            text,
        )
    )


def _balanced(text: str, start: int, opening: str, closing: str) -> int:
    depth = 0
    index = start
    quote = False
    while index < len(text):
        char = text[index]
        if char == '\\':
            index += 2
            continue
        if char == '"' and opening == '{':
            quote = not quote
        elif not quote:
            if char == opening:
                depth += 1
            elif char == closing:
                depth -= 1
                if depth == 0:
                    return index
        index += 1
    return -1


def _value(text: str, start: int) -> tuple[str, int]:
    # Unlike :func:`_balanced`, this reads whichever delimiter the field actually opens with
    # (``{…}``, ``"…"`` or a bare token), so no pair is handed in.
    while start < len(text) and text[start].isspace():
        start += 1
    if start >= len(text):
        return '', start
    pieces: list[str] = []
    index = start
    while index < len(text):
        char = text[index]
        if char == '{':
            end = _balanced(text, index, '{', '}')
            if end < 0:
                end = len(text) - 1
            pieces.append(text[index + 1 : end])
            index = end + 1
        elif char == '"':
            end = index + 1
            while end < len(text) and text[end] != '"':
                end += 2 if text[end] == '\\' else 1
            pieces.append(text[index + 1 : end])
            index = min(len(text), end + 1)
        else:
            end = index
            while end < len(text) and text[end] not in ',)#':
                end += 1
            pieces.append(text[index:end])
            index = end
        while index < len(text) and text[index].isspace():
            index += 1
        if index < len(text) and text[index] == '#':
            index += 1
            continue
        break
    return ''.join(pieces).strip(), index


def _fields(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    index = 0
    while index < len(body):
        while index < len(body) and body[index] in ' ,\t\r\n':
            index += 1
        match = re.match(r'[A-Za-z][A-Za-z0-9_\-]*', body[index:])
        if not match:
            index += 1
            continue
        name = match.group(0).lower()
        index += len(match.group(0))
        while index < len(body) and body[index].isspace():
            index += 1
        if index >= len(body) or body[index] != '=':
            continue
        value, index = _value(body, index + 1)
        if value:
            fields[name] = _clean(value)
    return fields


def _clean(value: str) -> str:
    text = str(value or '').strip()
    text = text.replace('\\&', '&').replace('\\%', '%').replace('\\_', '_')
    text = re.sub(r'\\[a-zA-Z]+\s*', '', text)
    text = text.replace('{', '').replace('}', '')
    return re.sub(r'\s+', ' ', text).strip()


def _records(text: str) -> list[tuple[str, dict[str, str]]]:
    records: list[tuple[str, dict[str, str]]] = []
    for match in _ENTRY.finditer(text):
        entry_type = match.group(1).lower()
        if entry_type in ('comment', 'string', 'preamble'):
            continue
        start = match.end() - 1
        opening = text[start]
        closing = '}' if opening == '{' else ')'
        end = _balanced(text, start, opening, closing)
        if end < 0:
            continue
        body = text[start + 1 : end]
        comma = body.find(',')
        if comma < 0:
            continue
        records.append((entry_type, _fields(body[comma + 1 :])))
    return records


def parse(text: str) -> tuple[list[dict], int]:
    rows: list[dict] = []
    skipped = 0
    for entry_type, fields in _records(text):
        title = fields.get('title', '')
        if not title:
            skipped += 1
            continue
        note = fields.get('note', '')
        refs = references_from_field(note) if note and ('[1]' in note or 'doi' in note.lower()) else []
        keywords = fields.get('keywords', '') or fields.get('keyword', '')
        rows.append(
            make_row(
                title=title,
                authors=split_authors(fields.get('author', '').replace(' and ', ';')),
                affiliations=fields.get('affiliation', '') or fields.get('institution', '') or fields.get('school', ''),
                journal=fields.get('journal', '') or fields.get('journaltitle', '') or fields.get('booktitle', ''),
                year=year_of(fields.get('year', '') or fields.get('date', '')),
                volume=fields.get('volume', ''),
                issue=fields.get('number', '') or fields.get('issue', ''),
                page_start=fields.get('pages', '').replace('--', '-'),
                keywords=re.sub(r'[;；,，、]+', ';', keywords).strip(';'),
                abstract=fields.get('abstract', ''),
                refs=refs,
                structured_refs=structured_references(refs),
                doi=fields.get('doi', ''),
                fmt=ID,
                tc=fields.get('citation-count', '') or fields.get('times-cited', '') or fields.get('tc', ''),
                usage=fields.get('usage', ''),
                funding=fields.get('funding', '') or fields.get('acknowledgement', ''),
                doctype=_TYPES.get(entry_type, entry_type.title()),
                language=fields.get('language', ''),
            )
        )
    return rows, skipped


SPEC = FormatSpec(
    id=ID,
    label=LABEL,
    extensions=('.bib', '.bibtex', '.txt'),
    capabilities=frozenset(
        (
            'refs',
            'tc',
            'usage',
            'abstract',
            'keywords',
            'doi',
            'doctype',
            'language',
            'funding',
        )
    ),
    detect=detect,
    parse=parse,
)
