"""Parsing and normalization of cited references.

Importers use this module to turn a format's raw reference text into the
structured ``引文`` column, and the bibliometric builder uses the same parser
when a table only carries raw ``参考文献``. Keeping one parser means a
co-citation graph cannot read a reference differently from the importer that
stored it.

The parser is deliberately conservative: a cited work needs either a title or
a journal to become a node. The caller measures the parse rate and refuses a
graph built mostly from fragments.
"""

import json
import re

_YEAR = re.compile(r'(?:19|20)\d{2}')
_REF_TYPE = re.compile(r'\[(?:J|M|D|C|N|R|S|G|P|A|EB/OL|J/OL|DB/OL|M/OL|C/OL)\]')
_LIST_SPLIT = re.compile(r'[;；,，、]+')
#: WoS plain-text references are ``AUTHOR V, 2019, JOURNAL, V1, P1``: no title
#: and no bracket type. The author block is uppercase ASCII, then the year.
_WOS_REF = re.compile(r'^(?P<authors>[A-Z][A-Z0-9 .,\'\-&]+?),\s*(?P<year>(?:19|20)\d{2})\s*,\s*(?P<rest>.+)$')


def _split(value) -> list[str]:
    seen: list[str] = []
    for part in _LIST_SPLIT.split(str(value or '')):
        item = part.strip().strip('.')
        if item and item not in seen:
            seen.append(item)
    return seen


def _year(value) -> int | None:
    match = _YEAR.search(str(value or ''))
    return int(match.group(0)) if match else None


def parse_reference(raw: str) -> dict | None:
    """One cited reference, from a Chinese, English, or WoS-style string."""
    text = re.sub(r'^\s*\[\d+\]\s*', '', str(raw or '')).strip()
    if not text:
        return None
    marker = _REF_TYPE.search(text)
    authors: list[str] = []
    title = ''
    journal = ''
    year = _year(text)
    if marker:
        head = text[: marker.start()].strip().rstrip('.．')
        parts = re.split(r'[.．]', head, maxsplit=1)
        authors = _split(parts[0]) if parts else []
        title = (parts[1] if len(parts) > 1 else '').strip().rstrip('.．')
        tail = text[marker.end() :].lstrip('.． ')
        if marker.group(0).startswith('[J'):
            found = re.match(r'([^,，.]+)', tail)
            if found:
                journal = found.group(1).strip()
    else:
        wos = _WOS_REF.match(text)
        if wos:
            authors = _split(wos.group('authors'))
            rest = [part.strip() for part in re.split(r'[,，]', wos.group('rest')) if part.strip()]
            journal = rest[0] if rest else ''
            # A WoS reference has no title field. Using the raw string as the
            # title keeps one cited work addressable without inventing words.
            title = text
        else:
            parts = re.split(r'[.．]\s*', text)
            if len(parts) >= 3:
                # English/PubMed style: Authors. Title. Journal. Year;vol(issue):pages.
                authors = _split(parts[0])
                title = parts[1].strip()
                journal = parts[2].strip()
            else:
                authors = _split(parts[0]) if parts else []
                title = (parts[1] if len(parts) > 1 else text).strip().rstrip('.．')
    if not title and not journal:
        return None
    title = re.sub(r'\s+', ' ', title).strip()
    return {
        'raw': text,
        'title': title,
        'authors': authors,
        'journal': journal,
        'year': year,
        'doi': '',
        'type': '',
    }


def normalize_reference(item: dict) -> dict | None:
    """A structured reference from an importer, with every field present."""
    if not isinstance(item, dict):
        return parse_reference(str(item or ''))
    title = re.sub(r'\s+', ' ', str(item.get('title') or '')).strip()
    journal = str(item.get('journal') or '').strip()
    raw = str(item.get('raw') or '').strip()
    if not title and not journal and raw:
        parsed = parse_reference(raw)
        if parsed is None:
            return None
        parsed.update(
            {
                key: item.get(key) if item.get(key) not in (None, '') else parsed.get(key, '')
                for key in ('title', 'journal', 'authors', 'year', 'doi', 'type')
            }
        )
        return parsed
    authors = item.get('authors') or []
    if isinstance(authors, str):
        authors = _split(authors)
    return {
        'raw': raw or title,
        'title': title or raw,
        'authors': [str(author).strip() for author in authors if str(author).strip()],
        'journal': journal,
        'year': _year(item.get('year')),
        'doi': str(item.get('doi') or '').strip(),
        'type': str(item.get('type') or '').strip(),
    }


def structured_references(raw_refs) -> list[dict]:
    """Parse a list of raw references, keeping only usable cited works."""
    parsed: list[dict] = []
    for raw in raw_refs or []:
        item = parse_reference(str(raw or ''))
        if item is not None:
            parsed.append(item)
    return parsed


def references_json(items: list[dict]) -> str:
    """Canonical JSON text stored in the ``引文`` column."""
    cleaned = [item for item in (normalize_reference(value) for value in items or []) if item]
    return json.dumps(cleaned, ensure_ascii=False, sort_keys=True, separators=(',', ':')) if cleaned else ''


def references_from_json(value) -> list[dict]:
    """Read a ``引文`` cell; an empty or malformed value yields an empty list."""
    if isinstance(value, list):
        source = value
    else:
        text = str(value or '').strip()
        if not text:
            return []
        try:
            source = json.loads(text)
        except (TypeError, ValueError):
            return []
    if not isinstance(source, list):
        return []
    return [item for item in (normalize_reference(value) for value in source) if item]
