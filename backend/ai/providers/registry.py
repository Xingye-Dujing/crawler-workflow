"""The one provider catalog. Every route, analyzer and test asks this module."""

from core.config import Config
from runtime import account_context

from ai import scopes
from ai.errors import AIError
from ai.providers.deepseek import DeepSeekProvider
from ai.providers.ollama import OllamaProvider
from ai.providers.opencode_go import OpenCodeGoProvider
from ai.providers.openrouter import OpenRouterProvider
from i18n import t

PROVIDERS = {
    provider.spec.id: provider
    for provider in (
        DeepSeekProvider(),
        OpenCodeGoProvider(),
        OpenRouterProvider(),
        OllamaProvider(),
    )
}

#: Stable order for the picker: the full API first, then the subscription, then the fallbacks.
ORDER = ('deepseek', 'opencode_go', 'openrouter', 'ollama')


def get_provider(provider_id: str):
    key = str(provider_id or '').strip()
    provider = PROVIDERS.get(key)
    # ``unknown`` is also the answer for another account's plugin provider: naming it exists, but
    # calling it would spend that account's endpoint choice from a conversation it never approved.
    if provider is None or not scopes.visible('providers', key, account_context.scope_key()):
        raise AIError('ai.unknownProvider', kind='bad_request', provider=key)
    return provider


def public_catalog() -> list:
    """Every provider the picker may show. This reads no daemon: the live model list is
    ``GET /api/ai/ws/providers/<id>/models``, which the panel asks for when the provider is local."""
    out = []
    for key in ORDER:
        provider = PROVIDERS[key]
        if not scopes.visible('providers', key, account_context.scope_key()):
            continue
        item = provider.public()
        item['local_available'] = not (provider.spec.local_only and Config.CLOUD_MODE)
        if provider.spec.local_only and Config.CLOUD_MODE:
            item['why_not_key'] = 'ai.localCloud'
            item['why_not_text'] = t('ai.localCloud', provider=provider.spec.id)
        out.append(item)
    return out


def list_models(provider_id: str, api_key: str = '', host: str = '') -> list:
    return get_provider(provider_id).list_models(api_key, host)


def local_transport_refusal(provider_id: str) -> str:
    """A cloud host's refusal for a local-only provider, or ``''`` when it may run.

    The old ``runtime.transport`` folded every name except ``openrouter`` into "local"; with
    three remote providers that would refuse DeepSeek and Go on a cloud host for no reason.
    """
    provider = PROVIDERS.get(str(provider_id or '').strip())
    if provider is None:
        return ''
    if Config.CLOUD_MODE and provider.spec.local_only:
        return t('ai.localCloud', provider=provider.spec.id)
    return ''
