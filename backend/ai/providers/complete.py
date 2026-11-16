"""One non-streaming chat call on top of the streaming providers.

The row analyzers (cleaner, emotion, tendency, NER, topic labels) send one prompt per row and do
not need blocks. They still must use the same provider catalog as the workspace, or a run could
claim DeepSeek while a second table silently sent OpenRouter. This helper drains a stream and
returns its text; it never advertises a transport it did not use.
"""

from ai.errors import AIError
from ai.providers import get_provider


def chat_once(
    provider_id: str,
    model: str,
    api_key: str,
    prompt: str,
    *,
    max_tokens: int = 512,
    timeout: int = 180,
    host: str = '',
    system: str = '',
    temperature: float = 0.1,
) -> str:
    provider = get_provider(provider_id)
    chosen = (model or '').strip() or (provider.spec.models[0].id if provider.spec.models else '')
    pieces = []
    for event in provider.stream(
        {
            'model': chosen,
            'api_key': api_key,
            'system': system,
            'messages': [{'role': 'user', 'content': prompt}],
            'tools': [],
            'thinking': False,
            'web_search': False,
            'safety': 'high',
            'title': False,
            'max_tokens': max(1, int(max_tokens)),
            'temperature': temperature,
            'timeout': max(10, int(timeout)),
            'cancel_event': None,
            'host': host,
        }
    ):
        kind = event.get('type')
        if kind == 'text_delta':
            pieces.append(str(event.get('text') or ''))
        elif kind == 'done':
            break
    text = ''.join(pieces).strip()
    if not text:
        raise AIError('ai.badResponse', kind='bad_response', detail='empty completion')
    return text
