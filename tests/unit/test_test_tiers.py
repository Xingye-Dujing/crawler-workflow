"""The test tiers themselves are under test.

Which tier runs by default is not a documentation question: ``pytest.ini``'s
``addopts`` is the only thing standing between ``pytest -q`` and an hour of real
crawling, and ``live_quick`` is the tier the project now runs before every change.
Both facts are config plus a hand-picked marker on nine tests, so a marker deleted
in a refactor or a platform that quietly grows a live file would leave the daily
tier believing it covers a platform it never visits.

Read statically on purpose — importing the live modules would start a browser.
"""

import ast
import configparser
import contextlib
import json
import sys
from pathlib import Path

import pytest

from crawl_capabilities import CAPABILITIES

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTEST_INI = REPO_ROOT / 'pytest.ini'
LIVE_DIR = REPO_ROOT / 'tests' / 'live_site'
TESTS_DIR = REPO_ROOT / 'tests'

#: ``live_quick`` exists to be short. Nine today; the ceiling is where a future
#: "just add one more" has to say why out loud instead of silently doubling the
#: time every change costs.
QUICK_BUDGET = 12


def _marker_names(decorator: ast.expr) -> set:
    """Marker names a decorator expression applies, ``pytest.mark.x`` and bare ``x`` alike."""
    names = set()
    for node in ast.walk(decorator):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute):
            if isinstance(node.value.value, ast.Name) and node.value.value.id == 'pytest' and node.value.attr == 'mark':
                names.add(node.attr)
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == 'mark':
            names.add(node.attr)
    return names


def _quick_marks_inside(node: ast.AST) -> bool:
    """True when a ``pytest.param(..., marks=pytest.mark.live_quick)`` appears below."""
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and getattr(child.func, 'id', '') == 'param':
            if any(_marker_names(kw.value) & {'live_quick'} for kw in child.keywords if kw.arg == 'marks'):
                return True
            for arg in child.args:
                if _marker_names(arg) & {'live_quick'}:
                    return True
    return False


