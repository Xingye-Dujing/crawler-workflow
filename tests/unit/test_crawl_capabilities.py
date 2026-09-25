"""The crawl matrix: one description of what each platform can collect.

``crawl_capabilities`` is now what the executor calls, what validation refuses and
what the browser's Data Source panel renders. Three behaviours are worth pinning
by themselves:

* **coercion** — a node's stored parameters are whatever the widget last wrote,
  including nothing at all; the crawler must still receive the figure the panel
  previewed (a cleared 目标条数 means 50, not None, and 0 分片 means "off");
* **mode resolution** — a stale or hand-written mode key falls back to the
  platform's first mode, which is the mode the executor will actually run;
* **payload shape** — the browser builds its form out of what
  ``GET /api/capabilities`` returns, so a field name that is not an identifier
  would be written straight into an inline ``onchange``.

The catalogue half of the contract lives in ``test_frontend_contract.py``.
"""

import inspect
from pathlib import Path

import pytest

from crawl_capabilities import (
    CAPABILITIES,
    COLLECT_KINDS,
    FILE_FIELDS,
    as_dict,
    capability,
    crawl_kwargs,
    declared_defaults,
    fields_for,
    has_platform,
    link_fields,
    mode_for,
    mode_keys_for,
    mode_of_node,
    modes_for,
    needs_session,
    platform_ids,
    required_missing,
    shows_nothing,
)

pytestmark = pytest.mark.unit

IDENTIFIER = 64  # the JS side refuses a key longer than this, or one with punctuation


def _mode(platform, key):
    mode = mode_for(platform, key)
    assert mode is not None, f'{platform} declares no mode at all'
    return mode


class TestCoercion:
    """Stored parameters are text from a browser: every one needs a type."""

    def test_a_missing_number_becomes_the_declared_default(self):
        mode = _mode('zhihu', 'posts')
        assert crawl_kwargs(mode, {'keyword': 'ai'})['target_count'] == 50

    def test_a_cleared_number_falls_back_rather_than_becoming_zero(self):
        # 0 is a real choice for some fields (不分片, 跳过评论面板), so it must come
        # from someone typing 0 — an empty box has to mean the panel's figure.
        mode = _mode('zhihu', 'posts')
        for blank in ('', '   ', None):
            assert crawl_kwargs(mode, {'keyword': 'ai', 'target_count': blank})['target_count'] == 50

    def test_junk_in_a_number_field_degrades_to_the_default_not_to_an_error(self):
        mode = _mode('zhihu', 'posts')
        assert crawl_kwargs(mode, {'keyword': 'ai', 'target_count': 'abc'})['target_count'] == 50

    def test_a_number_below_the_floor_is_raised_to_it(self):
        # target_count=0 would end the walk before it began and report success.
        mode = _mode('zhihu', 'posts')
        assert crawl_kwargs(mode, {'keyword': 'ai', 'target_count': -5})['target_count'] == 1

    def test_a_ceiling_is_honoured_too(self):
        mode = _mode('zhihu', 'posts')
        params = {'keyword': 'ai', 'target_count': 999999}
        assert crawl_kwargs(mode, params)['target_count'] == 999999  # no ceiling declared
        clamped = [f for f in mode.fields if f.key == 'target_count'][0]
        assert clamped.minimum == 1 and clamped.maximum is None

    def test_a_float_string_is_read_as_a_count_not_rejected(self):
        mode = _mode('zhihu', 'posts')
        assert crawl_kwargs(mode, {'keyword': 'ai', 'target_count': '20.0'})['target_count'] == 20

    def test_booleans_are_booleans(self):
        mode = _mode('zhihu', 'posts')
        # recrawl is the run's business and never reaches the crawl; full_body is the
        # crawl's own trade — excerpt or expanded body — so it does.
        assert crawl_kwargs(mode, {'keyword': 'ai', 'recrawl': True}) == {
            'keyword': 'ai',
            'target_count': 50,
            'full_body': True,
        }
        assert crawl_kwargs(mode, {'keyword': 'ai', 'full_body': False})['full_body'] is False

    def test_urls_arrive_as_a_list_holding_one_entry_per_line(self):
        mode = _mode('zhihu', 'comments')
        urls = crawl_kwargs(mode, {'urls': 'https://a/1\nhttps://b/2, https://c/3'})['urls']
        assert urls == ['https://a/1', 'https://b/2', 'https://c/3']

    def test_text_is_trimmed_but_otherwise_untouched(self):
        mode = _mode('zhihu', 'posts')
        assert crawl_kwargs(mode, {'keyword': '  人工智能  '})['keyword'] == '人工智能'

    def test_only_the_fields_of_the_selected_mode_are_sent(self):
        assert 'start_time' in crawl_kwargs(_mode('weibo', 'posts'), {'keyword': 'k'})
        assert 'start_time' not in crawl_kwargs(_mode('zhihu', 'posts'), {'keyword': 'k'})
        assert 'comment_preview' in crawl_kwargs(_mode('xiaohongshu', 'posts'), {'keyword': 'k'})
        assert 'comment_preview' not in crawl_kwargs(_mode('douyin', 'posts'), {'keyword': 'k'})

    def test_the_handler_is_not_an_argument(self):
        # `resume` is written by the executor from the store; a matrix field with
        # that name would let a saved workflow dictate where a crawl restarts.
        for cap in CAPABILITIES:
            for mode in cap.modes:
                keys = {f.key for f in mode.fields}
                assert 'resume' not in keys, f'{cap.platform}/{mode.key} declares a resume field'


