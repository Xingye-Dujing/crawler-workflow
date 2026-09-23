"""Tests for backend/i18n.py — the console message catalogue.

Every user-visible line in this app funnels through ``t()``, and the catalogue
is maintained by hand, so the tests double as the CI guard for it:

- a rendering problem must never raise (a crawl may not die because a message
  was written in printf style),
- the zh/en tables must stay in step — keys *and* placeholders,
- ``audit()`` has to keep returning ``[]``: a leftover ``%s`` is invisible until
  a user sees a literal ``%s`` in the console.

Language is thread-local and workflow runs live in worker threads, so that
boundary is pinned too.
"""

import ast
import re
import threading
from pathlib import Path

import pytest

import i18n
from i18n import DEFAULT_LANG, LANGS, audit, get_lang, missing_keys, normalize, set_lang, t

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def restore_lang():
    """Language is process state on this thread — hand it back untouched."""
    previous = getattr(i18n._local, 'lang', None)
    yield
    if previous is None:
        del i18n._local.lang
    else:
        i18n._local.lang = previous


@pytest.fixture(autouse=True)
def zh_by_default(restore_lang):
    set_lang('zh')


# ─── language selection ────────────────────────────────────────────────


class TestNormalize:
    @pytest.mark.parametrize(
        'value, expected',
        [
            ('zh', 'zh'),
            ('en', 'en'),
            ('zh-CN', 'zh'),
            ('en_US', 'en'),
            ('ZH-HANS', 'zh'),
            ('  en  ', 'en'),
            ('English', 'zh'),
            ('fr', 'zh'),
            ('en-GB', 'en'),
            ('', 'zh'),
            (None, 'zh'),
            (123, 'zh'),
        ],
    )
    def test_any_spelling_maps_onto_a_catalogue(self, value, expected):
        assert normalize(value) == expected

    def test_the_default_language_is_in_the_catalogue(self):
        assert DEFAULT_LANG in LANGS and set(i18n.MESSAGES) == set(LANGS)

    def test_set_lang_reports_what_it_stored(self, restore_lang):
        assert set_lang('en-US') == 'en' and get_lang() == 'en'
        assert set_lang('nonsense') == 'zh' and get_lang() == 'zh'


class TestThreadLocality:
    def test_a_worker_thread_starts_at_the_default(self, restore_lang):
        set_lang('en')
        seen = []
        thread = threading.Thread(target=lambda: seen.append(get_lang()))
        thread.start()
        thread.join()
        # Not inherited: a run worker must re-apply the captured language.
        assert seen == [DEFAULT_LANG]

    def test_a_worker_thread_can_pin_its_own_language(self, restore_lang):
        set_lang('en')
        seen = []

        def worker():
            set_lang('zh')
            seen.append(get_lang())

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        assert seen == ['zh'] and get_lang() == 'en'

    def test_pinning_in_one_thread_does_not_move_another(self, restore_lang):
        results = {}
        barrier = threading.Barrier(2, timeout=5)

        def worker(name, lang):
            set_lang(lang)
            barrier.wait()
            results[name] = get_lang()

        threads = [threading.Thread(target=worker, args=(f't{i}', lang)) for i, lang in enumerate(['zh', 'en'])]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert results == {'t0': 'zh', 't1': 'en'}


# ─── rendering ─────────────────────────────────────────────────────────


