"""Attachments across provider capabilities: files (native), vision (images) and text extraction.

The old gate asked every attachment for ``files``. That refused a plain .txt on a local model and
called an image's missing capability by the wrong name. These cases pin the split and the two
transports that carry an inline image.
"""

import base64

import pytest
from ai.types import ProviderSpec

pytestmark = pytest.mark.unit


class FakeProvider:
    def __init__(self, capabilities, provider_id='fake_provider'):
        self.spec = ProviderSpec(
            id=provider_id,
            label_key='x',
            notes_key='x',
            protocol='openai',
            base_url='',
            capabilities=frozenset(capabilities),
        )

    def supports(self, capability, model=''):
        return capability in self.spec.capabilities


def _note(tmp_path, name='note.txt', text='正文：这是附件里的字。'):
    source = tmp_path / name
    source.write_text(text, encoding='utf-8')
    return {
        'id': 'att_1',
        'name': name,
        'mime': 'text/plain' if name.endswith('.txt') else 'application/octet-stream',
        'path': str(source),
        'file_id': '',
        'purpose': 'user_data',
    }


def _image(tmp_path):
    from PIL import Image

    source = tmp_path / 'shot.png'
    Image.new('RGB', (8, 8), 'blue').save(source, format='PNG')
    return {
        'id': 'att_img',
        'name': 'shot.png',
        'mime': 'image/png',
        'path': str(source),
        'file_id': '',
        'purpose': 'user_data',
    }


def test_a_document_reaches_a_provider_without_files_as_text(monkeypatch, tmp_path):
    from ai import agent

    monkeypatch.setattr('ai.file_text.get_setting', lambda key: 0)
    row = _note(tmp_path)
    native, text, meta = agent._attachment_plan([row], FakeProvider({'tools'}), 'm')
    assert native == []
    assert '正文：这是附件里的字。' in text
    assert '<cai_xi_hui_attachments>' in text
    assert meta['attachments_extracted'] == 1
    assert meta['attachment_text_chars'] > 0


def test_a_provider_with_files_gets_the_native_file_and_no_extraction(monkeypatch, tmp_path):
    from ai import agent, file_text

    def explode(*_args, **_kwargs):
        raise AssertionError('a native Files upload must not be extracted again')

    monkeypatch.setattr(file_text, 'extract_attachment', explode)
    row = {**_note(tmp_path), 'file_id': 'file_123'}
    native, text, meta = agent._attachment_plan([row], FakeProvider({'files'}), 'm')
    assert text == ''
    assert native[0]['file_id'] == 'file_123'
    assert native[0]['kind'] == 'document'
    assert meta['attachment_texts'][0]['native'] is True


def test_native_files_still_allow_a_model_that_cannot_parse_them(monkeypatch, tmp_path):
    """DeepSeek's v4-pro has no ``files`` capability but its upload row has a file id; the text
    pass is the only way that turn can read the document."""
    from ai import agent

    monkeypatch.setattr('ai.file_text.get_setting', lambda key: 0)
    row = {**_note(tmp_path), 'file_id': 'file_123'}
    native, text, _meta = agent._attachment_plan([row], FakeProvider({'tools'}), 'm')
    assert native == []
    assert '正文' in text


def test_an_image_asks_for_vision_not_files(monkeypatch, tmp_path):
    from ai import agent
    from ai.errors import AIError

    row = _image(tmp_path)
    with pytest.raises(AIError) as refused:
        agent._attachment_plan([row], FakeProvider({'tools', 'files'}), 'm')
    assert refused.value.key == 'ai.capabilityRefused'
    assert refused.value.params['capability'] == 'vision'


def test_a_vision_provider_that_inlines_images_needs_no_upload(monkeypatch, tmp_path):
    from ai import agent

    row = _image(tmp_path)
    native, text, _meta = agent._attachment_plan([row], FakeProvider({'vision', 'inline_images'}), 'm')
    assert text == ''
    assert native[0]['kind'] == 'image'
    assert native[0]['path'] == row['path']


def test_a_vision_provider_without_inline_images_refuses_a_foreign_image(monkeypatch, tmp_path):
    """A row from another provider's conversation has no file id HERE; silently dropping it made
    the model answer about an image it never received."""
    from ai import agent
    from ai.errors import AIError

    row = _image(tmp_path)
    with pytest.raises(AIError) as refused:
        agent._attachment_plan([row], FakeProvider({'vision'}), 'm')
    assert refused.value.key == 'ai.imageNeedsUpload'


def test_openai_compatible_messages_carry_the_image_as_a_data_url(tmp_path):
    from ai.providers import openai_compat

    row = _image(tmp_path)
    messages = [
        {
            'role': 'user',
            'content': '这是什么？',
            'meta': {'attachments': [{**row, 'kind': 'image'}]},
        }
    ]
    out = openai_compat.to_messages('', messages)
    content = out[0]['content']
    assert isinstance(content, list)
    image = content[0]
    assert image['type'] == 'image_url'
    assert image['image_url']['url'].startswith('data:image/png;base64,')
    encoded = image['image_url']['url'].split(',', 1)[1]
    assert base64.b64decode(encoded).startswith(b'\x89PNG')
    assert content[1] == {'type': 'text', 'text': '这是什么？'}


def test_a_text_only_user_message_stays_a_plain_string():
    from ai.providers import openai_compat

    out = openai_compat.to_messages('', [{'role': 'user', 'content': 'hello', 'meta': {}}])
    assert out[0]['content'] == 'hello'


def test_ollama_puts_inline_images_in_its_own_field(tmp_path):
    from ai.providers.ollama import OllamaProvider

    row = _image(tmp_path)
    messages = [{'role': 'user', 'content': '看图', 'meta': {'attachments': [{**row, 'kind': 'image'}]}}]
    out = OllamaProvider()._messages({'messages': messages})
    user = out[-1]
    assert user['role'] == 'user' and user['content'] == '看图'
    assert base64.b64decode(user['images'][0]).startswith(b'\x89PNG')