class TestModeResolution:
    def test_each_platform_names_its_modes(self):
        # 热榜 sits between 作者 and 评论 on both platforms that publish one, and its
        # presence is a measurement (docs/crawler_notes.md), not a guess: xiaohongshu
        # has no board surface at all (its /hot redirects to the ordinary feed), so it
        # must NOT appear here.
        assert mode_keys_for('zhihu') == ('posts', 'author', 'hot', 'comments')
        assert mode_keys_for('weibo') == ('posts', 'author', 'hot', 'comments')
        assert mode_keys_for('wechat') == ('posts',), 'WeChat has no comment adapter'
        assert 'hot' not in mode_keys_for('xiaohongshu'), '小红书 has no measurable board'
        assert 'hot' not in mode_keys_for('douyin'), 'the douyin board is not settled yet (docs)'

    def test_an_unknown_mode_key_reads_as_the_first_mode(self):
        # Old canvases and hand-edited JSON both land here; the panel shows the
        # mode the executor will run, not a form for a crawl nobody performs.
        assert mode_for('wechat', 'comments').key == 'posts'
        assert mode_for('zhihu', 'nonsense').key == 'posts'
        assert mode_for('zhihu', '').key == 'posts'

    def test_an_unknown_platform_describes_nothing(self):
        assert mode_for('kuaishou', 'posts') is None
        assert modes_for('kuaishou') == ()
        assert not has_platform('kuaishou')

    def test_the_node_is_read_the_way_the_executor_reads_it(self):
        assert mode_of_node({'params': {'platform': 'zhihu', 'collect': 'comments'}}).key == 'comments'
        assert mode_of_node({'platform': 'weibo', 'params': {}}).key == 'posts'
        # A hand-written file may say `mode`; both spellings mean the same thing.
        assert mode_of_node({'params': {'platform': 'douyin', 'mode': 'comments'}}).key == 'comments'
        assert mode_of_node({'params': {}}) is None

    def test_the_handler_names_a_method_the_crawler_class_actually_has(self):
        from crawlers import crawler_class

        for cap in CAPABILITIES:
            for mode in cap.modes:
                if mode.handler == 'comments':
                    continue
                assert callable(getattr(crawler_class(cap.platform), mode.handler, None)), (
                    f'{cap.platform}.{mode.handler} does not exist'
                )


