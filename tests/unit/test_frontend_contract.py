"""Frontend contract tests — the half of the app pytest used to be blind to.

The console once spoke in bare ``node-N`` for a whole release because
``toWorkflowJSON`` (the browser→backend serializer) silently dropped ``title``:
every Python test hand-builds its own workflow dict, so none of them ever ran
the real serializer. These tests close that gap from three sides:

1. run the actual ``canvas.js`` in a Node harness and check what the backend
   would receive (title present, fields complete, ids intact);
2. every literal ``I18n.t('key')`` used anywhere in the frontend must exist in
   BOTH language catalogues — the display-layer twin of ``i18n.audit()``;
3. every palette ``data-type`` must have a params default and a node label,
   so a node can never ship draggable-but-undefined.
"""

import json
import re
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

import i18n
from crawlers import CRAWLERS, is_crawlable
from services.cookie_manager import CookieManager

pytestmark = pytest.mark.unit

STATIC_DIR = Path(__file__).resolve().parents[2] / 'backend' / 'static'
JS_DIR = STATIC_DIR / 'js'
HARNESS = Path(__file__).resolve().parents[1] / 'frontend' / 'harness_canvas.mjs'
VALIDATE_HARNESS = Path(__file__).resolve().parents[1] / 'frontend' / 'harness_validate.mjs'
CANVAS_JS = JS_DIR / 'canvas.js'

# Files whose I18n.t('literal') calls are audited against the catalogues.
I18N_USERS = ['app.js', 'canvas.js', 'workflow.js', 'menu.js', 'stats.js']

_KEY_REF = re.compile(r"""I18n\.t\(\s*(['"])([A-Za-z][\w.]*)\1\s*\)""")
_DICT_KEY = re.compile(r"""['"]([A-Za-z][\w.]*)['"]\s*:\s*['"]""")
_DATA_I18N = re.compile(r'data-i18n="([A-Za-z][\w.]*)"')


def _catalog_keys():
    """{lang: set(keys)} parsed out of app.js's I18n.dict literals."""
    src = (JS_DIR / 'app.js').read_text(encoding='utf-8')
    en_start = src.index('dict: {')
    en_body = src[en_start : src.index('zh: {', en_start)]
    zh_body = src[src.index('zh: {', en_start) : src.index('_missing:')]

    def grab(block):
        return {m.group(1) for m in _DICT_KEY.finditer(block)}

    return {'en': grab(en_body), 'zh': grab(zh_body)}


class TestCanvasSerialization:
    """toWorkflowJSON is the browser→backend wire; its shape is a real contract."""

    @classmethod
    @pytest.fixture(scope='class')
    def payload(cls):
        """A class-scoped fixture has to be a classmethod: defined as an instance method,
        the one instance it fills is thrown away before the first test runs, so every
        ``self.`` it set would be invisible to the tests it was built for.
        """
        node = shutil.which('node')
        if not node:
            pytest.skip('node not available')

        proc = run_node(HARNESS, CANVAS_JS)
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)

    def test_renamed_node_travels_with_its_title(self, payload):
        node = payload['nodes'][0]
        assert node['title'] == '我的抓取', (
            'toWorkflowJSON must carry title — the console addresses nodes by it, '
            'and a dropped title silently degrades every log line to bare node-N'
        )

    def test_every_node_has_the_fields_the_backend_reads(self, payload):
        for node in payload['nodes']:
            assert {'id', 'type', 'title', 'params'} <= set(node), node

    def test_a_title_equal_to_the_id_survives_untouched(self, payload):
        # node-2 in the harness is titled 'node-2'; the serializer must not
        # invent or drop titles — node_label decides how a bare id reads.
        assert payload['nodes'][1]['title'] == 'node-2'

    def test_connections_and_settings_shape(self, payload):
        assert payload['connections'] == [{'from': 'node-1', 'to': 'node-2'}]
        assert payload['settings']['mode'] in ('serial', 'parallel')


