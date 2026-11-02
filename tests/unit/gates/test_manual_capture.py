"""Every figure the manual prints has a way to be shot again — or a stated reason it cannot be.

`docs/manual/shots/capture.py` carries the recipe for each picture (one driver session, one entry per
figure). That table is only worth having if it still matches the book: a figure renamed in a chapter, or
a recipe typed with a name the dispatcher does not know, would otherwise be discovered halfway through a
re-shoot, with 20 pictures already overwritten.

Kept in the same place as the recipes, and read here: :data:`capture.RECIPES` (what can be shot from this
checkout) and :data:`capture.KEPT` (what cannot, with the fact that stops it). The second list is checked
in BOTH directions — a new figure with neither is a failure, and an excuse for a figure the book no longer
prints is a failure too, or the exemption outlives the reason it was written for.
"""

import importlib.util
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
MANUAL = REPO / 'docs' / 'manual'
CAPTURE = MANUAL / 'shots' / 'capture.py'

FIGURE = re.compile(r'\\includegraphics(?:\[[^\]]*\])?\{([^}]*)\}')


def capture_module():
    """The real script, imported (it defines tables and helpers; no driver is created by an import)."""
    spec = importlib.util.spec_from_file_location('manual_capture', CAPTURE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cited_figures() -> set[str]:
    """Every figure stem the chapters print, without the extension `graphicspath` resolves."""
    figures = set()
    for chapter in sorted(MANUAL.glob('*.tex')):
        for name in FIGURE.findall(chapter.read_text(encoding='utf-8')):
            figures.add(Path(name.strip()).stem)
    return figures


class TestTheRecipesCoverTheBook:
    def test_every_printed_figure_is_either_a_recipe_or_a_stated_exception(self):
        capture = capture_module()
        covered = {out for out, _kind, _args in capture.RECIPES} | set(capture.KEPT)
        missing = sorted(cited_figures() - covered)
        assert missing == [], f'figures with no way to be re-shot: {missing}'

    def test_no_exception_outlives_the_figure_it_excused(self):
        """An entry nobody cites any more is dead weight; it would survive a chapter rewrite."""
        capture = capture_module()
        stale = sorted(set(capture.KEPT) - cited_figures())
        assert stale == [], f'kept images the manual no longer prints: {stale}'

    def test_an_exception_says_why_it_exists(self):
        capture = capture_module()
        unexplained = sorted(name for name, why in capture.KEPT.items() if len(str(why).strip()) < 20)
        assert unexplained == [], f'kept images with no stated reason: {unexplained}'

    def test_the_scan_actually_read_the_chapters(self):
        assert len(cited_figures()) > 50


class TestTheRecipeTableIsExecutable:
    def test_figure_names_are_unique(self):
        """Two recipes writing one PNG mean one of the two is silently lost."""
        names = [out for out, _kind, _args in capture_module().RECIPES]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        assert duplicates == [], f'figures shot twice: {duplicates}'

    def test_every_kind_is_one_the_dispatcher_knows(self):
        capture = capture_module()
        unknown = sorted({kind for _out, kind, _args in capture.RECIPES if kind not in capture.KINDS})
        assert unknown == [], f'recipes the dispatcher would refuse mid-batch: {unknown}'

    def test_every_recipe_carries_the_argument_its_kind_needs(self):
        capture = capture_module()
        needs_workflow = {
            'canvas',
            'dark',
            'settings',
            'zoom',
            'node_element',
            'element',
            'chart',
            'dashboard',
            'dashboardzoom',
            'datapreview',
        }
        for out, kind, args in capture.RECIPES:
            if kind in needs_workflow:
                assert args.get('workflow'), f'{out}: no workflow'
            if kind == 'zoom':
                assert args.get('ids'), f'{out}: zoom with no ids'
            if kind == 'dock':
                assert args.get('button'), f'{out}: dock with no button'
            if kind in ('menu', 'element'):
                assert args.get('selector'), f'{out}: {kind} with no selector'

    def test_the_small_canvases_the_book_names_are_real_workflows(self):
        """Only checkable where the checkout has data/ (CI does not ship any runtime state)."""
        folder = REPO / 'data' / 'workflows'
        names = set()
        if folder.is_dir():
            for path in folder.glob('*.json'):
                text = path.read_text(encoding='utf-8', errors='replace')
                match = re.search(r'"name"\s*:\s*"([^"]+)"', text)
                if match:
                    names.add(match.group(1))
        if not names:
            pytest.skip('no data/workflows in this checkout')
        capture = capture_module()
        wanted = sorted({args['workflow'] for _out, _kind, args in capture.RECIPES if args.get('workflow')})
        missing = [name for name in wanted if name not in names]
        assert missing == [], f'recipes naming a workflow this checkout does not have: {missing}'