class TestRequirements:
    def test_a_keyword_mode_demands_the_keyword(self):
        missing = required_missing(_mode('zhihu', 'posts'), {})
        assert [f.key for f in missing] == ['keyword']

    def test_a_link_mode_demands_links_and_not_a_keyword(self):
        assert [f.key for f in required_missing(_mode('zhihu', 'comments'), {})] == ['urls']
        assert required_missing(_mode('zhihu', 'comments'), {'urls': 'https://x/1'}) == []

    def test_a_list_of_links_must_actually_hold_one(self):
        # ``urls=' , '``, ``urls='\n'`` — split_urls yields nothing, and a node
        # that looks filled in but collects nothing is the lie this prevents.
        assert required_missing(_mode('douyin', 'comments'), {'urls': '   \n  '})[0].key == 'urls'

    def test_only_modes_with_an_ownership_rule_are_checked(self):
        assert [f.key for f in link_fields(_mode('zhihu', 'comments'))] == ['urls']
        assert link_fields(_mode('wechat', 'posts')) == [], 'WeChat links have no comment router to agree with'

    def test_each_link_field_names_the_platform_its_links_belong_to(self):
        for cap in CAPABILITIES:
            for field in link_fields(_mode(cap.platform, 'comments')):
                assert field.links_of == cap.platform


class TestDefaults:
    def test_every_field_the_matrix_sends_is_read_by_the_crawl(self):
        # The executor calls the crawler method with every declared field by keyword, and
        # every crawler method ends in ``**_kwargs`` — so a switch the crawler does not
        # read is accepted in silence: the panel draws it, the node stores it, the run
        # reports success, and nothing was ever decided by it.
        #
        # Two shapes count as read: a named parameter, or the key spelled out as a string
        # in the crawler's own module (xiaohongshu takes 评论预览 out of the kwargs bag on
        # purpose, because its signature is shared with the other search methods). The
        # second clause is a text match, not a data-flow proof — it cannot tell a real read
        # from a comment that mentions the key. It is here because the alternative is a
        # test that would fail on the platform that does it this way.
        from crawlers import crawler_class

        offenders = []
        for cap in CAPABILITIES:
            cls = crawler_class(cap.platform)
            module = inspect.getmodule(cls)
            source = Path(module.__file__).read_text(encoding='utf-8')
            for mode in cap.modes:
                if mode.handler == 'comments':
                    continue  # routed to the shared comment engine, which reads the node
                method = getattr(cls, mode.handler, None)
                if method is None:
                    offenders.append(f'{cap.platform}/{mode.key}: no {cls.__name__}.{mode.handler}')
                    continue
                taken = set(inspect.signature(method).parameters)
                sent = set(crawl_kwargs(mode, declared_defaults(cap.platform)))
                unread = {key for key in sent - taken if f"'{key}'" not in source}
                offenders += [f'{cap.platform}/{mode.key}: {key}' for key in sorted(unread)]
        assert not offenders, 'matrix fields the crawler never reads:\n' + '\n'.join(offenders)

    def test_the_guard_itself_reads_something(self):
        # A check that compares against an empty set passes forever. This one asks every
        # platform's every mode, so name the size it is expected to cover.
        from crawlers import crawler_class

        pairs = [(cap.platform, mode.key) for cap in CAPABILITIES for mode in cap.modes if mode.handler != 'comments']
        assert len(pairs) >= 10, pairs
        assert all(crawler_class(platform) is not None for platform, _key in pairs)

    def test_defaults_cover_every_field_the_platforms_modes_mention(self):
        defaults = declared_defaults('xiaohongshu')
        assert defaults['target_count'] == 50 and defaults['comment_preview'] == 5
        assert defaults['urls'] == '' and defaults['format'] == 'csv'

    def test_the_shared_file_fields_are_part_of_every_platform(self):
        for platform in platform_ids():
            defaults = declared_defaults(platform)
            for field in FILE_FIELDS:
                assert field.key in defaults, f'{platform} lost {field.key}'

    def test_fields_for_a_mode_ends_with_the_file_block(self):
        keys = [f.key for f in fields_for('zhihu', 'posts')]
        assert keys[:2] == ['keyword', 'target_count']
        assert keys[-3:] == ['part_size', 'format', 'keep_parts']

    def test_unknown_platform_offers_no_fields(self):
        assert fields_for('kuaishou', 'posts') == ()
        assert declared_defaults('kuaishou') == {}


