"""The lint standard itself is under test, because a gate that can rot silently is no gate.

Three things are pinned here: no source file mutes a checker with an inline comment; CI really runs
pylint against all three tiers with the right config each; and the pytest-only exemptions never
leak into product code, where the same access is a real smell.

`# noqa` is deliberately NOT asserted: the measurement scripts need it for the one thing ruff has
no other answer to (imports that must follow a `sys.path` bootstrap), and that exception is listed
below rather than hidden in a config file.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
#: Sources the linters own. `.venv`, `dist`, `build` and the model/dataset trees are not our code.
SKIP_DIRS = {'.venv', 'dist', 'build', '.git', 'node_modules', 'data', 'logs', 'scratchpad', 'ml_train'}
#: `ml_train/scripts` IS linted; only the trained models and datasets under it are not.
LINTED_SUBTREES = {'ml_train': ('scripts',)}

INLINE_PYLINT_SUPPRESSION = re.compile(r'#\s*pylint:\s*disable')
BLANKET_RUFF_SUPPRESSION = re.compile(r'^#\s*ruff:\s*noqa')


def _sources():
    for path in REPO.rglob('*.py'):
        relative = path.relative_to(REPO)
        parts = set(relative.parts)
        if parts & SKIP_DIRS:
            continue
        top = relative.parts[0]
        if top in LINTED_SUBTREES and relative.parts[1:2] not in [(name,) for name in LINTED_SUBTREES[top]]:
            continue
        yield relative.as_posix(), path


class TestNoInlineSuppressions:
    def test_not_one_source_file_mutes_pylint(self):
        """The user's rule: a finding is fixed at its cause, never silenced where it is reported."""
        offenders = []
        for name, path in _sources():
            try:
                lines = path.read_text(encoding='utf-8').splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            offenders.extend(
                f'{name}:{index + 1}' for index, line in enumerate(lines) if INLINE_PYLINT_SUPPRESSION.search(line)
            )
        assert offenders == [], f'inline pylint suppressions found: {offenders}'

    def test_not_one_source_file_turns_ruff_off_for_a_whole_file(self):
        offenders = []
        for name, path in _sources():
            try:
                text = path.read_text(encoding='utf-8')
            except (OSError, UnicodeDecodeError):
                continue
            offenders.extend(name for line in text.splitlines() if BLANKET_RUFF_SUPPRESSION.match(line.strip()))
        assert offenders == []


