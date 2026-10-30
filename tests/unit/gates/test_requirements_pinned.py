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
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
REQUIREMENTS = REPO / 'requirements.txt'
OPTIONAL = REPO / 'requirements-optional.txt'
RUNTIME = REPO / 'desktop' / 'requirements-runtime.txt'

#: ``name==1.2.3`` with an optional ``[extra]`` and an optional ``; marker``.
PINNED = re.compile(r'^(?P<name>[A-Za-z0-9_.-]+)(?:\[[^\]]*\])?==(?P<version>[A-Za-z0-9_.+-]+)\s*(?:;.*)?$')


def _lines(path: Path) -> list[tuple[int, str]]:
    """``(line number, text)`` for every entry line, comments and blanks dropped."""
    entries = []
    for number, raw in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
        text = raw.split('#', 1)[0].strip()
        if not text:
            continue
        entries.append((number, text))
    return entries


def _pins(path: Path) -> dict[str, str]:
    """name → pinned version, refusing anything that is not an exact pin."""
    pins = {}
    for number, text in _lines(path):
        match = PINNED.match(text)
        assert match, f'{path.name}:{number} is not an exact pin: {text!r}'
        name = match.group('name').lower().replace('_', '-')
        pins[name] = match.group('version')
    return pins


def test_every_requirement_is_pinned():
    for path in (REQUIREMENTS, OPTIONAL):
        pins = _pins(path)
        assert pins, f'{path.name} declares nothing'
        # A range or a bare name would have failed _pins; this second assertion names the
        # counts so a file that silently lost entries is noticed rather than passing on a
        # smaller set.
        assert len(pins) == len(_lines(path)), f'{path.name} repeats a package'


def test_runtime_versions_match_the_source_requirements():
    """The frozen Windows app and a source install must answer with the same versions.

    ``desktop/requirements-runtime.txt`` is the packaged app's own list and already says why:
    two builders should produce the same folder. A source checkout that drifts from it means
    a bug reproduced in one and not the other.
    """
    source = _pins(REQUIREMENTS)
    runtime = _pins(RUNTIME)

    shared = set(source) & set(runtime)
    assert shared, 'the runtime file shares no package with requirements.txt — wrong file?'
    mismatched = {name: (source[name], runtime[name]) for name in shared if source[name] != runtime[name]}
    assert not mismatched, f'versions drifted between requirements.txt and desktop runtime: {mismatched}'
