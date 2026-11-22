"""Attachment text extraction: every format a user can attach is read by the server, not the provider."""

import base64
import io
import json
import zipfile

import pytest

pytestmark = pytest.mark.unit


def _settings(monkeypatch, limit=0):
    from ai import file_text

    monkeypatch.setattr(file_text, 'get_setting', lambda key: limit)
    return file_text


def _tiny_pdf(text='Hello PDF') -> bytes:
    """A valid one-page PDF with a Helvetica string, built here so the test needs no fixture file."""
    stream = f'BT /F1 24 Tf 72 720 Td ({text}) Tj ET'.encode('latin-1')
    bodies = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        (
            b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] '
            b'/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>'
        ),
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream',
    ]
    out = bytearray(b'%PDF-1.4\n')
    offsets = []
    for index, body in enumerate(bodies, start=1):
        offsets.append(len(out))
        out += f'{index} 0 obj\n'.encode() + body + b'\nendobj\n'
    xref = len(out)
    out += b'xref\n0 ' + str(len(bodies) + 1).encode() + b'\n0000000000 65535 f \n'
    for offset in offsets:
        out += f'{offset:010d} 00000 n \n'.encode()
    out += (
        b'trailer\n<< /Size '
        + str(len(bodies) + 1).encode()
        + b' /Root 1 0 R >>\nstartxref\n'
        + str(xref).encode()
        + b'\n%%EOF\n'
    )
    return bytes(out)


def test_plain_text_and_chinese_encodings_are_read(monkeypatch):
    file_text = _settings(monkeypatch)
    assert file_text.extract('note.txt', '正文：测试'.encode())['text'] == '正文：测试'
    gbk = file_text.extract('note.txt', '正文：测试'.encode('gb18030'))
    assert '正文' in gbk['text'], gbk


def test_html_keeps_visible_text_not_scripts(monkeypatch):
    file_text = _settings(monkeypatch)
    result = file_text.extract(
        'page.html',
        b'<html><head><style>.x{}</style><script>alert(1)</script></head>'
        b'<body><h1>Title</h1><p>first</p><p>second</p></body></html>',
    )
    assert 'Title' in result['text'] and 'first' in result['text'] and 'second' in result['text']
    assert 'alert(1)' not in result['text']
    assert '.x{}' not in result['text']


def test_docx_is_read_from_the_zip(monkeypatch):
    file_text = _settings(monkeypatch)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr(
            'word/document.xml',
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:r><w:t>第一段</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>second paragraph</w:t></w:r></w:p></w:body></w:document>',
        )
    result = file_text.extract('report.docx', buffer.getvalue())
    assert '第一段' in result['text'] and 'second paragraph' in result['text']
    assert result['kind'] == 'docx'


def test_pptx_is_read_slide_by_slide(monkeypatch):
    file_text = _settings(monkeypatch)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr(
            'ppt/slides/slide1.xml',
            '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            '<a:p><a:r><a:t>Slide one</a:t></a:r></a:p></p:sld>',
        )
        archive.writestr(
            'ppt/slides/slide2.xml',
            '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            '<a:p><a:r><a:t>Slide two</a:t></a:r></a:p></p:sld>',
        )
    result = file_text.extract('deck.pptx', buffer.getvalue())
    assert 'Slide one' in result['text'] and 'Slide two' in result['text']
    assert result['text'].index('Slide one') < result['text'].index('Slide two')


def test_xlsx_is_rendered_as_tab_separated_sheets(monkeypatch):
    import pandas as pd

    file_text = _settings(monkeypatch)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        pd.DataFrame({'平台': ['知乎'], '正文': ['hello']}).to_excel(writer, sheet_name='数据', index=False)
        pd.DataFrame({'a': [1]}).to_excel(writer, sheet_name='Other', index=False)
    result = file_text.extract('table.xlsx', buffer.getvalue())
    assert '[sheet 数据]' in result['text']
    assert '平台\t正文' in result['text']
    assert '[sheet Other]' in result['text']


def test_csv_is_read_with_a_header(monkeypatch):
    file_text = _settings(monkeypatch)
    result = file_text.extract('rows.csv', '平台,正文\n知乎,hello\n'.encode())
    assert '平台\t正文' in result['text']
    assert '知乎\thello' in result['text']


def test_pdf_pages_are_read(monkeypatch):
    file_text = _settings(monkeypatch)
    result = file_text.extract('paper.pdf', _tiny_pdf())
    assert 'Hello PDF' in result['text'], result
    assert result['pages'] == 1
    assert result['kind'] == 'pdf'


