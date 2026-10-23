"""CNKI RefWorks and CSSCI record importers.

CiteSpace's CNKI path is "export RefWorks, then import the download*.txt
file", and CSSCI exports a bracket-tag text file. Both formats are line
oriented, so this module keeps the parser deliberately literal: a tag line
starts a field, an indented/untagged line continues it, and a blank line or
``ER`` ends a record. Anything that does not look like either format is
returned as ``None`` so the Upload route keeps its old one-column text
behaviour.

The normalized table is the contract every bibliometric node reads:
``记录ID, 题名, 作者, 作者单位, 来源期刊, 年份, 卷, 期, 页码, 关键词, 摘要,
参考文献, DOI, 格式`` plus ``国家``/``学科`` only when the export really
carried them. ``记录ID`` is a content hash (title + first author + year +
journal), so a re-import and a resume address the same record.
"""

import hashlib
import re

from i18n import t

BASE_COLUMNS = [
    '记录ID',
    '题名',
    '作者',
    '作者单位',
    '来源期刊',
    '年份',
    '卷',
    '期',
    '页码',
    '关键词',
    '摘要',
    '参考文献',
    'DOI',
    '格式',
]

_CNKI_TAG = re.compile(r'^([A-Z][A-Z0-9])(?:\s+(.*))?$')
_CSSCI_TAG = re.compile(r'^【([^】]{1,20})】\s*(.*)$')
_CSSCI_TITLE_TAG = re.compile(r'(?m)^\s*【(?:来源篇名|篇名|题名)】')
_YEAR = re.compile(r'(?:19|20)\d{2}')
_REF_START = re.compile(r'^\s*\[\d+\]')
_LIST_SPLIT = re.compile(r'[;；,，、]+')
_AFF_SPLIT = re.compile(r'[;；]+')

CNKI = 'CNKI'
CSSCI = 'CSSCI'


class BiblioDecodeError(ValueError):
    """The bytes are neither UTF-8 nor GB18030; the Upload route keeps them as text."""


# ─── Encoding and detection ─────────────────────────────────────


def decode_text(raw: bytes, name: str = '') -> str:
    """Decode a Chinese export without guessing its encoding silently.

    CNKI writes UTF-8, but a CSSCI download or a re-saved file is routinely
    GB18030. Both are tried by name; a file neither can decode is a 400, not
    a table of replacement characters.
    """
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise BiblioDecodeError(t('api.biblioDecode', name=name or 'txt'))


def detect_format(text: str) -> str | None:
    """Which bibliographic export this is, or None for ordinary text.

    Detection is deliberately conservative. A plain sentence containing
    ``【`` or the word ``RT`` must keep the old single-column upload path;
    only the tag grammar that a real export uses switches to a record table.
    """
    if _CSSCI_TITLE_TAG.search(text) and re.search(r'【年份】|【作者】|【关键词】', text):
        return CSSCI
    if re.search(r'(?m)^RT\s+(?:Journal Article|Book|Conference|Dissertation|Report|Other)\b', text):
        # The RT marker alone is enough to take the record path: an export that
        # happens to contain no T1/A1/YR is still a (broken) export, not a
        # plain-text cell. The parser then refuses it by name when it yields
        # zero records, instead of silently storing the whole file as content.
        return CNKI
    return None


# ─── Shared record helpers ──────────────────────────────────────


def _lines(text: str) -> list[str]:
    return text.replace('\r\n', '\n').replace('\r', '\n').split('\n')


def _split_list(value: str, pattern=_LIST_SPLIT) -> list[str]:
    seen: list[str] = []
    for part in pattern.split(value or ''):
        item = part.strip().strip('.')
        if item and item not in seen:
            seen.append(item)
    return seen


def _join_list(value: str, pattern=_LIST_SPLIT) -> str:
    return ';'.join(_split_list(value, pattern))


def _first(fields: dict, *tags) -> str:
    for tag in tags:
        values = fields.get(tag) or []
        for value in values:
            text = str(value or '').strip()
            if text:
                return text
    return ''


def _all(fields: dict, *tags) -> str:
    values = []
    for tag in tags:
        values += [str(value or '') for value in fields.get(tag) or []]
    return ' '.join(values).strip()


