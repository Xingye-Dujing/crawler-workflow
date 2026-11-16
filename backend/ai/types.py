"""Small value types shared by providers, the store, the agent and the UI.

The wire format is JSON-shaped on purpose. A conversation is reloaded from SQLite, streamed to the
browser and replayed to a provider, so a dataclass hierarchy would need three serializers and one
of them would eventually disagree with the other two. These helpers keep the shape in one place.
"""

import re
import uuid
from dataclasses import dataclass, field

SKILL_ID_RE = re.compile(r'^[a-z][a-z0-9._-]{1,63}$')

#: Capabilities a provider may declare. A skill may require any of them; the UI and the agent
#: consult the same set, and an unknown capability is never silently treated as "supported".
CAPABILITIES = (
    'thinking',
    'web_search',
    'read_url',
    'files',
    'safety',
    'title',
    'latest_reminder',
    'tools',
    'ask_user',
    'vision',
    'tts',
    'asr',
    'ocr',
    'continue',
)


def new_id(prefix: str) -> str:
    return f'{prefix}_{uuid.uuid4().hex[:24]}'


@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str = ''
    max_context: int = 128000
    capabilities: frozenset = frozenset()

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'label': self.label or self.id,
            'max_context': self.max_context,
            'capabilities': sorted(self.capabilities),
        }


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label_key: str
    notes_key: str
    protocol: str
    base_url: str
    models: tuple = ()
    requires_key: bool = True
    local_only: bool = False
    capabilities: frozenset = frozenset()
    models_url: str = ''

    def supports(self, capability: str, model: str = '') -> bool:
        chosen = self.model(model)
        if chosen is not None and chosen.capabilities:
            return capability in chosen.capabilities
        return capability in self.capabilities

    def model(self, model_id: str) -> ModelSpec | None:
        for model in self.models:
            if model.id == model_id:
                return model
        return None

    def to_public(self) -> dict:
        return {
            'id': self.id,
            'label_key': self.label_key,
            'notes_key': self.notes_key,
            'protocol': self.protocol,
            'requires_key': self.requires_key,
            'local_only': self.local_only,
            'capabilities': sorted(self.capabilities),
            'models': [model.to_dict() for model in self.models],
            'models_url': self.models_url,
        }


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict
    permission: str = 'read:project'
    handler: object = None
    control: bool = False

    def schema(self) -> dict:
        return {'name': self.name, 'description': self.description, 'input_schema': self.parameters}


@dataclass
class SkillSpec:
    id: str
    name_key: str
    description_key: str
    prompt: str
    context: tuple = ()
    tools: tuple = ()
    requires: frozenset = frozenset()
    suggested: tuple = ()
    ask_policy: str = 'auto'
    builtin: bool = True
    version: int = 1
    account: str = ''
    icon: str = 'spark'
    name: str = ''
    description: str = ''

    def to_public(self) -> dict:
        return {
            'id': self.id,
            'name_key': self.name_key,
            'description_key': self.description_key,
            'name': self.name,
            'description': self.description,
            'context': list(self.context),
            'tools': list(self.tools),
            'requires': sorted(self.requires),
            'suggested': list(self.suggested),
            'ask_policy': self.ask_policy,
            'builtin': self.builtin,
            'version': self.version,
            'icon': self.icon,
        }

    def to_manifest(self) -> dict:
        return {
            'id': self.id,
            'name_key': self.name_key,
            'description_key': self.description_key,
            'name': self.name,
            'description': self.description,
            'prompt': self.prompt,
            'context': list(self.context),
            'tools': list(self.tools),
            'requires': sorted(self.requires),
            'suggested': list(self.suggested),
            'ask_policy': self.ask_policy,
            'version': self.version,
            'icon': self.icon,
        }


def text_block(text: str) -> dict:
    return {'type': 'text', 'text': text}


def thinking_block(text: str, signature: str = '') -> dict:
    return {'type': 'thinking', 'thinking': text, 'signature': signature}


def tool_use_block(call_id: str, name: str, arguments: dict) -> dict:
    return {'type': 'tool_use', 'id': call_id, 'name': name, 'input': arguments}


def tool_result_block(call_id: str, content, is_error: bool = False) -> dict:
    return {'type': 'tool_result', 'tool_use_id': call_id, 'content': content, 'is_error': is_error}


def block_text(blocks) -> str:
    return ''.join(str(block.get('text') or '') for block in blocks or () if block.get('type') == 'text')


def message_text(message: dict) -> str:
    return block_text(message.get('blocks') or ())


def skill_from_manifest(payload: dict, *, account: str = '', builtin: bool = False) -> SkillSpec:
    skill_id = str(payload.get('id') or '').strip()
    return SkillSpec(
        id=skill_id,
        name_key=str(payload.get('name_key') or f'ai.skillName.{skill_id}'),
        description_key=str(payload.get('description_key') or f'ai.skillDesc.{skill_id}'),
        prompt=str(payload.get('prompt') or '').strip(),
        context=tuple(payload.get('context') or ()),
        tools=tuple(payload.get('tools') or ()),
        requires=frozenset(payload.get('requires') or ()),
        suggested=tuple(payload.get('suggested') or ()),
        ask_policy=str(payload.get('ask_policy') or 'auto'),
        builtin=builtin,
        version=int(payload.get('version') or 1),
        account=account,
        icon=str(payload.get('icon') or 'spark'),
        name=str(payload.get('name') or ''),
        description=str(payload.get('description') or ''),
    )


@dataclass
class ProviderReply:
    """Non-streaming answer shape, used by tests and by the JSON fallback."""

    blocks: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    title: str = ''
    stop_reason: str = 'end_turn'


def usage_totals(usage: dict) -> dict:
    """Normalize the three provider usage dialects to the few numbers the UI shows."""
    usage = usage or {}
    prompt = int(usage.get('prompt_tokens') or usage.get('input_tokens') or 0)
    completion = int(usage.get('completion_tokens') or usage.get('output_tokens') or 0)
    details = usage.get('prompt_tokens_details') or {}
    completion_details = usage.get('completion_tokens_details') or {}
    return {
        'prompt_tokens': prompt,
        'completion_tokens': completion,
        'cached_tokens': int(details.get('cached_tokens') or usage.get('cache_read_input_tokens') or 0),
        'reasoning_tokens': int(completion_details.get('reasoning_tokens') or 0),
        'total_tokens': int(usage.get('total_tokens') or prompt + completion),
    }
