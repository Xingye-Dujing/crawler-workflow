"""Behaviour tests for the real left-palette filter (app.js: filterPalette).

Palette search is DOM-only and invisible to Python without a harness: this loads
custom-select.js + workflow.js + app.js (the same trio app.js boots against, in index.html's
order), builds a small palette, and checks that filterPalette narrows items by type/tag/label
and hides a category once nothing under it survives. See tests/frontend/harness_palette.mjs.

Skipped when node is not on PATH, like every other frontend harness.
"""

import json
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(shutil.which('node') is None, reason='node not installed'),
]

JS_DIR = Path(__file__).resolve().parents[3] / 'backend' / 'static' / 'js'
HARNESS = Path(__file__).resolve().parents[2] / 'frontend' / 'harness_palette.mjs'


@pytest.fixture(scope='module')
def pal():
    proc = run_node(str(HARNESS), str(JS_DIR))
    assert proc.returncode == 0, f'palette harness failed: {proc.stderr[-2000:]}: {proc.stdout[-2000:]}'
    return json.loads(proc.stdout)


class TestPaletteFilter:
    def test_empty_query_keeps_every_item_and_category(self, pal):
        assert pal['(empty)']['types'] == sorted(['name', 'source', 'upload', 'process', 'visualize', 'output'])
        assert pal['(empty)']['visibleCats'] == 4, 'every heading is visible when nothing is filtered'

    def test_query_narrows_to_the_matching_type(self, pal):
        assert pal['process']['types'] == ['process']
        assert pal['process']['visibleCats'] == 1, 'only the Processing heading should survive'

    def test_a_tag_abbreviation_matches_regardless_of_language(self, pal):
        """ "src"/"out" hit the [SRC]/[OUT] tags, not just the English label — a Chinese panel
        keeps answering an English fragment typed into the finder."""
        assert pal['src']['types'] == ['source']
        assert pal['out']['types'] == ['output']

    def test_no_match_hides_items_and_their_categories(self, pal):
        assert pal['xyz-nothing']['types'] == []
        assert pal['xyz-nothing']['visibleCats'] == 0, 'an emptied category must not linger as a heading'
