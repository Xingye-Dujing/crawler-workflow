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

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / 'backend' / 'static'
INDEX = STATIC / 'index.html'
STUDIO = STATIC / 'zenviz.html'
JS_DIR = STATIC / 'js'

PAGE_SCRIPT = re.compile(r'<script\b[^>]*\bsrc="(/js/[^"]+)"')
# One nesting level of parentheses is all a ``run_node(...)`` call needs to be read whole; if the
# call ever grows past that, the floor below stops reporting a scan that quietly matches nothing.
_RUN_NODE_CALL = re.compile(r'run_node\((?:[^()]|\([^()]*\))*\)')


def _page_scripts(page: Path) -> list[str]:
    """The module names the page loads, relative to ``js/`` — the SAME spelling the loader uses.

    ``i18n/settings.js``, not ``settings.js``: a reader that kept only the last segment would call
    a subdirectory module missing from disk while the loader found it, and the two would disagree
    about which files the page ships.
    """
    return [src.removeprefix('/js/') for src in PAGE_SCRIPT.findall(page.read_text(encoding='utf-8'))]


class TestThePageListsItsOwnModules:
    def test_every_script_the_page_loads_exists_on_disk(self):
        missing = [name for name in _page_scripts(INDEX) if not (JS_DIR / name).is_file()]
        assert missing == [], f'index.html loads scripts that are not in backend/static/js: {missing}'

    def test_every_module_is_loaded_by_a_page(self):
        """A module loaded by neither page is dead code whose tests would still pass."""
        loaded = set(_page_scripts(INDEX)) | set(_page_scripts(STUDIO))
        on_disk = {path.relative_to(JS_DIR).as_posix() for path in JS_DIR.rglob('*.js')}
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

    def test_a_split_out_module_comes_with_the_file_it_was_split_from(self, tmp_path):
        """Selecting ``workflow.js`` must also evaluate the modules split out of it — **and the ones
        split out of those**.

        The capability matrix, the chart preview and (earlier) the message catalogues used to live in
        that one file. A harness that names only the old file boots half a layer and dies the first
        time the scenario asks the other half anything — measured 2026-10-28, when moving the matrix
        out broke 14 test modules at boot with ``Cannot read properties of undefined``.

        The second level is the same trap one step deeper: ``panels/settings.js`` was cut again on
        2026-10-29 into one module per node type, so a one-level expansion hands a harness the panel
        shell WITHOUT the analysis/biblio/chart renderers it calls, and the scenario dies on a name
        that exists on the page. Transitivity is what the rule means; it is asserted here rather than
        trusted to the loader.
        """
        dom = (REPO / 'tests' / 'frontend' / 'harness_dom.mjs').as_posix()
        loader = (REPO / 'tests' / 'frontend' / 'page_scripts.mjs').as_posix()
        driver = tmp_path / 'driver.mjs'
        driver.write_text(
            "import vm from 'node:vm';\n"
            "import { pathToFileURL } from 'node:url';\n"
            f'const {{ baseSandbox, fixWindow }} = await import(pathToFileURL({dom!r}).href);\n'
            f'const {{ loadPageScripts }} = await import(pathToFileURL({loader!r}).href);\n'
            'const sandbox = baseSandbox();\n'
            'vm.createContext(sandbox);\n'
            'fixWindow(vm, sandbox);\n'
            "const loaded = loadPageScripts(sandbox, { only: ['workflow.js'] });\n"
            'process.stdout.write(JSON.stringify(loaded));\n',
            encoding='utf-8',
        )
        answer = run_node(str(driver))
        assert answer.returncode == 0, answer.stderr[-600:]
        loaded = json.loads(answer.stdout)
        assert 'workflow.js' in loaded
        assert 'capabilities.js' in loaded, f'the capability matrix is missing from {loaded}'
        assert 'chart-preview.js' in loaded, f'the chart preview is missing from {loaded}'
        # Two levels deep: the settings panel is itself split by node type, and a harness that names
        # workflow.js boots the whole panel family or it boots a panel that dies on first open.
        for name in ('panels/settings.js', 'panels/node-analysis.js', 'panels/node-chart.js'):
            assert name in loaded, f'{name} is missing from {loaded} — the closure stopped one level short'

    def test_the_python_driver_expands_the_same_closure_as_the_loader(self, tmp_path):
        """The two readers of ``splits.json`` must agree file-for-file, or a Python driver boots a
        different page than a node harness does and their green means different things."""
        from frontend_catalogue import with_companions

        js = REPO / 'backend' / 'static' / 'js'
        expanded = [Path(str(item)).relative_to(js).as_posix() for item in with_companions([js / 'workflow.js'])]
        assert 'panels/settings.js' in expanded
        for name in ('panels/node-analysis.js', 'panels/node-biblio.js', 'panels/node-chart.js'):
            assert name in expanded, f'the Python closure stopped one level short at {name}'

    def test_the_companion_map_names_files_the_page_really_ships(self):
        """A companion the page does not load would be a harness-only file: the browser would never
        have it, so the split would be a test fiction. The map is read from the loader source."""
        loader = (REPO / 'tests' / 'frontend' / 'page_scripts.mjs').read_text(encoding='utf-8')
        assert 'COMPANIONS' in loader or 'companions.mjs' in loader, 'the loader lost the companion rule'
        companions = json.loads((REPO / 'tests' / 'frontend' / 'splits.json').read_text(encoding='utf-8'))
        names = set(companions) | {name for group in companions.values() for name in group}
        # Both sides of every pair are page-shipped modules: the owner and the file split out of it.
        page = set(_page_scripts(INDEX))
        assert names <= page, f'companions the page never loads: {sorted(names - page)}'
        for name in names:
            assert (JS_DIR / name).is_file(), f'{name} is in the map but not on disk'

    def test_the_loader_reads_this_page_rather_than_a_checked_in_list(self):
        loader = (REPO / 'tests' / 'frontend' / 'page_scripts.mjs').read_text(encoding='utf-8')
        assert 'index.html' in loader
        assert re.search(r'<script\\b', loader), 'the loader must parse <script> tags, not name files itself'

    def test_a_key_two_domains_claim_is_refused_at_load(self, tmp_path):
        """With the dictionary split across files, "the later file wins" would be a word nobody chose.

        Inside one object a duplicate key is the same accident, but a side-by-side diff shows it;
        across two files nothing does. So app.js's merge names both claimants and stops the page —
        this proves the refusal fires on the real bundle, with a table that claims a word the
        shipped ``settings`` domain already owns.
        """
        dom = (REPO / 'tests' / 'frontend' / 'harness_dom.mjs').as_posix()
        loader = (REPO / 'tests' / 'frontend' / 'page_scripts.mjs').as_posix()
        driver = tmp_path / 'driver.mjs'
        driver.write_text(
            "import vm from 'node:vm';\n"
            "import { pathToFileURL } from 'node:url';\n"
            f'const {{ baseSandbox, fixWindow }} = await import(pathToFileURL({dom!r}).href);\n'
            f'const {{ loadPageScripts }} = await import(pathToFileURL({loader!r}).href);\n'
            'const sandbox = baseSandbox();\n'
            'vm.createContext(sandbox);\n'
            'fixWindow(vm, sandbox);\n'
            'vm.runInContext(\n'
            "    \"globalThis.I18N_CATALOGUES = [{name: 'mine', en: {'settings.file': 'x'}, "
            "zh: {'settings.file': 'x'}}];\",\n"
            '    sandbox\n'
            ');\n'
            'let message = "";\n'
            'try {\n'
            "    loadPageScripts(sandbox, { only: ['app.js'] });\n"
            '} catch (err) {\n'
            '    message = String((err && err.message) || err);\n'
            '}\n'
            'process.stdout.write(JSON.stringify({ message }));\n',
            encoding='utf-8',
        )
        answer = run_node(str(driver))
        assert answer.returncode == 0, answer.stderr[-600:]
        message = json.loads(answer.stdout)['message']
        # Both claimants are named: an editor must be told which two files disagree about the word.
        assert 'settings.file' in message and 'is defined by both' in message, message
        assert 'mine' in message and 'settings' in message, message

    def test_no_harness_keeps_a_private_list_of_product_modules(self):
        """A hand-written ``FILES`` array is a second opinion about the page — and its ORDER is a
        second opinion too. Four harnesses had one, and every one of them put ``custom-select.js``
        before ``workflow.js`` while the page loads them the other way round, so those scenarios
        evaluated a boot order no browser ever runs. A harness may still read a module's SOURCE
        (the catalogue and contract cases do); it may not decide for itself which product scripts to
        evaluate, because that list goes stale silently the day a module is split — and a list that
        stops including ``js/i18n/*.js`` turns every ``t()`` into its own key.

        Two shapes are the same defect: a ``FILES = [`` constant, and reading app.js's text out of
        the JS directory by name (``readFileSync(path.join(jsDir, 'app.js'))``) to concatenate it
        with its siblings. Three harnesses did the second one and kept passing on keys-against-keys
        comparisons after the dictionary moved (measured 2026-10-28). A harness that reads ONE leaf
        module by name (``custom-select.js``, which takes its words from its callers) is not this
        defect: the rule is about booting the app without the data the app merges.
        """
        offenders = []
        for path in sorted((REPO / 'tests' / 'frontend').glob('harness_*.mjs')):
            text = path.read_text(encoding='utf-8')
            boots_app = re.search(r"""['"]app\.js['"]""", text)
            if re.search(r'\bFILES\s*=\s*\[', text) or (boots_app and re.search(r'readFileSync\([^)]*jsDir', text)):
                offenders.append(path.name)
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

    def test_a_driver_that_boots_app_js_hands_it_its_catalogue(self):
        """A harness that evaluates ``app.js`` without ``js/i18n/*.js`` runs an app with no words.

        Every ``t()`` then echoes its own key, so an assertion about a sentence passes on the echo —
        measured on 2026-10-28, when the panel-actions harness printed ``3 settings.rows`` where it
        had printed ``3 rows``. The page-reading loaders handle this in ``page_scripts.mjs``; the
        drivers that hand file paths over need the same rule from the same place, so this asks every
        one of them.
        """
        calls_seen = 0
        offenders = []
        for path in sorted((REPO / 'tests').rglob('*.py')):
            calls = [match.group(0) for match in _RUN_NODE_CALL.finditer(path.read_text(encoding='utf-8'))]
            calls_seen += len(calls)
            offenders += [
                f'{path.name}: {call[:70]}…' for call in calls if "'app.js'" in call and 'with_catalogue' not in call
            ]
        assert calls_seen >= 20, f'the scan saw {calls_seen} run_node calls — its pattern has rotted'
        assert offenders == [], f'harness drivers that boot app.js without its catalogue: {offenders}'