class TestPayloadShape:
    """The browser builds its form from this dict, so its keys are an API."""

    def test_the_payload_is_json_ready_and_camel_cased(self):
        import json

        payload = json.loads(json.dumps(as_dict(), ensure_ascii=False))
        assert set(payload) == {'platforms', 'fileFields'}
        first = payload['platforms'][0]
        # `profileRecommended` travels with the platform, not the mode: running in a
        # throwaway browser is punished per site (a rotating session cookie, a risk
        # control that re-walls a replayed snapshot), and the pre-run notice is the
        # user's only chance to hear about it before the crawl starts.
        assert set(first) == {'platform', 'modes', 'profileRecommended', 'region', 'serialOnly'}
        mode = first['modes'][0]
        assert set(mode) == {
            'key',
            'labelKey',
            'handler',
            'rows',
            'noteKey',
            'actionKey',
            'actionJs',
            'collects',
            'needsSession',
            'fields',
        }
        # `serialOnly` marks the platform the site walls on concurrent paging (weibo):
        # two of its crawls queue whatever the 排队/错峰 switch says. Only weibo carries
        # it — a second platform flagged here would be a claim to re-measure.
        serial = {cap['platform'] for cap in payload['platforms'] if cap['serialOnly']}
        assert serial == {'weibo'}, serial
        # `nameKey` is deliberately absent: that word names the field in the
        # console, which is the backend's language, and shipping it would invite
        # the panel to grow a second, untranslated label path.
        assert set(mode['fields'][0]) == {
            'key',
            'control',
            'labelKey',
            'default',
            'hintKey',
            'options',
            'minimum',
            'maximum',
            'required',
            'coerce',
            'linksOf',
            'placeholder',
        }

    def test_a_field_key_has_to_survive_being_written_into_a_handler(self):
        # workflow.js refuses anything else, so declaring it here would be a
        # field the panel silently drops — a worse failure than a red test.
        bad = []
        for cap in CAPABILITIES:
            for mode in cap.modes:
                for field in mode.fields + FILE_FIELDS:
                    if not field.key.isidentifier() or len(field.key) > IDENTIFIER:
                        bad.append(f'{cap.platform}/{mode.key}: {field.key!r}')
        assert not bad, f'field keys must be plain identifiers: {bad}'

    def test_a_required_field_can_be_named_in_the_console(self):
        unnamed = [
            f'{cap.platform}/{mode.key}:{field.key}'
            for cap in CAPABILITIES
            for mode in cap.modes
            for field in mode.fields
            if field.required and not field.name_key
        ]
        assert not unnamed, f'required fields the console cannot name: {unnamed}'

    def test_a_number_field_default_is_a_number_the_panel_can_send(self):
        # The browser writes the default into an inline handler as a literal, so
        # anything but a number would be a broken statement, not a value.
        wrong = [
            f'{cap.platform}/{mode.key}:{field.key}={field.default!r}'
            for cap in CAPABILITIES
            for mode in cap.modes
            for field in mode.fields + FILE_FIELDS
            if field.coerce == 'number' and not isinstance(field.default, int)
        ]
        assert not wrong, f'number fields need an integer default: {wrong}'

    def test_every_control_is_one_the_renderer_knows(self):
        unknown = [
            f'{cap.platform}/{mode.key}:{field.key}={field.control}'
            for cap in CAPABILITIES
            for mode in cap.modes
            for field in mode.fields + FILE_FIELDS
            if field.control not in ('text', 'textarea', 'number', 'checkbox', 'select')
        ]
        assert not unknown, f'controls workflow.js cannot render: {unknown}'

    def test_a_select_carries_a_label_for_every_option(self):
        for cap in CAPABILITIES:
            for mode in cap.modes:
                for field in mode.fields + FILE_FIELDS:
                    if field.control == 'select':
                        assert field.options, f'{field.key} offers nothing to pick'
                        for value, label in field.options:
                            # The value is what gets stored in the node and what
                            # the backend reads back, so it cannot be prose.
                            assert value.isidentifier(), f'{field.key} stores an unusable value {value!r}'
                            assert label.startswith('format.') or label.startswith('settings.'), label

    def test_an_action_button_is_a_function_name_the_page_can_call(self):
        noted = [(mode.action_js, mode.action_key) for cap in CAPABILITIES for mode in cap.modes if mode.note_key]
        for action_js, action_key in noted:
            if not action_key:
                continue
            assert action_js.isidentifier(), f'{action_key} names no callable function'

    def test_a_mode_without_a_note_cannot_carry_a_button(self):
        orphan = [
            f'{cap.platform}/{mode.key}'
            for cap in CAPABILITIES
            for mode in cap.modes
            if mode.action_key and not mode.note_key
        ]
        assert not orphan, f'buttons with nowhere to sit: {orphan}'

    def test_the_comment_modes_note_only_the_window_they_actually_open(self):
        """A note that claims a window the executor won't open is the dishonesty #102
        removes. The scrolled/captcha comment platforms keep 「opens a visible
        window」 (commentHint); the fetch platforms (weibo/bilibili/YouTube — measured
        headless) carry a note that says a headless run opens no window (commentFetchHint).
        """
        for platform in ('zhihu', 'xiaohongshu', 'douyin', 'twitter'):
            assert _mode(platform, 'comments').note_key == 'settings.commentHint', platform
        for platform in ('weibo', 'bilibili', 'youtube'):
            assert _mode(platform, 'comments').note_key == 'settings.commentFetchHint', platform


