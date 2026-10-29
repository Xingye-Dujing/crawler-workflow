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
STUDIO = STATIC / 'zenviz.html'
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


@pytest.fixture(scope='module')
def studio_sweep():
    """The chart-studio page is much smaller than the workbench (its markup is ~120
    elements); the same four document questions still apply to it."""
    parser = _Sweep()
    parser.feed(STUDIO.read_text(encoding='utf-8'))
    assert parser.tags >= 100, f'the studio sweep only saw {parser.tags} elements'
    assert len(parser.ids) >= 40, f'the studio sweep only saw {len(parser.ids)} ids'
    assert len(parser.controls) >= 15, f'the studio sweep only saw {len(parser.controls)} buttons/links'
    return parser


def _duplicate_ids(parser, page):
    seen = {}
    duplicates = []
    for element_id, tag, (line, _col) in parser.ids:
        if element_id in seen:
            duplicates.append(f'#{element_id} (<{tag}>) at line {line}, first at line {seen[element_id]}')
        else:
            seen[element_id] = line
    assert not duplicates, f'duplicate ids in {page}: ' + '; '.join(duplicates)


def _nesting_errors(parser, page):
    assert not parser.errors, f'mis-nested markup in {page}:\n' + '\n'.join(parser.errors)
    assert not parser.stack, f'unclosed tags in {page}: {[tag for tag, _pos in parser.stack]}'


def _dangling_idrefs(parser, page):
    known = {element_id for element_id, _tag, _pos in parser.ids}
    dangling = [
        f'{name}="{value}" at line {pos[0]}'
        for name, value, pos in parser.idrefs
        for token in value.split()
        if token not in known
    ]
    assert not dangling, f'references to missing ids in {page}: ' + '; '.join(dangling)


def _unnamed_controls(parser, page):
    """An icon-only control with no text and no ``aria-label`` is announced as
    "button" — the SVG inside it carries no name."""
    unnamed = [
        f'<{control["tag"]}> at line {control["pos"][0]}'
        for control in parser.controls
        if not (
            control['text']
            or control['attrs'].get('aria-label')
            or control['attrs'].get('title')
            or control['attrs'].get('data-i18n-title')
        )
    ]
    assert not unnamed, f'controls with no accessible name in {page}: ' + ', '.join(unnamed)


class TestTheDocumentIsADocument:
    def test_every_id_is_unique(self, sweep):
        """``getElementById`` answers the FIRST match, so a duplicate id silently moves a
        panel, a label or a harness stub to the wrong element."""
        _duplicate_ids(sweep, 'index.html')

    def test_the_markup_nests_cleanly(self, sweep):
        """An unclosed or mis-nested tag makes the browser re-parent panels: the page
        still renders, but the panel a test (or a user) expects inside a container is
        not, and every position-based assumption downstream is wrong."""
        _nesting_errors(sweep, 'index.html')

    def test_every_id_reference_names_an_element_that_exists(self, sweep):
        _dangling_idrefs(sweep, 'index.html')

    def test_every_button_and_link_has_an_accessible_name(self, sweep):
        _unnamed_controls(sweep, 'index.html')


class TestTheStudioPageIsADocument:
    """``zenviz.html`` is a second page with its own ids and controls; it was 16,852 lines
    of inline style + script until 2026-10-29, which is exactly the shape in which a
    duplicate id or a mis-closed div goes unnoticed."""

    def test_every_id_is_unique(self, studio_sweep):
        _duplicate_ids(studio_sweep, 'zenviz.html')

    def test_the_markup_nests_cleanly(self, studio_sweep):
        _nesting_errors(studio_sweep, 'zenviz.html')

    def test_every_id_reference_names_an_element_that_exists(self, studio_sweep):
        _dangling_idrefs(studio_sweep, 'zenviz.html')

    def test_every_button_and_link_has_an_accessible_name(self, studio_sweep):
        _unnamed_controls(studio_sweep, 'zenviz.html')


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


