"""The browser catalogue is under test too, not only ``backend/i18n.py``.

AGENTS: 「A missing `t()` keyword is a printed bug, not a crash」. The Python half has walked
every call site with ``ast`` for a while; the JS half had no check at all, and two defects
shipped because of it (both measured on screen 2026-09-28):

* ``dialog.cookieDelete`` names the platform **twice**, and its call site used
  ``.replace('{platform}', …)`` — a string needle replaces the FIRST occurrence only, so the
  user read a literal ``{platform}`` in the middle of a Chinese sentence;
* ``settings.liveExportHint`` carries a ``{node}`` slot no call site ever filled.

Both are invisible to every existing guard: the key exists, is referenced, and its zh/en
templates match each other. The defect is at the call site, and it is a *counting* property —
a slot repeated is a slot that must be filled repeatedly, which is exactly what
``I18n.fill`` (added with this file) exists to make impossible.
"""

import json
import re
import shutil
from collections import Counter
from pathlib import Path

import pytest
from node_runner import run_node

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(shutil.which('node') is None, reason='node not installed'),
]

ROOT = Path(__file__).resolve().parents[2]
JS_DIR = ROOT / 'backend' / 'static' / 'js'
HARNESS = ROOT / 'tests' / 'frontend' / 'harness_i18n_catalog.mjs'

SLOT_RE = re.compile(r'\{(\w+)\}')
CALL_RE = re.compile(r"I18n\.t\(\s*'([^']+)'\s*([,{)])")

#: A slot that must be answered with a WORD the user reads, never the machine key.
PLATFORM_SLOTS = {'platform', 'platforms', 'plat', 'where'}
#: …and the helpers that produce that word. Anything else filling the slot prints `zhihu`.
LABEL_SOURCES = ('platformLabels(', 'entryLabels(', "I18n.t('platform.", 'platformLabel(')
#: Where printing the key IS the fact: a platform the matrix has no row for cannot be
#: labelled, and ``platformLabels`` would echo the same string back with a lookup missed.
BARE_KEY_IS_RIGHT = {('workflow.js', 'validate.sourceUnknownPlatform')}
#: A sentence handed to another file to fill. ``studio.multiCount`` is stored on
#: ``dataset.multiLabel`` by zenviz.js and formatted by custom-select.js when the count is
#: known — a call-site scan that cannot see across files would otherwise call it a hole.
HAND_FILLED = {('zenviz.js', 'studio.multiCount')}


def _catalogs():
    proc = run_node(str(HARNESS), str(JS_DIR))
    assert proc.returncode == 0, f'catalog harness failed: {proc.stderr[-1500:]} {proc.stdout[-400:]}'
    return json.loads(proc.stdout)


def _matching(text, start, opener, closer):
    """The index just past ``closer`` that balances ``opener`` from ``start``, or None."""
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index + 1
    return None


def _call_sites(source):
    """Every ``(key, region, vars_keys)`` where ``source`` asks the catalogue for a string.

    ``region`` is the rest of the statement — where a ``.replace('{slot}', …)`` chain would
    live — cut at the next ``;`` (or a bounded window when the statement runs long), because
    a fill that belongs to a *different* sentence must not count as covering this one.
    """
    for match in CALL_RE.finditer(source):
        key = match.group(1)
        rest = source[match.end() :]
        semi = rest.find(';')
        region = rest[: semi if 0 <= semi < 1200 else 1200]
        vars_keys = set()
        if match.group(2) == ',':
            brace = region.find('{')
            close = _matching(region, brace, '{', '}') if brace >= 0 else None
            if close:
                vars_keys = set(re.findall(r'[\'"]?(\w+)[\'"]?\s*:', region[brace:close]))
        yield key, region, vars_keys


def _uses_label(source, value):
    """Whether *value* produces a user-readable word rather than a machine key.

    A bare identifier is followed to its assignment, because the honest shape at these call
    sites is ``var who = entryLabels([…]);`` and then ``{ platform: who }`` — refusing that
    would only teach the next reader to inline the label call twice.
    """
    value = str(value).strip()
    if any(helper in value for helper in LABEL_SOURCES):
        return True
    if re.fullmatch(r'[A-Za-z_$][\w$]*', value):
        one = re.search(r'(?:var|let|const)\s+' + re.escape(value) + r'\s*=\s*([^;\n]{0,200})', source)
        if one and any(helper in one.group(1) for helper in LABEL_SOURCES):
            return True
    return False