class TestTheStandards:
    def test_the_three_tier_configs_exist_and_differ_only_where_documented(self):
        product = (REPO / '.pylintrc').read_text(encoding='utf-8')
        tests = (REPO / '.pylintrc.tests').read_text(encoding='utf-8')
        probes = (REPO / '.pylintrc.probes').read_text(encoding='utf-8')

        def disabled(text):
            match = re.search(r'^disable=(.*)$', text, re.MULTILINE)
            assert match, 'no disable line — the standard is undocumented'
            return {code.strip() for code in match.group(1).split(',') if code.strip()}

        product_codes, test_codes, probe_codes = disabled(product), disabled(tests), disabled(probes)
        # The pytest idioms are exempt in the test tree and checked in product code. If one of them
        # ever appears in the product list, the test tree has become the place exemptions leak to.
        pytest_only = {'W0212', 'W0613', 'W0621'}
        assert pytest_only <= test_codes, 'the test tree must stay lintable without the pytest idioms'
        assert not pytest_only & product_codes, 'a pytest-only exemption leaked into the product standard'
        # A sys.path bootstrap belongs to the measurement scripts alone: product modules are
        # imported by the app, never run standalone, so a late import there is a real cycle tell.
        assert 'C0413' in probe_codes and 'C0413' not in product_codes
        # `global` for a rebind seam is a decision both trees document (the store singletons the
        # conftest re-points, and the counters a probe accumulates), so it must be justified twice
        # rather than smuggled into one file.
        assert 'W0603' in probe_codes and 'W0603' in product_codes
        assert 'W0603' not in test_codes, 'a test that rebinds module state is a smell, not a seam'
        # Line width is NOT disabled anywhere: it is pinned to ruff's number so the tools agree.
        for text in (product, tests, probes):
            assert 'C0301' not in disabled(text)
            assert 'max-line-length=120' in text
        # The one CPython internals allowance is named per member, so a project object can never
        # hide behind it.
        assert 'exclude-protected=_current_frames' in product
        assert 'exclude-protected' not in tests and 'exclude-protected' not in probes

    def test_ci_runs_the_two_tiers_it_can_and_says_why_not_the_third(self):
        """The workflow must pass explicit FILES, and no project directory may share a name with
        an installed distribution: a target spelled `packaging` resolved to the PyPA library in
        site-packages, so the gate linted somebody else's code (the folder is `desktop/` now).

        The third tier stays local: the measurement scripts are gitignored on purpose, so a runner
        has none of them, and a CI step that "passed" over an empty list is the silent green this
        project refuses.
        """
        ci = (REPO / '.github' / 'workflows' / 'ci.yml').read_text(encoding='utf-8')
        assert ci.count('--rcfile=.pylintrc.tests') == 1
        assert re.search(r'--rcfile=\.pylintrc(?![.\w])', ci), 'the product tier is missing from CI'
        assert 'pylint.exe --persistent=n --rcfile=.pylintrc --ignore-patterns' not in ci
        assert 'Get-ChildItem' in ci, 'targets must be enumerated as files, not as bare directory names'
        assert ci.count('throw') >= 2, 'a tier that finds no sources must fail, not pass silently'
        # The gate checks FATAL/ERROR/WARNING, and it does so on the command line: a `--disable=C,R`
        # living in a tier config would hide conventions from local runs too, which is not the deal.
        scoped = [
            line
            for line in ci.splitlines()
            if '--disable=C,R --fail-on=W,E,F' in line and not line.lstrip().startswith('#')
        ]
        assert len(scoped) == 2, 'exactly the two CI steps must carry the FATAL/ERROR/WARNING scoping'
        assert '--disable=C,R' not in (REPO / '.pylintrc').read_text(encoding='utf-8')
        # The renamed folder is part of the gate, not a tidy-up: `Get-ChildItem packaging` would
        # silently lint the installed distribution again.
        assert 'Get-ChildItem desktop' in ci, 'the product tier must list the desktop/ build sources'
        assert not (REPO / 'packaging').exists(), 'no project directory may shadow an installed distribution'
        assert '--disable=C,R' not in (REPO / '.pylintrc.tests').read_text(encoding='utf-8')
        # The probes tier may be DOCUMENTED in this file (the local command is worth writing down),
        # but no step may RUN it — a step over an empty target list is the silent green we refuse.
        probes_lines = [line for line in ci.splitlines() if '.pylintrc.probes' in line]
        assert probes_lines, 'the local probes command should still be written down'
        assert all(line.lstrip().startswith('#') for line in probes_lines), (
            'the probes tier cannot run in CI: `backend/test_*.py` are not in the repository'
        )
        assert 'gitignored' in ci, 'the reason the third tier is local must be written where it is missing'

    def test_the_configs_are_versioned_and_the_probes_stay_unversioned(self):
        """.pylintrc itself used to be gitignored — a standard nobody else could see is not a standard."""
        ignore = (REPO / '.gitignore').read_text(encoding='utf-8')
        lines = {line.strip() for line in ignore.splitlines()}
        assert '.pylintrc' not in lines, 'the pylint standard must be in the repository'
        for name in ('.pylintrc', '.pylintrc.tests', '.pylintrc.probes'):
            assert (REPO / name).is_file(), f'{name} is part of the review standard'
        assert 'backend/test_*.py' in '\n'.join(lines), 'the probes stay out of git by decision, not by accident'

    def test_pylint_is_a_declared_dependency_of_the_gate(self):
        """CI installs `requirements.txt` only; a gate whose tool is not declared cannot run."""
        declared = (REPO / 'requirements.txt').read_text(encoding='utf-8').lower()
        assert 'pylint' in declared