def _live_files() -> list:
    """(path, module markers, {test name: (is quick, platforms it crawls, regions)}) per live file."""
    out = []
    for path in sorted(LIVE_DIR.glob('test_*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        module_marks = set()
        literals = {}
        called = {}
        quick = {}
        regions = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                getattr(target, 'id', '') == 'pytestmark' for target in node.targets
            ):
                for child in ast.walk(node.value):
                    if isinstance(child, ast.Attribute) and child.attr != 'mark':
                        module_marks.add(child.attr)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                own, refs = set(), set()
                for child in ast.walk(node):
                    if isinstance(child, ast.Constant) and isinstance(child.value, str):
                        own.add(child.value)
                    elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                        refs.add(child.id)
                    elif isinstance(child, ast.Attribute):
                        refs.add(child.attr)
                literals[node.name] = own
                called[node.name] = refs
                if node.name.startswith('test_'):
                    marks = set(module_marks)
                    for dec in node.decorator_list:
                        marks |= _marker_names(dec)
                    quick[node.name] = bool(marks & {'live_quick'}) or _quick_marks_inside(
                        ast.Module(body=[node], type_ignores=[])
                    )
                    regions[node.name] = marks & {'live_cn', 'live_os'}
        platforms = {name: _platforms_of(name, literals, called) for name in quick}
        out.append(
            (
                path,
                module_marks,
                {name: (is_quick, platforms[name], regions[name]) for name, is_quick in quick.items()},
            )
        )
    return out


def _platforms_of(name: str, literals: dict, called: dict) -> set:
    """The crawl-matrix platforms one test really visits — its own string literals
    plus those of the helpers it calls, transitively inside the same file.

    The whole file is the wrong unit: a comment module that also holds a zhihu
    case would otherwise mark itself as covering zhihu even when only its weibo
    case is in the quick tier, and the gap that leaves is exactly what this checks.
    """
    known = {capability.platform for capability in CAPABILITIES}
    seen, out, queue = {name}, set(), [name]
    while queue:
        current = queue.pop()
        out |= literals.get(current, set()) & known
        for ref in called.get(current, set()):
            if ref in literals and ref not in seen:
                seen.add(ref)
                queue.append(ref)
    return out


class TestDefaultFilter:
    def test_the_fast_tier_excludes_every_real_network_tier(self):
        """One missing name in this filter turns ``pytest -q`` into a crawl run."""
        parser = configparser.ConfigParser()
        parser.read_string(PYTEST_INI.read_text(encoding='utf-8'))
        addopts = parser['pytest']['addopts']
        expression = addopts.split('-m')[1]
        for marker in ('integration', 'live_ollama', 'live_site', 'live_quick'):
            assert f'not {marker}' in expression, f'{marker} would run on a plain pytest: {addopts}'

    def test_the_quick_marker_is_registered(self):
        declared = PYTEST_INI.read_text(encoding='utf-8')
        assert 'live_quick:' in declared, 'an unregistered marker is a warning away from being a typo'


class TestQuickTier:
    def test_quick_cases_exist_and_the_tier_stays_short(self):
        quick = [
            f'{path.name}::{name}'
            for path, _marks, tests in _live_files()
            for name, (is_quick, _platforms, _regions) in tests.items()
            if is_quick
        ]
        assert quick, 'nothing is marked live_quick, so the daily tier runs nothing'
        assert len(quick) <= QUICK_BUDGET, f'{len(quick)} quick cases, budget {QUICK_BUDGET}: {quick}'

    def test_every_crawlable_platform_is_visited_by_the_quick_tier(self):
        """The point of the split: a change must still meet every platform once.

        A new live file that designates no representative would leave its platform
        in the full tier only, and the full tier now runs at acceptance, not per
        change — a silent gap exactly as wide as the one this marker replaced.
        """
        covered = set()
        for _path, _marks, tests in _live_files():
            for is_quick, platforms, _regions in tests.values():
                if is_quick:
                    covered |= platforms
        missing = {capability.platform for capability in CAPABILITIES} - covered
        assert not missing, f'no live_quick case reaches these platforms: {sorted(missing)}'

    def test_quick_never_escapes_the_live_directory(self):
        """``live_quick`` is a subset of the live tier by construction: every case
        with it must also carry ``live_site``, or ``-m live_site`` stops being the
        full pass and the acceptance run quietly shrinks."""
        offenders = [
            f'{path.name}::{name}'
            for path, module_marks, tests in _live_files()
            for name, (is_quick, _platforms, _regions) in tests.items()
            if is_quick and 'live_site' not in module_marks
        ]
        assert not offenders, f'marked quick but not live: {offenders}'

    def test_no_module_marks_itself_quick_wholesale(self):
        """A module-level marker makes *every* case in it part of the daily tier,
        which is how a short tier silently becomes the long one again."""
        wholesale = [path.name for path, module_marks, _tests in _live_files() if 'live_quick' in module_marks]
        assert not wholesale, f'module-level live_quick in {wholesale}; mark one representative instead'


class TestRegionSplit:
    """``live_cn`` and ``live_os`` exist because one machine cannot be in two networks at
    once: with a VPN up douyin answers 502, without one x.com never loads. A case in the
    wrong group is not slow, it is **unrunnable** — and it fails as "0 rows", which reads
    as a broken crawler and sends somebody to read crawl code that was fine.

    The region is never restated here: it comes from the crawl matrix, so a platform whose
    network requirement changes moves its tests instead of leaving a copy behind.
    """

    def test_both_region_markers_are_registered(self):
        declared = PYTEST_INI.read_text(encoding='utf-8')
        for marker in ('live_cn', 'live_os'):
            assert f'{marker}:' in declared, f'{marker} runs under every filter and a typo stays silent'

    def test_every_live_case_declares_exactly_one_network(self):
        missing = [
            f'{path.name}::{name}'
            for path, _marks, tests in _live_files()
            for name, (_quick, _platforms, regions) in tests.items()
            if len(regions) != 1
        ]
        assert not missing, f'live cases without exactly one network marker: {missing}'

    def test_a_case_never_claims_the_wrong_network(self):
        """The matrix owns each platform's network, so the marker has to agree with it.

        A case that names no crawlable platform at all (it reaches the site through a
        helper whose literals live elsewhere) is left to the test above rather than
        guessed at here.
        """
        from crawl_capabilities import region_of

        #: The marker is a pytest name, the region is a matrix value; one mapping here is
        #: the only place the two spellings meet.
        marker_of = {'cn': 'live_cn', 'overseas': 'live_os'}
        wrong = []
        for path, _marks, tests in _live_files():
            for name, (_quick, platforms, regions) in tests.items():
                wanted = {marker_of[region] for region in (region_of(p) for p in platforms) if region}
                if wanted and not wanted <= regions:
                    wrong.append(f'{path.name}::{name}: matrix says {sorted(wanted)}, marked {sorted(regions)}')
        assert not wrong, 'the network marker disagrees with the crawl matrix:\n  ' + '\n  '.join(wrong)

    def test_each_network_has_a_quick_representative(self):
        """The point of the split is two short runs the user can choose to do, one per
        network. A group with no quick case means switching networks for nothing — and
        the daily gate quietly covering only half the platforms."""
        for marker in ('live_cn', 'live_os'):
            quick = [
                f'{path.name}::{name}'
                for path, _marks, tests in _live_files()
                for name, (is_quick, _platforms, regions) in tests.items()
                if is_quick and marker in regions
            ]
            assert quick, f'no live_quick case in {marker}: that network is only visited by the hour-long pass'

    def test_the_matrix_names_no_network_but_the_two(self):
        """A typo in a ``region=`` reads as "no opinion" everywhere, and the pre-run
        dialog would stay silent about a mixed canvas forever."""
        from crawl_capabilities import REGIONS

        assert REGIONS == ('cn', 'overseas')
        assert {capability.region for capability in CAPABILITIES} <= set(REGIONS)

    def test_the_warning_switch_hides_the_question_and_nothing_else(self):
        """Turning the dialog off must not change what a run does — the split of the
        live tier and the crawl itself read the matrix, never this setting."""
        text = (REPO_ROOT / 'backend' / 'settings_store.py').read_text(encoding='utf-8')
        assert "'warn_mixed_region': True" in text, 'asking is the default until somebody says otherwise'
        gate = (REPO_ROOT / 'backend' / 'crawl_gate.py').read_text(encoding='utf-8')
        assert 'warn_mixed_region' not in gate, 'a cosmetic dialog must not be wired into what actually runs'


class TestIsolationRunsBeforeTheAppIsImported:
    """No test module may import ``app`` at module level, because collection beats every fixture.

    ``app.py`` freezes paths into module-level singletons at its own import
    (``cookie_manager = CookieManager(Config.COOKIE_DIR)``, ``history_service`` opening
    ``data/history.db``). pytest imports every collected file during collection — before any fixture
    runs, and regardless of marker filters, since a deselected file is still imported. So the
    harness redirects at conftest **import** time instead, which reaches the whole suite no matter
    what a test file imports and when.

    This rule is the second lock on the same door, and it stays locked for two reasons: a redirect
    that has to beat collection is one refactor away from being a fixture again, and an early
    ``import app`` drags Flask, pandas and sklearn into every collection, including the ``-q`` run
    of a single unit test.

    Measured consequence, recorded in ``docs/crawler_notes.md``: one integration file with
    ``from app import _close_login_browser`` at the top made ``/api/cookies/save`` write
    ``{'name': 'SUB', 'value': 'x'}`` into the user's own ``data/cookies/weibo_cookies.json``, and a
    delete case removed the entries that were really there — while the suite reported green.
    """

    def _module_level_app_imports(self, path: Path) -> list:
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        found = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                found += [(node.lineno, alias.name) for alias in node.names if alias.name.split('.')[0] == 'app']
            elif isinstance(node, ast.ImportFrom) and (node.module or '').split('.')[0] == 'app':
                found.append((node.lineno, f'from {node.module} import ...'))
        return found

    def test_no_test_file_imports_the_app_module_at_top_level(self):
        offenders = []
        for path in sorted((REPO_ROOT / 'tests').rglob('*.py')):
            if '__pycache__' in str(path):
                continue
            offenders += [(path, hit) for hit in self._module_level_app_imports(path)]
        assert not offenders, [
            f'{path.relative_to(REPO_ROOT)}:{line} imports the application at module level, which '
            'collection does before any fixture — take the app_module fixture (or import inside the '
            'test) so the app is imported by something that runs after the harness is in place'
            for path, (line, _) in offenders
        ]

    def test_the_app_singleton_itself_writes_inside_the_throwaway_root(self, data_root, app_module):
        """The other half: the captured string, not the Config attribute it came from.

        Asserted against the live singleton rather than against ``Config``, because it is
        ``cookie_manager.cookie_dir`` that a cookie save actually writes through — and that is the
        value a too-early import would have frozen onto the user's directory.
        """
        from pathlib import Path as _Path

        captured = _Path(app_module.cookie_manager.cookie_dir).resolve()
        assert captured.is_relative_to(data_root.resolve()), (
            f'the application under test writes cookies to {captured}, outside the throwaway root '
            f'{data_root} — something captured the real path before the harness redirected it'
        )


class _FakeConfig:
    """Stands in for ``session.config`` with the one attribute the hook reaches for.

    Deliberately has **no** ``workerinput`` — that is how the hook tells a controller from an
    xdist worker, and a fake that defined it would take the raise-instead-of-report branch.
    """

    class _Plugins:
        def getplugin(self, _name):
            return None

    pluginmanager = _Plugins()


class _FakeSession:
    def __init__(self):
        self.exitstatus = pytest.ExitCode.OK
        self.config = _FakeConfig()


class TestUserDirectoryStaysReadOnly:
    """The suite reads the user's ``data/`` (cookies, profiles) and must never write to it.

    This is the guard that does not depend on anybody remembering an import rule. It exists because
    the same accident happened twice: paths captured at import time land on the real directory when
    the redirect arrives too late, and once the app's singletons hold a real path, no fixture can
    move them again — a cookies test then overwrote and deleted saved cookies while the suite said
    green. Two halves, both under test here: :func:`_isolate_paths` runs at conftest import (before
    collection), and :func:`pytest_sessionfinish` compares the two directories at the end.
    """

    def _every_captured_path(self) -> dict:
        """Each place a module-level singleton wrote down a path, as it stands right now."""
        import sys

        import settings_store
        from analyzers import ml_base
        from config import Config

        found = {
            'Config.DATA_DIR': Config.DATA_DIR,
            'Config.COOKIE_DIR': Config.COOKIE_DIR,
            'Config.EXPORT_DIR': Config.EXPORT_DIR,
            'Config.WORKFLOW_DIR': Config.WORKFLOW_DIR,
            'Config.LLM_CHECKPOINT_DIR': Config.LLM_CHECKPOINT_DIR,
            'Config.BROWSER_PROFILE_DIR': Config.BROWSER_PROFILE_DIR,
            'Config.LOG_DIR': Config.LOG_DIR,
            'Config.RUNS_DB': Config.RUNS_DB,
            'Config.DATASETS_DB': Config.DATASETS_DB,
            'settings_store._PATH': settings_store._PATH,
            'ml_base.MODEL_DIR': ml_base.MODEL_DIR,
        }
        app = sys.modules.get('app')
        if app is not None:
            # Only reachable once some test has taken the app_module fixture — which is the moment
            # the two singletons below freeze their paths, so when it has happened it must have
            # happened against the throwaway root.
            found['app.cookie_manager.cookie_dir'] = app.cookie_manager.cookie_dir
            found['app.history_service.db_path'] = app.history_service.db_path
        return found

    def test_every_path_captured_at_import_points_at_the_throwaway_root(self, data_root):
        outside = {
            name: str(value)
            for name, value in self._every_captured_path().items()
            if not Path(str(value)).resolve().is_relative_to(data_root.resolve())
        }
        assert not outside, (
            f'these captured a path outside the isolated root {data_root}: {outside} — a test that '
            'writes through any of them is writing into the user directory'
        )

    def test_the_diff_reports_what_appeared_vanished_or_moved(self):
        import isolation_guard

        before = {
            'data/a.json': ('file', 10, 111),
            'data/gone.json': ('file', 5, 222),
            'data/same.json': ('file', 7, 333),
            'data/chrome_profile/weibo': ('profile', 0, 0),
        }
        now = {
            'data/a.json': ('file', 10, 111),
            'data/new.json': ('file', 4, 444),
            'data/same.json': ('file', 7, 999),  # rewritten to the same size
            'data/chrome_profile/weibo': ('profile', 0, 0),
        }
        added, removed, changed = isolation_guard.diff(before, now)
        assert added == ['data/new.json'], added
        assert removed == ['data/gone.json'], removed
        assert changed == ['data/same.json'], changed
        assert isolation_guard.diff(before, before) == ([], [], []), 'a clean run must say nothing'

    def test_the_check_itself_is_quiet_on_a_read_only_session(self):
        """Fingerprinting ``data/`` twice, with nothing but reads in between, must say nothing.

        The live tier opens the user's real cookie files and profile markers; if merely reading
        them moved an entry, the guard would cry wolf every run and be silenced within a week.
        """
        import isolation_guard

        first = isolation_guard.fingerprint()
        for key, tag in list(first.items())[:20]:
            path = REPO_ROOT / key
            if tag[0] == 'file' and path.is_file():
                # A Chrome profile file can be locked by a browser the user has open; skipping it
                # costs this check nothing, since it is the *fingerprint* that must not move.
                with contextlib.suppress(OSError):
                    path.read_bytes()
        assert isolation_guard.diff(first, isolation_guard.fingerprint()) == ([], [], [])

    def test_a_leak_fails_the_run_and_names_the_path(self, capsys):
        """A leak must change the exit status, because a green line next to it is invisible.

        Verified end to end once by hand — a throwaway test writing ``data/_guard_probe.json`` made
        a run report ``1 passed`` and still exit 1, naming that file. Proved here without writing
        anything into the user directory.
        """
        import isolation_guard

        session = _FakeSession()
        clean = isolation_guard.enforce(session, {'data/_never_written.json': ('file', 1, 1)})
        assert clean is False, 'a missing file was not reported as a leak'
        assert session.exitstatus == pytest.ExitCode.TESTS_FAILED, 'a leak did not fail the run'
        err = capsys.readouterr().err
        assert 'data/_never_written.json' in err, err
        assert isolation_guard.REPORT_HEADLINE in err, err

    def test_a_clean_session_leaves_the_exit_status_alone(self, capsys):
        import isolation_guard

        session = _FakeSession()
        assert isolation_guard.enforce(session, isolation_guard.fingerprint()) is True
        assert session.exitstatus == pytest.ExitCode.OK
        assert isolation_guard.REPORT_HEADLINE not in capsys.readouterr().err

    def test_an_app_imported_before_any_fixture_still_sees_the_throwaway_root(self):
        """The ordering itself, proved in fresh interpreters rather than argued.

        Two children, differing only in whether conftest was imported first: one sees the throwaway
        cookie directory, the other sees the real one. That difference is the whole incident — a
        module-level ``from app import ...`` is exactly "conftest first, then app", and the second
        child is what the harness used to answer. Importing ``config`` writes nothing beyond
        ``makedirs(exist_ok=True)`` on directories that already exist, so the comparison is made
        without opening the application or touching the user's files.
        """
        import subprocess

        def run(source: str) -> dict:
            out = subprocess.run([sys.executable, '-c', source], capture_output=True, text=True, timeout=180)
            assert out.returncode == 0, out.stderr[-1500:]
            return json.loads(out.stdout.strip().splitlines()[-1])

        paths = f'sys.path[:0] = [{str(TESTS_DIR)!r}, {str(REPO_ROOT / "backend")!r}]'
        isolated = run(
            '\n'.join(
                (
                    'import json, sys',
                    paths,
                    'import conftest',
                    'from config import Config',
                    'print(json.dumps({"cookies": Config.COOKIE_DIR, "root": str(conftest.ISOLATED_ROOT)}))',
                )
            )
        )
        plain = run(
            '\n'.join(
                (
                    'import json, sys',
                    paths,
                    'from config import Config',
                    'print(json.dumps({"cookies": Config.COOKIE_DIR}))',
                )
            )
        )
        root = Path(isolated['root']).resolve()
        assert Path(isolated['cookies']).resolve().is_relative_to(root), (
            f'conftest no longer redirects before an early import: {isolated["cookies"]} is outside {root}'
        )
        assert not Path(plain['cookies']).resolve().is_relative_to(root), (
            'a bare config import answered the throwaway root, so the comparison above measured '
            'nothing and this case can no longer catch the incident it exists for'
        )

    def test_the_conftest_hook_is_the_side_that_holds_the_import_time_fingerprint(self):
        """The half that cannot move into a module: pytest has to call it, at both ends of the run.

        Read statically for the same reason the app-import rule is: importing ``conftest`` from a
        test reaches whichever of this tree's four conftest files was collected last, not this one.
        """
        source = (TESTS_DIR / 'conftest.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        names = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assert 'pytest_sessionfinish' in names, 'the session-finish hook is gone from conftest'
        assert 'PROTECTED_AT_IMPORT = _fingerprint_protected()' in source, (
            'the fingerprint must be taken at conftest import, before collection imports any test '
            'module — a fixture is too late for a path a singleton already captured'
        )
        assert 'enforce(session, PROTECTED_AT_IMPORT)' in source, 'the hook no longer consults the guard'


class TestLiveCrawlerFixture:
    """The helper that holds a platform's turn is under test too — with no browser.

    A case that asks for a second browser of a platform it is *still* holding parks inside
    the gate for ``Config.PLATFORM_GATE_TIMEOUT`` — 900 seconds that look exactly like a
    slow crawl, because the wait happens before the browser exists. That is a property of
    this fixture rather than of any site, so it is checked by driving the fixture itself
    with both ends replaced: :func:`crawl_gate.hold` becomes a recorder that refuses an
    overlapping turn, and ``get_crawler`` a stub that closes on command.
    """

    def _drive(self, monkeypatch, raises=None):
        import contextlib
        import importlib.util

        import crawl_gate

        import crawlers

        spec = importlib.util.spec_from_file_location('live_conftest_under_test', LIVE_DIR / 'conftest.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        monkeypatch.setattr(module, 'has_cookie', lambda platform: True)

        held: list = []
        events: list = []

        @contextlib.contextmanager
        def fake_hold(platform, log=None, abort=None):
            if platform in held:
                raise AssertionError(f'{platform} held twice by one thread: the next crawler parks in the gate')
            held.append(platform)
            events.append(f'take:{platform}')
            try:
                yield False
            finally:
                held.remove(platform)
                events.append(f'give:{platform}')

        class Stub:
            def __init__(self, platform, use_profile=None):
                self.platform = platform
                self.use_profile = use_profile
                self.closed = False

            def close(self):
                self.closed = True

        made: list = []

        def fake_get_crawler(platform, headless=True, cookie_dir=None, use_profile=None):
            if isinstance(raises, Exception):
                raise raises
            stub = Stub(platform, use_profile)
            made.append(stub)
            return stub

        monkeypatch.setattr(crawl_gate, 'hold', fake_hold)
        monkeypatch.setattr(crawlers, 'get_crawler', fake_get_crawler)
        # ``__wrapped__`` is the undecorated generator function: pytest refuses to have a
        # fixture called directly, and it is right — but driving the helper's own body is
        # exactly what this class is for, so the decoration is taken off rather than the
        # tier rewritten to need a browser.
        fixture = getattr(module.live_crawler, '__wrapped__', None)
        assert fixture is not None, 'pytest stopped exposing the undecorated fixture'
        generator = fixture('cookies')
        factory = next(generator)

        def finish():
            next(generator, None)

        return factory, events, made, finish

    def test_asking_twice_for_one_platform_hands_the_turn_back_first(self, monkeypatch):
        factory, events, made, finish = self._drive(monkeypatch)
        try:
            first = factory('zhihu')
            second = factory('zhihu')
            assert events == ['take:zhihu', 'give:zhihu', 'take:zhihu'], events
            assert first.closed, 'the crawler it replaced was left holding a browser'
            assert second is not first and not second.closed
        finally:
            finish()

    def test_two_platforms_may_be_held_at_once(self, monkeypatch):
        # The gate is keyed by platform; a helper that released a *different* platform's
        # turn to make room would take the tier's fidelity back out again.
        factory, events, _made, finish = self._drive(monkeypatch)
        try:
            factory('zhihu')
            factory('weibo')
            assert events == ['take:zhihu', 'take:weibo'], events
        finally:
            finish()

    def test_releasing_by_hand_returns_the_turn_once(self, monkeypatch):
        factory, events, _made, finish = self._drive(monkeypatch)
        try:
            crawler = factory('zhihu')
            factory.release(crawler)
            factory.release(crawler)  # a double release must not give back someone else's turn
            assert events == ['take:zhihu', 'give:zhihu'], events
        finally:
            finish()

    def test_the_teardown_gives_back_what_the_test_never_released(self, monkeypatch):
        factory, events, made, finish = self._drive(monkeypatch)
        factory('zhihu')
        finish()
        assert events == ['take:zhihu', 'give:zhihu'], events
        assert made[0].closed, 'a crawler left open by a test still has to be closed'

    def test_a_profile_held_by_this_tier_stays_red_instead_of_skipping(self, monkeypatch):
        """The one failure mode this fixture must NOT report as "no browser here".

        A profile the previous case has not finished closing raises `ProfileUnavailable`
        after `PROFILE_LOCK_TIMEOUT`, which arrives through the same `Exception` as a
        missing Chrome — and skipping it would turn a serialization bug in this tier into
        a grey line in a run the user is told must be all-green. Seen for real when the
        device + live tiers ran back to back and a 热榜 case skipped for that reason.
        """
        from crawlers.base import ProfileUnavailableError

        factory, _events, _made, finish = self._drive(monkeypatch, raises=ProfileUnavailableError('profile held'))
        with pytest.raises(ProfileUnavailableError):
            factory('weibo')
        finish()

    def test_a_case_may_ask_for_no_profile_and_is_honoured(self, monkeypatch):
        """The boards are measured on a throwaway browser, so their cases have to be able
        to say so; a fixture that dropped the argument would quietly run them on the
        user's real profile instead."""
        factory, _events, made, finish = self._drive(monkeypatch)
        try:
            factory('weibo', use_profile=False)
        finally:
            finish()
        assert made[-1].use_profile is False, 'the request to skip the profile was dropped'
