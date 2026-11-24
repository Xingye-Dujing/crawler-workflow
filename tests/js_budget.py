"""One JS module, one budget — declared here, once.

A module that carries several jobs is where a defect hides: the 4,446-line ``ai-workspace.js`` held the
state, the stream decoder, the routes, the transcript and the studios at the same time, and a change in
one of them was reviewed as a change in all of them. The rule is therefore mechanical: **a module the
browser loads is at most ``BUDGET`` lines, or it is split.**

Three things a reader must be able to trust about this scan:

* ``PAGE`` is the ONE place the measured tree is declared: the modules ``index.html``'s ``<script>``
  lines name, plus every file ``tests/frontend/splits.json`` splits out of them. A file the browser
  loads and the page does not name cannot exist, so this needs no second list.
* ``GENERATED`` names the two rendered modules (the Chart Studio bundle and the node-types fallback).
  Machine-written bytes cannot be hand-split, so they are exempt BY NAME — an exemption is a name in
  this tuple, never a pattern that would also excuse a hand-written file that grew.
* ``FROZEN`` is the ratchet. Fifteen hand-written modules were already over the ceiling when the scan
  widened from the AI layer to the whole page; forcing them all to shrink in one change would be a
  rewrite, so each is frozen at its current size and may only get smaller (`tests/unit/gates/
  test_module_budget.py` is the same rule for Python).
"""

from pathlib import Path

from static_assets import INDEX, JS_DIR

#: The line budget for one browser module.
BUDGET = 600

#: How far below its frozen size a module may fall before the freeze is considered stale.
SLACK = 60

#: The page whose ``<script>`` lines decide the measured tree.
PAGE = INDEX

#: Rendered files: nobody edits them by hand, so nobody splits them by hand.
GENERATED = (
    'zenviz-page.js',
    'node-types-fallback.js',
)

#: Translation catalogues: one line per string, and the product grows by adding strings. A ceiling
#: here would be a gate against translating.
DATA_DIRS = ('i18n/',)

#: Hand-written modules above the ceiling, frozen at their 2026-11-25 size.
#: Lowering a number here is the reward for a split; raising one needs a reason in the review.
FROZEN: dict[str, int] = {
    'canvas.js': 2745,
    'workflow.js': 2305,
    'panels/settings.js': 1471,
    'panels/cookies.js': 1407,
    'chart-preview.js': 1174,
    'panels/data-views.js': 1165,
    'panels/runs.js': 1100,
    'reusable.js': 1037,
    'panels/shell.js': 850,
    'panels/files.js': 847,
    'zenviz.js': 839,
    'custom-select.js': 818,
    'app.js': 757,
    'panels/settings-panel.js': 706,
    'panels/biblio.js': 658,
}


def measured_files(page: Path = PAGE) -> list[Path]:
    """Every module the page boots, in page order, minus the generated and data files."""

    from static_assets import page_js

    seen: list[Path] = []
    for path in page_js(page):
        name = relative(path)
        if path.name in GENERATED or name.startswith(DATA_DIRS) or path in seen:
            continue
        seen.append(path)
    return seen


def line_count(path: Path) -> int:
    """Physical lines as the browser's own file has them (a trailing newline is not a line)."""

    return len(path.read_text(encoding='utf-8').splitlines())


def violations(paths, budget: int = BUDGET) -> list[str]:
    """``name: N lines`` for every path over the budget — the scan's single answer.

    Takes the paths as an argument so the gate can be proved on a synthetic tree: a checker that can
    only be pointed at the real directory cannot show that it would ever say no.
    """

    return [f'{Path(path).name}: {line_count(Path(path))} lines' for path in paths if line_count(Path(path)) > budget]


def overruns(paths, frozen: dict[str, int] = None) -> list[str]:
    """Unfrozen modules over the ceiling, and frozen ones that grew past their recorded size."""

    frozen = FROZEN if frozen is None else frozen
    grown: list[str] = []
    for path in paths:
        size = line_count(Path(path))
        name = module_name(Path(path))
        if name in frozen:
            if size > frozen[name]:
                grown.append(f'{name}: {size} > {frozen[name]}')
        elif size > BUDGET:
            grown.append(f'{name}: {size} lines')
    return sorted(grown)


def stale(paths, frozen: dict[str, int] = None, slack: int = SLACK) -> list[str]:
    """Freezes that fell well under their number: the budget must follow the split down."""

    frozen = FROZEN if frozen is None else frozen
    sizes = {module_name(Path(path)): line_count(Path(path)) for path in paths}
    return sorted(
        f'{name}: budget {budget}, now {sizes[name]}'
        for name, budget in frozen.items()
        if name in sizes and sizes[name] < budget - slack
    )


def module_name(path: Path) -> str:
    """The module's name as the page spells it; a synthetic tree's file is its own basename."""

    try:
        return relative(Path(path))
    except ValueError:
        return Path(path).name


def relative(path: Path) -> str:
    """The module's name as ``index.html`` and ``splits.json`` spell it."""

    return Path(path).relative_to(JS_DIR).as_posix()
