"""Project text quotes with the language's own marks, never with \u300c\u300d/\u300e\u300f.

The corner bracket is the Japanese/vertical-Chinese mark. This repository writes Chinese and English side
by side (a Chinese README beside English docstrings, an i18n catalogue whose two halves must read the same
way), and mixing two bracket systems in that text makes a sentence that quotes the UI's own wording look
like a different kind of citation — a file path, a node label, a config key. One rule keeps it legible:
**Chinese text uses “ ” (nested ‘ ’), English text uses " "** (nested ' '), and the corner bracket is not
used at all.

Data is not prose, so it is not scanned: `ml_train/datasets/` and `ml_train/models/` carry crawled corpora
and third-party model cards verbatim, and `backend/static/vendor`/`geo` are pinned by SHA-256 — rewriting a
byte there would break a provenance pin rather than fix a sentence.
"""

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]

CORNER_BRACKETS = ('\u300c', '\u300d', '\u300e', '\u300f')

#: Prose and code, never binaries: an image or a PDF has no quotes to fix.
TEXT_SUFFIXES = {
    '.py',
    '.js',
    '.mjs',
    '.json',
    '.jsonc',
    '.md',
    '.txt',
    '.yml',
    '.yaml',
    '.toml',
    '.cfg',
    '.ini',
    '.tex',
    '.bib',
    '.html',
    '.css',
    '.sh',
    '.ps1',
    '.sql',
}

SCANNED_TREES = ('backend', 'tests', 'docs', 'desktop', 'tools', 'deploy', '.github', '.opencode', 'ml_train/scripts')

ROOT_FILES = (
    'AGENTS.md',
    'README.md',
    'LICENSE',
    'pytest.ini',
    'ruff.toml',
    'requirements.txt',
    'requirements-optional.txt',
    'docker-compose.yml',
    '.gitignore',
    '.gitattributes',
    '.dockerignore',
    '.pylintrc',
    '.pylintrc.tests',
    '.pylintrc.probes',
)

#: Quoted bytes that belong to someone else: a vendored bundle pinned by digest, a crawled corpus, a model
#: card, an installed package. Each is excluded for a stated reason, not to make the scan pass.
EXCLUDED = (
    'backend/static/vendor',
    'backend/static/geo',
    'ml_train/datasets',
    'ml_train/models',
    'desktop/.venv-build',
    '.venv',
    'data',
    'dist',
    'logs',
    'scratchpad',
    'samples/vendor',
)

#: Pruned during the walk, so a 22k-file build environment is not read to be skipped.
PRUNED_NAMES = {'__pycache__', '.venv-build', 'site-packages', 'node_modules', '.pytest_cache', '.ruff_cache'}


def scanned_files() -> list[Path]:
    """Every project text file the rule applies to."""
    files = []
    for tree in SCANNED_TREES:
        root = REPO / tree
        if not root.exists():
            continue
        for base, dirs, names in os.walk(root):
            dirs[:] = [name for name in dirs if name not in PRUNED_NAMES]
            for name in names:
                path = Path(base) / name
                if path.suffix.lower() not in TEXT_SUFFIXES:
                    continue
                relative = path.relative_to(REPO).as_posix()
                if any(relative.startswith(excluded) for excluded in EXCLUDED):
                    continue
                files.append(path)
    files.extend(REPO / name for name in ROOT_FILES if (REPO / name).is_file())
    return files


def offenders(text: str) -> int:
    """How many corner brackets *text* contains."""
    return sum(text.count(bracket) for bracket in CORNER_BRACKETS)


class TestTheProjectUsesItsOwnQuotes:
    def test_no_corner_brackets_anywhere_in_the_project(self):
        found = {}
        for path in scanned_files():
            text = path.read_text(encoding='utf-8', errors='replace')
            count = offenders(text)
            if count:
                line = next(number for number, content in enumerate(text.splitlines(), 1) if offenders(content))
                found[path.relative_to(REPO).as_posix()] = f'{count} at line {line}'
        assert found == {}, 'corner brackets belong to no language this project writes: ' + '; '.join(
            f'{path} ({where})' for path, where in sorted(found.items())
        )

    def test_the_scan_actually_reads_the_project(self):
        """A guard that scans three files passes for the wrong reason."""
        assert len(scanned_files()) > 700

    def test_the_detector_sees_each_corner_bracket(self):
        assert offenders('a \u300cb\u300d c \u300ed\u300f') == 4
        assert offenders('a \u201cb\u201d and "c"') == 0

    def test_a_fabricated_corner_bracket_is_caught(self, tmp_path):
        """The rule has to convict: the same reader applied to a planted file reports it."""
        planted = tmp_path / 'planted.md'
        planted.write_text('运行前提示\u300c部分平台不发布属地\u300d。', encoding='utf-8')
        assert offenders(planted.read_text(encoding='utf-8')) == 2
