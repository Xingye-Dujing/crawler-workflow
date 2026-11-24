"""The frontend's one-file budget: a browser module that carries too many jobs is split, not waived.

Measured before W5: ``ai-workspace.js`` was 4,446 lines and held the SSE decoder, the routes, the
transcript, the composer, the sidebar and the studios. The rule this gate enforces is the one that
change was made for, and the self-tests below prove the gate can say no — a checker pointed only at
the real tree would pass just as well if its comparison were broken.

The declaration (budget, measured scope, generated exemptions) lives in ``tests/js_budget.py`` so a
later slice widens it in one place instead of editing this module.
"""

from pathlib import Path

import pytest
from js_budget import BUDGET, GENERATED, SCOPE, line_count, measured_files, relative, violations

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[3]
JS_DIR = ROOT / 'backend' / 'static' / 'js'


class TestTheWorkspaceTreeFitsItsBudget:
    def test_every_measured_module_is_under_the_budget(self):
        paths = measured_files()
        assert len(paths) >= 20, (
            f'the scan saw only {len(paths)} modules — a lost splits.json entry shrinks the measured '
            f'tree instead of failing: {[relative(path) for path in paths]}'
        )
        assert violations(paths) == [], (
            'a browser module carries too many jobs for one file; split it instead of raising the budget'
        )

    def test_the_scan_covers_the_entry_and_its_split_outs(self):
        """The closure, not the entry file: a split that is not measured is a budget nobody enforces."""

        names = {relative(path) for path in measured_files()}
        for expected in (
            'ai-workspace.js',
            'ai/kernel/store.js',
            'ai/kernel/sse.js',
            'ai/kernel/http.js',
            'ai/kernel/dom.js',
            'ai/features/chat.js',
            'ai/render/markdown.js',
            'ai/render/toolcard.js',
        ):
            assert expected in names, f'{expected} is not measured; the scan is {sorted(names)}'

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
        assert SCOPE == ('ai-workspace.js',), 'a second scope entry belongs in splits.json, not here'


class TestTheGateCanFail:
    """Synthetic files: the same checker, a tree that is wrong on purpose."""

    @staticmethod
    def _write(directory: Path, name: str, lines: int) -> Path:
        path = directory / name
        path.write_text('\n'.join(f'/* line {index} */' for index in range(1, lines + 1)) + '\n', encoding='utf-8')
        return path

    def test_a_file_over_the_budget_is_reported_by_name(self, tmp_path):
        too_long = self._write(tmp_path, 'monolith.js', BUDGET + 1)

        assert violations([too_long]) == [f'monolith.js: {BUDGET + 1} lines']

    def test_a_file_exactly_on_the_budget_passes(self, tmp_path):
        at_budget = self._write(tmp_path, 'fits.js', BUDGET)

        assert line_count(at_budget) == BUDGET
        assert violations([at_budget]) == []

    def test_the_line_count_is_physical_lines_not_bytes(self, tmp_path):
        """A 3-line file with long lines is 3 lines; a byte budget would have called it fat."""

        path = tmp_path / 'wide.js'
        path.write_text('\n'.join(['/* ' + 'x' * 400 + ' */'] * 3) + '\n', encoding='utf-8')

        assert line_count(path) == 3
        assert violations([path]) == []

    def test_a_generated_file_is_exempt_by_name_even_when_it_is_huge(self, tmp_path):
        """The exemption is a name in one tuple; the checker honours it, the tuple is what a reader audits."""

        assert GENERATED == ('zenviz-page.js', 'node-types-fallback.js'), (
            'a new exemption is a decision: declare it in tests/js_budget.py with its reason'
        )
        huge = self._write(tmp_path, 'zenviz-page.js', BUDGET * 4)

        assert measured_files() and not any(path.name in GENERATED for path in measured_files())
        assert violations([huge]) == [f'zenviz-page.js: {BUDGET * 4} lines'], (
            'the raw checker measures everything; the exemption is applied where a scope is resolved'
        )

    def test_an_honest_split_moves_the_budget(self, tmp_path):
        """The failure is not the length of the whole tree but of one file: two halves both pass."""

        first = self._write(tmp_path, 'half-a.js', BUDGET - 10)
        second = self._write(tmp_path, 'half-b.js', BUDGET - 10)

        assert violations([first, second]) == []
        assert line_count(first) + line_count(second) > BUDGET
