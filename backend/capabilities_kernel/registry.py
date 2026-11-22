"""Discovery for capability manifests: one directory entry per capability.

``backend/capabilities_kernel/<kind>/<id>.py`` declares ``MANIFEST``. The package form
``backend/capabilities_kernel/<kind>/<id>/manifest.py`` is the migration target because a capability
also owns its executor, examples and knowledge beside it; both forms are accepted while the tree
moves, and a capability declared in both is refused by name.

The registry is the only reader of the tree. Ordered, duplicate-free, and lazy: asking for one
manifest imports one module, and an executor is imported only when ``register_node_executors`` asks
for its handler. That is what keeps ``nodes.catalog`` light enough to run on the DAG-parse path.
"""

from __future__ import annotations

import importlib
from pathlib import Path

from capabilities_kernel.manifest import API_VERSION, KINDS, Manifest

#: The capability tree. Tests point this at a temporary directory to prove duplicate/id/version
#: refusals without writing into the checkout.
KERNEL_ROOT = Path(__file__).resolve().parent

#: Directory name per kind. A kind is a singular manifest vocabulary (``node``), the tree is the
#: plural collection (``nodes``) — the same shape ``capabilities/platforms`` already uses.
KIND_DIRS = {
    'node': 'nodes',
    'operator': 'operators',
    'chart': 'charts',
    'platform': 'platforms',
    'tool': 'tools',
    'skill': 'skills',
}

_CACHE: dict[str, Manifest] = {}
_ALL: dict[str, tuple[Manifest, ...]] = {}


class ManifestError(ValueError):
    """A capability tree that cannot answer honestly: duplicate id, wrong version, missing handler."""


def _root(kind: str) -> Path:
    if kind not in KINDS:
        raise ManifestError(f'unknown capability kind {kind!r}; known kinds: {", ".join(KINDS)}')
    return KERNEL_ROOT / KIND_DIRS[kind]


def describe(kind: str) -> dict[str, tuple[str, str]]:
    """``{id: (declaring path, module name)}`` for *kind*, without importing anything.

    The path check is also the duplicate check: an ``<id>.py`` beside an ``<id>/manifest.py`` is the
    same capability declared twice, and the second home would silently win for whichever caller
    imported first. The id must equal its directory/module name so the tree itself is the index.
    """
    root = _root(kind)
    if not root.is_dir():
        return {}
    tree = KIND_DIRS[kind]
    found: dict[str, tuple[str, str]] = {}
    for entry in sorted(root.iterdir()):
        if entry.name.startswith(('_', '.')) or entry.name == '__pycache__':
            continue
        if entry.is_file() and entry.suffix == '.py':
            ident = entry.stem
            module = f'capabilities_kernel.{tree}.{ident}'
        elif entry.is_dir() and (entry / 'manifest.py').is_file():
            ident = entry.name
            module = f'capabilities_kernel.{tree}.{ident}.manifest'
        else:
            continue
        if ident in found:
            raise ManifestError(
                f'capability {kind}:{ident} is declared twice: {found[ident][0]} and {entry}',
            )
        found[ident] = (str(entry), module)
    return found


def _import(module: str) -> Manifest:
    imported = importlib.import_module(module)
    manifest = getattr(imported, 'MANIFEST', None)
    if not isinstance(manifest, Manifest):
        raise ManifestError(f'{module} does not declare a capabilities_kernel.manifest.Manifest as MANIFEST')
    return manifest


def _load(kind: str, ident: str, module: str) -> Manifest:
    manifest = _import(module)
    if manifest.api_version != API_VERSION:
        raise ManifestError(
            f'capability {kind}:{ident} declares api_version {manifest.api_version}; '
            f'this kernel speaks {API_VERSION} — migrate the manifest, do not reinterpret it',
        )
    if manifest.identity.kind != kind:
        raise ManifestError(f'{module} declares kind {manifest.identity.kind!r} under the {kind!r} tree')
    if manifest.identity.id != ident:
        raise ManifestError(f'{module} declares id {manifest.identity.id!r}; its directory is {ident!r}')
    problems = manifest.problems()
    if problems:
        raise ManifestError(f'capability {kind}:{ident} is incomplete: ' + '; '.join(problems))
    return manifest


def _cached_load(kind: str, ident: str, module: str) -> Manifest:
    cached = _CACHE.get(module)
    if cached is None:
        cached = _load(kind, ident, module)
        _CACHE[module] = cached
    return cached


def manifests(kind: str) -> tuple[Manifest, ...]:
    """Every manifest of *kind*, ordered by the slot it declares, then by id."""
    if kind not in _ALL:
        loaded = [_cached_load(kind, ident, module) for ident, (_path, module) in describe(kind).items()]
        _ALL[kind] = tuple(sorted(loaded, key=lambda item: (item.identity.order, item.identity.id)))
    return _ALL[kind]


def get(kind: str, ident: str) -> Manifest | None:
    """One manifest by id, or ``None`` — the caller words the refusal."""
    module = describe(kind).get(ident)
    if module is None:
        return None
    return _cached_load(kind, ident, module[1])


def manifest_for_node(node_type: str) -> Manifest | None:
    wanted = str(node_type or '')
    for manifest in manifests('node'):
        if manifest.identity.id == wanted:
            return manifest
    return None


def resolve(reference: str):
    """Import a ``module:function`` reference. A malformed or missing target is named, never guessed."""
    module_name, _, attribute = str(reference or '').partition(':')
    if not module_name or not attribute:
        raise ManifestError(f'handler {reference!r} is not module:function')
    imported = importlib.import_module(module_name)
    try:
        target = getattr(imported, attribute)
    except AttributeError as exc:
        raise ManifestError(f'handler {reference!r}: {module_name} has no {attribute!r}') from exc
    return target


def node_entries() -> tuple[dict, ...]:
    """The node catalogue projection ``nodes.catalog`` builds its plugins from."""
    return tuple(
        {
            'type': manifest.identity.id,
            'label_key': manifest.identity.title_key,
            'category': manifest.identity.category,
            'rows': manifest.ports.rows,
            'quiet': manifest.execution.quiet,
            'order': manifest.identity.order,
            'defaults_from': manifest.ui.defaults_from,
        }
        for manifest in manifests('node')
    )


def node_defaults() -> dict[str, dict]:
    """Seed parameters for every migrated node type whose defaults are its own.

    A type that declares ``ui.defaults_from`` derives them where its facts live (the source node's
    form is the platform matrix), so it has no entry here and the API answers ``defaultsFrom``.
    """
    return {
        manifest.identity.id: manifest.defaults() for manifest in manifests('node') if not manifest.ui.defaults_from
    }


def register_node_executors() -> None:
    """Register every migrated node's ``run`` in ``nodes.registry``.

    Called by ``nodes.registry.load_builtin_executors`` after the legacy executor package has
    registered its own types, so ``registered_types() == catalog.NODE_TYPES`` keeps holding while
    the tree is half-migrated.
    """
    from nodes import registry as node_registry

    for manifest in manifests('node'):
        handler = resolve(manifest.execution.handler)
        if not callable(handler):
            raise ManifestError(
                f'capability node:{manifest.identity.id}: handler {manifest.execution.handler!r} is not callable',
            )
        node_registry.register(manifest.identity.id, handler)


def reset_for_tests() -> None:
    """Drop both caches; the next read re-discovers the tree. Manifest modules stay imported."""
    _CACHE.clear()
    _ALL.clear()