class TestTranslation:
    def test_a_known_key_renders_in_the_active_language(self, restore_lang):
        key = 'wf.executing_node'
        params = {'wf': 'WF1', 'nid': 'node-2', 'ntype': 'source'}
        set_lang('zh')
        zh = t(key, **params)
        set_lang('en')
        assert t(key, **params) != zh
        assert 'node-2' in t(key, **params)

    def test_placeholders_are_filled_from_the_keywords(self):
        rendered = t('api.unsupportedPlatform', platform='douyin')
        assert 'douyin' in rendered and '{platform}' not in rendered

    def test_an_unknown_key_shows_itself_instead_of_a_foreign_language(self):
        assert t('there.is.no.such.message') == 'there.is.no.such.message'

    def test_a_missing_parameter_returns_the_raw_template(self):
        template = i18n._ZH['wf.executing_node']
        assert t('wf.executing_node', i=1) == template
        assert '{nid}' in t('wf.executing_node')

    def test_extra_parameters_are_ignored(self, restore_lang):
        assert t('chart.count', unused='x') == i18n._ZH['chart.count']

    def test_a_positional_template_is_not_a_crash(self, restore_lang):
        # str.format cannot fill printf placeholders; the user must still get
        # *something* readable, which is the raw template.
        i18n._ZH['temp.printf'] = '端口 %s 被占用'
        try:
            assert t('temp.printf', port=5000) == '端口 %s 被占用'
        finally:
            del i18n._ZH['temp.printf']

    def test_the_other_language_is_a_fallback_not_an_empty_string(self, monkeypatch):
        monkeypatch.setitem(i18n.MESSAGES, 'en', {})
        set_lang('en')
        assert t('chart.count') == i18n._ZH['chart.count']

    def test_empty_catalogue_for_the_default_language_still_returns_the_key(self, monkeypatch):
        monkeypatch.setitem(i18n.MESSAGES, 'zh', {})
        monkeypatch.setitem(i18n.MESSAGES, 'en', {})
        assert t('wf.completed') == 'wf.completed'

    def test_every_key_renders_without_raising(self, restore_lang):
        for lang in LANGS:
            set_lang(lang)
            for key in i18n.MESSAGES[lang]:
                assert isinstance(t(key), str) and t(key)


# ─── catalogue health ──────────────────────────────────────────────────


class TestCatalogueHealth:
    def test_audit_is_clean(self):
        # Guards the future: one untranslated/printf key and this names it.
        assert audit() == []

    def test_zh_and_en_hold_the_same_keys(self):
        assert missing_keys() == {'en_only': [], 'zh_only': []}

    def test_the_tables_are_the_same_size(self):
        assert len(i18n._ZH) == len(i18n._EN)

    def test_placeholders_match_between_languages(self):
        import re

        pattern = re.compile(r'\{([a-zA-Z0-9_]+)\}')
        for key, template in i18n._ZH.items():
            assert sorted(set(pattern.findall(template))) == sorted(set(pattern.findall(i18n._EN[key]))), key

    def test_no_template_is_empty(self):
        for table in i18n.MESSAGES.values():
            assert all(isinstance(value, str) and value.strip() for value in table.values())

    def test_engine_messages_exist_for_every_validated_node_type(self):
        for suffix in (
            'source_no_platform',
            'source_unknown_platform',
            'source_unknown_mode',
            'source_missing',
            'source_link_mismatch',
            'upload_no_file',
            'process_no_op',
            'output_no_op',
            'analysis_no_op',
            'tokenize_no_column',
            'visualize_no_chart',
            'visualize_no_x',
            'name_no_label',
            'name_not_head',
            'name_no_downstream',
        ):
            key = f'engine.{suffix}'
            assert key in i18n._ZH and key in i18n._EN

    def test_audit_names_a_broken_template(self):
        i18n._EN['temp.audit'] = 'value: %d'
        try:
            problems = audit()
            assert any('temp.audit' in problem for problem in problems)
        finally:
            del i18n._EN['temp.audit']
            assert audit() == []


