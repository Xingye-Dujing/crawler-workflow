"""DeepSeek Files API and the standalone Search / Fetch tools.

These are the product's independent tool APIs, not the model-facing `deepseek_web_search` server
tool: a caller can upload a document, search the web, or fetch one page without asking the model to
do it. The same functions are used by the agent's `web_search`/`web_fetch` tools and by the HTTP
routes, so there is one request shape and one error mapping.
"""

import hashlib
import mimetypes
import os
from urllib.parse import urlparse

import requests
from runtime import paths

from ai import store
from ai.context import safe_filename
from ai.errors import AIError, AIProviderError
from ai.providers.base import http_error

DEEPSEEK_BASE = 'https://api.deepseek.com'
MAX_FILE_BYTES = 100 * 1024 * 1024
DOCUMENT_SUFFIXES = ('.pdf', '.doc', '.docx', '.ppt', '.pptx')
IMAGE_SUFFIXES = ('.jpg', '.jpeg', '.png', '.gif', '.webp')
TEXT_SUFFIXES = ('.txt', '.md', '.csv', '.json', '.log', '.py', '.js', '.html', '.xml', '.yaml', '.yml')


def purpose_for(filename: str, mime: str = '') -> str:
    lowered = str(filename or '').lower()
    if str(mime or '').startswith('image/') or lowered.endswith(IMAGE_SUFFIXES):
        return 'user_data'
    if lowered.endswith(DOCUMENT_SUFFIXES):
        return 'text_recognition'
    if lowered.endswith(TEXT_SUFFIXES) or str(mime or '').startswith('text/'):
        return 'user_data'
    return 'user_data'


def _guess_mime(filename: str, mime: str) -> str:
    return str(mime or '').strip() or mimetypes.guess_type(filename)[0] or 'application/octet-stream'


def _check_key(api_key: str) -> str:
    key = str(api_key or '').strip()
    if not key:
        raise AIError('ai.noKey', kind='auth')
    return key


def _error(status: int, body: str, *, is_fetch: bool = False) -> AIProviderError:
    if is_fetch and status == 403:
        return AIProviderError('ai.fetchBlocked', kind='capability', status=status, detail=body[:300])
    if is_fetch and status == 404:
        return AIProviderError('ai.fetchNotFound', kind='not_found', status=status, detail=body[:300])
    return http_error(status, body)


def save_local(data: bytes, filename: str) -> tuple[str, str]:
    digest = hashlib.sha256(data).hexdigest()
    directory = paths.active().ensure().ai_files_dir
    os.makedirs(directory, exist_ok=True)
    target = os.path.join(directory, f'{digest[:20]}_{safe_filename(filename)}')
    if not os.path.exists(target):
        with open(target, 'wb') as handle:
            handle.write(data)
    return target, digest


