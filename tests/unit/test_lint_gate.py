"""The lint standard itself is under test, because a gate that can rot silently is no gate.

Three things are pinned here: no source file mutes a checker with an inline comment; CI really runs
pylint against all three tiers with the right config each; and the pytest-only exemptions never
leak into product code, where the same access is a real smell.

`# noqa` is deliberately NOT asserted: the measurement scripts need it for the one thing ruff has
no other answer to (imports that must follow a `sys.path` bootstrap), and that exception is listed
below rather than hidden in a config file.
"""

import ast
import re
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
#: Sources the linters own. `dist`, `build` and the model/dataset trees are not our code.
SKIP_DIRS = {'dist', 'build', '.git', 'node_modules', 'data', 'logs', 'scratchpad', 'ml_train'}
#: A Python environment is third-party code whatever it is called. Naming `.venv` was not enough:
#: the packaging build keeps `desktop/.venv-build`, and the moment that folder existed on a developer
#: machine this gate reported 185 inline suppressions in `site-packages` — files nobody here wrote,
#: and a red gate nobody can act on is a gate that gets ignored. `pyvenv.cfg` is the marker,
#: so the rule is the `.venv*` prefix plus `site-packages`, not one more directory name each time a
#: second environment appears.
VENV_DIR_PREFIX = '.venv'
SITE_PACKAGES = 'site-packages'
#: `ml_train/scripts` IS linted; only the trained models and datasets under it are not.
LINTED_SUBTREES = {'ml_train': ('scripts',)}

INLINE_PYLINT_SUPPRESSION = re.compile(r'#\s*pylint:\s*disable')
BLANKET_RUFF_SUPPRESSION = re.compile(r'^#\s*ruff:\s*noqa')


def _is_third_party(parts) -> bool:
    """True for anything inside an installed interpreter environment, by shape rather than by name."""
    return any(part == SITE_PACKAGES or part.startswith(VENV_DIR_PREFIX) for part in parts)


def _sources():
    for path in REPO.rglob('*.py'):
        relative = path.relative_to(REPO)
        parts = set(relative.parts)
        if parts & SKIP_DIRS or _is_third_party(relative.parts):
            continue
        top = relative.parts[0]
        if top in LINTED_SUBTREES and relative.parts[1:2] not in [(name,) for name in LINTED_SUBTREES[top]]:
            continue
        yield relative.as_posix(), path


