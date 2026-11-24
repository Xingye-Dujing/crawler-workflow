"""The frontend's one-file budget: a browser module that carries too many jobs is split, not waived.

Measured before W5: ``ai-workspace.js`` was 4,446 lines and held the SSE decoder, the routes, the
transcript, the composer, the sidebar and the studios. The rule this gate enforces is the one that
change was made for, and the self-tests below prove the gate can say no — a checker pointed only at
the real tree would pass just as well if its comparison were broken.

The declaration (budget, measured page, generated exemptions, the frozen ratchet) lives in
``tests/js_budget.py`` so a later slice widens it in one place instead of editing this module.
"""

from pathlib import Path

import pytest
from js_budget import BUDGET, FROZEN, GENERATED, PAGE, line_count, measured_files, overruns, relative, stale

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[3]
JS_DIR = ROOT / 'backend' / 'static' / 'js'


class TestThePageTreeFitsItsBudget:
    def test_every_measured_module_is_under_the_budget_or_frozen(self):
        paths = measured_files()
        assert len(paths) >= 60, (
            f'the scan saw only {len(paths)} modules — a lost splits.json entry shrinks the measured '
            f'tree instead of failing: {[relative(path) for path in paths]}'
        )
        assert overruns(paths) == [], (
            'a browser module carries too many jobs for one file; split it instead of raising the budget'
        )

    def test_the_scan_is_the_whole_page_not_one_layer(self):
        """Widened from the AI workspace to every module ``index.html`` boots, and it says so."""

        names = {relative(path) for path in measured_files()}
        for expected in (
            'ai-workspace.js',
            'ai/kernel/http.js',
            'ai/features/studio.js',
            'canvas.js',
            'workflow.js',
            'panels/runs.js',
            'accounts.js',
            'app.js',
        ):
            assert expected in names, f'{expected} is not measured; the scan is {sorted(names)}'

    def test_data_and_rendered_files_are_not_measured(self):
        """A translation catalogue grows one line per string; a rendered bundle cannot be split."""

        names = {relative(path) for path in measured_files()}
        assert not any(name.startswith('i18n/') for name in names), sorted(names)
        assert not any(name in GENERATED for name in names)

    def test_the_entry_file_is_wiring_not_a_monolith(self):
        """``ai-workspace.js`` keeps the boot and the markup wrappers; every surface lives elsewhere."""

        assert line_count(JS_DIR / 'ai-workspace.js') < 300, (
            'the entry file grew back into a surface: move the behaviour to the file that owns it'
        )

    def test_no_measured_file_is_empty(self):
        """An empty module is a split that moved nothing; the scan must not count it as a pass."""

        empty = [relative(path) for path in measured_files() if line_count(path) == 0]
        assert empty == [], f'measured modules with no content: {empty}'

    def test_the_scope_is_the_one_declaration(self):
        assert PAGE.name == 'index.html', 'the measured tree is the page the browser boots, declared once'

    def test_a_frozen_module_did_not_grow(self):
        assert FROZEN, 'the ratchet list is empty: every module would have to fit in one change'
        assert all(size > BUDGET for size in FROZEN.values()), (
            'a freeze exists because the module is over the ceiling; one that fits is an ordinary module'
        )

    def test_a_freeze_that_fell_far_below_is_lowered(self):
        paths = measured_files()
        assert stale(paths) == [], 'lower the recorded freeze so the file cannot grow back into the space a split freed'

    def test_every_freeze_names_a_measured_module(self):
        names = {relative(path) for path in measured_files()}
        assert sorted(set(FROZEN) - names) == [], 'the ratchet names files the page no longer loads'


class TestTheGateCanFail:
    """Synthetic files: the same checker, a tree that is wrong on purpose."""

    @staticmethod
    def _write(directory: Path, name: str, lines: int) -> Path:
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('\n'.join(f'/* line {index} */' for index in range(1, lines + 1)) + '\n', encoding='utf-8')
        return path

    def test_a_file_over_the_budget_is_reported_by_name(self, tmp_path):
        too_long = self._write(tmp_path, 'monolith.js', BUDGET + 1)

        assert overruns([too_long], {}) != []
        assert line_count(too_long) == BUDGET + 1

    def test_a_file_exactly_on_the_budget_passes(self, tmp_path):
        at_budget = self._write(tmp_path, 'fits.js', BUDGET)

        assert line_count(at_budget) == BUDGET
        assert overruns([at_budget], {}) == []

    def test_the_line_count_is_physical_lines_not_bytes(self, tmp_path):
        """A 3-line file with long lines is 3 lines; a byte budget would have called it fat."""

        path = tmp_path / 'wide.js'
        path.write_text('\n'.join(['/* ' + 'x' * 400 + ' */'] * 3) + '\n', encoding='utf-8')

        assert line_count(path) == 3
        assert overruns([path], {}) == []

    def test_a_generated_file_is_exempt_by_name_even_when_it_is_huge(self, tmp_path):
        """The exemption is a name in one tuple; the checker honours it, the tuple is what a reader audits."""

        assert GENERATED == ('zenviz-page.js', 'node-types-fallback.js'), (
            'a new exemption is a decision: declare it in tests/js_budget.py with its reason'
        )
        huge = self._write(tmp_path, 'zenviz-page.js', BUDGET * 4)

        assert measured_files() and not any(path.name in GENERATED for path in measured_files())
        assert overruns([huge], {}) == [f'zenviz-page.js: {BUDGET * 4} lines'], (
            'the raw checker measures everything; the exemption is applied where the scope is resolved'
        )

    def test_a_frozen_file_may_only_shrink(self, tmp_path):
        """The ratchet's two answers: at or under the frozen number passes, one line over is a defect."""

        path = self._write(tmp_path, 'canvas.js', 700)

        assert overruns([path], {'canvas.js': 700}) == []
        assert overruns([path], {'canvas.js': 699}) == ['canvas.js: 700 > 699']

    def test_an_honest_split_moves_the_budget(self, tmp_path):
        """The failure is not the length of the whole tree but of one file: two halves both pass."""

        first = self._write(tmp_path, 'half-a.js', BUDGET - 10)
        second = self._write(tmp_path, 'half-b.js', BUDGET - 10)

        assert overruns([first, second], {}) == []
        assert line_count(first) + line_count(second) > BUDGET
