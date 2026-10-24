"""PubMed XML (PubMedArticle / PubMedBookArticle)."""

import re
import xml.etree.ElementTree as ET

from i18n import t
from services.biblio_formats.base import FormatSpec
from services.biblio_formats.common import countries, make_row, year_of
from services.biblio_refs import normalize_reference, parse_reference

ID = 'PubMed'
LABEL = 'PubMed'
_ENTITY = re.compile(r'<!ENTITY|<!DOCTYPE[^>]*\[', re.IGNORECASE)


def detect(text: str) -> bool:
    head = str(text or '')[:5000]
    if any(marker in head for marker in ('<PubmedArticle', '<PubmedArticleSet', '<PubmedBookArticle')):
        return True
    return bool(re.search(r'(?m)^PMID-\s+\d+', text) and re.search(r'(?m)^TI\s{2}-', text))


def _local(tag: str) -> str:
    return str(tag).rsplit('}', 1)[-1]


def _children(element, name: str):
    return [child for child in list(element) if _local(child.tag) == name]


def _descendants(element, name: str):
    return [child for child in element.iter() if _local(child.tag) == name]


def _first(element, name: str):
    for child in element.iter():
        if _local(child.tag) == name:
            return child
    return None


def _text(element, name: str) -> str:
    found = _first(element, name)
    return re.sub(r'\s+', ' ', ''.join(found.itertext())).strip() if found is not None else ''


def _all_text(element, name: str) -> list[str]:
    return [
        re.sub(r'\s+', ' ', ''.join(child.itertext())).strip()
        for child in _descendants(element, name)
        if ''.join(child.itertext()).strip()
    ]


def _authors(article) -> tuple[str, str]:
    authors: list[str] = []
    affiliations: list[str] = []
    author_list = _first(article, 'AuthorList')
    if author_list is None:
        return '', ''
    for author in _children(author_list, 'Author'):
        collective = _text(author, 'CollectiveName')
        if collective:
            authors.append(collective)
        else:
            last = _text(author, 'LastName')
            fore = _text(author, 'ForeName') or _text(author, 'Initials')
            name = ' '.join(part for part in (fore, last) if part) or _text(author, 'Name')
            if name:
                authors.append(name)
        for info in _descendants(author, 'Affiliation'):
            value = re.sub(r'\s+', ' ', ''.join(info.itertext())).strip()
            if value:
                affiliations.append(value)
    return ';'.join(authors), ';'.join(affiliations)


def _abstract(article) -> str:
    pieces: list[str] = []
    for part in _descendants(article, 'AbstractText'):
        value = re.sub(r'\s+', ' ', ''.join(part.itertext())).strip()
        if not value:
            continue
        label = part.attrib.get('Label') or part.attrib.get('NlmCategory') or ''
        pieces.append(f'{label}: {value}' if label else value)
    return ' '.join(pieces)


def _doi(article) -> str:
    for loc in _descendants(article, 'ELocationID'):
        if str(loc.attrib.get('EIdType') or '').lower() == 'doi':
            value = ''.join(loc.itertext()).strip()
            if value:
                return value
    for identifier in _descendants(article, 'ArticleId'):
        if str(identifier.attrib.get('IdType') or '').lower() == 'doi':
            value = ''.join(identifier.itertext()).strip()
            if value:
                return value
    return ''


def _references(element, citation) -> tuple[list[str], list[dict]]:
    raw: list[str] = []
    structured: list[dict] = []
    for ref in _descendants(element, 'Reference'):
        value = _text(ref, 'Citation')
        doi = ''
        for identifier in _descendants(ref, 'ArticleId'):
            if str(identifier.attrib.get('IdType') or '').lower() == 'doi':
                doi = ''.join(identifier.itertext()).strip()
        if not value and not doi:
            continue
        item = parse_reference(value) if value else None
        if item is None:
            item = normalize_reference({'raw': value, 'title': value, 'doi': doi})
        if item is None:
            continue
        if doi:
            item['doi'] = doi
        raw.append(value or doi)
        structured.append(item)
    if not raw:
        # A citation list on the record itself is rare, but PubMed books use
        # their own citation element; keep the fallback honest.
        citation_text = ''.join(citation.itertext()).strip() if citation is not None else ''
        if citation_text:
            parsed = parse_reference(citation_text)
            if parsed:
                raw.append(citation_text)
                structured.append(parsed)
    return raw, structured


