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

    @pytest.fixture(scope='class')
    def payload(self):
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
        ('clean', {'operation': 'clean'}, None),
        ('emotion_default', {'operation': 'emotion'}, None),
        ('emotion_llm', {'operation': 'emotion', 'mode': 'llm'}, None),
        ('emotion_ml', {'operation': 'emotion', 'mode': 'ml'}, None),
        ('tendency_llm', {'operation': 'tendency', 'mode': 'llm'}, None),
        ('tendency_ml', {'operation': 'tendency', 'mode': 'ml'}, None),
        ('ner_default', {'operation': 'ner'}, None),
        ('ner_regex', {'operation': 'ner', 'mode': 'regex'}, None),
        ('ner_llm', {'operation': 'ner', 'mode': 'llm'}, None),
        ('ner_bogus_mode', {'operation': 'ner', 'mode': 'sklearn'}, None),
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

    @pytest.fixture(scope='class')
    def js_answers(self, tmp_path_factory):
        if shutil.which('node') is None:
            pytest.skip('node not available')
        scenarios = [{'id': name, 'needsLlm': params, 'operation': operation} for name, params, operation in self.CASES]
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


class TestFrontendCatalog:
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