def test_a_legacy_doc_is_refused_with_the_way_out(monkeypatch):
    from ai.errors import AIError

    file_text = _settings(monkeypatch)
    with pytest.raises(AIError) as excinfo:
        file_text.extract('old.doc', b'\xd0\xcf\x11\xe0binary')
    assert excinfo.value.key == 'ai.attachConvert'
    assert excinfo.value.params['format'] == 'doc'


def test_empty_and_scanned_documents_are_refused_by_name(monkeypatch):
    from ai.errors import AIError

    file_text = _settings(monkeypatch)
    with pytest.raises(AIError) as empty:
        file_text.extract('empty.txt', b'')
    assert empty.value.key == 'ai.attachEmpty'
    with pytest.raises(AIError) as scanned:
        file_text.extract('scan.pdf', _tiny_pdf(''))
    assert scanned.value.key in ('ai.attachNoText', 'ai.attachUnreadable'), scanned.value.key


def test_an_unknown_binary_is_refused_but_an_unknown_text_extension_is_read(monkeypatch):
    from ai.errors import AIError

    file_text = _settings(monkeypatch)
    with pytest.raises(AIError) as refused:
        file_text.extract('blob.xyz', b'\x00\x01\x02')
    assert refused.value.key == 'ai.attachUnreadable'
    assert file_text.extract('captions.srt', b'1\n00:00:01,000 --> 00:00:02,000\nhello\n')['text']


def test_the_character_limit_is_reported_when_it_cuts(monkeypatch):
    file_text = _settings(monkeypatch, limit=10)
    result = file_text.extract('long.txt', b'x' * 50)
    assert result['truncated'] is True
    assert 'cut at 10 chars' in result['text']
    assert result['chars'] == 10


def test_zero_means_no_application_limit(monkeypatch):
    file_text = _settings(monkeypatch, limit=0)
    result = file_text.extract('long.txt', b'x' * 5000)
    assert result['truncated'] is False
    assert len(result['text']) == 5000


def test_extraction_is_cached_and_a_changed_limit_re_extracts(monkeypatch, tmp_path):
    file_text = _settings(monkeypatch)
    source = tmp_path / 'note.txt'
    source.write_text('cached words', encoding='utf-8')
    row = {'name': 'note.txt', 'path': str(source)}
    first = file_text.extract_attachment(row)
    assert first['text'] == 'cached words'
    assert (tmp_path / 'note.txt.text.json').is_file()

    # A second read comes from the cache: the extractor must not even be called.
    def explode(*_args, **_kwargs):
        raise AssertionError('extract() was called despite a valid cache')

    monkeypatch.setattr(file_text, 'extract', explode)
    assert file_text.extract_attachment(row)['text'] == 'cached words'

    # A different limit invalidates the cache; the old cut must not be served as the new answer.
    monkeypatch.setattr(file_text, 'get_setting', lambda key: 6)
    monkeypatch.undo()
    _settings(monkeypatch, limit=6)
    fresh = file_text.extract_attachment(row)
    assert fresh['truncated'] is True and fresh['chars'] == 6


def test_an_image_payload_is_base64_and_a_missing_copy_is_named(monkeypatch, tmp_path):
    from ai.errors import AIError
    from PIL import Image

    file_text = _settings(monkeypatch)
    path = tmp_path / 'shot.png'
    Image.new('RGB', (4, 4), 'red').save(path, format='PNG')
    mime, encoded = file_text.image_payload({'name': 'shot.png', 'path': str(path), 'mime': 'image/png'})
    assert mime == 'image/png'
    assert base64.b64decode(encoded).startswith(b'\x89PNG')
    with pytest.raises(AIError) as missing:
        file_text.image_payload({'name': 'gone.png', 'path': str(tmp_path / 'gone.png')})
    assert missing.value.key == 'ai.attachUnreadable'


def test_a_cached_result_is_json_the_agent_can_reuse(monkeypatch, tmp_path):
    file_text = _settings(monkeypatch)
    source = tmp_path / 'table.csv'
    source.write_text('a,b\n1,2\n', encoding='utf-8')
    file_text.extract_attachment({'name': 'table.csv', 'path': str(source)})
    payload = json.loads((tmp_path / 'table.csv.text.json').read_text(encoding='utf-8'))
    assert payload['kind'] == 'sheet'
    assert '1\t2' in payload['text']