def _year(value: str) -> int | str:
    match = _YEAR.search(str(value or ''))
    return int(match.group(0)) if match else ''


def _record_id(title: str, authors: str, year, journal: str) -> str:
    first_author = (authors.split(';')[0] if authors else '').strip()
    raw = f'{title.strip()}|{first_author}|{year}|{journal.strip()}'.encode()
    return hashlib.sha1(raw).hexdigest()[:16]


def _refs_from_lines(lines: list[str]) -> list[str]:
    """One raw reference per entry, joining wrapped continuation lines.

    A reference often wraps after its journal name. Joining until the next
    ``[n]`` marker keeps one cited work as one node; splitting every physical
    line would invent a citation for each fragment.
    """
    refs: list[str] = []
    for raw in lines:
        line = str(raw or '').strip()
        if not line:
            continue
        if _REF_START.match(line) or not refs:
            refs.append(line)
        else:
            refs[-1] = f'{refs[-1]} {line}'.strip()
    return refs


def _refs_text(refs: list[str]) -> str:
    return '\n'.join(refs)


def _row(
    *,
    title: str,
    authors: str,
    affiliations: str,
    journal: str,
    year,
    volume: str,
    issue: str,
    pages: str,
    keywords: str,
    abstract: str,
    refs: list[str],
    doi: str,
    fmt: str,
    country: str = '',
    category: str = '',
) -> dict:
    return {
        '记录ID': _record_id(title, authors, year, journal),
        '题名': title.strip(),
        '作者': _join_list(authors),
        '作者单位': _join_list(affiliations, _AFF_SPLIT),
        '来源期刊': journal.strip(),
        '年份': year,
        '卷': volume.strip(),
        '期': issue.strip(),
        '页码': pages.strip(),
        '关键词': _join_list(keywords),
        '摘要': abstract.strip(),
        '参考文献': _refs_text(refs),
        'DOI': doi.strip(),
        '格式': fmt,
        '国家': _join_list(country),
        '学科': _join_list(category),
    }


# ─── CNKI RefWorks ──────────────────────────────────────────────


def _cnki_blocks(text: str) -> list[dict]:
    blocks: list[dict] = []
    fields: dict[str, list[str]] = {}
    current: str | None = None

    def flush():
        nonlocal fields, current
        if fields:
            blocks.append(fields)
        fields = {}
        current = None

    for raw in _lines(text):
        line = raw.rstrip()
        match = _CNKI_TAG.match(line)
        if match:
            tag, value = match.group(1), (match.group(2) or '').strip()
            if tag == 'ER':
                flush()
                continue
            if tag == 'RT' and fields.get('RT'):
                # A second record without an ER line: the RT tag is the boundary.
                flush()
            fields.setdefault(tag, []).append(value)
            current = tag
            continue
        if not line.strip():
            # RefWorks separates records with a blank line. A blank inside an
            # abstract is rare; ER is the definitive end marker when present.
            if fields.get('RT') or fields.get('T1'):
                flush()
            continue
        if current:
            value = line.strip()
            if value:
                previous = fields[current][-1]
                fields[current][-1] = f'{previous} {value}'.strip()
    if fields:
        blocks.append(fields)
    return blocks


def parse_cnki(text: str) -> tuple[list[dict], int]:
    rows = []
    skipped = 0
    for fields in _cnki_blocks(text):
        title = _all(fields, 'T1')
        authors = _all(fields, 'A1')
        affiliations = _all(fields, 'AD')
        journal = _first(fields, 'JF', 'JO', 'T2')
        if not title:
            # A record with no title cannot be a node in any of the graphs this
            # table feeds; keeping it would only put an empty label on the canvas.
            skipped += 1
            continue
        refs = _refs_from_lines([line for value in fields.get('CR') or [] for line in str(value).split('\n')])
        rows.append(
            _row(
                title=title,
                authors=authors,
                affiliations=affiliations,
                journal=journal,
                year=_year(_first(fields, 'YR', 'PY')),
                volume=_first(fields, 'VO'),
                issue=_first(fields, 'IS'),
                pages=_first(fields, 'OP', 'SP'),
                keywords=_all(fields, 'K1'),
                abstract=_all(fields, 'AB'),
                refs=refs,
                doi=_first(fields, 'DO'),
                fmt=CNKI,
            )
        )
    return rows, skipped