def _unfilled(catalogs, files):
    problems = []
    for name, source in files:
        for key, region, vars_keys in _call_sites(source):
            if (name, key) in HAND_FILLED:
                continue
            template = catalogs['en'].get(key)
            if template is None:
                continue  # a computed or unknown key is TestJsCatalogueParity's business
            for slot, wanted in Counter(SLOT_RE.findall(template)).items():
                filled = region.count(".replace('{" + slot + "}'")
                if slot in vars_keys:
                    # ``I18n.fill`` replaces every occurrence, so one vars entry covers them all.
                    filled = wanted
                if not filled:
                    problems.append(f'{name}: {key} never fills {{{slot}}}')
                elif filled < wanted:
                    problems.append(f'{name}: {key} repeats {{{slot}}} {wanted}x but fills it {filled}x')
    return problems


def _raw_platform_words(catalogs, files):
    problems = []
    for name, source in files:
        for key, region, vars_keys in _call_sites(source):
            template = catalogs['en'].get(key)
            if template is None:
                continue
            if (name, key) in BARE_KEY_IS_RIGHT:
                continue
            for slot in SLOT_RE.findall(template):
                if slot not in PLATFORM_SLOTS:
                    continue
                if slot in vars_keys:
                    brace = region.find('{')
                    close = _matching(region, brace, '{', '}') if brace >= 0 else None
                    body = region[brace:close] if close else ''
                    marker = slot + ':'
                    at = body.find(marker)
                    if at < 0:
                        continue  # reported as unfilled above
                    value = body[at + len(marker) :]
                    # The entry ends at the next key or the object's own close; reading the
                    # rest of the object as this slot's value made a clean
                    # ``{ platform: who, n: 3 }`` look like an unresolved expression.
                    value = re.split(r'[},]', value)[0]
                    if not _uses_label(source, value):
                        problems.append(f'{name}: {key} fills {{{slot}}} with a key, not a word')
                    continue
                needle = ".replace('{" + slot + "}'"
                at = region.find(needle)
                while at >= 0:
                    # The opening paren of the `.replace(` itself — NOT the next one after the
                    # needle, which is the first paren of the VALUE (`platformLabels(`), and
                    # reading that as the argument made every correct label call look like a bug.
                    open_paren = region.find('(', at)
                    end = _matching(region, open_paren, '(', ')') if open_paren >= 0 else None
                    value = region[open_paren + 1 : end - 1] if end else ''
                    if not _uses_label(source, value):
                        problems.append(f'{name}: {key} fills {{{slot}}} with a key, not a word')
                    at = region.find(needle, at + 1)
    return problems


def _js_files():
    return [(path.name, path.read_text(encoding='utf-8')) for path in sorted(JS_DIR.glob('*.js'))]


class TestJsCallSitePlaceholders:
    def test_every_template_slot_is_filled_as_many_times_as_it_appears(self):
        assert _unfilled(_catalogs(), _js_files()) == []

    def test_the_two_languages_repeat_a_slot_the_same_number_of_times(self):
        catalogs = _catalogs()
        drift = []
        for key, en in catalogs['en'].items():
            zh = catalogs['zh'].get(key)
            if zh is None:
                continue  # key parity is pinned by test_frontend_js
            if Counter(SLOT_RE.findall(en)) != Counter(SLOT_RE.findall(zh)):
                drift.append(
                    f'{key}: en {sorted(Counter(SLOT_RE.findall(en)).items())} '
                    f'vs zh {sorted(Counter(SLOT_RE.findall(zh)).items())}'
                )
        assert drift == []

    def test_a_platform_slot_is_answered_with_a_word_not_the_key(self):
        assert _raw_platform_words(_catalogs(), _js_files()) == []

    def test_the_dialog_that_shipped_a_raw_placeholder_is_filled_through_the_formatter(self):
        """The exact regression, pinned at the call site rather than only by the scan."""
        source = (JS_DIR / 'workflow.js').read_text(encoding='utf-8')
        # The account is a PARAMETER of the delete now (a management row deletes its own
        # login, not whatever is typed), so the pinned line names the argument it forwards.
        # What may not regress is that the dialog is told WHICH session is about to go.
        assert 'var who = entryLabels([{ platform: platform, account: account }]);' in source, (
            'the delete dialog stopped naming the ACCOUNT whose file is about to go — one platform '
            'holds several logins, and 「删除 知乎 的 Cookie 文件」 while the box says `work` describes '
            'a file this request does not touch'
        )
        assert "I18n.t('dialog.cookieDelete', { platform: who })" in source, (
            'the delete dialog went back to `.replace`, which fills only the first of its two '
            '{platform} slots — that is how a literal {platform} reached the screen'
        )


