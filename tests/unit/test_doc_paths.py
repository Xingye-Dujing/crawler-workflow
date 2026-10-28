"""Every project path a document cites must still exist.

Docs in this repo are evidence, not prose: `docs/crawler_notes.md` is 2,450 lines of measurements that
name the file and line a finding came from, and `AGENTS.md` points its rules at the same places. A
restructure (docs/refactor_plan.md) moves those files by the dozen, and a citation that now points at
nothing is worse than none — it reads like the measurement still stands. This test is the tripwire for
that, and it is deliberately run *before* the moves start.

Two exclusions, each a fact rather than an exemption:

* **deleted one-off probes** (`backend/test_*.py`): those scripts were archived outside the repo on
  purpose, and the docs cite them as the provenance of a number, not as code that should exist;
* **the plan itself** (`docs/refactor_plan.md`): it names target paths that do not exist yet, which is
  the opposite of a stale citation.

Anything else that goes missing is a regression, so a fabricated path is proven to be caught.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]

#: Only real project trees are scanned: a third-party path in prose (`jieba/_compat.py`) is a fact
#: about someone else's package, and the resolver would have nothing to check it against.
_PROJECT_DIRS = (
    'api',
    'analyzers',
    'capabilities',
    'core',
    'crawlers',
    'desktop',
    'docs',
    'engine',
    'i18n_catalog',
    'ml_train',
    'nodes',
    'samples',
    'scheduling',
    'sessions',
    'services',
    'static',
    'tests',
    'tools',
)

#: The lookbehind is what makes `snownlp/utils/tnt.py` one third-party path instead of a broken
#: citation of our own `utils/` — a project dir name is only a project path when nothing continues it.
CITATION = re.compile(
    r'`?(?<![\w./-])((?:backend/)?(?:' + '|'.join(_PROJECT_DIRS) + r')/[A-Za-z0-9_./-]*\.py)(?::\d+(?:-\d+)?)?`?'
)

#: Where a bare citation could live. The crawler docs abbreviate `crawlers/engine/wall.py` as
#: `engine/wall.py`, so the shorthand resolves too — and a genuinely deleted file still does not.
_ROOTS = ('', 'backend/', 'backend/crawlers/')

DOC_FILES = sorted((REPO / 'docs').glob('*.md')) + [
    REPO / 'README.md',
    REPO / 'AGENTS.md',
    REPO / 'agents.md',
    REPO / 'ml_train' / 'README.md',
    REPO / 'desktop' / 'README.md',
]

#: Cited as the source of a measurement, then deleted on purpose. Not a broken reference.
DELETED_PROBES = re.compile(r'(?:^|/)test_[A-Za-z0-9_]*\.py$')

#: Files whose job is to name paths that do not exist yet.
_PLANS = {'refactor_plan.md'}

#: A module that was deleted, cited as the thing that was deleted. `docs/collection.md` and
#: `docs/crawler_notes.md` record that 抖音's sort menu went together with its `search()` and its live
#: cases — naming the removed file IS the measurement. Adding to this list is a decision to argue
#: about, the same way an exemption in a linter config is.
_DELETED_MODULES = {
    'engine/menu.py': 'the 抖音 sort-menu helper, deleted with the mode it served (docs/crawler_notes.md 338)',
    # 2026-10-27: the login-state domain was assembled out of modules that lived elsewhere, and
    # docs/ARCHITECTURE.md names the old path so a reader who arrives with the old spelling in mind
    # can see where it went. The file is gone; the citation is the provenance, not a claim.
    'services/cookie_manager.py': 'moved to sessions/cookies.py (docs/ARCHITECTURE.md sessions row)',
    'services/cookie_flow.py': 'moved to sessions/flow.py (docs/ARCHITECTURE.md sessions row)',
    # 2026-10-28: the two /api/browser/profiles routes merged into sessions/routes.py with the
    # rest of the cookie surface; ARCHITECTURE names the old path as provenance.
    'api/browser_profiles.py': 'merged into sessions/routes.py (docs/ARCHITECTURE.md sessions row)',
}


def _doc_files() -> list[Path]:
    return [path for path in DOC_FILES if path.exists()]


def unresolved(text: str, origin: str) -> list[str]:
    """The project paths in *text* that no longer resolve, from a document called *origin*."""
    if origin in _PLANS:
        return []
    bad = []
    for match in CITATION.finditer(text):
        cited = match.group(1)
        if DELETED_PROBES.search(cited):
            continue
        relative = cited[len('backend/') :] if cited.startswith('backend/') else cited
        if any((REPO / (root + relative)).exists() for root in _ROOTS):
            continue
        if cited in _DELETED_MODULES:
            continue
        bad.append(cited)
    return bad


class TestTheDocsPointAtRealFiles:
    def test_every_cited_project_path_exists(self):
        broken = {}
        for path in _doc_files():
            for cited in unresolved(path.read_text(encoding='utf-8', errors='replace'), path.name):
                broken.setdefault(cited, set()).add(path.name)
        assert broken == {}, 'stale doc citations: ' + '; '.join(
            f'{cited} <- {", ".join(sorted(origins))}' for cited, origins in sorted(broken.items())
        )

    def test_the_scan_actually_looks_for_paths(self):
        """A guard that finds nothing in 7,900 lines of docs is a regex that never matched."""
        found = sum(len(CITATION.findall(path.read_text(encoding='utf-8', errors='replace'))) for path in _doc_files())
        assert found > 150, f'only {found} citations parsed — the pattern stopped matching the way docs write paths'

    def test_a_moved_file_is_convicted_not_just_missed(self):
        assert unresolved('see `sessions/cookies.py` for the fold', 'x.md') == []
        assert unresolved('see `sessions/cookie_jar_gone.py` for the fold', 'x.md') == ['sessions/cookie_jar_gone.py']

    def test_every_backend_package_is_inside_the_scanned_set(self):
        """A directory the docs can cite but the scanner cannot see is a silent hole: the guard would
        report zero broken paths and look like a green suite. One direction only — the list also names
        trees a later stage has not created yet.
        """
        present = sorted(path.name for path in (REPO / 'backend').iterdir() if path.is_dir() and any(path.glob('*.py')))
        unscanned = [name for name in present if name not in _PROJECT_DIRS]
        assert unscanned == [], f'backend packages the doc guard cannot resolve: {unscanned}'

    def test_a_deleted_probe_stays_a_legal_citation(self):
        """The probe scripts were archived outside the repo; docs naming them record provenance."""
        assert unresolved('measured by `backend/test_weibo_recipe.py` on 2026-09-27', 'crawler_notes.md') == []

    def test_the_plan_may_name_paths_that_do_not_exist_yet(self):
        assert unresolved('`core/coerce.py` holds the coercions', 'refactor_plan.md') == []

    def test_an_excused_citation_is_still_a_citation(self):
        """A ledger nobody checks becomes a hiding place: an entry whose file is no longer cited
        anywhere must fail, or the exemption outlives the fact it excused."""
        cited = set()
        for path in _doc_files():
            for match in CITATION.finditer(path.read_text(encoding='utf-8', errors='replace')):
                cited.add(match.group(1))
        unused = set(_DELETED_MODULES) - cited
        assert unused == set(), f'excused paths nobody cites any more: {sorted(unused)}'
