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
from pathlib import Path

import pytest

from crawl_capabilities import CAPABILITIES

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTEST_INI = REPO_ROOT / 'pytest.ini'
LIVE_DIR = REPO_ROOT / 'tests' / 'live_site'

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
    """(path, module markers, {test name: (is quick, platforms it crawls)}) per live file."""
    out = []
    for path in sorted(LIVE_DIR.glob('test_*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        module_marks = set()
        literals = {}
        called = {}
        quick = {}
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
                    marks = set()
                    for dec in node.decorator_list:
                        marks |= _marker_names(dec)
                    quick[node.name] = bool(marks & {'live_quick'}) or _quick_marks_inside(
                        ast.Module(body=[node], type_ignores=[])
                    )
        platforms = {name: _platforms_of(name, literals, called) for name in quick}
        out.append((path, module_marks, {name: (is_quick, platforms[name]) for name, is_quick in quick.items()}))
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
            for name, (is_quick, _platforms) in tests.items()
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
            for is_quick, platforms in tests.values():
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
            for name, (is_quick, _platforms) in tests.items()
            if is_quick and 'live_site' not in module_marks
        ]
        assert not offenders, f'marked quick but not live: {offenders}'

    def test_no_module_marks_itself_quick_wholesale(self):
        """A module-level marker makes *every* case in it part of the daily tier,
        which is how a short tier silently becomes the long one again."""
        wholesale = [path.name for path, module_marks, _tests in _live_files() if 'live_quick' in module_marks]
        assert not wholesale, f'module-level live_quick in {wholesale}; mark one representative instead'
