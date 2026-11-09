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
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
REQUIREMENTS = REPO / 'requirements.txt'
OPTIONAL = REPO / 'requirements-optional.txt'
RUNTIME = REPO / 'desktop' / 'requirements-runtime.txt'
PLATFORMS = ('win32', 'darwin', 'linux')

#: ``name==1.2.3`` with an optional ``[extra]`` and an optional ``; marker``.
PINNED = re.compile(
    r'^(?P<name>[A-Za-z0-9_.-]+)(?:\[[^\]]*\])?==(?P<version>[A-Za-z0-9_.+-]+)\s*(?:;\s*(?P<marker>.+))?$'
)
_SYS_PLATFORM = re.compile(r'sys_platform\s*==\s*"([^"]+)"')


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
        match = PINNED.match(text)
        assert match, f'{path.name}:{number} is not an exact pin: {text!r}'
        marker = (match.group('marker') or '').strip()
        if marker:
            # The parser only claims to understand the sys_platform marker used by this repo.
            assert _SYS_PLATFORM.search(marker), f'{path.name}:{number} has an unknown marker: {marker!r}'
        rows.append((match.group('name').lower().replace('_', '-'), match.group('version'), marker))
    return rows


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
    for path in (REQUIREMENTS, OPTIONAL):
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
