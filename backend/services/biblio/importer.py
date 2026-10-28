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
from services.biblio.refs import references_json, structured_references

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

#: Columns emitted only when the export really carried the field. Order is the
#: contract the upload response and the biblio builder read; a format that
#: cannot carry one simply never grows the column.
OPTIONAL_COLUMNS = (
    '国家',
    '学科',
    '引用次数',
    '使用次数',
    '使用次数2013',
    '基金',
    '文献类型',
    '语言',
    '引文',
)

_CNKI_TAG = re.compile(r'^([A-Z][A-Z0-9])(?:\s+(.*))?$')
_CSSCI_TAG = re.compile(r'^【([^】]{1,20})】\s*(.*)$')
_CSSCI_TITLE_TAG = re.compile(r'(?m)^\s*【(?:来源篇名|篇名|题名)】')
_YEAR = re.compile(r'(?:19|20)\d{2}')
_REF_START = re.compile(r'^\s*(?:\[\d+\]|\d+[\.、\]])')
_LIST_SPLIT = re.compile(r'[;；,，、]+')
_AFF_SPLIT = re.compile(r'[;；]+')
#: CSSCI separates authors, keywords and institutions with `/`, not `;`
#: (`曾美红/李霞/何玉雪`, `关系自我扩展/恋爱关系稳定性`). Read with the CNKI separator
#: the whole author list becomes one node and one keyword becomes one term, so the
#: network would be wrong without ever raising an error.
_CSSCI_SPLIT = re.compile(r'[/;｜|，,、]+')
#: 【机构名称】prefixes every affiliation with its author: `[张静]黄淮学院.应用技术大学研究中心`.
_CSSCI_AUTHOR_TAG = re.compile(r'\[[^\]]*\]')
#: CSSCI pads its tag names to line the values up in a column, so the real file
#: writes 关 键 词 / 期    刊 / 基    金 (U+3000 or ASCII spaces). Measured on the
#: centre's own download: 13 tags, none of them spelled the way a human types them.
_TAG_SPACE = re.compile(r'[ \t　]+')
#: 【年代卷期】2021,(2):146-155 carries year, issue and pages in one field.
#: All 18 forms in the real download: `2000,(5):22-25`, `2007,23(4):74-77`,
#: `2013,21(3):508-511,378` (volume optional, pages may be a comma list), plus
#: full-width brackets and a missing page range in `2003,(6):67`.
_CSSCI_ISSUE = re.compile(
    r'(?P<year>(?:19|20)\d{2})'
    r'\s*[,,]?\s*(?:(?P<volume>\d{1,4})\s*[,,]?)?'
    r'[（(]\s*(?P<issue>[^）)】]{1,12}?)\s*[）)]'
    r'(?:\s*[:：]\s*(?P<pages>[\dA-Za-z,，\-—–\./\s]+))?'
)

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
    if _CSSCI_TITLE_TAG.search(text) and _cssci_tags(text) & _CSSCI_RECORD_TAGS:
        return CSSCI
    if re.search(r'(?m)^RT\s+(?:Journal Article|Book|Conference|Dissertation|Report|Other)\b', text):
        # The RT marker alone is enough to take the record path: an export that
        # happens to contain no T1/A1/YR is still a (broken) export, not a
        # plain-text cell. The parser then refuses it by name when it yields
        # zero records, instead of silently storing the whole file as content.
        return CNKI
    from services.biblio import formats

    return formats.detect_format(text)


def _normalize_tag(name: str) -> str:
    """Fold the padding CSSCI puts inside its tag names (``关 键 词`` -> ``关键词``)."""
    return _TAG_SPACE.sub('', str(name or '')).strip()


#: The tags that prove this is a CSSCI record table rather than a sentence that
#: happens to contain 【. Measured from the centre's own download, which writes
#: 年代卷期 / 来源作者 / 关 键 词 and never the 【年份】【作者】【关键词】 the
#: synthetic fixture used — a gate on those three names silently refused every real file.
_CSSCI_RECORD_TAGS = frozenset({'年代卷期', '来源作者', '第一作者', '期刊', '关键词', '机构名称', '年份', '作者'})