class TestCatalogueShape:
    """Two ways a catalogue can be wrong that a parity scan cannot see.

    Both were found while writing the account list: the browser catalogue was missing the
    key the server sends for 「默认账号2」 (so the panel would have printed
    `cookies.accountDefaultNumbered` on screen), and one pre-existing key was simply
    written twice in each language.
    """

    def test_no_key_is_written_twice_in_one_language(self):
        """A repeated key in an object literal is legal JavaScript and the LAST wins.

        The parity harness reads a parsed dictionary, which has already collapsed the pair —
        so a duplicated key is invisible to every "same keys, same slots" check while one of
        the two answers is dead code that the next editor will wonder about.
        """
        source = (JS_DIR / 'app.js').read_text(encoding='utf-8')
        counts = Counter(re.findall(r"^\s+'([A-Za-z][\w.]*)':", source, re.M))
        wrong = {key: n for key, n in counts.items() if n != 2}
        assert wrong == {}, f'each key belongs to exactly one catalogue per language: {wrong}'

    def test_every_account_label_the_server_sends_has_a_word_in_both_languages(self):
        """``labelKey`` crosses the wire as a KEY; the browser is the one that must own it.

        A generated account name is this program's word, so it travels as a catalogue key —
        and a key the browser cannot answer is printed raw. A name the user typed is the
        other half of the rule: it carries NO key and is shown exactly as typed.
        """
        from services.cookie_manager import CookieManager

        catalogs = _catalogs()
        for account in ('', 'default2', 'default10', 'work'):
            key, args = CookieManager.account_label_key(account)
            if not key:
                assert account == 'work', f'{account} is generated, so it must have a key'
                continue
            for lang, table in catalogs.items():
                template = table.get(key)
                assert template is not None, f'{lang} browser catalogue has no {key} the server sends'
                slots = Counter(SLOT_RE.findall(template))
                assert set(slots) == set(args), f'{key}/{lang}: template slots {dict(slots)} vs sent {args}'
                assert all(n == 1 for n in slots.values()), f'{key}/{lang} repeats a slot: {template}'


def _dead_app_keys(en_keys, app_text, other_js, html, backend):
    """Every ``app.js`` catalogue key no app surface renders.

    A key is reachable when some file spells it — ``I18n.t('k')`` / an inline handler in the JS,
    a ``data-i18n*`` in index.html, or a literal in the backend that ships it over the wire (a
    server-sent ``label_key`` such as ``cookies.accountDefault``) — OR when it is built at runtime
    off a ``'prefix.' +`` root the JS actually uses (``nodeType.``, ``op.``, ``platform.`` …).
    ``app.js`` holds BOTH the dictionary and the app logic, so its own keys count as used only when
    they appear more than the two catalogue definitions (one per language)."""
    all_js = app_text + '\n' + other_js
    dyn_roots = {root for root in re.findall(r"['\"]([A-Za-z][\w.]*\.)['\"]\s*\+", all_js)}

    def qcount(text, key):
        return text.count(f"'{key}'") + text.count(f'"{key}"')

    dead = []
    for key in en_keys:
        if any(f'{attr}="{key}"' in html for attr in ('data-i18n', 'data-i18n-title', 'data-i18n-placeholder')):
            continue
        if any(key.startswith(root) and len(key) > len(root) for root in dyn_roots):
            continue
        if qcount(other_js, key) or qcount(html, key) or qcount(backend, key):
            continue
        if qcount(app_text, key) > 2:  # 2 catalogue definitions; a 3rd is app.js's own logic
            continue
        dead.append(key)
    return sorted(dead)


