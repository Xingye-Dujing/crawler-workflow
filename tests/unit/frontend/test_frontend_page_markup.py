"""``index.html`` itself is a contract: ids, nesting, and where its scripts load.

Every other page test reads the markup for ONE fact (a ``data-i18n`` key, a palette
``data-type``, a settings control). Nothing asked whether the document is a document:
a duplicated id silently retargets ``getElementById`` to the first element, a mis-closed
``<div>`` makes the browser re-parent whole panels, an inline ``<script>`` defeats a
strict CSP and escapes ``node --check``, and a module listed twice re-declares its
top-level ``const`` and kills the page at load. All four render a page that mostly works,
which is why none of them was noticed by a test that only looks at attributes.

The sweep is one ``html.parser`` pass over the shipped file; no browser and no node are
needed, so this half stays green on a machine without either.
"""

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / 'backend' / 'static'
INDEX = STATIC / 'index.html'
JS_DIR = STATIC / 'js'

#: Tags the HTML spec leaves unclosed; every other tag in this page is written closed.
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}

#: Attributes that name another element by id.
IDREF_ATTRS = ('for', 'aria-labelledby', 'aria-describedby', 'aria-controls', 'aria-owns')

#: The scripts that must exist regardless of the markup sweep (the sweep's own floor).
REQUIRED_SCRIPTS = {'canvas.js', 'workflow.js', 'app.js', 'theme-boot.js'}

_SCRIPT_SRC = re.compile(r'^/js/(.+)$')