class TestKeyReachability:
    """A message nobody can reach is a bug report that will never be written.

    zh/en parity (``audit``) only proves both languages hold the same keys, so a
    key left behind by a removed feature — or a typo that no call site ever
    matches — passes that check forever. Twelve such keys survived here until the
    WeChat comment code was deleted, which is why this direction is now tested
    too.
    """

    # Keys assembled at runtime cannot appear as a literal in any source file.
    DYNAMIC_PREFIXES = (
        'cookie.',  # services/cookie_flow.py: t(f'cookie.{platform}.purpose')
        'comment.status.',  # app.py: t(f'comment.status.{status}')
    )

    @staticmethod
    def _sources():
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        files = list((root / 'backend').rglob('*.py')) + list((root / 'backend' / 'static').rglob('*.js'))
        files += list((root / 'tests').rglob('*.py'))
        return '\n'.join(f.read_text(encoding='utf-8', errors='replace') for f in files if f.name != 'i18n.py')

    @staticmethod
    def _referenced(key: str, sources: str) -> bool:
        """Either quote style counts as a reference.

        A message used inside an f-string has to be written with double quotes
        (the string it lives in is single-quoted), and the rule this check
        enforces is about the *name* being spelled somewhere, not about which
        character the call site happened to use.
        """
        return f"'{key}'" in sources or f'"{key}"' in sources

    def _unreachable(self):
        sources = self._sources()
        dead = []
        for key in i18n._ZH:
            if key.startswith(self.DYNAMIC_PREFIXES):
                continue
            if not self._referenced(key, sources):
                dead.append(key)
        return dead

    def test_every_static_key_is_referenced_somewhere(self):
        assert self._unreachable() == []

    def test_the_quote_inspection_is_actually_needed(self):
        """If no call site ever needs the double-quoted form, drop that branch
        rather than keep a widening of the rule nobody uses."""
        sources = self._sources()
        single_only = [key for key in i18n._ZH if f"'{key}'" in sources]
        double_only = [
            key
            for key in i18n._ZH
            if f'"{key}"' in sources and f"'{key}'" not in sources and not key.startswith(self.DYNAMIC_PREFIXES)
        ]
        assert single_only, 'no key is referenced in single quotes at all'
        assert double_only, 'nothing needs the double-quoted form any more'

    def test_the_dynamic_allowlist_is_still_needed(self):
        """If a dynamic family ever stops being built at runtime, it must be
        checked literally like everything else rather than hide in the allowlist."""
        sources = self._sources()
        assert "f'cookie." in sources and "f'comment.status." in sources

    #: A hand-written ``t('key')`` whose key the catalogue does not hold.
    _CALL = re.compile(r"\bt\(\s*['\"]([A-Za-z][A-Za-z0-9_.]*)['\"]")

    def test_every_called_key_exists_in_the_catalogue(self):
        """The other direction of the same mistake — and the louder one.

        ``t()`` answers an unknown key by printing the key, so a typo is not a
        crash but a console line the user reads as gibberish. Seven call sites
        shipped that way (``crawl.resume_have`` on every resumed crawl,
        ``ds.too_many_rows`` as an error message, three dedupe notes) because
        parity and reachability are both silent about a key that is *missing*.
        """
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        missing = []
        for path in sorted((root / 'backend').rglob('*.py')):
            if path.name == 'i18n.py':
                continue
            for number, line in enumerate(path.read_text(encoding='utf-8', errors='replace').splitlines(), 1):
                for key in self._CALL.findall(line):
                    if key not in i18n._ZH:
                        missing.append(f'{path.name}:{number} {key}')
        assert missing == [], 'unknown message keys: ' + ', '.join(missing)

    def test_the_missing_key_check_would_actually_fire(self):
        """A guard that cannot fail is not a guard."""
        assert self._CALL.findall("logger.info(t('no.such.key', n=1))") == ['no.such.key']
        # ``get(``/``dict(``/``format(`` all end in t( — the word boundary is what
        # keeps this check from drowning in false positives.
        assert self._CALL.findall("data.get('workflow'); out.format('x'); d=dict(y)") == []


class TestNoDuplicateKeys:
    """A key written twice in one catalogue silently keeps the last spelling.

    Parity cannot see it (both languages can hold the same duplicate and still
    match each other), and the first message becomes unreachable text that no
    call site will ever print — the exact accident of editing this file: a
    rename landed as a new line next to the old one, and the run kept printing
    the stale wording.
    """

    @staticmethod
    def _key_lists():
        import ast
        from pathlib import Path

        source = (Path(__file__).resolve().parents[2] / 'backend' / 'i18n.py').read_text(encoding='utf-8')
        found = {}
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', '') in ('_ZH', '_EN'):
                found[node.targets[0].id] = [key.value for key in node.value.keys]
        return found

    def test_neither_catalogue_defines_a_key_twice(self):
        lists = self._key_lists()
        assert set(lists) == {'_ZH', '_EN'}, 'the guard stopped finding the catalogues'
        for name, keys in lists.items():
            seen = {key for key in keys if keys.count(key) > 1}
            assert not seen, f'{name} declares duplicated keys: {sorted(seen)}'

    def test_the_two_catalogues_hold_the_same_multiset_of_keys(self):
        lists = self._key_lists()
        # Not just the same *set*: the same count, so a duplicate on one side
        # only cannot pass as parity.
        assert sorted(lists['_ZH']) == sorted(lists['_EN'])


