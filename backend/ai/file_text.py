"""Attachment text extraction for providers that cannot parse files themselves.

The workspace used to require DeepSeek for every attachment: the browser refused a file when the
provider had no ``files`` capability, and the server refused it again. That made the local model,
OpenRouter and the Go gateway unable to read a PDF the user had already uploaded — even though
reading the file is OUR job, not the provider's.

This module turns the bytes into text ONCE, caches it beside the account's local copy, and lets the
agent put that text in the turn's context. It is deliberately independent of `vision`: an image is
an image (a vision model reads it, or the turn is refused by name), a document is words (any model
can read them). The one limit is the account setting ``ai_attachment_text_chars`` (0 = no cap); a
cut is reported, never silent.
"""

from __future__ import annotations

import io
import json
import os
import re
import zipfile
from html.parser import HTMLParser
from xml.etree import ElementTree

from runtime.settings import get_setting

from ai.errors import AIError

#: Files whose bytes are already text (or markup we can strip).
TEXT_SUFFIXES = frozenset(
    {
        '.txt',
        '.md',
        '.markdown',
        '.csv',
        '.tsv',
        '.json',
        '.jsonl',
        '.log',
        '.py',
        '.js',
        '.ts',
        '.css',
        '.xml',
        '.yaml',
        '.yml',
        '.ini',
        '.toml',
        '.sql',
    }
)
HTML_SUFFIXES = frozenset({'.html', '.htm', '.xhtml'})
SHEET_SUFFIXES = frozenset({'.xlsx', '.xlsm', '.xls'})
LEGACY_BINARY_SUFFIXES = frozenset({'.doc', '.ppt'})
#: A table larger than this is not parsed into one prompt block: it is a dataset the assistant
#: reads through the dataset tools. The upload route registers big tables first, so reaching this
#: is the "unreadable file" path, not the normal one.
TABLE_PARSE_MAX_BYTES = 32 * 1024 * 1024

_W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
_A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
_SLIDE = re.compile(r'ppt/slides/slide\d+\.xml$')


# ─── Decode / strip ───


def _decode(data: bytes) -> str:
    """UTF-8 first, then the Chinese desktop encodings, then a lossy UTF-8 read.

    A CSV exported by Excel on a Chinese Windows box is GBK far more often than UTF-8; decoding it
    as UTF-8 with ``errors='replace'`` turns every Chinese cell into U+FFFD, and the model then
    answers about rows that contain no words.
    """
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        return data.decode('utf-16', errors='replace')
    for encoding in ('utf-8-sig', 'gb18030', 'big5'):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode('utf-8', errors='replace')


class _HtmlText(HTMLParser):
    """Visible text only: scripts, styles and comments are not part of the document."""

    _BLOCKS = frozenset(
        {
            'p',
            'div',
            'br',
            'li',
            'tr',
            'h1',
            'h2',
            'h3',
            'h4',
            'h5',
            'h6',
            'section',
            'article',
            'header',
            'footer',
            'table',
            'blockquote',
            'pre',
        }
    )

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self._skip += 1
        elif tag in self._BLOCKS:
            self.parts.append('\n')
        elif tag in ('td', 'th'):
            self.parts.append('\t')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self._skip = max(0, self._skip - 1)
        elif tag in self._BLOCKS:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def _html_text(data: bytes) -> str:
    parser = _HtmlText()
    parser.feed(_decode(data))
    parser.close()
    text = ''.join(parser.parts)
    return re.sub(r'\n{3,}', '\n\n', text)


# ─── Office formats (stdlib zip + XML for docx/pptx; pandas for sheets) ───


