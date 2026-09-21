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

import threading

import pytest

import i18n
from i18n import DEFAULT_LANG, LANGS, audit, get_lang, missing_keys, normalize, set_lang, t

pytestmark = pytest.mark.unit


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
        params = {'i': 1, 'nid': 'node-2', 'ntype': 'source'}
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
            'source_no_keyword',
            'source_no_urls',
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
