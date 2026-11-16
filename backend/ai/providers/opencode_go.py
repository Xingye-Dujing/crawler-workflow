"""OpenCode Go: the subscription gateway's OpenAI-compatible chat endpoint.

Go is intended for coding-agent traffic and asks clients to identify themselves and to carry a
stable session id. The transport therefore sets both headers; the capability manifest leaves out
the DeepSeek server tools (search, read-link, files, title, safety) because the gateway does not
offer them. A skill that needs one of those is refused by name rather than silently answered
without it.
"""

from ai.providers.openai_compat import OpenAICompatibleProvider
from ai.types import ModelSpec, ProviderSpec

GO_CAPABILITIES = frozenset({'thinking', 'tools', 'ask_user', 'vision'})

SPEC = ProviderSpec(
    id='opencode_go',
    label_key='ai.provider.opencode_go',
    notes_key='ai.providerNote.opencode_go',
    protocol='openai',
    base_url='https://opencode.ai/inference/go/openai/v1/chat/completions',
    models=(
        ModelSpec('deepseek-v4.1-flash', 'DeepSeek V4.1 Flash (Go)', 512000, GO_CAPABILITIES),
        ModelSpec('deepseek-v4-pro', 'DeepSeek V4 Pro (Go)', 512000, GO_CAPABILITIES),
        ModelSpec('glm-5.3-flash', 'GLM-5.3 Flash (Go)', 256000, GO_CAPABILITIES),
        ModelSpec('kimi-k3', 'Kimi K3 (Go)', 256000, GO_CAPABILITIES),
        ModelSpec('qwen3.8-flash', 'Qwen3.8 Flash (Go)', 256000, GO_CAPABILITIES),
    ),
    capabilities=GO_CAPABILITIES,
    models_url='https://opencode.ai/inference/go/openai/v1/models',
)


class OpenCodeGoProvider(OpenAICompatibleProvider):
    def __init__(self):
        super().__init__(SPEC, user_agent='CaiXiHui-AI/1.0')
