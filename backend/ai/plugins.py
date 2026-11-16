"""Plugin host: install, list, enable and uninstall AI extensions.

The built-in modules register into the same typed registry as user plugins, so a provider, tool or
skill has one lifecycle. Declarative plugins are data; a local code plugin may add Python
registrations, but only on a local/desktop host and only for an administrator. Cloud mode refuses
that kind by name rather than pretending the code did not run.
"""

import importlib.util
import json
import os
import re
from urllib.parse import urlparse

import requests
from core.config import Config
from extensions import API_VERSION, HOST, validate_manifest
from runtime import account_context, paths

from ai import skills, store, tools
from ai.errors import AIError
from ai.providers import PROVIDERS
from ai.providers.openai_compat import OpenAICompatibleProvider
from ai.types import CAPABILITIES, ModelSpec, ProviderSpec, ToolSpec

BUILTIN_PLUGINS = (
    {
        'id': 'core.providers',
        'name': 'Core providers',
        'version': '1.0.0',
        'kind': 'provider-pack',
        'api': API_VERSION,
        'permissions': ['provider:custom'],
        'description': 'DeepSeek, OpenCode Go, OpenRouter and Ollama.',
        'builtin': True,
    },
    {
        'id': 'core.tools',
        'name': 'Core read-only tools',
        'version': '1.0.0',
        'kind': 'tool-pack',
        'api': API_VERSION,
        'permissions': ['read:project', 'read:dataset', 'read:run', 'read:docs'],
        'description': 'Project facts, datasets, runs, charts and docs.',
        'builtin': True,
    },
    {
        'id': 'core.skills',
        'name': 'Core skills',
        'version': '1.0.0',
        'kind': 'skill-pack',
        'api': API_VERSION,
        'permissions': ['read:project', 'read:dataset', 'read:run', 'read:docs'],
        'description': (
            'Project guide, crawl advisor, diagnosis, analysis, workflow, charts, report, research and developer.'
        ),
        'builtin': True,
    },
    {
        'id': 'core.ui',
        'name': 'Core workspace UI',
        'version': '1.0.0',
        'kind': 'skill-pack',
        'api': API_VERSION,
        'permissions': [],
        'description': 'Chat, sessions, agent trace, questions, artifacts and the skill studio.',
        'builtin': True,
    },
)

_DYNAMIC: dict[str, dict] = {}


def register_builtin() -> None:
    """Populate the host with the product's own contributions. Idempotent per import."""
    for provider in PROVIDERS.values():
        if HOST.get('providers', provider.spec.id) is None:
            HOST.register('providers', provider.spec.id, provider, 'core.providers')
    for tool in tools.TOOLS.values():
        if HOST.get('tools', tool.name) is None:
            HOST.register('tools', tool.name, tool, 'core.tools')
    for skill in skills.BUILTIN.values():
        if HOST.get('skills', skill.id) is None:
            HOST.register('skills', skill.id, skill, 'core.skills')


def public_plugins() -> list:
    stored = {row['id']: row for row in store.list_plugins()}
    out = []
    for manifest in BUILTIN_PLUGINS:
        out.append({**manifest, 'enabled': True, 'source': 'builtin'})
    for plugin_id, row in stored.items():
        payload = row.get('manifest') or {}
        if not isinstance(payload, dict):
            payload = {}
        out.append(
            {
                **payload,
                'id': plugin_id,
                'enabled': bool(row.get('enabled')),
                'source': row.get('source') or 'user',
                'permissions': row.get('permissions') or payload.get('permissions') or [],
            }
        )
    return sorted(out, key=lambda item: (item.get('source') != 'builtin', item.get('id') or ''))


def _allowed_host(url: str, hosts: list) -> bool:
    parsed = urlparse(str(url or ''))
    if parsed.scheme not in ('https', 'http'):
        return False
    host = (parsed.hostname or '').lower()
    if not host:
        return False
    allowed = {str(item).lower() for item in hosts}
    return host in allowed or any(host.endswith('.' + item) for item in allowed)


