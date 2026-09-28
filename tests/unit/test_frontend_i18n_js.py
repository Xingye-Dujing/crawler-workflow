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
        assert 'var who = entryLabels([{ platform: platform, account: cookieAccount() }]);' in source, (
            'the delete dialog stopped naming the ACCOUNT whose file is about to go — one platform '
            'holds several logins, and 「删除 知乎 的 Cookie 文件」 while the box says `work` describes '
            'a file this request does not touch'
        )
        assert "I18n.t('dialog.cookieDelete', { platform: who })" in source, (
            'the delete dialog went back to `.replace`, which fills only the first of its two '
            '{platform} slots — that is how a literal {platform} reached the screen'
        )


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