def _cssci_tags(text: str) -> frozenset[str]:
    """Every bracket tag in the file, spacing folded. Line by line, because
    ``_CSSCI_TAG`` is anchored and is applied to a single line everywhere else."""
    return frozenset(
        _normalize_tag(match.group(1)) for line in _lines(text) if (match := _CSSCI_TAG.match(line.strip()))
    )


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


def _join_authors(value: str) -> str:
    """Authors are separated by semicolons, never by a comma inside a name."""
    seen: list[str] = []
    for part in re.split(r'[;；\n]+', str(value or '')):
        item = part.strip()
        if item and item not in seen:
            seen.append(item)
    return ';'.join(seen)


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
    tc='',
    usage='',
    usage2013='',
    funding: str = '',
    doctype: str = '',
    language: str = '',
    citations: list[dict] | None = None,
) -> dict:
    structured = citations if citations is not None else structured_references(refs)
    return {
        '记录ID': _record_id(title, authors, year, journal),
        '题名': title.strip(),
        '作者': _join_authors(authors),
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
        '引用次数': tc,
        '使用次数': usage,
        '使用次数2013': usage2013,
        '基金': _join_list(funding),
        '文献类型': str(doctype or '').strip(),
        '语言': str(language or '').strip(),
        '引文': references_json(structured),
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
        authors = ';'.join(str(value).strip() for value in fields.get('A1') or [] if str(value).strip())
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
                doctype=_first(fields, 'RT'),
                language=_first(fields, 'LA'),
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
            tag, value = _normalize_tag(match.group(1)), match.group(2).strip()
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


def _cssci_bibliographic(fields: dict) -> tuple[str, str, str, str]:
    """Split year / volume / issue / pages out of 【年代卷期】.

    The centre writes ``2021,(2):146-155`` — one field for what CNKI splits across
    年/卷/期/页码. Returning blanks (rather than putting the raw string into 年份)
    keeps 年份 a number the slicer can group on, and a value it cannot read stays
    empty so the import warning names it.
    """
    raw = _first(fields, '年代卷期', '年卷期', '卷期页')
    match = _CSSCI_ISSUE.search(raw)
    if not match:
        return _year(raw), '', '', ''
    pages = (match.group('pages') or '').strip('.,，。')
    year = _year(match.group('year'))
    volume = (match.group('volume') or '').strip()
    issue = (match.group('issue') or '').strip()
    return year, volume, issue, pages


def _cssci_value(fields: dict, *tags) -> str:
    return _first(fields, *tags)


def parse_cssci(text: str) -> tuple[list[dict], int]:
    """Read the CSSCI centre's bracket-tag download.

    Tag names below are the ones the real file carries (see ``samples/CSSCI.txt``):
    来源作者 for the author list, 机构名称 for affiliations, 年代卷期 for the issue
    block and 关 键 词 padded inside the brackets. The old names (作者/年份/关键词) stay
    as candidates so a re-saved or older dialect still reads.
    """
    rows = []
    skipped = 0
    for chunk in _cssci_chunks(text):
        fields = _cssci_fields(chunk)
        title = _cssci_value(fields, '来源篇名', '篇名', '题名')
        if not fields:
            # The copyright banner above the first record is not a dropped record.
            continue
        if not title:
            skipped += 1
            continue
        refs = _refs_from_lines(fields.get('参考文献') or [])
        year, volume, issue, pages = _cssci_bibliographic(fields)
        authors = _join_list(_cssci_value(fields, '来源作者', '第一作者', '作者'), _CSSCI_SPLIT)
        affiliations = _join_list(
            _CSSCI_AUTHOR_TAG.sub('', _cssci_value(fields, '机构名称', '第一机构', '作者单位', '机构')),
            _CSSCI_SPLIT,
        )
        keywords = _join_list(_cssci_value(fields, '关键词'), _CSSCI_SPLIT)
        rows.append(
            _row(
                title=title,
                authors=authors,
                affiliations=affiliations,
                journal=_cssci_value(fields, '期刊', '刊名', '来源期刊'),
                year=year or _year(_cssci_value(fields, '年份')),
                volume=volume or _cssci_value(fields, '卷号', '卷'),
                issue=issue or _cssci_value(fields, '期号', '期'),
                pages=pages or _cssci_value(fields, '页码'),
                keywords=keywords,
                abstract=_cssci_value(fields, '摘要'),
                refs=refs,
                doi=_cssci_value(fields, 'DOI'),
                fmt=CSSCI,
                country=_cssci_value(fields, '国家', '国别'),
                # 中图类号 is a Chinese Library Classification code (B844.2), which is a
                # subject taxonomy — but it is a code, not a discipline name, and the
                # 学科 network reads whatever the file really offered.
                category=_cssci_value(fields, '学科', '学科分类', '中图类号'),
                tc=_cssci_value(fields, '引用次数', '被引次数'),
                funding=_join_list(_cssci_value(fields, '基金', '基金类别', '基金项目'), _CSSCI_SPLIT),
                doctype=_cssci_value(fields, '文献类型', '文章类型'),
                language=_cssci_value(fields, '语言'),
            )
        )
    return rows, skipped


# ─── Public entry ───────────────────────────────────────────────


def _observed_capabilities(rows: list[dict]) -> dict[str, bool]:
    """What this particular file really carried, not what its format could carry."""
    return {
        'refs': any(str(row.get('参考文献') or '').strip() or str(row.get('引文') or '').strip() for row in rows),
        'tc': any(str(row.get('引用次数') or '').strip() for row in rows),
        'usage': any(
            str(row.get('使用次数') or '').strip() or str(row.get('使用次数2013') or '').strip() for row in rows
        ),
        'categories': any(str(row.get('学科') or '').strip() for row in rows),
        'grants': any(str(row.get('基金') or '').strip() for row in rows),
        'abstract': any(str(row.get('摘要') or '').strip() for row in rows),
        'keywords': any(str(row.get('关键词') or '').strip() for row in rows),
        'country': any(str(row.get('国家') or '').strip() for row in rows),
        'doi': any(str(row.get('DOI') or '').strip() for row in rows),
        'doctype': any(str(row.get('文献类型') or '').strip() for row in rows),
        'language': any(str(row.get('语言') or '').strip() for row in rows),
        'funding': any(str(row.get('基金') or '').strip() for row in rows),
    }


def _finalize(rows: list[dict], fmt: str, skipped: int = 0) -> dict:
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
    for optional in OPTIONAL_COLUMNS:
        if any(str(row.get(optional) or '').strip() for row in unique):
            columns.append(optional)
    for row in unique:
        for optional in OPTIONAL_COLUMNS:
            if optional not in columns:
                row.pop(optional, None)
    observed = _observed_capabilities(unique)
    return {
        'format': fmt,
        'rows': [{column: row.get(column, '') for column in columns} for row in unique],
        'columns': columns,
        'warnings': warnings,
        'capabilities': observed,
    }


def parse_text(text: str, fmt: str | None = None) -> dict | None:
    """Parse a decoded export; ``None`` means "not a bibliographic file".

    A file that no format recognises is not automatically an ordinary table: a vendor
    export can share column names with a format we read (Lens' patent download has a
    ``Title`` and a ``Lens ID``). Those are refused by name, because storing them as a
    plain table is how a wrong graph gets drawn without a single error message.
    """
    fmt = fmt or detect_format(text)
    if fmt is None:
        from services.biblio import formats

        refusal = formats.detect_refusal(text)
        if refusal:
            raise ValueError(refusal)
        return None
    if fmt == CNKI:
        rows, skipped = parse_cnki(text)
    elif fmt == CSSCI:
        rows, skipped = parse_cssci(text)
    else:
        from services.biblio import formats

        rows, skipped = formats.parse_format(text, fmt)
    return _finalize(rows, fmt, skipped)


def parse_frame(frame, fmt: str | None = None) -> dict | None:
    """Parse a spreadsheet/CSV frame when its columns name a known export."""
    from services.biblio import formats

    fmt = fmt or formats.detect_frame(frame)
    if fmt is None:
        return None
    rows, skipped = formats.parse_frame(frame, fmt)
    return _finalize(rows, fmt, skipped)


def parse_bytes(raw: bytes, name: str = '', fmt: str | None = None) -> dict | None:
    text = decode_text(raw, name)
    return parse_text(text, fmt)
