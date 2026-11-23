"""Every declared dependency carries an exact ``==`` version.

Unpinned direct dependencies made the green suite a statement about the day it ran: pytest
moved 9.1.1→9.2.0 mid-day on 2026-10-28 and class-scoped fixtures stopped registering, while
CI installs whatever the index serves that morning. The desktop runtime file was already
pinned ("keep them pinned so two builders produce the same folder"), so this gate extends the
same rule to the two source requirement files and keeps the shared names in step with
``desktop/requirements-runtime.txt``.

The parser is deliberately small: these files are hand-maintained lists of ``name==version``
(optionally with a PEP 508 marker), not a dependency language. An entry the parser cannot
read is a failure, because "we could not tell" is exactly the state this gate exists to make
impossible.

A package may appear twice when the markers select different platforms (onnxruntime is 1.31.0
on Windows/Linux and 1.19.2 on macOS, because 1.31 publishes an arm64-only macOS wheel). The
duplicate check is therefore per ``(name, marker)`` and the version comparison is per platform.

A dependency with no index release is pinned by a committed wheel under ``vendor/`` instead: the
line names the artifact, and the artifact's filename and METADATA must agree, so a rebuild that
forgets to replace the file (or a hand-renamed wheel) is a red gate rather than a mystery import.
"""

import ast
import re
import sys
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
REQUIREMENTS = REPO / 'requirements.txt'
OPTIONAL = REPO / 'requirements-optional.txt'
RUNTIME = REPO / 'desktop' / 'requirements-runtime.txt'
BUILD = REPO / 'desktop' / 'requirements-build.txt'
PLATFORMS = ('win32', 'darwin', 'linux')

#: ``name==1.2.3`` with an optional ``[extra]`` and an optional ``; marker``.
PINNED = re.compile(
    r'^(?P<name>[A-Za-z0-9_.-]+)(?:\[[^\]]*\])?==(?P<version>[A-Za-z0-9_.+-]+)\s*(?:;\s*(?P<marker>.+))?$'
)
_SYS_PLATFORM = re.compile(r'sys_platform\s*==\s*"([^"]+)"')
#: A committed wheel: ``vendor/<name>-<version>-py3-none-any.whl``, relative to the repository
#: root. ``pip`` resolves it against the working directory, which is why the file documents that
#: installs run from the root.
WHEEL = re.compile(r'^vendor/(?P<filename>[A-Za-z0-9_.+-]+\.whl)$')


def _lines(path: Path) -> list[tuple[int, str]]:
    """``(line number, text)`` for every entry line, comments and blanks dropped."""
    entries = []
    for number, raw in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
        text = raw.split('#', 1)[0].strip()
        if not text:
            continue
        entries.append((number, text))
    return entries


def _entries(path: Path) -> list[tuple[str, str, str]]:
    """``(name, version, marker)`` for every entry, refusing anything that is not an exact pin."""
    rows = []
    for number, text in _lines(path):
        if WHEEL.match(text):
            continue
        match = PINNED.match(text)
        assert match, f'{path.name}:{number} is not an exact pin: {text!r}'
        marker = (match.group('marker') or '').strip()
        if marker:
            # The parser only claims to understand the sys_platform marker used by this repo.
            assert _SYS_PLATFORM.search(marker), f'{path.name}:{number} has an unknown marker: {marker!r}'
        rows.append((match.group('name').lower().replace('_', '-'), match.group('version'), marker))
    return rows


def _wheel_entries(path: Path) -> list[tuple[int, str]]:
    """``(line number, filename)`` for every committed-wheel line in one requirements file."""
    rows = []
    for number, text in _lines(path):
        match = WHEEL.match(text)
        if match:
            rows.append((number, match.group('filename')))
    return rows


def _wheel_metadata(path: Path) -> tuple[str, str, set[str]]:
    """``(distribution name, version, importable top-level modules)`` from the wheel's own metadata."""
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        metadata = [name for name in names if name.endswith('.dist-info/METADATA')]
        assert len(metadata) == 1, f'{path.name} carries {len(metadata)} METADATA files'
        text = archive.read(metadata[0]).decode('utf-8')
    fields = {'Name': '', 'Version': ''}
    for line in text.splitlines():
        key, sep, value = line.partition(': ')
        if sep and key in fields:
            fields[key] = value.strip()
    assert fields['Name'] and fields['Version'], f'{path.name} METADATA declares no name/version'
    modules = {name[: -len('.py')] for name in names if '/' not in name and name.endswith('.py')}
    modules |= {name[: -len('/__init__.py')] for name in names if name.endswith('/__init__.py')}
    return fields['Name'], fields['Version'], modules


def _matches(marker: str, system: str) -> bool:
    if not marker:
        return True
    return any(platform == system for platform in _SYS_PLATFORM.findall(marker))


def _pins_for(path: Path, system: str) -> dict[str, str]:
    """Effective pins for one platform; a package selected twice is a defect."""
    pins = {}
    for name, version, marker in _entries(path):
        if not _matches(marker, system):
            continue
        assert name not in pins, f'{path.name} selects {name} twice on {system}'
        pins[name] = version
    return pins