# ─── CSSCI bracket format ───────────────────────────────────────


def _cssci_chunks(text: str) -> list[str]:
    starts = [match.start() for match in _CSSCI_TITLE_TAG.finditer(text)]
    if len(starts) >= 2:
        chunks = [text[start:end] for start, end in zip(starts, starts[1:] + [len(text)], strict=True)]
        prefix = text[: starts[0]]
        if prefix.strip():
            # A header/preamble with tags but no title is still a record the
            # importer dropped; counting it lets the warning say so instead of
            # letting it vanish between chunks.
            chunks.insert(0, prefix)
        return chunks
    return [text]


def _cssci_fields(chunk: str) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    current: str | None = None
    for raw in _lines(chunk):
        line = raw.strip()
        match = _CSSCI_TAG.match(line)
        if match:
            tag, value = match.group(1).strip(), match.group(2).strip()
            fields.setdefault(tag, []).append(value)
            current = tag
            continue
        if current and line:
            if current == '参考文献':
                # Every physical line is a candidate reference; _refs_from_lines
                # joins wrapped ones at the next [n] marker.
                fields[current].append(line)
            else:
                previous = fields[current][-1]
                fields[current][-1] = f'{previous} {line}'.strip()
    return fields


def _cssci_value(fields: dict, *tags) -> str:
    return _first(fields, *tags)


def parse_cssci(text: str) -> tuple[list[dict], int]:
    rows = []
    skipped = 0
    for chunk in _cssci_chunks(text):
        fields = _cssci_fields(chunk)
        title = _cssci_value(fields, '来源篇名', '篇名', '题名')
        authors = _cssci_value(fields, '作者')
        if not title:
            skipped += 1
            continue
        refs = _refs_from_lines(fields.get('参考文献') or [])
        rows.append(
            _row(
                title=title,
                authors=authors,
                affiliations=_cssci_value(fields, '作者单位', '机构'),
                journal=_cssci_value(fields, '刊名', '来源期刊', '期刊'),
                year=_year(_cssci_value(fields, '年份')),
                volume=_cssci_value(fields, '卷号', '卷'),
                issue=_cssci_value(fields, '期号', '期'),
                pages=_cssci_value(fields, '页码'),
                keywords=_cssci_value(fields, '关键词'),
                abstract=_cssci_value(fields, '摘要'),
                refs=refs,
                doi=_cssci_value(fields, 'DOI'),
                fmt=CSSCI,
                country=_cssci_value(fields, '国家', '国别'),
                category=_cssci_value(fields, '学科', '学科分类'),
            )
        )
    return rows, skipped


# ─── Public entry ───────────────────────────────────────────────


def parse_text(text: str, fmt: str | None = None) -> dict | None:
    """Parse a decoded export; ``None`` means "not a bibliographic file"."""
    fmt = fmt or detect_format(text)
    if fmt is None:
        return None
    rows, skipped = parse_cnki(text) if fmt == CNKI else parse_cssci(text)
    if not rows:
        raise ValueError(t('api.biblioEmpty', format=fmt))

    warnings: list[str] = []
    unique: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        key = row['记录ID']
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    if len(unique) != len(rows):
        warnings.append(t('biblio.import_duplicates', n=len(rows) - len(unique)))
    no_year = sum(1 for row in unique if row['年份'] == '')
    if no_year:
        warnings.append(t('biblio.import_no_year', n=no_year))
    if skipped:
        warnings.append(t('biblio.import_skipped', n=skipped))

    columns = list(BASE_COLUMNS)
    for optional in ('国家', '学科'):
        if any(row.get(optional) for row in unique):
            columns.append(optional)
    for row in unique:
        for optional in ('国家', '学科'):
            if optional not in columns:
                row.pop(optional, None)
    return {
        'format': fmt,
        'rows': [{column: row.get(column, '') for column in columns} for row in unique],
        'columns': columns,
        'warnings': warnings,
    }


def parse_bytes(raw: bytes, name: str = '', fmt: str | None = None) -> dict | None:
    text = decode_text(raw, name)
    return parse_text(text, fmt)
