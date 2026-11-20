"""Plugin host: install, list, enable and uninstall AI extensions.

The built-in modules register into the same typed registry as user plugins, so a provider, tool or
skill has one lifecycle. Declarative plugins are data; a local code plugin may add Python
registrations, but only on a local/desktop host and only for an administrator. Cloud mode refuses
that kind by name rather than pretending the code did not run.

A provider/tool/code pack registers into the process-wide tables every account's turn reads
(``PROVIDERS``/``tools.TOOLS``/``skills.BUILTIN``), so installing one is a machine-level write and
the route refuses a non-administrator when the account registry is on (``api/ai.py``). A skill pack
writes only the caller's own skill library and is per-account as before. Enabling and disabling are
symmetric: both add and remove the contributions from the registry AND from those tables, because
``tools.execute`` reads the table, not the registry.
"""

import importlib.util
import json
import os
import re
from urllib.parse import urljoin, urlparse

import requests
from core.config import Config
from extensions import API_VERSION, HOST, validate_manifest
from runtime import account_context, paths

from ai import scopes, skills, store, tools
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

#: How many redirect hops an HTTP plugin tool may follow before it is refused by name. Bounds a
#: redirect loop and keeps a chain of allowed hosts from growing the request without end.
_MAX_REDIRECTS = 5


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
        # requests follows redirects by default, which would let an allowed host bounce this tool
        # into an internal address the allowlist never approved. Drive the hops ourselves: every
        # Location is resolved to an absolute URL and re-checked, and a loop is bounded by _MAX_REDIRECTS.
        try:
            hops = 0
            while True:
                if method == 'GET':
                    response = requests.get(target, timeout=20, allow_redirects=False)
                else:
                    response = requests.post(target, json=args, timeout=20, allow_redirects=False)
                location = response.headers.get('Location')
                if not location or response.status_code not in (301, 302, 303, 307, 308):
                    break
                if hops >= _MAX_REDIRECTS:
                    raise AIError('ai.toolRefused', kind='bad_request', tool=name, reason='too many redirects')
                hops += 1
                target = urljoin(target, location)
                if not _allowed_host(target, hosts):
                    raise AIError(
                        'ai.toolRefused', kind='bad_request', tool=name, reason='redirect host is not in allowed_hosts'
                    )
        except requests.RequestException as exc:
            raise AIError('ai.toolRefused', kind='network', tool=name, reason=str(exc)[:200]) from exc
        text = response.text[:20000]
        return {'status': response.status_code, 'body': text, 'truncated': len(response.text) > 20000}

    tool = ToolSpec(name, description, parameters, permission='net:http', handler=handler)
    # The duplicate check is the REGISTRY's, and it runs BEFORE the product table is touched.
    # ``tools.execute`` resolves a call from ``tools.TOOLS``, never from the registry, so
    # assigning first meant a manifest the install route then REFUSED (400) had already
    # replaced the built-in tool of that name for every later turn until restart.
    if HOST.get('tools', name) is not None or name in tools.TOOLS:
        raise ValueError(f'tool {name} already exists')
    HOST.register('tools', name, tool, f'plugin:{plugin_id}')
    tools.TOOLS[name] = tool
    scopes.claim('tools', name, account_context.scope_key())
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
    # Registry first, product table second — the same order as ``_http_tool`` and for the
    # same reason: a refused duplicate must leave nothing behind.
    if HOST.get('providers', provider_id) is not None:
        raise ValueError(f'provider {provider_id} already exists')
    HOST.register('providers', provider_id, provider, f'plugin:{plugin_id}')
    PROVIDERS[provider_id] = provider
    scopes.claim('providers', provider_id, account_context.scope_key())
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
        owner = f'plugin:{self.plugin_id}'
        if HOST.get('tools', spec.name) is not None:
            raise ValueError(f'tool {spec.name} already exists')
        HOST.register('tools', spec.name, spec, owner)
        tools.TOOLS[spec.name] = spec
        scopes.claim('tools', spec.name, account_context.scope_key())

    def add_provider(self, provider) -> None:
        owner = f'plugin:{self.plugin_id}'
        if HOST.get('providers', provider.spec.id) is not None:
            raise ValueError(f'provider {provider.spec.id} already exists')
        HOST.register('providers', provider.spec.id, provider, owner)
        PROVIDERS[provider.spec.id] = provider
        scopes.claim('providers', provider.spec.id, account_context.scope_key())

    def add_skill(self, skill) -> None:
        owner = f'plugin:{self.plugin_id}'
        if HOST.get('skills', skill.id) is not None:
            raise ValueError(f'skill {skill.id} already exists')
        HOST.register('skills', skill.id, skill, owner)
        skills.BUILTIN[skill.id] = skill
        scopes.claim('skills', skill.id, account_context.scope_key())


#: The product table each contribution kind actually lives in. The registry is the index; these
#: are what ``tools.execute``, ``get_provider`` and the skill list read.
_TABLES = {
    'tools': lambda: tools.TOOLS,
    'providers': lambda: PROVIDERS,
    'skills': lambda: skills.BUILTIN,
}


