"""DeepSeek's standalone Search / Fetch tools.

These are the product's independent tool APIs, not the model-facing server tool: the workspace's
``web_search``/``fetch_url`` tools ask this host for them, and the API key is the browser's, carried
by the request that needs it. One request shape, one error mapping.
"""

from urllib.parse import urlparse

import requests

from ai.errors import AIError, AIProviderError
from ai.providers.base import http_error

DEEPSEEK_BASE = 'https://api.deepseek.com'


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