class TestTheGateKnowsWhatsOurs:
    """`_sources()` decides what the gate can see, so its scope is a tested behaviour."""

    def test_an_environment_is_skipped_having_any_name_and_at_any_depth(self, tmp_path, monkeypatch):
        buried = tmp_path / 'desktop' / '.venv-build' / 'Lib' / 'site-packages' / 'sortedcontainers'
        buried.mkdir(parents=True)
        (buried / 'sortedlist.py').write_text('x = 1\n', encoding='utf-8')
        odd = tmp_path / 'tools' / '.venv-check'
        odd.mkdir(parents=True)
        (odd / 'thing.py').write_text('x = 1\n', encoding='utf-8')
        (tmp_path / 'desktop' / 'compress_dist.py').write_text('x = 1\n', encoding='utf-8')
        monkeypatch.setattr(sys.modules[__name__], 'REPO', tmp_path)
        assert [name for name, _ in _sources()] == ['desktop/compress_dist.py'], (
            'a gate that reports other people code as our violation gets ignored, which is how a gate dies'
        )

    def test_the_real_tree_reports_no_environment_path_as_ours(self):
        names = [name for name, _ in _sources()]
        assert not [name for name in names if '.venv' in name or 'site-packages' in name], names[:5]
        assert 'desktop/compress_dist.py' in names, 'the product tree has to still be inside the gate'


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
        # Either shell may enumerate the targets, as long as it enumerates FILES and fails on an empty
        # list. The bug this pins is a bare directory name reaching pylint as a package name — `packaging`
        # resolved to the PyPA distribution in site-packages, so the gate linted somebody else's code —
        # and that bug is identical on Windows and on Linux, so the rule is not "use PowerShell".
        enumerated = 'Get-ChildItem' in ci or 'find ' in ci
        assert enumerated, 'targets must be enumerated as files, not as bare directory names'
        # …and the enumeration must FLATTEN. Measured on the runner: the product step was written
        # ``@( (Get-ChildItem backend…), (Get-ChildItem desktop…) ) | ForEach-Object FullName``, which
        # builds an array of TWO arrays — and ``ForEach-Object -MemberName`` does not member-enumerate
        # an array it is handed. pylint received two empty arguments and answered
        # ``No files to lint: exiting.`` with exit 1. It failed LOUDLY, which is the only reason
        # anyone noticed: the same shape on a day the lists happen to work would have been a green
        # step checking nobody's code. The pin is the projection: per-object ``{ $_.FullName }`` over a
        # flattened ``@()``, and each step says out loud how many files it read.
        # The pin is the projection, asked of the CODE and not of the prose: the workflow's own comment
        # quotes the broken spelling to explain it, and a substring check over comments would convict
        # the explanation of the fix.
        ci_code = '\n'.join(line for line in ci.splitlines() if not line.lstrip().startswith('#'))
        assert 'ForEach-Object FullName' not in ci_code, 'project per object: { $_.FullName }'
        assert ci_code.count('ForEach-Object { $_.FullName }') == 2, 'both tiers must enumerate this way'
        counting = re.findall(r'Write-Output "linting \$\(\$targets\.Count\)', ci_code)
        assert len(counting) == 2, 'a gate must report how much it linted, in the log'
        failing = ci.count('throw') + ci.count('-z "$') + ci.count('-z ${')
        assert failing >= 2, 'a tier that finds no sources must fail, not pass silently'
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

    #: The roots the PRODUCT tier enumerates — the same list CI lints, so this test sees what CI sees.
    _PRODUCT_ROOTS = ('backend', 'desktop', 'tools', 'ml_train/scripts')

    def _optional_import_names(self) -> set[str]:
        """Package names declared in `requirements-optional.txt`, spelled as Python imports them."""
        names = set()
        for line in (REPO / 'requirements-optional.txt').read_text(encoding='utf-8').splitlines():
            text = line.split(';')[0].strip()  # a platform marker is not part of the name
            if not text or text.startswith('#'):
                continue
            names.add(re.split(r'[<>=!~\[]', text)[0].strip().replace('-', '_'))
        return names

    def _imported_optional_names(self, optional: set[str]) -> set[str]:
        """Which of those names product code actually imports — i.e. what a runner cannot resolve."""
        found = set()
        for root in self._PRODUCT_ROOTS:
            for path in sorted((REPO / root).rglob('*.py')):
                if any(part.startswith('.venv') or part == 'site-packages' for part in path.parts):
                    continue
                tree = ast.parse(path.read_text(encoding='utf-8'))
                for node in ast.walk(tree):
                    for name in (
                        [alias.name for alias in node.names]
                        if isinstance(node, ast.Import)
                        else [node.module or '']
                        if isinstance(node, ast.ImportFrom) and not node.level
                        else []
                    ):
                        root_name = name.split('.')[0]
                        if root_name in optional:
                            found.add(root_name)
        return found

    def test_the_optional_runtime_exemption_is_scoped_and_complete(self):
        """`E0401` stays ON in the product tier; only the six optional runtimes are excused, by name.

        Measured on CI run 40457992451 — the first run whose pylint step actually received file
        names — where the product tier reported 19 `E0401` for `torch`, `transformers`, `onnx`,
        `sentence_transformers`, `bertopic` and `uiautomation`. Every one of those is declared in
        `requirements-optional.txt` and imported inside a guard that probes for it, and AGENTS keeps
        that stack out of CI (torch is a multi-gigabyte wheel), so the finding was the environment
        answering a question about the code. It read clean locally because every name IS installed
        here — which is the general lesson: a gate whose machine differs from the runner's proves
        less than it says.

        Two directions are pinned so the exemption cannot rot:

        * nothing excused that is not an optional dependency — otherwise a package silently leaving
          `requirements.txt` is hidden instead of reported;
        * nothing optional that product code imports left out — that is the CI failure coming back.

        A misspelled import (`tranformers`) is still E0401: the list is module names, not the message.
        """
        cfg = (REPO / '.pylintrc').read_text(encoding='utf-8')
        match = re.search(r'^ignored-modules=(.+)$', cfg, re.M)
        assert match, 'the product tier must excuse the optional stack BY MODULE NAME'
        ignored = {name.strip() for name in match.group(1).split(',') if name.strip()}
        assert ignored, 'an empty ignored-modules would be the same as no exemption'

        disabled = re.search(r'^disable=(.+)$', cfg, re.M)
        assert disabled and 'E0401' not in disabled.group(1), (
            'import-error may not be switched off wholesale — only the named optional runtimes'
        )

        optional = self._optional_import_names()
        unexplained = ignored - optional
        assert unexplained == set(), (
            f'exempted but not declared optional: {sorted(unexplained)}; an import that left '
            f'requirements.txt is a bug to report, not to excuse'
        )
        needed = self._imported_optional_names(optional)
        assert len(needed) >= 4, f'the scan found only {sorted(needed)} — did the optional stack move?'
        missing = needed - ignored
        assert missing == set(), (
            f'product code imports these optional runtimes but pylint still tries to resolve them '
            f'on a runner that has none: {sorted(missing)}'
        )