class TestCollectionKind:
    """`collects` is the matrix's answer to 「what does a visible window show」 (#102).

    Not prose from the AGENTS rule but the field the comment executor and the panel
    read, so the values are pinned against measurement:
    ``backend/test_headless_comments.py`` (2026-09-25) proved weibo and bilibili
    comment walks answer a HEADLESS browser with the same rows a window sees, which is
    what makes them ``'fetch'`` and lets them honour 无头.
    """

    def test_every_mode_declares_a_kind_the_code_knows(self):
        bad = [
            f'{cap.platform}/{mode.key}={mode.collects!r}'
            for cap in CAPABILITIES
            for mode in cap.modes
            if mode.collects not in COLLECT_KINDS
        ]
        assert not bad, f'unknown collects values: {bad}'

    def test_the_fetch_modes_are_exactly_the_measured_list(self):
        """Reclassifying one of these must be a deliberate edit backed by a measurement,
        because the comment executor lets a ``'fetch'`` platform run headless on it.
        """
        fetched = {(cap.platform, mode.key) for cap in CAPABILITIES for mode in cap.modes if mode.collects == 'fetch'}
        assert fetched == {
            ('weibo', 'author'),
            ('weibo', 'comments'),
            # Both boards were measured answering with a window that shows nothing:
            # one page load, then the site's own JSON.
            ('weibo', 'hot'),
            ('zhihu', 'hot'),
            ('bilibili', 'hot'),
            ('bilibili', 'comments'),
            ('youtube', 'posts'),
            ('youtube', 'author'),
            ('youtube', 'comments'),
        }, fetched

    def test_only_the_measured_board_answers_an_anonymous_browser(self):
        """`needs_session` is what stops the cookie gate refusing a crawl the site would
        have served. Exactly one mode is measured doing that, so exactly one is exempt —
        a second False would be a claim nobody re-measured."""
        anonymous = {(cap.platform, mode.key) for cap in CAPABILITIES for mode in cap.modes if not mode.needs_session}
        assert anonymous == {('weibo', 'hot')}, anonymous
        assert needs_session('weibo', 'hot') is False
        assert needs_session('weibo', 'posts') is True, 'the same platform, a different answer'
        assert needs_session('zhihu', 'hot') is True, 'the zhihu board is 401 without a session'
        # No answer is not evidence of anonymity: an unknown platform or mode keeps
        # the probe on.
        assert needs_session('kuaishou', 'hot') is True
        assert needs_session('weibo', 'nonsense') is True

    def test_shows_nothing_follows_the_field_not_a_second_list(self):
        assert shows_nothing('weibo', 'comments') is True
        assert shows_nothing('bilibili', 'hot') is True
        assert shows_nothing('zhihu', 'comments') is False
        assert shows_nothing('douyin', 'posts') is False
        # An unknown platform/mode is answered honestly, not with a guess.
        assert shows_nothing('wechat', 'nonsense') is False

    def test_wechat_states_its_limits_and_offers_the_reason(self):
        mode = _mode('wechat', 'posts')
        assert mode.note_key == 'settings.wechatLimitsNote'
        assert mode.action_key == 'settings.wechatLimitsBtn'
        assert mode.action_js == 'explainWechatLimits'