def test_every_requirement_is_pinned():
    for path in (REQUIREMENTS, OPTIONAL, BUILD):
        rows = _entries(path)
        assert rows, f'{path.name} declares nothing'
        # A range or a bare name would have failed _entries; this second assertion names the
        # duplicate package+marker so a file that silently repeats an entry is noticed. The same
        # package may repeat with a different platform marker.
        assert len(rows) == len({(name, marker) for name, _version, marker in rows}), (
            f'{path.name} repeats a package for the same marker'
        )
        for system in PLATFORMS:
            assert _pins_for(path, system), f'{path.name} selects nothing on {system}'


#: Import name → distribution name, for the packages whose two spellings differ.
_IMPORT_NAMES = {
    'pil': 'pillow',
    'sklearn': 'scikit-learn',
    'sentence_transformers': 'sentence-transformers',
    'flask_cors': 'flask-cors',
    'webview': 'pywebview',
    'yaml': 'pyyaml',
}

#: Top-level packages of this repository, never third-party dependencies.
_LOCAL_PACKAGES = {
    'ai',
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


def test_every_vendored_wheel_is_declared_and_named_after_its_metadata():
    """The committed wheel's file IS the pin, so its name and METADATA must tell one story.

    A rebuild that writes a new version but leaves the old file (or a hand-renamed wheel) would
    otherwise install one thing while the requirements line claims another.
    """
    declared = {filename for _number, filename in _wheel_entries(REQUIREMENTS)}
    assert declared, 'requirements.txt declares no committed wheel'
    on_disk = {path.name for path in (REPO / 'vendor').glob('*.whl')}
    assert on_disk == declared, (
        f'vendor/ does not match requirements.txt: undeclared {sorted(on_disk - declared)}, '
        f'missing {sorted(declared - on_disk)}'
    )
    for filename in sorted(declared):
        name, version, modules = _wheel_metadata(REPO / 'vendor' / filename)
        expected = f'{name.replace("-", "_")}-{version}-py3-none-any.whl'
        assert filename == expected, f'vendor/{filename} holds {name} {version}, which would be named {expected}'
        assert modules, f'vendor/{filename} carries no importable top-level module'


def test_a_vendored_wheel_is_not_also_pinned_by_version():
    """One dependency, one declaration: a ``name==version`` line for the same distribution would
    let pip fetch a different artifact from the index while the vendored one sits unused."""
    vendored = {
        _wheel_metadata(REPO / 'vendor' / filename)[0].lower().replace('_', '-')
        for _number, filename in _wheel_entries(REQUIREMENTS)
    }
    for path in (REQUIREMENTS, OPTIONAL):
        pinned = {name for name, _version, _marker in _entries(path)}
        assert not (vendored & pinned), f'{path.name} pins {sorted(vendored & pinned)} twice'


def test_a_function_level_third_party_import_is_declared_for_the_runtime():
    """An import inside a function is invisible to the module-level dependency check.

    ``services/update.py`` imports ``cryptography`` inside ``verify_feed_signature``; the
    packaged runtime did not declare it, so enabling the signed-update trust root was the one
    configuration that could never update. This walks the backend AST and requires every
    non-stdlib, non-local module imported anywhere to be in the runtime or optional set.
    """
    declared = set()
    for path in (RUNTIME, OPTIONAL):
        declared.update(name for name, _version, _marker in _entries(path))
    imported = set()
    for path in (REPO / 'backend').rglob('*.py'):
        if any(part.startswith('.venv') or part == '__pycache__' for part in path.parts):
            continue
        tree = ast.parse(path.read_text(encoding='utf-8', errors='replace'), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split('.')[0])
    third_party = {
        _IMPORT_NAMES.get(name.lower(), name.lower().replace('_', '-'))
        for name in imported
        if name and name not in sys.stdlib_module_names and name not in _LOCAL_PACKAGES and not name.startswith('_')
    }
    missing = sorted(third_party - declared - {''})
    assert not missing, f'imported by backend code but not declared in the packaged runtime/optional set: {missing}'


def test_runtime_versions_match_the_source_requirements():
    """The frozen desktop app and a source install must answer with the same versions per OS.

    ``desktop/requirements-runtime.txt`` is shared by the Windows and macOS packages; markers keep
    the two onnxruntime builds apart. Comparing the flat last-wins map hid that split, so each
    platform's effective set is compared here.
    """
    for system in PLATFORMS:
        source = _pins_for(REQUIREMENTS, system)
        runtime = _pins_for(RUNTIME, system)
        shared = set(source) & set(runtime)
        assert shared, f'the runtime file shares no package with requirements.txt on {system}'
        mismatched = {name: (source[name], runtime[name]) for name in shared if source[name] != runtime[name]}
        assert not mismatched, (
            f'versions drifted between requirements.txt and desktop runtime on {system}: {mismatched}'
        )
