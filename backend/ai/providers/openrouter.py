"""OpenRouter's OpenAI-compatible catalog, retained as a free-model fallback.

The row analyzers already used this endpoint. It is now one provider behind the same catalog as
DeepSeek and Go; the existing ``/api/llm/models`` route can keep answering because the catalog
shape is unchanged.
"""

import requests

from ai.providers.openai_compat import OpenAICompatibleProvider
from ai.types import ModelSpec, ProviderSpec

OPENROUTER_CHAT_URL = 'https://openrouter.ai/api/v1/chat/completions'
OPENROUTER_MODELS_URL = 'https://openrouter.ai/api/v1/models'
OPENROUTER_REFERER = 'http://localhost:5000'
OPENROUTER_TITLE = 'Crawler Workflow'

CAPABILITIES = frozenset({'thinking', 'tools', 'ask_user'})

SPEC = ProviderSpec(
    id='openrouter',
    label_key='ai.provider.openrouter',
    notes_key='ai.providerNote.openrouter',
    protocol='openai',
    base_url=OPENROUTER_CHAT_URL,
    models=(ModelSpec('openrouter/free', 'OpenRouter free model', 128000, CAPABILITIES),),
    capabilities=CAPABILITIES,
    models_url=OPENROUTER_MODELS_URL,
)


class OpenRouterProvider(OpenAICompatibleProvider):
    def __init__(self):
        super().__init__(
            SPEC,
            extra_headers={'HTTP-Referer': OPENROUTER_REFERER, 'X-Title': OPENROUTER_TITLE},
            user_agent='CaiXiHui-AI/1.0',
        )

    def list_models(self, api_key: str = '', host: str = '') -> list:
        try:
            response = requests.get(OPENROUTER_MODELS_URL, timeout=15)
            response.raise_for_status()
            rows = response.json().get('data', [])
        except (requests.RequestException, ValueError):
            return super().list_models(api_key, host)
        models = []
        for row in rows:
            pricing = row.get('pricing') or {}
            if str(pricing.get('prompt', '1')) != '0' or str(pricing.get('completion', '1')) != '0':
                continue
            if row.get('id'):
                models.append({'id': str(row['id']), 'label': str(row.get('name') or row['id'])})
        return sorted(models, key=lambda item: item['id']) or super().list_models(api_key, host)


def list_free_models(timeout: int = 15) -> list:
    """The historical helper the AI settings panel calls; one catalog, no second list."""
    response = requests.get(OPENROUTER_MODELS_URL, timeout=timeout)
    response.raise_for_status()
    models = response.json().get('data', [])
    return sorted(
        model['id']
        for model in models
        if str(model.get('pricing', {}).get('prompt', '1')) == '0'
        and str(model.get('pricing', {}).get('completion', '1')) == '0'
    )