def _row(element) -> dict | None:
    citation = element if _local(element.tag) == 'MedlineCitation' else _first(element, 'MedlineCitation')
    article = _first(citation, 'Article') if citation is not None else None
    if article is None:
        article = _first(element, 'BookDocument')
    if article is None:
        citation = element
        article = element
    title = _text(article, 'ArticleTitle') or _text(article, 'BookTitle')
    if not title:
        return None
    authors, affiliations = _authors(article)
    journal = _text(article, 'Title') or _text(article, 'ISOAbbreviation') or _text(article, 'BookTitle')
    pub_date = _first(article, 'PubDate')
    year = _text(pub_date, 'Year') if pub_date is not None else ''
    if not year and pub_date is not None:
        year = _text(pub_date, 'MedlineDate')
    if not year:
        year = _text(article, 'Year')
    refs, structured = _references(element, citation)
    grants = []
    for grant in _descendants(element, 'Grant'):
        agency = _text(grant, 'Agency')
        grant_id = _text(grant, 'GrantID')
        grants.append(' '.join(part for part in (agency, grant_id) if part))
    return make_row(
        title=title,
        authors=authors,
        affiliations=affiliations,
        journal=journal,
        year=year_of(year),
        volume=_text(article, 'Volume'),
        issue=_text(article, 'Issue'),
        page_start=_text(article, 'MedlinePgn') or _text(article, 'StartPage'),
        page_end=_text(article, 'EndPage'),
        keywords=';'.join(_all_text(element, 'Keyword')),
        abstract=_abstract(article),
        refs=refs,
        structured_refs=structured,
        doi=_doi(element),
        fmt=ID,
        country=countries(affiliations),
        funding=';'.join(item for item in grants if item),
        doctype=';'.join(_all_text(element, 'PublicationType')),
        language=_text(element, 'Language'),
    )


_MEDLINE_TAG = re.compile(r'^([A-Z]{2,4})\s*-\s?(.*)$')


def _medline_records(text: str) -> list[dict[str, list[str]]]:
    records: list[dict[str, list[str]]] = []
    fields: dict[str, list[str]] = {}
    current: str | None = None

    def flush():
        nonlocal fields, current
        if fields:
            records.append(fields)
        fields = {}
        current = None

    for raw in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        if not raw.strip():
            if fields:
                flush()
            continue
        match = _MEDLINE_TAG.match(raw)
        if match:
            tag, value = match.group(1), match.group(2).strip()
            fields.setdefault(tag, []).append(value)
            current = tag
            continue
        if current:
            fields[current][-1] = f'{fields[current][-1]} {raw.strip()}'.strip()
    if fields:
        flush()
    return records


def _first_field(fields: dict[str, list[str]], *tags: str) -> str:
    for tag in tags:
        for value in fields.get(tag) or []:
            if str(value).strip():
                return str(value).strip()
    return ''


def _all_fields(fields: dict[str, list[str]], *tags: str) -> str:
    values: list[str] = []
    for tag in tags:
        values += [str(value).strip() for value in fields.get(tag) or [] if str(value).strip()]
    return ';'.join(values)


def parse_medline(text: str) -> tuple[list[dict], int]:
    rows: list[dict] = []
    skipped = 0
    for fields in _medline_records(text):
        title = _first_field(fields, 'TI')
        if not title:
            skipped += 1
            continue
        doi = ''
        for value in fields.get('LID') or fields.get('AID') or []:
            if '[doi]' in str(value).lower():
                doi = re.sub(r'\s*\[doi\]\s*$', '', str(value), flags=re.IGNORECASE).strip()
                break
        affiliations = ';'.join(fields.get('AD') or [])
        rows.append(
            make_row(
                title=title,
                authors=_all_fields(fields, 'FAU', 'AU'),
                affiliations=affiliations,
                journal=_first_field(fields, 'JT', 'TA'),
                year=year_of(_first_field(fields, 'DP', 'DEP')),
                volume=_first_field(fields, 'VI'),
                issue=_first_field(fields, 'IP'),
                page_start=_first_field(fields, 'PG'),
                keywords=_all_fields(fields, 'OT', 'MH'),
                abstract=' '.join(fields.get('AB') or []),
                doi=doi,
                fmt=ID,
                country=countries(affiliations),
                funding=_all_fields(fields, 'GR'),
                doctype=_all_fields(fields, 'PT'),
                language=_first_field(fields, 'LA'),
            )
        )
    return rows, skipped


def parse(text: str) -> tuple[list[dict], int]:
    if not str(text or '').lstrip().startswith('<'):
        return parse_medline(text)
    if _ENTITY.search(str(text or '')):
        raise ValueError(t('api.biblioXmlUnsafe'))
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(t('api.biblioXmlBad', err=exc)) from exc
    rows: list[dict] = []
    skipped = 0
    records = _descendants(root, 'PubmedArticle') + _descendants(root, 'PubmedBookArticle')
    if not records:
        records = [root]
    for record in records:
        if _local(record.tag) == 'PubmedArticleSet':
            continue
        row = _row(record)
        if row is None:
            skipped += 1
            continue
        rows.append(row)
    return rows, skipped


SPEC = FormatSpec(
    id=ID,
    label=LABEL,
    extensions=('.xml', '.nbib', '.txt'),
    capabilities=frozenset(
        (
            'refs',
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
)
