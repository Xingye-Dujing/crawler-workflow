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

pytestmark = pytest.mark.unit

STATIC_DIR = Path(__file__).resolve().parents[2] / 'backend' / 'static'
JS_DIR = STATIC_DIR / 'js'
HARNESS = Path(__file__).resolve().parents[1] / 'frontend' / 'harness_canvas.mjs'
CANVAS_JS = JS_DIR / 'canvas.js'

# Files whose I18n.t('literal') calls are audited against the catalogues.
I18N_USERS = ['app.js', 'canvas.js', 'workflow.js', 'menu.js', 'stats.js']

_KEY_REF = re.compile(r"""I18n\.t\(\s*(['"])([A-Za-z][\w.]*)\1\s*\)""")
_DICT_KEY = re.compile(r"""['"]([A-Za-z][\w.]*)['"]\s*:\s*['"]""")


def _catalog_keys():
    """{lang: set(keys)} parsed out of app.js's I18n.dict literals."""
    src = (JS_DIR / 'app.js').read_text(encoding='utf-8')
    en_start = src.index('dict: {')
    en_body = src[en_start : src.index('zh: {', en_start)]
    zh_body = src[src.index('zh: {', en_start) : src.index('_missing:')]
    grab = lambda block: {m.group(1) for m in _DICT_KEY.finditer(block)}  # noqa: E731
    return {'en': grab(en_body), 'zh': grab(zh_body)}


class TestCanvasSerialization:
    """toWorkflowJSON is the browser→backend wire; its shape is a real contract."""

    @pytest.fixture(scope='class')
    def payload(self):
        node = shutil.which('node')
        if not node:
            pytest.skip('node not available')
        import subprocess

        proc = subprocess.run(
            [node, str(HARNESS), str(CANVAS_JS)],
            capture_output=True,
            text=True,
            timeout=60,
            # Windows would decode this UTF-8 JSON with the GBK locale default.
            encoding='utf-8',
        )
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
        source_defaults = re.search(r"if \(type === 'source'\) return \{([^}]+)\}", canvas_src)
        assert source_defaults and 'collect' in source_defaults.group(1)