def _app_surfaces():
    app_text = (JS_DIR / 'app.js').read_text(encoding='utf-8')
    other_js = '\n'.join(p.read_text(encoding='utf-8') for p in sorted(JS_DIR.glob('*.js')) if p.name != 'app.js')
    html = (JS_DIR.parent / 'index.html').read_text(encoding='utf-8')
    backend = '\n'.join(
        p.read_text(encoding='utf-8', errors='replace')
        for p in sorted((ROOT / 'backend').rglob('*.py'))
        if p.name != 'i18n.py'
    )
    return app_text, other_js, html, backend


class TestJsCatalogueParity:
    """The two browser catalogues must hold the SAME keys.

    The Python side has guarded this forever (``missing_keys`` / same-size); the ``app.js`` word
    list only checked *slot* parity, so a key added to one language and not the other slipped
    through and printed raw the moment the interface switched. English is the table the call-site
    scans read, so a ``zh``-only hole is the silent one — this closes both directions."""

    def test_both_languages_define_the_same_keys(self):
        catalogs = _catalogs()
        en, zh = set(catalogs['en']), set(catalogs['zh'])
        assert en - zh == set(), f'keys in en but not zh: {sorted(en - zh)}'
        assert zh - en == set(), f'keys in zh but not en: {sorted(zh - en)}'


class TestJsKeyReachability:
    """A browser word nothing renders is a removed feature waiting to be resurrected (AGENTS:
    a dead key is how a deleted button comes back). Mirrors ``TestKeyReachability`` on the Python
    side; the reference universe is the app (JS + index.html + the backend that ships label keys),
    NOT the tests — a key the test suite references but no screen paints is still dead in product."""

    def test_no_browser_key_is_unreachable(self):
        catalogs = _catalogs()
        app_text, other_js, html, backend = _app_surfaces()
        dead = _dead_app_keys(catalogs['en'], app_text, other_js, html, backend)
        assert dead == [], f'app.js holds keys nothing renders: {dead}'

    def test_the_reachability_rule_rejects_a_stray_key(self):
        """A guard that cannot fail is not a guard. Feed a key that exists in no surface and prove
        the same predicate calls it dead, while one the app really renders stays reachable."""
        app_text, other_js, html, backend = _app_surfaces()
        dead = _dead_app_keys(['zzz.no.screen.paints.this'], app_text, other_js, html, backend)
        assert dead == ['zzz.no.screen.paints.this'], dead
        # And a genuinely used key is NOT flagged — otherwise the rule would pass by finding nothing.
        assert _dead_app_keys(['btn.execute'], app_text, other_js, html, backend) == []


class TestTheScanFires:
    """A guard that cannot fail is not a guard (the Python side pins its own scan the same way)."""

    EN = {
        'temp.twice': '删除 {platform} 的 Cookie，{platform} 属于哪种情况',
        'temp.once': '已保存 {n} 条',
        'temp.hole': '本节点的 {node}.live 文件',
    }
    ZH = dict(EN)

    def _scan(self, source):
        return _unfilled({'en': self.EN, 'zh': self.ZH}, [('temp.js', source)])

    def test_a_repeated_slot_filled_once_is_reported(self):
        found = self._scan("I18n.t('temp.twice').replace('{platform}', p);")
        assert any('temp.twice' in one and 'platform' in one for one in found), found

    def test_a_slot_no_call_site_fills_is_reported(self):
        found = self._scan("I18n.t('temp.hole');")
        assert any('temp.hole' in one and 'node' in one for one in found), found

    def test_filling_every_occurrence_and_the_vars_form_are_both_accepted(self):
        assert self._scan("I18n.t('temp.twice').replace('{platform}', a).replace('{platform}', b);") == []
        assert self._scan("I18n.t('temp.twice', { platform: platformLabels([p]) });") == []

    def test_the_raw_word_check_reports_a_key_but_not_a_label_helper(self):
        catalogs = {'en': {'temp.plat': '删除 {platform} 的文件'}, 'zh': {'temp.plat': '删除 {platform} 的文件'}}
        raw = _raw_platform_words(catalogs, [('temp.js', "I18n.t('temp.plat').replace('{platform}', platform);")])
        assert raw == ['temp.js: temp.plat fills {platform} with a key, not a word'], raw
        assert (
            _raw_platform_words(
                catalogs, [('temp.js', "I18n.t('temp.plat', { platform: platformLabels([platform]) });")]
            )
            == []
        )