class TestThePageLoadsItsStylesheets:
    """``style.css`` was one 5,017-line file; it is now one sheet per UI domain, and the page
    list is the only thing that decides which rule wins a tie. So the list itself is a contract:
    every sheet on disk is loaded, no sheet twice, and no page reaches for a file that is not there."""

    CSS_DIR = STATIC / 'css'
    _CSS_HREF = re.compile(r'<link\b[^>]*\brel="stylesheet"[^>]*\bhref="/css/([^"]+)"')

    def _hrefs(self, page: Path) -> list[str]:
        return self._CSS_HREF.findall(page.read_text(encoding='utf-8'))

    def test_every_stylesheet_the_pages_name_exists_and_is_named_once(self):
        offenders = []
        for page in (INDEX, STUDIO):
            hrefs = self._hrefs(page)
            missing = [name for name in hrefs if not (self.CSS_DIR / name).is_file()]
            duplicated = sorted({name for name in hrefs if hrefs.count(name) > 1})
            offenders += [f'{page.name}: missing {missing}' for missing in [missing] if missing]
            offenders += [f'{page.name}: loaded twice {duplicated}' for duplicated in [duplicated] if duplicated]
        assert offenders == [], offenders

    def test_no_stylesheet_on_disk_is_unloaded(self):
        """An orphan sheet is either dead code or a file somebody forgot to link — the browser
        never parses it, so a rule that looks fixed there is not fixed at all."""
        loaded = set(self._hrefs(INDEX)) | set(self._hrefs(STUDIO))
        on_disk = {path.name for path in self.CSS_DIR.glob('*.css')}
        assert on_disk - loaded == set(), f'stylesheets no page loads: {sorted(on_disk - loaded)}'

    def test_the_workbench_loads_its_sheets_in_the_order_the_rules_were_written(self):
        """The split is by contiguous slice, so the page order IS the old file order."""
        from static_assets import css_text  # the helper the CSS-reading tests share

        sheet = css_text(INDEX)
        # The first and last rule of the old single stylesheet, in the order they were written:
        # the design-system banner before any selector, the export-guide overlay after.
        assert sheet.index('Crawler Workflow — design system') < sheet.index('#top-menu {')
        assert sheet.index('#top-menu {') < sheet.index('Export-guide overlay')


class TestTheStudioPageLoadsItsFiles:
    def test_the_studio_page_carries_no_inline_style_or_script(self, studio_sweep):
        """The chart studio was a 16,852-line document: a ~1,920-line ``<style>`` and a
        ~14,700-line inline ``<script>``. Both are files now — a strict CSP can ban inline
        code, and ``node --check`` never saw the largest script in the project."""
        assert not studio_sweep.inline_scripts, f'inline script bodies are back: {studio_sweep.inline_scripts}'
        html = STUDIO.read_text(encoding='utf-8')
        assert re.search(r'<style\b', html) is None, 'an inline <style> block is back in zenviz.html'

    def test_every_module_the_studio_names_is_shipped(self, studio_sweep):
        missing = []
        for attrs, pos in studio_sweep.scripts:
            match = _SCRIPT_SRC.match(attrs.get('src') or '')
            if match and not (JS_DIR / match.group(1)).is_file():
                missing.append(f'/js/{match.group(1)} at line {pos[0]}')
        assert not missing, f'zenviz.html loads scripts that are not on disk: {missing}'
        names = [attrs.get('src') for attrs, _pos in studio_sweep.scripts if attrs.get('src')]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        assert not duplicates, f'zenviz.html loads these more than once: {duplicates}'

    def test_the_studio_page_script_and_its_stylesheet_are_page_owned(self, studio_sweep, sweep):
        """The studio app is loaded by the studio page only (like its bridge): the workbench
        has its own embedded host, and two page apps on one page would fight over ``#chart-mount``."""
        loaded = {
            _SCRIPT_SRC.match(attrs['src']).group(1)
            for attrs, _pos in studio_sweep.scripts
            if _SCRIPT_SRC.match(attrs['src'])
        }
        workbench = {
            _SCRIPT_SRC.match(attrs['src']).group(1) for attrs, _pos in sweep.scripts if _SCRIPT_SRC.match(attrs['src'])
        }
        assert 'zenviz-page.js' in loaded, f'the studio page app is not loaded: {sorted(loaded)}'
        assert 'zenviz-page.js' not in workbench, 'the studio page app leaked onto the workbench page'
        assert (STATIC / 'css' / 'zenviz.css').is_file()