CONSOLE_LEVELS = ('info', 'warning', 'error', 'exception')


def _prose(value: str) -> bool:
    """True when a literal reads like a sentence rather than punctuation."""
    return len([word for word in value.split() if any(char.isalpha() for char in word)]) >= 2


def _literals_in(node):
    """Every string literal that could reach the console from this argument."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        if _prose(node.value):
            yield node.value
    elif isinstance(node, ast.JoinedStr):
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str) and _prose(part.value):
                yield part.value
    elif isinstance(node, ast.BinOp):
        yield from _literals_in(node.left)
        yield from _literals_in(node.right)


class TestNoHardcodedConsoleText:
    """Anything the run console can print has to come from the catalogue.

    A sentence typed into Python or JS is English no matter what language the
    rest of the screen speaks, and it also escapes the parity check above, so the
    two catalogues can drift with nobody noticing. ``logger.debug`` is exempt:
    the console handler's level is INFO, so those lines reach the file log only,
    where English is what a developer searching the log wants.
    """

    @staticmethod
    def _scan(source: str, label: str) -> list:
        """Offending console/print calls in one parsed module."""
        offenders = []
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            from_logger = (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id in ('logger', 'logging')
                and func.attr in CONSOLE_LEVELS
            )
            to_console = isinstance(func, ast.Name) and func.id == 'add_log'
            if not (from_logger or to_console):
                continue
            for text in _literals_in(node.args[0]):
                offenders.append(f'{label}:{node.lineno}: {text[:60]!r}')
        return offenders

    @classmethod
    def _python_offenders(cls) -> list:
        found = []
        for path in sorted((REPO / 'backend').rglob('*.py')):
            found.extend(cls._scan(path.read_text(encoding='utf-8'), str(path.relative_to(REPO))))
        return found

    @staticmethod
    def _javascript_offenders() -> list:
        offenders = []
        # Only a literal held DIRECTLY by the call is hardcoded prose:
        # `showToast(I18n.t('x') + ': ' + err)` composes a catalogued sentence and
        # must not be flagged with it.
        pattern = re.compile(r"(?:showToast|alert)\s*\(\s*'([^']{4,})'")
        for path in sorted((REPO / 'backend' / 'static' / 'js').glob('*.js')):
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                match = pattern.search(line)
                if match and _prose(match.group(1)):
                    offenders.append(f'{path.relative_to(REPO)}:{number}: {match.group(1)[:60]!r}')
        return offenders

    def test_no_python_line_reaches_the_console_untranslated(self):
        assert self._python_offenders() == []

    def test_no_javascript_toast_is_untranslated(self):
        assert self._javascript_offenders() == []

    def test_the_scan_catches_the_shape_it_bans(self):
        """A guard that matches nothing proves nothing; feed it the exact
        violation, plus the two forms that must stay allowed."""
        banned = 'import logging\nlogger = logging.getLogger(__name__)\nlogger.warning("could not read the file")\n'
        assert len(self._scan(banned, 'sample.py')) == 1
        allowed = (
            'import logging\nfrom i18n import t\nlogger = logging.getLogger(__name__)\n'
            "logger.debug('developer-only note: %s', t)\n"
            "logger.warning(t('misc.save_workflow_failed'))\n"
            'add_log(f\'{t("misc.cookie_save_failed")}: {str(err)[:120]}\')\n'
        )
        assert self._scan(allowed, 'sample.py') == []
