"""Plugin manifests and the permission vocabulary.

A manifest is data. It names what the plugin contributes, which permissions it needs and which
API version it was written for; the host validates all three before a single handler is reached.
"""

import re
from dataclasses import dataclass, field

API_VERSION = 1

PLUGIN_ID_RE = re.compile(r'^[a-z][a-z0-9._-]{2,63}$')
VERSION_RE = re.compile(r'^\d+\.\d+\.\d+$')

PERMISSIONS = frozenset(
    {
        'read:project',
        'read:canvas',
        'read:dataset',
        'read:run',
        'read:docs',
        'read:code',
        'read:web',
        'net:http',
        'provider:custom',
        'code:execute',
    }
)

KINDS = frozenset({'skill-pack', 'provider-pack', 'tool-pack', 'code'})

CONTRIBUTIONS = frozenset({'skills', 'providers', 'tools', 'ui'})


@dataclass(frozen=True)
class Manifest:
    id: str
    name: str
    version: str
    kind: str
    api: int = API_VERSION
    permissions: frozenset = frozenset()
    skills: tuple = ()
    providers: tuple = ()
    tools: tuple = ()
    ui: tuple = ()
    entry: str = ''
    description: str = ''
    raw: dict = field(default_factory=dict, compare=False)

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'version': self.version,
            'kind': self.kind,
            'api': self.api,
            'permissions': sorted(self.permissions),
            'skills': list(self.skills),
            'providers': list(self.providers),
            'tools': list(self.tools),
            'ui': list(self.ui),
            'entry': self.entry,
            'description': self.description,
        }


def validate_manifest(payload) -> Manifest:
    if not isinstance(payload, dict):
        raise ValueError('manifest must be an object')
    plugin_id = str(payload.get('id') or '').strip()
    if not PLUGIN_ID_RE.match(plugin_id):
        raise ValueError(f'invalid plugin id: {plugin_id or "(empty)"}')
    name = str(payload.get('name') or plugin_id).strip()
    version = str(payload.get('version') or '').strip()
    if not VERSION_RE.match(version):
        raise ValueError('version must look like 1.2.3')
    kind = str(payload.get('kind') or 'skill-pack').strip()
    if kind not in KINDS:
        raise ValueError(f'unknown plugin kind: {kind}')
    api = int(payload.get('api') or payload.get('api_version') or API_VERSION)
    if api != API_VERSION:
        raise ValueError(f'unsupported plugin API {api}')
    permissions = frozenset(str(item) for item in payload.get('permissions') or ())
    unknown = permissions - PERMISSIONS
    if unknown:
        raise ValueError(f'unknown permission(s): {", ".join(sorted(unknown))}')
    if kind == 'code' and 'code:execute' not in permissions:
        raise ValueError('a code plugin must request code:execute')
    if kind == 'provider-pack' and 'provider:custom' not in permissions:
        raise ValueError('a provider pack must request provider:custom')
    if kind == 'tool-pack' and 'net:http' not in permissions:
        raise ValueError('a tool pack must request net:http')
    return Manifest(
        id=plugin_id,
        name=name,
        version=version,
        kind=kind,
        api=api,
        permissions=permissions,
        skills=tuple(payload.get('skills') or ()),
        providers=tuple(payload.get('providers') or ()),
        tools=tuple(payload.get('tools') or ()),
        ui=tuple(payload.get('ui') or ()),
        entry=str(payload.get('entry') or ''),
        description=str(payload.get('description') or ''),
        raw=dict(payload),
    )
