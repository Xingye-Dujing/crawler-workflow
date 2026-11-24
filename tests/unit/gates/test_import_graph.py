"""The import graph is the architecture: these tests read it instead of trusting a docstring.

Three rules, each one a defect that was actually present on 2026-11-24:

1. **Only the HTTP layer imports the HTTP layer.** ``services/analysis/params.py``,
   ``nodes/executors/*`` and ``engine/run.py`` imported ``api.http`` for a numeric parser, which
   meant a service could not run without Flask and the "services may not depend on api" sentence in
   ``docs/ARCHITECTURE.md`` was only a sentence. ``test_import_direction`` refuses it by name.
2. **Nothing imports ``app``.** ``runtime.settings`` imported the Flask app to update
   ``MAX_CONTENT_LENGTH`` — the inner layer reaching for the composition root. The root now
   registers a hook instead.
3. **No module is unreachable.** ``core/asset.py`` was a 116-line contract nobody imported while
   ``AGENTS.md`` called it "the shared identity of a node output"; 16 empty
   ``capabilities_kernel/nodes/<id>/__init__.py`` files were scaffolding for packages that are
   discovered by walking ``manifest.py``. ``test_no_dead_modules`` refuses both.

The reference set includes what a static import cannot see: ``module:function`` handler strings,
module-name literals inside a file that calls ``importlib.import_module``, ``__main__`` entry
points, and every ``capabilities_kernel/**/manifest.py`` (the registry discovers those by walking
the tree).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / 'backend'

#: Top-level packages that live under ``backend/``; anything else is the standard library or a
#: third-party import and not this gate's business.
BACKEND_PACKAGES = {
    'ai',
    'ai_host',
    'analyzers',
    'api',
    'app',
    'capabilities',
    'capabilities_kernel',
    'config',
    'core',
    'crawlers',
    'engine',
    'extensions',
    'i18n',
    'i18n_catalog',
    'nodes',
    'runtime',
    'scheduling',
    'services',
    'sessions',
}

#: ``core`` may only reach the standard library, the message catalogue, and these dated exceptions.
#: An exception that is no longer needed fails the gate, so this table cannot rot.
CORE_EXCEPTIONS: dict[str, dict[str, str]] = {
    'core.machine': {
        'services.components.manifest': (
            'W4: the installer-manifest branch of find_chrome/find_node/find_catbus_cli belongs to '
            'services/components/locate.py; moving it is a behaviour change for the crawler'
        ),
    },
}

#: Modules with no production importer, each with the fact that keeps it alive or the plan item
#: that will consume it. An entry that stops being an orphan fails the gate: exemptions are debt,
#: not furniture.
ORPHAN_EXEMPTIONS: dict[str, str] = {
    'core.asset': 'P2/R2: node output assets have no writer yet; wired in W2',
    'crawlers.platforms.hongguo.addon': 'mitmdump runs the file by path, it is never imported',
    'crawlers.platforms.instagram.dialogs': 'popup word list; W4 decides import-or-delete',
    'crawlers.platforms.youtube.dialogs': 'popup word list; W4 decides import-or-delete',
    'runtime.events': 'P1 contract, imported by its gate test only; W6 re-decides',
    'runtime.flags': 'P1 migration switches, read by its gate test only; W6 re-decides',
    'runtime.fsm': 'P1 contract, imported by its gate test only; W6 re-decides',
    'services.components.feed': 'the installer bootstrap imports it before the app exists',
    'services.update_worker': 'started as `--update-worker <job>` by the updater, never imported',
}


def module_name(path: Path, root: Path) -> str:
    """``backend/services/x/y.py`` → ``services.x.y`` (a package's ``__init__`` loses the name)."""
    parts = list(path.relative_to(root).with_suffix('').parts)
    if parts[-1] == '__init__':
        parts = parts[:-1]
    return '.'.join(parts)


def python_modules(root: Path) -> dict[str, Path]:
    return {module_name(path, root): path for path in root.rglob('*.py') if '__pycache__' not in path.parts}


def dynamic_module_names(path: Path) -> bool:
    """Whether this file imports modules by name (so a module-name literal is a reference)."""
    text = path.read_text(encoding='utf-8')
    return 'import_module' in text or '__import__' in text


def references(path: Path, root: Path, known: set[str]) -> set[str]:
    """Every backend module *path* names, through any of the ways Python can name one.

    Besides ``import``/``from`` this reads:

    * string literals containing ``:`` — a manifest handler is ``module:function``;
    * module-name literals in a file that calls ``importlib.import_module`` — the validator,
      previewer and comment-walk registries list their built-ins that way;
    * every ``capabilities_kernel.*.manifest`` module, because the registry discovers manifests by
      walking the tree rather than importing a table.
    """
    try:
        tree = ast.parse(path.read_text(encoding='utf-8'))
    except SyntaxError:
        return set()
    found: set[str] = set()
    dynamic = dynamic_module_names(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = module_name(path, root).split('.')
                if path.name != '__init__.py':
                    base = base[:-1]
                base = base[: len(base) - node.level + 1]
                target = '.'.join([*base, node.module]) if node.module else '.'.join(base)
            else:
                target = node.module or ''
            if not target:
                continue
            found.add(target)
            for alias in node.names:
                candidate = f'{target}.{alias.name}'
                if candidate in known:
                    found.add(candidate)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
            if ':' in text:
                found.add(text.split(':', 1)[0])
            if dynamic:
                found.add(text)
    return found


def edges(root: Path) -> dict[str, set[str]]:
    modules = python_modules(root)
    known = set(modules)
    return {
        name: {target for target in references(path, root, known) if target.split('.')[0] in BACKEND_PACKAGES}
        for name, path in modules.items()
    }


def offending_imports(root: Path, rule) -> list[str]:
    """``module:line target`` for every import edge *rule* rejects."""
    found: list[str] = []
    modules = python_modules(root)
    known = set(modules)
    for name, path in sorted(modules.items()):
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = module_name(path, root).split('.')
                    if path.name != '__init__.py':
                        base = base[:-1]
                    base = base[: len(base) - node.level + 1]
                    target = '.'.join([*base, node.module]) if node.module else '.'.join(base)
                else:
                    target = node.module or ''
                targets = [target] if target else []
            else:
                continue
            for target in targets:
                reason = rule(name, target, path, root, known)
                if reason:
                    found.append(f'{path.relative_to(root).as_posix()}:{node.lineno} {name} -> {target}: {reason}')
    return found


def _api_reason(name: str, target: str) -> str:
    """The HTTP-layer rule: only ``api/`` and the composition root may import ``api``."""
    if name == 'app' or name == 'api' or name.startswith('api.'):
        return ''
    if target == 'api' or target.startswith('api.'):
        return 'only api/ and app.py may import the HTTP layer'
    return ''


def _app_reason(target: str) -> str:
    if target == 'app' or target.startswith('app.'):
        return 'the composition root is never imported by a module it wires'
    return ''


def _core_reason(name: str, target: str, known: set[str]) -> str:
    """``core`` may not import another *backend* layer; third-party use is a separate contract.

    ``test_foundation_layering`` owns the heavy-library question (it enumerates what may be
    imported); this gate owns the direction, so only a backend package counts here.
    """
    if not (name == 'core' or name.startswith('core.')):
        return ''
    head = target.split('.')[0]
    if head not in BACKEND_PACKAGES or head in {'core', 'i18n', 'i18n_catalog'}:
        return ''
    if target in CORE_EXCEPTIONS.get(name, {}):
        return ''
    return 'core imports no other backend layer (see CORE_EXCEPTIONS for dated exceptions)'


class TestImportDirection:
    def test_only_the_http_layer_imports_the_http_layer(self):
        found = offending_imports(BACKEND, lambda name, target, *_: _api_reason(name, target))
        assert found == [], 'a service/node may not reach into api/: ' + '; '.join(found)

    def test_nothing_imports_app(self):
        found = offending_imports(BACKEND, lambda name, target, *_: _app_reason(target))
        assert found == [], 'import the owner (runtime.*) instead of app: ' + '; '.join(found)

    def test_core_stays_a_leaf(self):
        found = offending_imports(BACKEND, lambda name, target, _path, _root, known: _core_reason(name, target, known))
        assert found == [], 'core is the inner layer: ' + '; '.join(found)

    def test_every_core_exception_is_still_needed(self):
        """A stale exemption hides the next violation of the same shape."""
        used = {
            (name, target)
            for name, targets in CORE_EXCEPTIONS.items()
            for target in targets
            if target in edges(BACKEND).get(name, set())
        }
        declared = {(name, target) for name, targets in CORE_EXCEPTIONS.items() for target in targets}
        assert declared - used == set(), f'remove the stale exception: {sorted(declared - used)}'

    def test_the_gate_can_fail(self, tmp_path):
        """A synthetic ``services`` module importing ``api.http`` must be reported."""
        (tmp_path / 'api').mkdir()
        (tmp_path / 'api' / '__init__.py').write_text('', encoding='utf-8')
        (tmp_path / 'api' / 'http.py').write_text('VALUE = 1\n', encoding='utf-8')
        (tmp_path / 'services').mkdir()
        (tmp_path / 'services' / '__init__.py').write_text('', encoding='utf-8')
        (tmp_path / 'services' / 'bad.py').write_text('from api.http import VALUE\n', encoding='utf-8')
        found = offending_imports(tmp_path, lambda name, target, *_: _api_reason(name, target))
        assert found and 'services.bad' in found[0], found


class TestNoDeadModules:
    def test_every_module_is_reachable_or_declared(self):
        modules = python_modules(BACKEND)
        imported: set[str] = set()
        for _name, path in modules.items():
            for target in references(path, BACKEND, set(modules)):
                if target.split('.')[0] not in BACKEND_PACKAGES:
                    continue
                imported.add(target)
                parts = target.split('.')
                imported.update('.'.join(parts[:i]) for i in range(1, len(parts)))
        for path in (REPO / 'tools').rglob('*.py'):
            for target in references(path, REPO / 'tools', set(modules)):
                if target.split('.')[0] in BACKEND_PACKAGES:
                    imported.add(target)

        orphans = set()
        for name, path in modules.items():
            if name in imported or name == 'app':
                continue
            if name.endswith('.__init__') or name.endswith('.__main__'):
                continue
            if "__name__ == '__main__'" in path.read_text(encoding='utf-8'):
                continue
            if name.startswith('capabilities_kernel.') and name.endswith('.manifest'):
                continue
            orphans.add(name)

        undeclared = orphans - set(ORPHAN_EXEMPTIONS)
        assert undeclared == set(), (
            'no importer and no reason to stay: '
            + ', '.join(sorted(undeclared))
            + '. Delete it, wire it, or declare it in ORPHAN_EXEMPTIONS with the fact that keeps it'
        )
        stale = set(ORPHAN_EXEMPTIONS) - orphans
        assert stale == set(), f'remove the stale exemption (the module is live again): {sorted(stale)}'

    def test_the_gate_can_fail(self, tmp_path):
        (tmp_path / 'pkg').mkdir()
        (tmp_path / 'pkg' / '__init__.py').write_text('', encoding='utf-8')
        (tmp_path / 'pkg' / 'used.py').write_text('X = 1\n', encoding='utf-8')
        (tmp_path / 'pkg' / 'main.py').write_text('from pkg.used import X\n', encoding='utf-8')
        (tmp_path / 'pkg' / 'nobody.py').write_text('Y = 2\n', encoding='utf-8')
        modules = python_modules(tmp_path)
        imported = {target for name, path in modules.items() for target in references(path, tmp_path, set(modules))}
        assert 'pkg.nobody' in set(modules) - imported
