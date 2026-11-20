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
    on_delta=None,
) -> str:
    """One prompt -> full text. ``on_delta(text)``, when given, sees each token as it arrives.

    The provider catalog is the single source of truth: stream() already yields canonical
    ``text_delta`` events, so the row analyzers and the workspace cannot disagree about the
    transport. The optional callback is how a node-trace conversation mirrors the answer while
    it is being generated instead of only after it finished; without it the behaviour is exactly
    the buffered ``chat_once`` the analyzers have always used.
    """
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
            delta = str(event.get('text') or '')
            pieces.append(delta)
            if on_delta is not None and delta:
                on_delta(delta)
        elif kind == 'done':
            break
    text = ''.join(pieces).strip()
    if not text:
        raise AIError('ai.badResponse', kind='bad_response', detail='empty completion')
    return text