class _Sweep(HTMLParser):
    """Collect the four facts the tests below need, with source positions for failures."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.errors = []
        self.ids = []
        self.idrefs = []
        self.tags = 0
        self.scripts = []
        self.inline_scripts = []
        self.controls = []
        self._open_script = None
        self._open_control = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags += 1
        if 'id' in attrs:
            self.ids.append((attrs['id'], tag, self.getpos()))
        for name in IDREF_ATTRS:
            if attrs.get(name):
                self.idrefs.append((name, attrs[name], self.getpos()))
        if tag == 'script':
            self.scripts.append((attrs, self.getpos()))
            self._open_script = attrs
        if tag in ('button', 'a'):
            self._open_control = {'tag': tag, 'attrs': attrs, 'pos': self.getpos(), 'text': ''}
        if tag in VOID:
            return
        self.stack.append((tag, self.getpos()))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.stack.pop()

    def handle_endtag(self, tag):
        if tag == 'script':
            self._open_script = None
        if tag in ('button', 'a') and self._open_control:
            self.controls.append(self._open_control)
            self._open_control = None
        if tag in VOID:
            return
        if not self.stack:
            self.errors.append(f'</{tag}> at line {self.getpos()[0]} closes nothing')
            return
        opened, pos = self.stack.pop()
        if opened != tag:
            self.errors.append(f'</{tag}> at line {self.getpos()[0]} closes <{opened}> opened at line {pos[0]}')

    def handle_data(self, data):
        if self._open_control is not None and data.strip():
            self._open_control['text'] += data.strip()
        if self._open_script is not None and 'src' not in self._open_script and data.strip():
            self.inline_scripts.append((self.getpos(), data.strip()[:60]))


@pytest.fixture(scope='module')
def sweep():
    parser = _Sweep()
    parser.feed(INDEX.read_text(encoding='utf-8'))
    # The floors are part of the fixture: a sweep that stopped finding elements because
    # the page was rewritten (or the parser was pointed at the wrong file) must fail here,
    # not quietly pass every check below.
    assert parser.tags >= 600, f'the sweep only saw {parser.tags} elements'
    assert len(parser.ids) >= 190, f'the sweep only saw {len(parser.ids)} ids'
    assert len(parser.controls) >= 100, f'the sweep only saw {len(parser.controls)} buttons/links'
    return parser


class TestTheDocumentIsADocument:
    def test_every_id_is_unique(self, sweep):
        """``getElementById`` answers the FIRST match, so a duplicate id silently moves a
        panel, a label or a harness stub to the wrong element."""
        seen = {}
        duplicates = []
        for element_id, tag, (line, _col) in sweep.ids:
            if element_id in seen:
                duplicates.append(f'#{element_id} (<{tag}>) at line {line}, first at line {seen[element_id]}')
            else:
                seen[element_id] = line
        assert not duplicates, 'duplicate ids in index.html: ' + '; '.join(duplicates)

    def test_the_markup_nests_cleanly(self, sweep):
        """An unclosed or mis-nested tag makes the browser re-parent panels: the page
        still renders, but the panel a test (or a user) expects inside a container is
        not, and every position-based assumption downstream is wrong."""
        assert not sweep.errors, 'mis-nested markup in index.html:\n' + '\n'.join(sweep.errors)
        assert not sweep.stack, f'unclosed tags: {[tag for tag, _pos in sweep.stack]}'

    def test_every_id_reference_names_an_element_that_exists(self, sweep):
        known = {element_id for element_id, _tag, _pos in sweep.ids}
        dangling = [
            f'{name}="{value}" at line {pos[0]}'
            for name, value, pos in sweep.idrefs
            for token in value.split()
            if token not in known
        ]
        assert not dangling, 'references to missing ids in index.html: ' + '; '.join(dangling)

    def test_every_button_and_link_has_an_accessible_name(self, sweep):
        """An icon-only control with no text and no ``aria-label`` is announced as
        "button" — the SVG inside it carries no name."""
        unnamed = [
            f'<{control["tag"]}> at line {control["pos"][0]}'
            for control in sweep.controls
            if not (
                control['text']
                or control['attrs'].get('aria-label')
                or control['attrs'].get('title')
                or control['attrs'].get('data-i18n-title')
            )
        ]
        assert not unnamed, 'controls with no accessible name: ' + ', '.join(unnamed)


class TestThePageLoadsItsScripts:
    def test_the_page_carries_no_inline_script(self, sweep):
        """The pre-paint theme block used to be the one inline script. It lives in
        ``js/theme-boot.js`` now: a strict Content-Security-Policy can ban inline
        scripts, and an inline block is the one product file no linter checks."""
        assert not sweep.inline_scripts, f'inline script bodies are back: {sweep.inline_scripts}'

    def test_each_module_is_listed_exactly_once(self, sweep):
        """A module loaded twice re-declares its top-level ``const`` bindings, which is a
        SyntaxError that kills every later script on the page."""
        names = [attrs.get('src') for attrs, _pos in sweep.scripts if attrs.get('src')]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        assert not duplicates, f'index.html loads these more than once: {duplicates}'

    def test_every_js_module_the_page_names_is_shipped(self, sweep):
        missing = []
        for attrs, pos in sweep.scripts:
            match = _SCRIPT_SRC.match(attrs.get('src') or '')
            if match and not (JS_DIR / match.group(1)).is_file():
                missing.append(f'/js/{match.group(1)} at line {pos[0]}')
        assert not missing, f'index.html loads scripts that are not on disk: {missing}'
        loaded = {
            _SCRIPT_SRC.match(attrs['src']).group(1) for attrs, _pos in sweep.scripts if _SCRIPT_SRC.match(attrs['src'])
        }
        assert loaded >= REQUIRED_SCRIPTS, f'the page stopped loading: {sorted(REQUIRED_SCRIPTS - loaded)}'

    def test_the_theme_bootstrap_is_the_first_script_and_blocks_paint(self, sweep):
        """theme-boot.js applies the saved theme before the first frame. Deferred or moved
        below the panels, the default light page paints first and the dark choice flashes."""
        js_scripts = [(attrs, pos) for attrs, pos in sweep.scripts if _SCRIPT_SRC.match(attrs.get('src') or '')]
        assert js_scripts, 'the page loads no module at all'
        first_attrs, _first_pos = js_scripts[0]
        assert first_attrs.get('src') == '/js/theme-boot.js', f'the first module is {first_attrs.get("src")}'
        assert 'defer' not in first_attrs and 'async' not in first_attrs, (
            'a deferred bootstrap runs after the light default is already on screen'
        )
        html = INDEX.read_text(encoding='utf-8')
        assert html.index('/js/theme-boot.js') < html.index('id="menu-trigger"'), (
            'the bootstrap must run before the visible chrome is parsed'
        )