def _http_tool(spec: dict, plugin_id: str):
    name = str(spec.get('name') or '').strip()
    if not re.match(r'^[a-z][a-z0-9_]{2,48}$', name):
        raise ValueError(f'invalid tool name {name!r}')
    hosts = [str(item) for item in spec.get('allowed_hosts') or ()]
    if not hosts:
        raise ValueError(f'tool {name} needs allowed_hosts')
    method = str(spec.get('method') or 'GET').upper()
    url = str(spec.get('url') or '')
    description = str(spec.get('description') or '')
    parameters = (
        spec.get('parameters') if isinstance(spec.get('parameters'), dict) else {'type': 'object', 'properties': {}}
    )

    def handler(args: dict, _ctx: dict) -> dict:
        target = url
        for key, value in (args or {}).items():
            target = target.replace('{' + str(key) + '}', str(value))
        if not _allowed_host(target, hosts):
            raise AIError('ai.toolRefused', kind='bad_request', tool=name, reason='host is not in allowed_hosts')
        try:
            if method == 'GET':
                response = requests.get(target, timeout=20)
            else:
                response = requests.post(target, json=args, timeout=20)
        except requests.RequestException as exc:
            raise AIError('ai.toolRefused', kind='network', tool=name, reason=str(exc)[:200]) from exc
        text = response.text[:20000]
        return {'status': response.status_code, 'body': text, 'truncated': len(response.text) > 20000}

    tool = ToolSpec(name, description, parameters, permission='net:http', handler=handler)
    tools.TOOLS[name] = tool
    HOST.register('tools', name, tool, f'plugin:{plugin_id}')
    return tool


def _provider_pack(spec: dict, plugin_id: str):
    provider_id = str(spec.get('id') or '').strip()
    if not re.match(r'^[a-z][a-z0-9_]{2,48}$', provider_id):
        raise ValueError(f'invalid provider id {provider_id!r}')
    if provider_id in PROVIDERS:
        raise ValueError(f'provider {provider_id} already exists')
    models = []
    for item in spec.get('models') or ():
        model_id = str(item.get('id') or '').strip() if isinstance(item, dict) else str(item).strip()
        if not model_id:
            continue
        models.append(
            ModelSpec(
                model_id,
                str(item.get('label') or model_id),
                int(item.get('max_context') or 128000),
                frozenset(item.get('capabilities') or ()),
            )
        )
    if not models:
        raise ValueError(f'provider {provider_id} needs at least one model')
    capabilities = frozenset(str(item) for item in spec.get('capabilities') or () if str(item) in CAPABILITIES)
    provider_spec = ProviderSpec(
        id=provider_id,
        label_key=f'plugin.{plugin_id}.{provider_id}.label',
        notes_key=f'plugin.{plugin_id}.{provider_id}.note',
        protocol='openai',
        base_url=str(spec.get('base_url') or ''),
        models=tuple(models),
        requires_key=bool(spec.get('requires_key', True)),
        capabilities=capabilities,
        models_url=str(spec.get('models_url') or ''),
    )
    provider = OpenAICompatibleProvider(provider_spec, user_agent='CaiXiHui-AI/1.0')
    PROVIDERS[provider_id] = provider
    HOST.register('providers', provider_id, provider, f'plugin:{plugin_id}')
    return provider


def _code_plugin(manifest) -> None:
    if Config.CLOUD_MODE:
        raise AIError('ai.pluginCloudCode', kind='capability')
    account = account_context.current()
    if account is not None and not account.is_admin:
        raise AIError('ai.pluginCloudCode', kind='capability')
    entry = os.path.abspath(os.path.join(paths.active().ai_plugins_dir, manifest.entry or 'plugin.py'))
    root = os.path.abspath(paths.active().ai_plugins_dir)
    if not entry.startswith(root + os.sep):
        raise AIError('ai.pluginBadManifest', kind='bad_request', reason='entry escapes the plugin directory')
    if not os.path.isfile(entry):
        raise AIError('ai.pluginBadManifest', kind='bad_request', reason=f'entry not found: {manifest.entry}')
    spec = importlib.util.spec_from_file_location(f'cai_xi_hui_plugin_{manifest.id.replace(".", "_")}', entry)
    if spec is None or spec.loader is None:
        raise AIError('ai.pluginBadManifest', kind='bad_request', reason='entry cannot be loaded')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    register = getattr(module, 'register', None)
    if not callable(register):
        raise AIError('ai.pluginBadManifest', kind='bad_request', reason='code plugin needs register(registry)')
    module.register(_CodeApi(manifest.id))