def upload_file(
    conversation_id: str,
    name: str,
    mime: str,
    data: bytes,
    api_key: str,
    *,
    purpose: str = '',
    provider: str = 'deepseek',
    timeout: int = 300,
) -> dict:
    if str(provider or '') != 'deepseek':
        raise AIError('ai.fileUnsupported', kind='capability')
    key = _check_key(api_key)
    if len(data) > MAX_FILE_BYTES:
        raise AIError('ai.fileTooLarge', kind='bad_request', mb=MAX_FILE_BYTES // (1024 * 1024))
    chosen_purpose = str(purpose or purpose_for(name, mime)).strip()
    if chosen_purpose not in ('user_data', 'text_recognition', 'rich_layout_recognition'):
        raise AIError('ai.fileUnsupported', kind='bad_request')
    digest = hashlib.sha256(data).hexdigest()
    try:
        response = requests.post(
            DEEPSEEK_BASE + '/files',
            headers={'Authorization': f'Bearer {key}'},
            files=[
                ('purpose', (None, chosen_purpose)),
                ('file', (name, data, _guess_mime(name, mime))),
            ],
            timeout=(15, max(30, int(timeout))),
        )
    except requests.RequestException as exc:
        raise AIProviderError('ai.network', kind='network', detail=str(exc)[:300]) from exc
    if response.status_code != 200:
        raise _error(response.status_code, response.text[:400])
    try:
        payload = response.json()
    except ValueError as exc:
        raise AIProviderError('ai.badResponse', kind='bad_response', detail=response.text[:200]) from exc
    file_id = str(payload.get('id') or '')
    if not file_id:
        raise AIProviderError('ai.badResponse', kind='bad_response', detail='missing file id')
    # The local copy is written only after the provider accepted the upload. Saving first left a
    # file in ai_files/ with no attachment row whenever the request failed, forever.
    try:
        local_path, digest = save_local(data, name)
    except OSError as exc:
        raise AIError('ai.fileSaveFailed', kind='error', detail=str(exc)[:200]) from exc
    row = store.add_attachment(
        conversation_id,
        str(payload.get('filename') or name),
        _guess_mime(name, mime),
        int(payload.get('bytes') or len(data)),
        digest,
        chosen_purpose,
        file_id,
        local_path,
    )
    return row


def delete_file(file_id: str, api_key: str) -> bool:
    key = _check_key(api_key)
    try:
        response = requests.delete(
            DEEPSEEK_BASE + '/files/' + str(file_id),
            headers={'Authorization': f'Bearer {key}'},
            timeout=30,
        )
    except requests.RequestException as exc:
        raise AIProviderError('ai.network', kind='network', detail=str(exc)[:300]) from exc
    if response.status_code in (200, 404):
        return True
    raise _error(response.status_code, response.text[:300])


def search(
    api_key: str,
    query: str,
    *,
    count: int = 10,
    need_content: bool = False,
    ori_question: str = '',
    localization: str = '',
) -> dict:
    key = _check_key(api_key)
    text = str(query or '').strip()
    if not text or len(text) > 128:
        raise AIError('ai.searchQuery', kind='bad_request')
    body = {
        'query': text,
        'count': max(1, min(50, int(count or 10))),
        'need_content': bool(need_content),
    }
    if ori_question:
        body['ori_question'] = str(ori_question)[:128]
    if localization:
        body['localization'] = str(localization)
    try:
        response = requests.post(
            DEEPSEEK_BASE + '/v1/tools/search',
            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
            json=body,
            timeout=60,
        )
    except requests.RequestException as exc:
        raise AIProviderError('ai.network', kind='network', detail=str(exc)[:300]) from exc
    if response.status_code != 200:
        raise _error(response.status_code, response.text[:400])
    try:
        payload = response.json()
    except ValueError as exc:
        raise AIProviderError('ai.badResponse', kind='bad_response', detail=response.text[:200]) from exc
    return {'results': payload.get('results') or []}


def fetch(api_key: str, url: str) -> dict:
    key = _check_key(api_key)
    target = str(url or '').strip()
    if len(target) > 8192:
        raise AIError('ai.fetchUrl', kind='bad_request')
    parsed = urlparse(target)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise AIError('ai.fetchUrl', kind='bad_request')
    try:
        response = requests.post(
            DEEPSEEK_BASE + '/v1/tools/fetch',
            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
            json={'url': target},
            timeout=60,
        )
    except requests.RequestException as exc:
        raise AIProviderError('ai.network', kind='network', detail=str(exc)[:300]) from exc
    if response.status_code != 200:
        raise _error(response.status_code, response.text[:400], is_fetch=True)
    try:
        payload = response.json()
    except ValueError as exc:
        raise AIProviderError('ai.badResponse', kind='bad_response', detail=response.text[:200]) from exc
    return {'title': str(payload.get('title') or ''), 'content': str(payload.get('content') or '')}


def attachments_payload(attachments: list) -> list:
    """The assistant-request shapes for stored attachments; the provider only sees file ids."""
    out = []
    for row in attachments or ():
        file_id = str(row.get('file_id') or '')
        if not file_id:
            continue
        kind = (
            'image'
            if str(row.get('purpose') or '') == 'user_data' and str(row.get('mime') or '').startswith('image/')
            else 'document'
        )
        out.append({'file_id': file_id, 'kind': kind, 'name': row.get('name') or 'file'})
    return out
