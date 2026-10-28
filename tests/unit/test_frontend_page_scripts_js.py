"""The page's script list is the single source of load order — and it must be complete.

``tests/frontend/page_scripts.mjs`` reads ``<script src="/js/…">`` out of ``index.html``
so a harness never keeps a second copy of the module list. That only helps if the page
itself lists every module: a new file that nobody references would load in the browser
nowhere and in the harness nowhere, and both would stay green. So the questions are asked
in both directions — every script the page names exists, every module on disk is named by a
page — and then of the harnesses: no private list, and the worlds they boot are loaded
through the page.
"""

import json
import re
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

pytestmark = [pytest.mark.unit, pytest.mark.skipif(shutil.which('node') is None, reason='node not on PATH')]

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

    def test_selecting_app_js_also_loads_the_catalogue_it_merges(self, tmp_path):
        """app.js without its data is an app with no words — every ``t()`` would echo the key.

        The rule lives in the loader so no harness can forget it; this proves the loader applies it
        with a synthetic page rather than trusting the shipped one to already be split.
        """
        js = tmp_path / 'js'
        (js / 'i18n').mkdir(parents=True)
        (js / 'i18n' / 'chrome.js').write_text(
            'globalThis.SEEN = (globalThis.SEEN || []).concat("chrome");', encoding='utf-8'
        )
        (js / 'app.js').write_text('globalThis.SEEN = (globalThis.SEEN || []).concat("app");', encoding='utf-8')
        page = tmp_path / 'index.html'
        page.write_text(
            '<script src="/js/i18n/chrome.js"></script><script src="/js/app.js"></script>',
            encoding='utf-8',
        )
        driver = tmp_path / 'driver.mjs'
        loader = (REPO / 'tests' / 'frontend' / 'page_scripts.mjs').as_posix()
        driver.write_text(
            "import vm from 'node:vm';\n"
            "import { pathToFileURL } from 'node:url';\n"
            f'const {{ loadPageScripts }} = await import(pathToFileURL({loader!r}).href);\n'
            'const sandbox = { console };\n'
            'vm.createContext(sandbox);\n'
            f'const loaded = loadPageScripts(sandbox, {{ jsDir: {str(js)!r}, only: ["app.js"], '
            f'indexHtml: {str(page)!r} }});\n'
            'process.stdout.write(JSON.stringify(loaded));\n',
            encoding='utf-8',
        )
        answer = run_node(str(driver))
        assert answer.returncode == 0, answer.stderr[-400:]
        # page order — and the catalogue comes along although only app.js was named
        assert json.loads(answer.stdout) == ['i18n/chrome.js', 'app.js'], answer.stdout

    def test_the_loader_reads_this_page_rather_than_a_checked_in_list(self):
        loader = (REPO / 'tests' / 'frontend' / 'page_scripts.mjs').read_text(encoding='utf-8')
        assert 'index.html' in loader
        assert re.search(r'<script\\b', loader), 'the loader must parse <script> tags, not name files itself'

    def test_no_harness_keeps_a_private_list_of_product_modules(self):
        """A hand-written ``FILES`` array is a second opinion about the page — and its ORDER is a
        second opinion too. Four harnesses had one, and every one of them put ``custom-select.js``
        before ``workflow.js`` while the page loads them the other way round, so those scenarios
        evaluated a boot order no browser ever runs. A harness may still read a module's SOURCE
        (the catalogue and contract cases do); it may not decide for itself which product scripts to
        evaluate, because that list goes stale silently the day a module is split.
        """
        offenders = [
            path.name
            for path in sorted((REPO / 'tests' / 'frontend').glob('harness_*.mjs'))
            if re.search(r'\bFILES\s*=\s*\[', path.read_text(encoding='utf-8'))
        ]
        assert offenders == [], f'harnesses with a hand-maintained module list: {offenders}'

    def test_the_harnesses_that_boot_a_world_ask_the_page_for_the_order(self):
        """The replacement for the deleted lists: importing the loader is what says so."""
        users = [
            path.name
            for path in sorted((REPO / 'tests' / 'frontend').glob('harness_*.mjs'))
            if 'loadPageScripts' in path.read_text(encoding='utf-8')
        ]
        # 2026-10-28: app / comment-region-notice / cookie-gate / data-preview / dialog-a11y /
        # palette / profiles. The floor, not the exact set: a new multi-module harness should join
        # this group, and a deleted one must not silently leave the rule covering nothing.
        assert len(users) >= 7, f'only these harnesses use the page loader: {users}'
