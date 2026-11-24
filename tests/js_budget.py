"""One JS module, one budget — declared here, once.

A module that carries several jobs is where a defect hides: the 4,446-line ``ai-workspace.js`` held the
state, the stream decoder, the routes, the transcript and the studios at the same time, and a change in
one of them was reviewed as a change in all of them. The rule is therefore mechanical: **a module the
browser loads is at most ``BUDGET`` lines, or it is split.**

Two things a reader must be able to trust about this scan:

* ``SCOPE`` is the ONE place the measured tree is declared. W5 starts with the AI workspace layer
  (``ai-workspace.js`` plus every file ``tests/frontend/splits.json`` splits out of it, transitively).
  A later slice widens the scope here, never by adding a file name to a test.
* ``GENERATED`` names the two rendered modules (the Chart Studio bundle and the node-types fallback).
  Machine-written bytes cannot be hand-split, so they are exempt BY NAME — an exemption is a name in
  this tuple, never a pattern that would also excuse a hand-written file that grew.
"""

from pathlib import Path

from static_assets import JS_DIR

#: The line budget for one browser module.
BUDGET = 600

#: Rendered files: nobody edits them by hand, so nobody splits them by hand.
GENERATED = (
    'zenviz-page.js',
    'node-types-fallback.js',
)

#: The trees measured today, each named the way ``js/`` spells them.
SCOPE = ('ai-workspace.js',)


def measured_files(scope: tuple[str, ...] = SCOPE) -> list[Path]:
    """Every module in the scope's split closure, in page order, minus the generated ones."""

    from static_assets import js_files

    seen: list[Path] = []
    for name in scope:
        for path in js_files(name):
            if path.name in GENERATED or path in seen:
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


def relative(path: Path) -> str:
    """The module's name as ``index.html`` and ``splits.json`` spell it."""

    return Path(path).relative_to(JS_DIR).as_posix()