class TestRegions:
    """Which network each platform is reachable from — the fact behind the pre-run
    warning about mixing 国内 and 海外, and behind the ``live_cn`` / ``live_os`` split of
    the real-site tier.

    Measured on this machine: with a VPN up, douyin answers 502 and refuses the crawl;
    without one, x.com never loads. So one canvas holding both halves cannot be run
    from either network, and the classification has to be as deliberate as a mode's
    field list — the default is ``cn``, which means an overseas platform that forgot to
    say so fails as "an empty search", not as a missing declaration.
    """

    def test_every_platform_names_exactly_one_of_the_two(self):
        from crawl_capabilities import REGIONS, region_of

        assert REGIONS == ('cn', 'overseas')
        for cap in CAPABILITIES:
            assert cap.region in REGIONS, f'{cap.platform} names {cap.region!r}'
            assert region_of(cap.platform) == cap.region

    def test_the_overseas_set_is_stated_rather_than_fallen_into(self):
        from crawl_capabilities import platform_ids

        overseas = sorted(cap.platform for cap in CAPABILITIES if cap.region == 'overseas')
        assert overseas == ['twitter', 'youtube'], (
            f'which platforms need a foreign network is a decision, not a default: {overseas}. '
            f'Known platforms: {list(platform_ids())}'
        )

    def test_a_platform_nothing_crawls_has_no_region_rather_than_a_guess(self):
        """Instagram holds a cookie and cannot be crawled, so it is absent from the
        matrix — and a canvas can never contain it, which is why the mixed-run warning
        does not need a word to say."""
        from crawl_capabilities import region_of

        assert region_of('instagram') == ''
        assert region_of('tumblr') == ''

    def test_the_split_keeps_canvas_order_dedupes_and_drops_strangers(self):
        from crawl_capabilities import split_regions

        split = split_regions(['douyin', 'twitter', 'douyin', 'tumblr', 'youtube'])
        assert split == {'cn': ['douyin'], 'overseas': ['twitter', 'youtube']}

    def test_a_single_network_canvas_is_not_mixed(self):
        from crawl_capabilities import split_regions

        domestic = split_regions(['zhihu', 'weibo', 'bilibili', 'wechat', 'xiaohongshu', 'douyin'])
        assert domestic['overseas'] == []
        assert sorted(domestic['cn']) == sorted(['zhihu', 'weibo', 'bilibili', 'wechat', 'xiaohongshu', 'douyin'])
        assert split_regions([]) == {'cn': [], 'overseas': []}
        assert split_regions(None)['cn'] == []


class TestPlatformOrder:
    def test_the_matrix_lists_every_platform_once(self):
        ids = platform_ids()
        assert len(ids) == len(set(ids))
        assert capability('zhihu') is not None

    def test_a_platforms_first_mode_is_what_an_untouched_node_runs(self):
        # The canvas seeds `platform: 'zhihu'` and no mode key, so the first mode
        # of the first platform is the default behaviour of the whole product.
        assert _mode('zhihu', '').key == 'posts'
        assert platform_ids()[0] == 'zhihu'