class TestLlmGateParity:
    """``nodeNeedsLlm`` (workflow.js) and ``_workflow_needs_llm`` (app.py) agree.

    The browser refuses to open the console without a model when a node will
    need one; the server refuses the same way before the worker starts. When the
    two lists drift, either a rules-only crawl gets blocked for a missing API key
    or a run starts and dies on its first row — both invisible to a suite that
    only tests one side. Every process op is in the table, modes included.
    """

    CASES = [
        # ``clean`` was the one operation listed as always needing a model. It has a mode
        # of its own now, and its rule set pays for nothing — so a blank (which means the
        # declared default, llm) and the regex mode must answer differently on BOTH sides.
        ('clean', {'operation': 'clean'}, None),
        ('clean_llm', {'operation': 'clean', 'mode': 'llm'}, None),
        ('clean_regex', {'operation': 'clean', 'mode': 'regex'}, None),
        ('clean_blank_mode', {'operation': 'clean', 'mode': '  '}, None),
        ('clean_bogus_mode', {'operation': 'clean', 'mode': 'rules'}, None),
        ('emotion_default', {'operation': 'emotion'}, None),
        ('emotion_llm', {'operation': 'emotion', 'mode': 'llm'}, None),
        ('emotion_ml', {'operation': 'emotion', 'mode': 'ml'}, None),
        ('tendency_llm', {'operation': 'tendency', 'mode': 'llm'}, None),
        ('tendency_ml', {'operation': 'tendency', 'mode': 'ml'}, None),
        ('ner_default', {'operation': 'ner'}, None),
        ('ner_regex', {'operation': 'ner', 'mode': 'regex'}, None),
        ('ner_llm', {'operation': 'ner', 'mode': 'llm'}, None),
        ('ner_bogus_mode', {'operation': 'ner', 'mode': 'sklearn'}, None),
        # Polarity answers the same question four ways, three of which need no model, so
        # the whole grid is in here: `mode !== 'ml'` was the old reading and it would
        # block a SnowNLP run behind an API key nothing in the canvas asked for.
        ('sentiment_default', {'operation': 'sentiment'}, None),
        ('sentiment_snownlp', {'operation': 'sentiment', 'mode': 'snownlp'}, None),
        ('sentiment_ml', {'operation': 'sentiment', 'mode': 'ml'}, None),
        ('sentiment_bert', {'operation': 'sentiment', 'mode': 'bert'}, None),
        ('sentiment_llm', {'operation': 'sentiment', 'mode': 'llm'}, None),
        ('sentiment_blank_mode', {'operation': 'sentiment', 'mode': '  '}, None),
        ('sentiment_bogus_mode', {'operation': 'sentiment', 'mode': 'TextBlob'}, None),
        ('keyword', {'operation': 'keyword'}, None),
        ('cluster', {'operation': 'cluster'}, None),
        ('anomaly', {'operation': 'anomaly'}, None),
        ('correlation', {'operation': 'correlation'}, None),
        ('no_operation_at_all', {}, None),
        # The wire carries ``operation`` on the node as well; the backend reads
        # that one first, so the gate may not ignore it.
        ('node_level_operation', {'text_column': '正文'}, 'clean'),
        ('node_level_ner_llm', {'text_column': '正文'}, 'ner'),
    ]

    @classmethod
    @pytest.fixture(scope='class')
    def js_answers(cls, tmp_path_factory):
        if shutil.which('node') is None:
            pytest.skip('node not available')
        scenarios = [{'id': name, 'needsLlm': params, 'operation': operation} for name, params, operation in cls.CASES]
        path = tmp_path_factory.mktemp('gate') / 'scenarios.json'
        path.write_text(json.dumps(scenarios, ensure_ascii=False), encoding='utf-8')
        proc = run_node(VALIDATE_HARNESS, JS_DIR / 'workflow.js', path)
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)['needsLlm']

    @pytest.mark.parametrize('name, params, operation', CASES, ids=[case[0] for case in CASES])
    def test_the_browser_and_the_server_ask_for_a_model_on_the_same_nodes(self, js_answers, name, params, operation):
        from app import _workflow_needs_llm

        node = {'type': 'process', 'params': params}
        if operation:
            node['operation'] = operation
        assert js_answers[name] == _workflow_needs_llm({'nodes': [node]}), name

    def test_the_process_selector_offers_exactly_the_operations_the_executor_serves(self):
        """``PROCESS_OPS`` in workflow.js is what the 算法处理 node's dropdown offers; the
        branches inside ``_execute_process_node`` are what actually run. Read from the
        source of both, because either half drifting is silent in the other direction:

        a name only in the browser is an option that validates, runs, and then fails on
        「未知操作」 after the user paid for the crawl above it; a name only in the backend
        is a capability nobody can reach.
        """
        import ast

        js = (JS_DIR / 'workflow.js').read_text(encoding='utf-8')
        listed = js[js.index('var PROCESS_OPS = [') :]
        offered = re.findall(r"""'([a-z_]+)'""", listed[: listed.index('];')])

        source = (STATIC_DIR.parent / 'app.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        served = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.FunctionDef) and node.name == '_execute_process_node'):
                continue
            for test in ast.walk(node):
                # Only the top-level dispatch tests count: `if op == 'clean'` routes the
                # node, while a comparison against some other variable is that branch's
                # own business and says nothing about what the operation is called.
                if (
                    isinstance(test, ast.Compare)
                    and isinstance(test.left, ast.Name)
                    and test.left.id == 'op'
                    and len(test.ops) == 1
                    and isinstance(test.ops[0], ast.Eq)
                    and isinstance(test.comparators[0], ast.Constant)
                    and isinstance(test.comparators[0].value, str)
                ):
                    served.append(test.comparators[0].value)
        assert offered == sorted(set(offered), key=offered.index), f'the selector lists an operation twice: {offered}'
        assert sorted(offered) == sorted(set(served)), (
            f'only the browser offers {sorted(set(offered) - set(served))}; '
            f'only the executor serves {sorted(set(served) - set(offered))}'
        )

    def test_every_offered_operation_that_chooses_an_algorithm_declares_its_options(self):
        """An op with a select-shaped parameter must be in ``PROCESS_ENUMS``, or its select
        is a field the executor reads without ever checking it — the exact shape that let
        ``method='TF-IDF'`` run TextRank and stamp the table with the name that had not
        run. Ops with no such field (clean, anomaly) are legitimately absent, so the two
        lists are compared against what the panels actually render."""
        from app import PROCESS_ENUMS

        js = (JS_DIR / 'workflow.js').read_text(encoding='utf-8')
        panelled = {
            op
            for op in ('emotion', 'tendency', 'sentiment', 'keyword', 'cluster', 'ner', 'correlation')
            if f"p.operation === '{op}'" in js
        }
        assert panelled <= set(PROCESS_ENUMS), sorted(panelled - set(PROCESS_ENUMS))
        assert 'sentiment' in PROCESS_ENUMS and 'mode' in PROCESS_ENUMS['sentiment']

    def test_every_literal_i18n_key_exists_in_both_languages(self):
        catalogs = _catalog_keys()
        missing = []
        for name in I18N_USERS:
            src = (JS_DIR / name).read_text(encoding='utf-8')
            for m in _KEY_REF.finditer(src):
                key = m.group(2)
                for lang, table in catalogs.items():
                    if key not in table:
                        missing.append(f'{name}: {key} missing from {lang}')
        assert not missing, '\n'.join(missing)


class TestFrontendCatalog:
    def test_every_static_label_in_the_page_exists_in_both_languages(self):
        """``data-i18n`` is how the HTML gets re-worded when the language flips.

        A key that exists in no catalogue is invisible until someone switches to
        the other language and finds a button still wearing the first one's text
        — the failure the English cookie dialog once shipped as a horizontal
        scrollbar. Buttons added to index.html are covered here, not in JS.
        """
        catalogs = _catalog_keys()
        html = (STATIC_DIR / 'index.html').read_text(encoding='utf-8')
        missing = []
        for key in _DATA_I18N.findall(html):
            for lang, table in catalogs.items():
                if key not in table:
                    missing.append(f'index.html: {key} missing from {lang}')
        assert not missing, '\n'.join(sorted(set(missing)))

    def test_the_page_actually_uses_the_attribute_it_is_checked_for(self):
        # A regex that matches nothing would make the check above pass forever.
        html = (STATIC_DIR / 'index.html').read_text(encoding='utf-8')
        assert len(_DATA_I18N.findall(html)) > 50


class TestPaletteContract:
    def _palette_types(self):
        html = (STATIC_DIR / 'index.html').read_text(encoding='utf-8')
        palette = html[html.index('id="node-palette"') : html.index('id="node-palette"') + 6000]
        return re.findall(r'data-type="([\w]+)"', palette)

    def test_every_palette_node_has_params_and_a_label(self):
        canvas_src = CANVAS_JS.read_text(encoding='utf-8')
        app_src = (JS_DIR / 'app.js').read_text(encoding='utf-8')
        for ntype in self._palette_types():
            assert f"if (type === '{ntype}')" in canvas_src, f'getDefaultParams lacks {ntype}'
            assert f"'node.{ntype}'" in app_src, f'catalogue lacks node.{ntype}'

    def test_comments_is_a_source_mode_not_a_palette_item(self):
        # The standalone CMT node lingers in the engine for old canvases, but
        # new users reach 评论采集 through the Data Source's collect mode.
        assert 'comment' not in self._palette_types()
        canvas_src = CANVAS_JS.read_text(encoding='utf-8')
        assert "if (type === 'source') return this._defaultSourceParams();" in canvas_src, (
            'the Data Source stopped seeding itself from the matrix'
        )
        seeder = canvas_src[canvas_src.index('_defaultSourceParams()') :]
        assert "params.collect = Capabilities.mode(platform, '').key" in seeder, (
            'a new node must arrive already naming the mode it will run, not leaving it blank'
        )


class TestCookiePanelParity:
    """The Cookie panel is wired together from three files that nothing else
    cross-checks: the platform list is HTML, its translation lives in app.js, the
    guidance the panel renders lives in the backend catalogue, and the crawl
    permission lives in the crawler registry. Any one of the four can change alone,
    and each of those changes makes the panel lie."""

    def _select_options(self, html: str, select_id: str) -> list[str]:
        start = html.index(f'id="{select_id}"')
        block = html[start : html.index('</select>', start)]
        return re.findall(r'<option value="([\w]+)"', block)

    def test_the_cookie_select_offers_exactly_the_platforms_that_can_hold_a_file(self):
        html = (STATIC_DIR / 'index.html').read_text(encoding='utf-8')
        offered = self._select_options(html, 'cookie-platform')
        assert set(offered) == set(CookieManager.PLATFORMS), (
            'a platform the panel lists but the manager refuses saves nothing, and a platform with '
            'a file but no row is a cookie nobody can refresh from the UI'
        )
        assert len(offered) == len(set(offered)), f'a platform is listed twice: {offered}'

    def test_the_data_source_list_offers_exactly_the_platforms_that_really_crawl(self):
        """The panel's platform list and the crawl registry are one fact now.

        The Data Source select is generated from the matrix, so what can still go
        wrong is the matrix itself: a platform it describes but nothing can crawl
        offers a form whose run refuses to start, and a crawlable platform it
        forgot opens a panel that can only say "no crawler yet". The second half
        is the guard against the old shape coming back — a list typed into
        workflow.js, which is exactly how the two drifted apart before.
        """
        import crawl_capabilities

        assert set(crawl_capabilities.platform_ids()) == {p for p in CRAWLERS if is_crawlable(p)}, (
            'the crawl matrix and the crawler registry disagree about which platforms exist'
        )
        workflow_src = (JS_DIR / 'workflow.js').read_text(encoding='utf-8')
        hand_listed = [p for p in CRAWLERS if f"'platform.{p}'" in workflow_src]
        assert not hand_listed, f'workflow.js names platforms by hand again: {hand_listed}'

    def test_the_steps_tell_the_user_to_press_buttons_that_are_actually_there(self):
        """Every platform's steps name two controls by their exact label. The panel
        renamed both a while ago and nothing went red: the guidance quietly started
        pointing at buttons no longer on screen, which no Python test can see unless
        somebody asks it to."""
        app_src = (JS_DIR / 'app.js').read_text(encoding='utf-8')
        en_src = app_src[app_src.index('dict: {') : app_src.index('zh: {')]
        zh_src = app_src[app_src.index('zh: {') : app_src.index('_missing:')]

        def labels(block: str) -> dict:
            found = dict(re.findall(r"'(cookies\.(?:generate|doneBtn))': '([^']*)'", block))
            assert len(found) == 2, f'the panel labels moved, and this test cannot follow: {found}'
            return found

        for language, table, panel in (('zh', i18n._ZH, labels(zh_src)), ('en', i18n._EN, labels(en_src))):
            for platform in CookieManager.PLATFORMS:
                steps = table[f'cookie.{platform}.steps']
                for key in ('cookies.generate', 'cookies.doneBtn'):
                    assert panel[key] in steps, f'{platform}/{language}: steps never name the real "{key}" label'

    def test_every_cookie_platform_is_spelled_in_both_panel_languages(self):
        html = (STATIC_DIR / 'index.html').read_text(encoding='utf-8')
        keys = set(re.findall(r'data-i18n="(platform\.[\w]+)"', self._select_block(html)))
        assert keys == {f'platform.{p}' for p in CookieManager.PLATFORMS}

    @staticmethod
    def _select_block(html: str) -> str:
        start = html.index('id="cookie-platform"')
        return html[start : html.index('</select>', start)]


class TestSettingsPanelParity:
    """A server-side setting reaches the screen through four files, and three of them
    are never read by any other test: ``settings_store.DEFAULTS`` (the key), the bool
    branch in ``save_settings`` (so it saves at all), ``AppSettings._inputMap`` (so it
    is read back), and the control in index.html (so a user can change it). A key
    missing from any of the four is a setting that exists in one file only."""

    def _input_map(self) -> dict:
        app = (JS_DIR / 'app.js').read_text(encoding='utf-8')
        block = app.split('_inputMap', 1)[1].split('}', 1)[0]
        return dict(re.findall(r"(\w+):\s*'(set-[\w-]+)'", block))

    def test_every_server_setting_has_a_wired_control(self):
        import settings_store

        pairs = self._input_map()
        html = (STATIC_DIR / 'index.html').read_text(encoding='utf-8')
        missing = sorted(key for key in settings_store.DEFAULTS if key not in pairs)
        assert not missing, f'settings nobody can edit from the panel: {missing}'
        for key in settings_store.DEFAULTS:
            element_id = pairs[key]
            assert f'id="{element_id}"' in html, f'{key} is mapped to a missing #{element_id}'
            assert f"onSettingInput('{key}'" in html, f'#{element_id} never tells the server about {key}'

    def test_the_preflight_switch_is_wired_in_the_panel(self):
        """The check is now the only Cookie run-gate, so the panel must keep its
        control; an orphaned row or a lost id would leave the setting unreachable."""
        html = (STATIC_DIR / 'index.html').read_text(encoding='utf-8')
        assert 'id="set-cookie-preflight"' in html, 'the panel lost the preflight switch'
        assert "onSettingInput('cookie_preflight_before_run'" in html, 'the preflight switch never reaches the server'


class TestCrawlMatrixParity:
    """The Data Source panel is generated from the crawl matrix, so the matrix now
    owns every word that panel says — and those words live in two catalogues: the
    browser's in app.js, the console's in i18n.py. A key that exists in neither is
    a panel printing its own key, which is what this file was written for.
    """

    @staticmethod
    def _keys():
        import crawl_capabilities

        labels, hints, names = set(), set(), set()
        for cap in crawl_capabilities.CAPABILITIES:
            for mode in cap.modes:
                labels.add(mode.label_key)
                labels.add('settings.platform')
                for field in mode.fields + crawl_capabilities.FILE_FIELDS:
                    labels.add(field.label_key)
                    if field.hint_key:
                        hints.add(field.hint_key)
                    if field.name_key:
                        names.add(field.name_key)
                if mode.note_key:
                    labels.add(mode.note_key)
                if mode.action_key:
                    labels.add(mode.action_key)
        # The link fields of a comments form get their hint from the platform
        # rule, which the renderer assembles from these two keys.
        hints.add('settings.commentUrlsHintPlat')
        return labels, hints, names

    def test_every_panel_word_the_matrix_names_exists_in_both_browser_languages(self):
        catalogues = _catalog_keys()
        labels, hints, _names = self._keys()
        missing = [
            f'{key} missing from {lang}'
            for key in sorted(labels | hints)
            for lang, table in catalogues.items()
            if key not in table
        ]
        assert not missing, '\n'.join(missing)

    def test_the_matrix_actually_names_something(self):
        """A helper that returned empty sets would pass the test above forever."""
        labels, hints, names = self._keys()
        assert len(labels) >= 12 and len(hints) >= 5 and names, (labels, hints, names)

    def test_every_console_field_name_exists_in_both_backend_languages(self):
        _labels, _hints, names = self._keys()
        missing = [
            f'{key} missing from {lang}'
            for key in sorted(names)
            for lang, table in (('zh', i18n._ZH), ('en', i18n._EN))
            if key not in table
        ]
        assert not missing, '\n'.join(missing)

    def test_the_matrix_sends_the_browser_only_to_functions_that_exist(self):
        source = (JS_DIR / 'workflow.js').read_text(encoding='utf-8')
        import crawl_capabilities

        for cap in crawl_capabilities.CAPABILITIES:
            for mode in cap.modes:
                if mode.action_js:
                    assert f'function {mode.action_js}(' in source, (
                        f'{cap.platform}/{mode.key} calls a missing {mode.action_js}'
                    )


class TestChromeOfThePageItself:
    """Rules about the page's own furniture: what may interrupt the user, and where.

    A node harness has no CSS and no browser chrome, and a Selenium pass is too slow to
    be the gate for a one-line stylesheet edit, so these are pinned against the very
    source the browser loads.
    """

    def test_no_dialog_is_asked_of_the_browser_itself(self):
        """``window.confirm``/``alert`` cannot follow the interface language, cannot be
        styled with the page, and answer with a bare boolean that says nothing about what
        is about to be lost. The app has its own dialog for every one of them."""
        offender = re.compile(r"""window\.(?:confirm|alert|prompt)\s*\(""")
        for name in I18N_USERS:
            source = (JS_DIR / name).read_text(encoding='utf-8')
            hits = [line.strip() for line in source.splitlines() if offender.search(line)]
            assert not hits, f'{name} still interrupts the user with a native dialog: {hits}'

    def test_the_resume_banner_moves_down_when_the_menu_bar_is_pinned(self):
        """The bar is ``position: fixed`` and slides over the top of the workspace while
        pinned, so a banner at ``top: 8px`` sat underneath it — including the 继续 button
        the user came to the page to press."""
        css = (STATIC_DIR / 'css' / 'style.css').read_text(encoding='utf-8')
        html = (STATIC_DIR / 'index.html').read_text(encoding='utf-8')
        assert '--menuH' in css, 'the rule needs the bar height, and the bar is what owns it'
        assert '#top-menu.pinned ~ #workspace #resume-banner' in css
        assert 'top: calc(var(--menuH)' in css
        assert 'transition: top' in css, 'the banner must slide, not teleport under the bar'
        # A selector that matches nothing is how the old `.panel` audit stayed green while
        # measuring zero elements, so the structure the `~` needs is checked, not assumed.
        assert html.count('<nav id="top-menu">') == 1 and html.count('<div id="workspace">') == 1
        assert html.index('<nav id="top-menu">') < html.index('<div id="workspace">')
        nav_line = next(line for line in html.splitlines() if '<nav id="top-menu">' in line)
        workspace_line = next(line for line in html.splitlines() if '<div id="workspace">' in line)
        assert nav_line.index('<') == workspace_line.index('<'), (
            'the two must sit at one indentation to be siblings, or the rule is dead text'
        )

    def test_an_overflowing_menu_bar_is_anchored_and_admits_it(self):
        """``justify-content: center`` inside ``overflow: auto`` is the one combination
        that hides content with no way back — a scroller cannot reach a negative
        overflow, so at 1366px English the bar's first button sat 63px off the left
        edge with its scrollbar hidden. The browser tier measures the pixels; this
        pins the declarations that produce them, so the fix cannot be dropped by an
        edit that never opens Chrome."""
        css = (STATIC_DIR / 'css' / 'style.css').read_text(encoding='utf-8')
        bar = css[css.index('#top-menu {') : css.index('#menu-trigger:hover')]
        assert 'justify-content: safe center' in bar, f'the bar is centred again: {bar}'
        assert 'scrollbar-width: none' not in bar, 'the overflow affordance is hidden again'
        assert 'scrollbar-width: thin' in bar
        assert 'overflow-y: hidden' in bar, 'a vertical bar would push the row out of the 48px strip'
        assert '#top-menu::-webkit-scrollbar {' in css
        assert 'display: none' not in css[css.index('#top-menu::-webkit-scrollbar {') :].split('}')[0]

    def test_the_workbench_copy_of_the_bar_keeps_the_same_rule(self):
        """``zenviz.html`` carries its own inline copy of the top-menu block for the
        embedded workbench. Left alone, the main-page fix silently forks."""
        page = (STATIC_DIR / 'zenviz.html').read_text(encoding='utf-8')
        bar = page[page.index('#top-menu {') : page.index('#menu-trigger:hover')]
        assert 'justify-content: safe center' in bar, 'the embedded page still centres an overflowing row'
        assert 'scrollbar-width: none' not in bar

    def test_a_centred_panel_that_can_grow_tall_has_a_ceiling(self):
        """``overflow-y: auto`` on a vertically centred, uncapped box does nothing:
        the box grows to its content and hangs off the viewport, so the top of a long
        node form simply existed above the screen (measured ``top: -177`` in 550px)."""
        css = (STATIC_DIR / 'css' / 'style.css').read_text(encoding='utf-8')
        for selector in ('#node-settings {', '#cookie-dialog {'):
            block = css[css.index(selector) : css.index('}', css.index(selector))]
            assert 'max-height: calc(100vh - 24px)' in block, f'{selector} can outgrow the screen again'
            assert 'overflow-y: auto' in block, f'{selector} lost the scroll the ceiling exists to enable'

    def test_a_single_select_option_row_ellipsises_and_carries_its_full_text(self):
        """The ellipsis rule used to live only under ``.cselect-option.multi``, so a
        single option longer than the capped menu was cut with no ellipsis, no
        scrollbar meaning and no tooltip — and the option text of this app is crawled
        column names, which are exactly that long."""
        css = (STATIC_DIR / 'css' / 'style.css').read_text(encoding='utf-8')
        label = css[css.index('.cselect-option-label {') : css.index('}', css.index('.cselect-option-label {'))]
        assert 'text-overflow: ellipsis' in label and 'min-width: 0' in label, label
        menu = css[css.index('.cselect-menu {') : css.index('}', css.index('.cselect-menu {'))]
        assert 'max-width' in menu, 'the popup has no width ceiling beside the JS one it mirrors'
        js = (JS_DIR / 'custom-select.js').read_text(encoding='utf-8')
        assert 'b.title = o.textContent' in js, 'an ellipsised option says its full text nowhere'

    def test_a_wire_that_leaves_the_world_box_is_still_painted(self):
        """The world is infinite for a NODE (a <div>, whose overflow is visible) but the
        wires are drawn into one <svg> that is 100% of the finite #canvas-inner, and an
        <svg> ROOT clips to its own viewport by UA default. So a node dragged past
        x=10000 — or to a negative coordinate, which pan has always allowed — stayed
        perfectly visible while its curve was CUT at the border: the further apart two
        boxes sat, the less of the wire between them existed. `overflow: visible` is the
        one declaration that un-clips it, and #workspace is then what keeps the paint
        inside the window, so the named clipper is checked as well as the fix."""
        css = (STATIC_DIR / 'css' / 'style.css').read_text(encoding='utf-8')
        html = (STATIC_DIR / 'index.html').read_text(encoding='utf-8')

        def block_of(selector):
            start = css.index(selector)
            return css[start : css.index('}', start)]

        layer = block_of('#svg-layer {')
        assert 'overflow: visible' in layer, f'the wires are clipped to the world box again: {layer}'
        assert 'position: absolute' in layer, 'the layer no longer shares the nodes coordinate space'
        # A wire nobody can click is a wire the user cannot delete: the hit paths live in
        # this same layer, so un-clipping must not have taken the pointer away with it.
        assert 'pointer-events: none' in layer
        assert 'pointer-events: stroke' in block_of('.conn-delete-hit {'), (
            'the delete hit-area needs its own pointer-events, since its layer has none'
        )
        window = block_of('#workspace {')
        assert 'overflow: hidden' in window, 'nothing now bounds the paint, so wires cross the chrome'
        world = block_of('#canvas-inner {')
        assert 'width: 10000px' in world, 'the world box is the finite box the rule above exists to outgrow'

        # The nesting is what makes `100%` mean the world box; restructure the page and the
        # rule above is dead text, which is exactly the audit that used to pass on nothing.
        svg = html.index('<svg id="svg-layer">')
        assert html.index('<div id="canvas-inner">') < svg < html.index('<div id="nodes-container">')
        assert html.index('<div id="workspace">') < html.index('<div id="canvas-inner">')
        # And nothing bounds the NODE coordinate either — an unbounded pan is what lets a
        # port sit outside the world box in the first place, so a clamp appearing here
        # would mean the un-clipped wire was unnecessary after all.
        js = (JS_DIR / 'canvas.js').read_text(encoding='utf-8')
        assert "['panX', view.panX, -Infinity, Infinity]" in js, 'pan gained a bound'
        assert "['panY', view.panY, -Infinity, Infinity]" in js, 'pan gained a bound'

    def test_the_train_button_does_not_choose_the_label_column_it_cannot_see(self):
        """``trainMLModel`` used to end its payload with
        ``modelType === 'emotion' ? 'emotion' : 'tendency'`` — a second opinion about which
        column holds the labels, held in the one file that has never seen the table. It was
        harmless while two classifiers existed and became a wrong training set the moment a
        third arrived: 「训练」 on a sentiment node would have fitted itself from the
        tendency column and reported ``ok``. The server answers from the same table that
        decides what ``mode='ml'`` loads, so the field is simply not sent."""
        js = (JS_DIR / 'workflow.js').read_text(encoding='utf-8')
        body = js[js.index('async function trainMLModel(') :]
        body = body[: body.index('\n}\n')]
        assert 'label_column' not in body, 'the browser is choosing the label column again'
        assert 'model_type = modelType' in body, 'the train call lost the model it was asked for'
        # …and the backend really does answer it per model type, so nothing is unsent by accident.
        import app as app_module

        assert app_module._ML_LABEL_COLUMNS['sentiment'] == 'sentiment'
        assert set(app_module._ML_LABEL_COLUMNS) == set(app_module._ML_MODEL_TYPES), (
            'a classifier can be trained whose label column nobody defaults'
        )

    def test_a_reloaded_page_is_wired_to_take_the_console_back_up(self):
        """The reconnect logic lives in workflow.js and the boot sequence lives in app.js, so
        the wiring between them is the one place this feature can die silently: a refresh
        would still show an empty console over a run that is writing, and every unit test
        would pass because each file is correct on its own.

        ``workflow`` is a top-level const in workflow.js — never a ``window`` property —
        so the guard has to name the binding. That exact mistake (``if (window.X)`` on a
        top-level const) is already written down in AGENTS.md as a frontend rule, and this
        is the call site that would have made it a silent no-op.
        """
        app = (JS_DIR / 'app.js').read_text(encoding='utf-8')
        wf = (JS_DIR / 'workflow.js').read_text(encoding='utf-8')
        assert "boot('consoleReconnect'" in app, 'a boot step that is not registered is a boot step that never runs'
        assert 'workflow.reconnectConsole()' in app
        assert "typeof workflow !== 'undefined'" in app, 'the guard must read the binding, not window.workflow'
        assert 'if (window.workflow' not in app, 'a top-level const never reaches window, so that guard is always false'
        # …and the step must sit in the DOMContentLoaded body like its neighbours, not in
        # some function nothing calls.
        boot_body = app[app.index("document.addEventListener('DOMContentLoaded'") :]
        assert "boot('consoleReconnect'" in boot_body[: boot_body.index("boot('locks'")], (
            'the reconnect step must run with the other post-boot steps'
        )
        assert 'reconnectConsole: async function' in wf or 'async reconnectConsole()' in wf, (
            'the method the boot step calls must exist'
        )

    def test_the_console_poller_has_exactly_one_owner(self):
        """Two intervals reading one console append the same line twice, and the delta
        cursor cannot tell them apart because both answers are valid. The reconnect path is
        the second caller that exists now, so the timer needs an owner rather than a local.
        """
        wf = (JS_DIR / 'workflow.js').read_text(encoding='utf-8')
        body = wf[wf.index('pollStatus: function') :]
        body = body[: body.index('\n};')]
        assert 'if (this._pollTimer) return;' in body, 'the poller can be started twice again'
        assert 'this._pollTimer = interval;' in body, 'the timer is never recorded, so the guard reads nothing'
        assert 'clearInterval(interval)' not in body, (
            'a callback that clears its own local handle leaves _pollTimer set and the next '
            'start refused forever — every stop must go through the owner'
        )
        assert body.count('self._stopPoll();') >= 3, (
            f'every exit that ends the run must release the owner, saw {body.count("self._stopPoll();")}'
        )

    def test_the_tab_bar_is_built_in_one_place_for_the_poller_and_the_replay(self):
        """A reconnecting page has not started the poller, so it must be able to rebuild the
        workflow tabs from a status read. A second copy of that markup is a bar that drifts
        from the one the user runs."""
        wf = (JS_DIR / 'workflow.js').read_text(encoding='utf-8')
        assert wf.count('function consoleTabsHtml(') == 1
        assert wf.count('consoleTabsHtml(') >= 3, 'the builder is declared but no caller uses it'
        assert wf.count('class="console-tab\'') == 2, (
            'the tab template exists more than once, so the two bars can disagree'
        )

        """The browser labels a platform from ``platform.*`` in app.js and the backend from
        ``i18n._PLATFORM_LABELS``. Two lists of the same nine words drift the moment one of
        them is edited — and the console and the dialog would then name the same site
        differently, in the same language, on the same screen."""
        import i18n

        source = (JS_DIR / 'app.js').read_text(encoding='utf-8')
        for lang, body in (
            ('en', source[source.index('dict: {') : source.index('zh: {')]),
            (
                'zh',
                source[source.index('zh: {') : source.index('_missing:')],
            ),
        ):
            front = dict(re.findall(r"""['"]platform\.([\w-]+)['"]\s*:\s*['"]([^'"]*)['"]""", body))
            back = i18n._PLATFORM_LABELS[lang]
            assert set(front) == set(back), f'{lang}: the two layers list different platforms'
            for key, label in front.items():
                assert back[key] == label, f'{lang}/{key}: {back[key]!r} != {label!r}'
        for platform in CookieManager.PLATFORMS:
            assert platform in i18n._PLATFORM_LABELS['zh'], f'{platform} has no label in either list'

    def test_the_export_totals_read_as_a_summary_under_the_list(self):
        """共 N 个文件 / 合计 X counts the whole export folder, so it belongs under the
        table as a summary — the user asked for exactly that after trying it pinned at the
        head, where it read as a figure about the first row."""
        css = (STATIC_DIR / 'css' / 'style.css').read_text(encoding='utf-8')
        block = css[css.index('.exports-summary {') :]
        block = block[: block.index('}')]
        assert 'text-align: center' in block
        assert 'position: sticky' not in block, 'it is a summary, not a header that follows you down'


class TestEveryServedScriptParses:
    """A file that does not parse does not lose one widget; it loses every global in it.

    Measured 2026-09-26: a Chinese panel note was added to ``app.js`` as three adjacent
    string literals — which is how Python continues a line and how JS does not. The page
    came up blank of behaviour and printed ``SyntaxError: Unexpected string``, then
    ``I18n is not defined`` and ``Settings is not defined``, because the catalogue and the
    ``Settings`` object live in the file that never finished evaluating. The harnesses only
    parse the files they load, so this walks the whole served directory instead: a new JS
    file is covered the moment it exists, with no list here to fall behind.
    """

    @pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')
    def test_each_script_under_static_js_is_valid_javascript(self):
        scripts = sorted(JS_DIR.glob('*.js'))
        assert len(scripts) >= 7, f'expected the served scripts, found {[s.name for s in scripts]}'
        broken = []
        for script in scripts:
            proc = run_node('--check', str(script))
            if proc.returncode != 0:
                broken.append(f'{script.name}: {(proc.stderr or proc.stdout).strip()[:300]}')
        assert not broken, '\n'.join(broken)


class TestOverlayLayering:
    """The full-screen chart window is opened FROM the dashboard board (and from the
    preview panels), so it must be layered above them. All are position:fixed in one
    stacking context; when the window and the board shared a z-index the board could bury
    the very window launched from its own cells. The layering is a stylesheet constant, so
    it is pinned against the CSS directly rather than by a click."""

    @staticmethod
    def _z_index(css: str, selector: str) -> int:
        match = re.search(re.escape(selector) + r'\s*\{[^}]*?z-index:\s*(\d+)', css, re.S)
        assert match, f'no z-index declared for {selector}'
        return int(match.group(1))

    def test_the_fullscreen_chart_window_out_ranks_the_dashboard(self):
        css = (STATIC_DIR / 'css' / 'style.css').read_text(encoding='utf-8')
        fullscreen = self._z_index(css, '#chart-fullscreen-panel')
        board = self._z_index(css, '#dashboard-panel')
        assert fullscreen > board, (
            f'the full-screen chart window ({fullscreen}) must sit above the dashboard ({board}) '
            'it opens from; a tie lets the board bury the window'
        )

    def test_the_fullscreen_window_also_covers_the_preview_panels(self):
        """It is also launched from the visualize / data preview surfaces, so it must clear
        those too (they sit at 1002, under the board)."""
        css = (STATIC_DIR / 'css' / 'style.css').read_text(encoding='utf-8')
        fullscreen = self._z_index(css, '#chart-fullscreen-panel')
        for preview in ('#chart-preview-panel', '#data-preview-panel'):
            assert fullscreen > self._z_index(css, preview), f'{preview} must stay under the full-screen window'


class TestTouchTargets:
    """Tablet/phone touch adaptation is a stylesheet rule scoped to (pointer: coarse), so a
    desktop viewport (and every desktop-measured layout test) is untouched. Pinned by reading
    the CSS: the coarse block exists, widens the canvas's per-node buttons and the line-delete
    hit area to finger size, and stops the browser swallowing a canvas drag as a page scroll."""

    def test_coarse_pointer_block_widens_targets_and_pins_touch_action(self):
        css = (STATIC_DIR / 'css' / 'style.css').read_text(encoding='utf-8')
        start = css.find('@media (pointer: coarse)')
        assert start >= 0, 'no (pointer: coarse) touch-target block'
        block = css[start:]
        assert 'touch-action: none' in block, 'a canvas drag must not be treated as a page scroll'
        for selector in ('#workspace', '.node-action-btn', '.node-power-btn', '.conn-delete-hit'):
            assert selector in block, f'{selector} is not covered by the coarse-pointer block'