def _release(plugin_id: str) -> None:
    """Remove every contribution this plugin added, from the registry AND the product tables.

    Unregistering only from the registry used to leave the object where the code reads it:
    ``tools.execute`` resolved the disabled tool anyway, and the next ``register_builtin()``
    re-registered the leftover as ``core.tools`` — a pack the user deleted came back as a
    built-in that ``uninstall`` could no longer reach.
    """
    owner = f'plugin:{plugin_id}'
    for kind, table_of in _TABLES.items():
        for name in HOST.owned(kind, owner):
            table = table_of()
            if table.get(name) is HOST.get(kind, name):
                table.pop(name, None)
            scopes.release(kind, name)
    HOST.unregister_owner(owner)


def _apply(manifest) -> list:
    """Register one validated manifest's contributions; answer the user-skill ids it created.

    Every step registers into the registry before the product table, so a refusal part-way
    leaves nothing callable behind; the caller wraps this in :func:`_release` for that case.
    """
    created = []
    if manifest.kind == 'skill-pack':
        for item in manifest.skills:
            if not isinstance(item, dict):
                raise AIError('ai.pluginBadManifest', kind='bad_request', reason='a skill entry must be an object')
            item = {**item}
            item.setdefault('id', f'{manifest.id}.{item.get("name", "skill")}'.lower().replace(' ', '_'))
            skills.save_user_skill(item)
            created.append(str(item['id']))
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
    return created


def install(payload: dict) -> dict:
    manifest = validate_manifest(payload)
    existing = store.get_plugin(manifest.id)
    if existing is not None:
        raise AIError('ai.pluginConflict', kind='bad_request', plugin=manifest.id)
    # The contribution registry is PROCESS-WIDE and releases by the bare ``plugin:<id>`` owner.
    # A second account installing a different pack under the same id would therefore have its
    # uninstall/disable remove the FIRST account's contributions too. Ids are process-wide names:
    # refuse a colliding install before any contribution is registered.
    owner = f'plugin:{manifest.id}'
    if manifest.id in _DYNAMIC or any(HOST.owned(kind, owner) for kind in HOST.KINDS):
        raise AIError('ai.pluginConflict', kind='bad_request', plugin=manifest.id)
    try:
        installed_skills = _apply(manifest)
    except BaseException:
        # A manifest that installs three tools and fails on the fourth used to leave two
        # callable — and, for the duplicate case, one built-in tool already replaced.
        _release(manifest.id)
        raise
    _DYNAMIC[manifest.id] = {'kind': manifest.kind, 'skills': installed_skills}
    row = store.save_plugin(
        manifest.to_dict(), sorted(manifest.permissions), source='code' if manifest.kind == 'code' else 'user'
    )
    return {**manifest.to_dict(), 'enabled': True, 'source': row.get('source') or 'user'}


def visible_tool(name: str) -> bool:
    """Whether the signed-in account may see and call this tool (see ``ai.scopes``)."""
    return scopes.visible('tools', name, account_context.scope_key())


def _manifest_of(row: dict):
    """The validated manifest a stored row carries, or a named refusal."""
    payload = row.get('manifest')
    if not isinstance(payload, dict):
        raise AIError('ai.pluginBadManifest', kind='bad_request', plugin=row.get('id') or '')
    return validate_manifest(payload)


def set_enabled(plugin_id: str, enabled: bool) -> bool:
    row = store.get_plugin(plugin_id)
    if row is None:
        raise AIError('ai.pluginNotFound', kind='not_found', plugin=plugin_id)
    if not enabled:
        # Release the CONTRIBUTIONS, not just the registry entry: ``tools.execute`` reads
        # ``tools.TOOLS``, so a "disabled" tool stayed callable, and the next bootstrap
        # adopted the leftover as a core contribution.
        _release(plugin_id)
        dynamic = _DYNAMIC.pop(plugin_id, {})
        for skill_id in dynamic.get('skills') or ():
            if skill_id:
                store.delete_user_skill(skill_id)
        if not store.set_plugin_enabled(plugin_id, False):
            raise AIError('ai.pluginNotFound', kind='not_found', plugin=plugin_id)
        return True
    # Re-enabling has to re-register: the disable path removed the contributions, so the
    # switch used to be one-way — on again, and nothing was offered any more.
    if plugin_id not in _DYNAMIC:
        manifest = _manifest_of(row)
        created = _apply(manifest)
        _DYNAMIC[plugin_id] = {'kind': manifest.kind, 'skills': created}
    if not store.set_plugin_enabled(plugin_id, True):
        raise AIError('ai.pluginNotFound', kind='not_found', plugin=plugin_id)
    return True


def uninstall(plugin_id: str) -> bool:
    row = store.get_plugin(plugin_id)
    if row is None:
        raise AIError('ai.pluginNotFound', kind='not_found', plugin=plugin_id)
    _release(plugin_id)
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
            created = _apply(manifest)
        except (ValueError, AIError):
            # A half-applied pack (three tools of four) must not stay callable.
            _release(plugin_id)
            continue
        _DYNAMIC[plugin_id] = {'kind': manifest.kind, 'skills': created}


def manifest_json(plugin_id: str) -> str:
    row = store.get_plugin(plugin_id)
    if row is None:
        raise AIError('ai.pluginNotFound', kind='not_found', plugin=plugin_id)
    return json.dumps(row.get('manifest') or {}, ensure_ascii=False, indent=2)
