"""The page's script list is the single source of load order — and it must be complete.

``tests/frontend/page_scripts.mjs`` reads ``<script src="/js/…">`` out of ``index.html``
so a harness never keeps a second copy of the module list. That only helps if the page
itself lists every module: a new file that nobody references would load in the browser
nowhere and in the harness nowhere, and both would stay green. These cases ask the two
questions in opposite directions — every script the page names exists, and every module
on disk is named by a page.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
STATIC = REPO / 'backend' / 'static'
INDEX = STATIC / 'index.html'
STUDIO = STATIC / 'zenviz.html'
JS_DIR = STATIC / 'js'

PAGE_SCRIPT = re.compile(r'<script\b[^>]*\bsrc="(/js/[^"]+)"')


def _page_scripts(page: Path) -> list[str]:
    return [src.rsplit('/', 1)[1] for src in PAGE_SCRIPT.findall(page.read_text(encoding='utf-8'))]


class TestThePageListsItsOwnModules:
    def test_every_script_the_page_loads_exists_on_disk(self):
        missing = [name for name in _page_scripts(INDEX) if not (JS_DIR / name).is_file()]
        assert missing == [], f'index.html loads scripts that are not in backend/static/js: {missing}'

    def test_every_module_is_loaded_by_a_page(self):
        """A module loaded by neither page is dead code whose tests would still pass."""
        loaded = set(_page_scripts(INDEX)) | set(_page_scripts(STUDIO))
        on_disk = {path.name for path in JS_DIR.glob('*.js')}
        assert on_disk - loaded == set(), f'frontend modules no page loads: {sorted(on_disk - loaded)}'

    def test_the_chart_studio_bridge_is_loaded_by_the_studio_not_the_workbench(self):
        """The bridge talks to the iframe's `window`; loaded on the workbench it is noise at best."""
        assert 'zenviz-bridge.js' in _page_scripts(STUDIO)
        assert 'zenviz-bridge.js' not in _page_scripts(INDEX)

    def test_the_loader_reads_this_page_rather_than_a_checked_in_list(self):
        loader = (REPO / 'tests' / 'frontend' / 'page_scripts.mjs').read_text(encoding='utf-8')
        assert 'index.html' in loader
        assert re.search(r'<script\\b', loader), 'the loader must parse <script> tags, not name files itself'