class _CodeApi:
    """The narrow surface a local code plugin receives; it cannot reach Flask or the account tree."""

    def __init__(self, plugin_id: str):
        self.plugin_id = plugin_id

    def add_tool(self, spec: ToolSpec) -> None:
        tools.TOOLS[spec.name] = spec
        HOST.register('tools', spec.name, spec, f'plugin:{self.plugin_id}')

    def add_provider(self, provider) -> None:
        PROVIDERS[provider.spec.id] = provider
        HOST.register('providers', provider.spec.id, provider, f'plugin:{self.plugin_id}')

    def add_skill(self, skill) -> None:
        skills.BUILTIN[skill.id] = skill
        HOST.register('skills', skill.id, skill, f'plugin:{self.plugin_id}')


def install(payload: dict) -> dict:
    manifest = validate_manifest(payload)
    existing = store.get_plugin(manifest.id)
    if existing is not None:
        raise AIError('ai.pluginConflict', kind='bad_request', plugin=manifest.id)
    installed_skills = []
    if manifest.kind == 'skill-pack':
        for item in manifest.skills:
            if not isinstance(item, dict):
                raise AIError('ai.pluginBadManifest', kind='bad_request', reason='a skill entry must be an object')
            item = {**item}
            item.setdefault('id', f'{manifest.id}.{item.get("name", "skill")}'.lower().replace(' ', '_'))
            skills.save_user_skill(item)
            installed_skills.append(str(item['id']))
    elif manifest.kind == 'provider-pack':
        for item in manifest.providers:
            _provider_pack(item, manifest.id)
    elif manifest.kind == 'tool-pack':
        for item in manifest.tools:
            _http_tool(item, manifest.id)
    elif manifest.kind == 'code':
        _code_plugin(manifest)
    for item in manifest.ui:
        HOST.register('ui_commands', f'{manifest.id}.{item.get("id")}', item, f'plugin:{manifest.id}')
    _DYNAMIC[manifest.id] = {'kind': manifest.kind, 'skills': installed_skills}
    row = store.save_plugin(
        manifest.to_dict(), sorted(manifest.permissions), source='code' if manifest.kind == 'code' else 'user'
    )
    return {**manifest.to_dict(), 'enabled': True, 'source': row.get('source') or 'user'}


def set_enabled(plugin_id: str, enabled: bool) -> bool:
    row = store.get_plugin(plugin_id)
    if row is None:
        raise AIError('ai.pluginNotFound', kind='not_found', plugin=plugin_id)
    if not store.set_plugin_enabled(plugin_id, enabled):
        raise AIError('ai.pluginNotFound', kind='not_found', plugin=plugin_id)
    if not enabled:
        HOST.unregister_owner(f'plugin:{plugin_id}')
        dynamic = _DYNAMIC.pop(plugin_id, {})
        for skill_id in dynamic.get('skills') or ():
            if skill_id:
                store.delete_user_skill(skill_id)
    return True


def uninstall(plugin_id: str) -> bool:
    row = store.get_plugin(plugin_id)
    if row is None:
        raise AIError('ai.pluginNotFound', kind='not_found', plugin=plugin_id)
    HOST.unregister_owner(f'plugin:{plugin_id}')
    dynamic = _DYNAMIC.pop(plugin_id, {})
    for skill_id in dynamic.get('skills') or ():
        if skill_id:
            store.delete_user_skill(skill_id)
    return store.delete_plugin(plugin_id)


def register_stored_plugins() -> None:
    """Re-register enabled declarative plugins on first use after a restart."""
    for row in store.list_plugins():
        if not row.get('enabled'):
            continue
        payload = row.get('manifest')
        if not isinstance(payload, dict):
            continue
        plugin_id = str(payload.get('id') or row.get('id') or '')
        if plugin_id in _DYNAMIC or not plugin_id:
            continue
        try:
            manifest = validate_manifest(payload)
        except ValueError:
            continue
        try:
            if manifest.kind == 'provider-pack':
                for item in manifest.providers:
                    _provider_pack(item, plugin_id)
            elif manifest.kind == 'tool-pack':
                for item in manifest.tools:
                    _http_tool(item, plugin_id)
            elif manifest.kind == 'code':
                _code_plugin(manifest)
        except (ValueError, AIError):
            continue
        _DYNAMIC[plugin_id] = {
            'kind': manifest.kind,
            'skills': [str(item.get('id') or '') for item in manifest.skills if isinstance(item, dict)],
        }


def manifest_json(plugin_id: str) -> str:
    row = store.get_plugin(plugin_id)
    if row is None:
        raise AIError('ai.pluginNotFound', kind='not_found', plugin=plugin_id)
    return json.dumps(row.get('manifest') or {}, ensure_ascii=False, indent=2)
