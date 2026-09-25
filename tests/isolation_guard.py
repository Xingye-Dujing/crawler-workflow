"""The rule the harness enforces, in a module a test can actually import.

A test run may **read** ``data/`` and ``logs/`` — the live tier crawls with the user's saved
cookies and profile directories by absolute path, on purpose — and may not **write** to them.

Two reasons this lives here instead of inside ``tests/conftest.py``:

* pytest imports four ``conftest.py`` files in this tree, so the name ``conftest`` in
  ``sys.modules`` belongs to whichever was collected last — a test that imported it to reach the
  guard would be testing an unrelated module (measured: it passes alone and fails in a full run);
* the guard's *decision* is the interesting part, and a decision made in a file no test can import
  is a decision with no test.

``conftest.py`` keeps the two things only it can do — take the fingerprint at import time, before
collection imports any test module, and hand the session to :func:`enforce` at the end.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The user's own state, as far as this suite is concerned: readable, never writable.
PROTECTED_DIRS = (REPO_ROOT / 'data', REPO_ROOT / 'logs')

#: Inside those, the subtree that is not walked file by file. A Chrome profile holds tens of
#: thousands of files that only its owning browser ever touches; recording each profile directory
#: and the files at its top (``browser_profiles`` writes its marker there) catches a crawler that
#: ignored the redirect, and walking the rest would cost more than the check is worth.
PROTECTED_SHALLOW = 'data/chrome_profile'

#: How many offending paths to name per line before truncating.
REPORT_LIMIT = 12

#: The headline of the report. Exported because the test asserts it appears.
REPORT_HEADLINE = 'THE SUITE WROTE INTO THE USER DIRECTORY'


def fingerprint() -> dict:
    """Every path under ``data/`` and ``logs/``, with the size and mtime of each file.

    Directory *mtimes* are not compared: one moves when a file inside it is merely read on some
    filesystems, and this is a check about bytes gained or lost, not about who looked.
    """
    seen: dict = {}
    for root in PROTECTED_DIRS:
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            rel = Path(dirpath).relative_to(REPO_ROOT).as_posix()
            for name in filenames:
                stat = (Path(dirpath) / name).stat()
                seen[f'{rel}/{name}'] = ('file', stat.st_size, stat.st_mtime_ns)
            if rel == PROTECTED_SHALLOW:
                for name in dirnames:
                    seen[f'{rel}/{name}'] = ('profile', 0, 0)
                # Not descended: the profile's own subtree is the browser's business.
                dirnames[:] = []
    return seen


def diff(before: dict, now: dict) -> tuple:
    """What the protected directories gained, lost or changed. Pure, so it is testable.

    A file is reported when its kind, its size **or** its mtime moved: a rewrite that happens to
    produce the same byte count (a fake cookie as long as the real one is not that unlikely) is
    still a write. Reading moves no timestamp here, so the live tier's reads are not reported.
    """
    added = sorted(key for key in now if key not in before)
    removed = sorted(key for key in before if key not in now)
    changed = sorted(key for key, tag in now.items() if key in before and before[key] != tag)
    return added, removed, changed


def report(added: list, removed: list, changed: list) -> str:
    """The message a leak produces: the paths, and what to do rather than what to delete.

    ASCII only on purpose — this goes to ``stderr`` at session finish, where the console code page
    is whatever the terminal happens to be, and one smart quote could turn the report into a
    ``UnicodeEncodeError`` that loses the only thing the user needs to read.
    """
    return (
        '\n'
        + '=' * 78
        + f'\n{REPORT_HEADLINE} - data/ and logs/ are read-only here.\n'
        + f'  added:   {", ".join(added[:REPORT_LIMIT]) or "-"}\n'
        + f'  removed: {", ".join(removed[:REPORT_LIMIT]) or "-"}\n'
        + f'  changed: {", ".join(changed[:REPORT_LIMIT]) or "-"}\n'
        + '  Something captured a real path at import time: redirect it in ISOLATED_PATHS in\n'
        + '  tests/conftest.py, or make its owner read Config at call time. Do not delete these\n'
        + "  files and move on - this is where the user's cookies, workflows and models live.\n"
        + '=' * 78
    )


def is_worker(config) -> bool:
    """Whether this process is a pytest-xdist worker (which must not report; the controller does)."""
    return hasattr(config, 'workerinput')


def terminal_reporter(config):
    """The terminal plugin, or None when the run was started without one (``-p no:terminal``)."""
    plugins = getattr(config, 'pluginmanager', None)
    return plugins.getplugin('terminalreporter') if plugins is not None else None


def enforce(session, before: dict) -> bool:
    """Report and fail the run if ``data/`` or ``logs/`` moved since ``before`` was fingerprinted.

    Returns whether the session is clean. The exit status is what makes this worth having: a leak
    next to 3,900 green tests is otherwise invisible, which is exactly how the user's saved cookies
    were destroyed once — every test passed, and the ones that wrote into ``data/cookies`` wrote
    there.
    """
    added, removed, changed = diff(before, fingerprint())
    if not (added or removed or changed):
        return True
    text = report(added, removed, changed)
    if is_worker(session.config):
        raise RuntimeError(text)
    reporter = terminal_reporter(session.config)
    if reporter is not None:
        # ``write_sep`` exists on a TerminalReporter; ``get_terminal_writer()`` answers an object
        # that has no write_line at all, and a guard that raises on its way to reporting a leak
        # reports nothing (measured, on the first run of this hook).
        reporter.write_sep('=', REPORT_HEADLINE, red=True)
    # stderr as well as the separator: the report has to survive ``-s``-less capture and a
    # terminalwriter that is not installed at all.
    sys.stderr.write(text + '\n')
    sys.stderr.flush()
    session.exitstatus = pytest.ExitCode.TESTS_FAILED
    return False