def _docx_text(data: bytes) -> str:
    """.docx is a zip of WordprocessingML; paragraphs and table cells are enough for a prompt."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        root = ElementTree.fromstring(archive.read('word/document.xml'))
    lines = []
    for paragraph in root.iter(_W + 'p'):
        text = ''.join(node.text or '' for node in paragraph.iter(_W + 't'))
        lines.append(text)
    return '\n'.join(lines)


def _pptx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        slides = sorted(name for name in archive.namelist() if _SLIDE.search(name))
        chunks = []
        for index, name in enumerate(slides, start=1):
            root = ElementTree.fromstring(archive.read(name))
            lines = [''.join(node.text or '' for node in paragraph.iter(_A + 't')) for paragraph in root.iter(_A + 'p')]
            chunks.append(f'[slide {index}]\n' + '\n'.join(line for line in lines if line.strip()))
    return '\n\n'.join(chunks)


def _sheet_text(name: str, data: bytes) -> str:
    import pandas as pd

    lowered = str(name or '').lower()
    buffer = io.BytesIO(data)
    if lowered.endswith(('.csv', '.tsv')):
        last_error: Exception | None = None
        for encoding in ('utf-8-sig', 'gb18030'):
            try:
                buffer.seek(0)
                frame = pd.read_csv(
                    buffer,
                    sep='\t' if lowered.endswith('.tsv') else ',',
                    dtype=str,
                    keep_default_na=False,
                    encoding=encoding,
                )
                return _frame_text({name: frame})
            except (UnicodeDecodeError, pd.errors.ParserError) as exc:
                last_error = exc
                continue
        if last_error is not None:
            raise last_error
        return ''
    sheets = pd.read_excel(buffer, sheet_name=None, dtype=str, keep_default_na=False)
    return _frame_text(sheets)


def _frame_text(sheets: dict) -> str:
    chunks = []
    for title, frame in (sheets or {}).items():
        lines = ['\t'.join(str(column) for column in frame.columns)]
        lines.extend('\t'.join(str(cell) for cell in row) for row in frame.itertuples(index=False, name=None))
        chunks.append(f'[sheet {title}]\n' + '\n'.join(lines))
    return '\n\n'.join(chunks)


# ─── PDF ───


def _pdf_text(data: bytes) -> tuple[str, int]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted and not reader.decrypt(''):
        raise AIError('ai.attachLocked', kind='bad_request')
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        text = str(page.extract_text() or '').strip()
        if text:
            pages.append(f'[page {index}]\n{text}')
    return '\n\n'.join(pages), len(reader.pages)


# ─── The public surface ───


def char_limit() -> int:
    """0 = no application cap (the model window is the only limit)."""
    return int(get_setting('ai_attachment_text_chars') or 0)


def _bounded(text: str) -> tuple[str, dict]:
    limit = char_limit()
    meta = {'limit': limit, 'chars': min(len(text), limit) if limit > 0 else len(text)}
    meta['truncated'] = limit > 0 and len(text) > limit
    if not meta['truncated']:
        return text, meta
    return text[:limit] + f'\n…[cut at {limit} chars by ai_attachment_text_chars]', meta


def extract(name: str, data: bytes) -> dict:
    """Read one attachment's words.

    The return value is the whole contract the agent needs: ``text``, ``kind``, ``pages`` (PDF) and
    the truncation report. Every failure is an ``AIError`` whose key says WHICH format failed and
    what to do — a silently empty document reads to the model as "the user attached nothing".
    """
    suffix = os.path.splitext(str(name or '').lower())[1]
    if not data:
        raise AIError('ai.attachEmpty', kind='bad_request', name=name or 'file')
    try:
        pages = 0
        if suffix in LEGACY_BINARY_SUFFIXES:
            raise AIError('ai.attachConvert', kind='bad_request', name=name, format=suffix.lstrip('.'))
        if suffix == '.pdf':
            text, pages = _pdf_text(data)
            kind = 'pdf'
        elif suffix == '.docx':
            text = _docx_text(data)
            kind = 'docx'
        elif suffix == '.pptx':
            text = _pptx_text(data)
            kind = 'pptx'
        elif suffix in SHEET_SUFFIXES or suffix in ('.csv', '.tsv'):
            if len(data) > TABLE_PARSE_MAX_BYTES:
                raise AIError(
                    'ai.attachTableTooBig',
                    kind='bad_request',
                    name=name,
                    mb=round(len(data) / (1024 * 1024), 1),
                    limit=TABLE_PARSE_MAX_BYTES // (1024 * 1024),
                )
            text = _sheet_text(name, data)
            kind = 'sheet'
        elif suffix in HTML_SUFFIXES:
            text = _html_text(data)
            kind = 'html'
        elif suffix in TEXT_SUFFIXES:
            text = _decode(data)
            kind = 'text'
        else:
            # An unknown suffix is not automatically unreadable: a `.srt` or a `.tex` is text. A
            # NUL byte in the first block is what separates "text with an odd extension" from a
            # binary the model cannot use.
            if b'\x00' in data[:4096]:
                raise AIError('ai.attachUnreadable', kind='bad_request', name=name or 'file')
            text = _decode(data)
            kind = 'text'
    except AIError:
        raise
    except Exception as exc:  # a corrupt office file or a malformed PDF
        raise AIError('ai.attachUnreadable', kind='bad_request', name=name or 'file', detail=str(exc)[:160]) from exc
    if not str(text or '').strip():
        raise AIError('ai.attachNoText', kind='bad_request', name=name or 'file')
    bounded, meta = _bounded(text)
    return {'text': bounded, 'kind': kind, 'pages': pages, 'chars': meta['chars'], 'truncated': meta['truncated']}


def cache_path(local_path: str) -> str:
    return str(local_path) + '.text.json'


def extract_attachment(row: dict) -> dict:
    """Extract one stored attachment, from the account's local copy, with a cache beside it.

    Extraction is not free (a 200-page PDF takes a second), and the same attachment is re-read on
    every turn that names it, so the result is cached by the local copy's content-addressed path.
    The cache records the limit it was cut at: changing ``ai_attachment_text_chars`` re-extracts
    instead of silently serving the old cut.
    """
    name = str((row or {}).get('name') or 'file')
    local_path = str((row or {}).get('path') or '')
    if not local_path or not os.path.isfile(local_path):
        raise AIError('ai.attachUnreadable', kind='bad_request', name=name)
    cache = cache_path(local_path)
    limit = char_limit()
    if os.path.isfile(cache):
        try:
            with open(cache, encoding='utf-8') as handle:
                cached = json.load(handle)
            if int(cached.get('limit') or 0) == limit and isinstance(cached.get('text'), str):
                return cached
        except (OSError, ValueError, TypeError):
            pass
    try:
        with open(local_path, 'rb') as handle:
            data = handle.read()
    except OSError as exc:
        raise AIError('ai.attachUnreadable', kind='bad_request', name=name, detail=str(exc)[:120]) from exc
    result = extract(name, data)
    result['limit'] = limit
    try:
        temp = cache + '.tmp'
        with open(temp, 'w', encoding='utf-8') as handle:
            json.dump(result, handle, ensure_ascii=False)
        os.replace(temp, cache)
    except OSError:
        # A cache that cannot be written is a slower turn, not a failed one.
        pass
    return result


#: An inline image is base64 in a JSON request: 8 MB of source bytes becomes ~11 MB of text, which
#: most gateways refuse. Anything larger is downscaled locally before it travels.
INLINE_IMAGE_MAX_BYTES = 8 * 1024 * 1024
INLINE_IMAGE_MAX_DIMENSION = 4096


def image_payload(row: dict) -> tuple[str, str]:
    """``(mime, base64)`` for a vision model, from the account's local copy.

    A provider with ``vision`` but no Files API gets the bytes inline. A photo straight from a
    phone is 12 MP and several MB, so an oversized image is downscaled here rather than refused:
    the model needs the picture, not the camera's resolution. The refusal only happens when even
    the recompressed image is too large to send.
    """
    import base64

    name = str((row or {}).get('name') or 'image')
    path = str((row or {}).get('path') or '')
    if not path or not os.path.isfile(path):
        raise AIError('ai.attachUnreadable', kind='bad_request', name=name)
    try:
        with open(path, 'rb') as handle:
            data = handle.read()
    except OSError as exc:
        raise AIError('ai.attachUnreadable', kind='bad_request', name=name, detail=str(exc)[:120]) from exc
    mime = str((row or {}).get('mime') or '').strip() or 'image/png'
    if len(data) > INLINE_IMAGE_MAX_BYTES:
        data, mime = _shrink_image(data, name)
    if len(data) > INLINE_IMAGE_MAX_BYTES:
        raise AIError(
            'ai.imageTooLarge',
            kind='bad_request',
            name=name,
            mb=round(len(data) / (1024 * 1024), 1),
            limit=INLINE_IMAGE_MAX_BYTES // (1024 * 1024),
        )
    return mime, base64.b64encode(data).decode('ascii')


def _shrink_image(data: bytes, name: str) -> tuple[bytes, str]:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            image.thumbnail((INLINE_IMAGE_MAX_DIMENSION, INLINE_IMAGE_MAX_DIMENSION))
            if image.mode not in ('RGB', 'L'):
                image = image.convert('RGB')
            output = io.BytesIO()
            image.save(output, format='JPEG', quality=85, optimize=True)
        return output.getvalue(), 'image/jpeg'
    except Exception as exc:  # a corrupt or unsupported image
        raise AIError('ai.attachUnreadable', kind='bad_request', name=name, detail=str(exc)[:120]) from exc


def is_image(row: dict) -> bool:
    mime = str((row or {}).get('mime') or '').lower()
    if mime.startswith('image/'):
        return True
    return os.path.splitext(str((row or {}).get('name') or '').lower())[1] in {
        '.jpg',
        '.jpeg',
        '.png',
        '.gif',
        '.webp',
        '.bmp',
        '.tif',
        '.tiff',
    }
