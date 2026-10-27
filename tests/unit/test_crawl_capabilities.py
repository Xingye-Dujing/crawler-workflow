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
    fed_keys,
    feed_of,
    fields_for,
    has_platform,
    is_url_cell,
    link_fields,
    mode_for,
    mode_keys_for,
    mode_of_node,
    modes_for,
    names_also_accepted,
    needs_session,
    platform_ids,
    required_missing,
    unoffered_selections,
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

    @pytest.mark.parametrize('off', ['false', 'False', 'FALSE', '  false  ', '0', 'no', 'off', '否'])
    def test_a_switch_written_as_text_is_not_read_as_on(self, off):
        """``bool(raw)`` was the old reading, and ``bool('false')`` is True.

        That is not hypothetical: a checkbox in this app stores the strings
        ``'true'``/``'false'``, so an unticked 正文展开 (one page-wait per row, and the
        click that navigates away from a column card) meant "expand every answer", and
        an unticked 重新采集 released the already-collected ledger — re-crawling, at the
        user's cost, every item the node had already paid for.
        """
        mode = _mode('zhihu', 'posts')
        assert crawl_kwargs(mode, {'keyword': 'ai', 'full_body': off})['full_body'] is False

    @pytest.mark.parametrize('on', ['true', 'True', 'yes', '1', '是'])
    def test_a_switch_written_as_text_is_not_read_as_off(self, on):
        mode = _mode('zhihu', 'posts')
        assert crawl_kwargs(mode, {'keyword': 'ai', 'full_body': on})['full_body'] is True

    def test_a_cleared_switch_is_the_figure_the_panel_showed(self):
        """Blank answers the Field's own default, in both directions: 正文展开 defaults
        to on and 保留分片 to off, so neither box may be flipped by deleting its text.

        A value that is neither grammar — ``[]``, ``{}``, a random word — takes the
        declared default too. It used to be read as "off" by ``bool()``, which turned a
        corrupt field into a silent behaviour change; "states nothing" is the truer
        reading, and the panel's figure is what a person saw when they saved.
        """
        posts = _mode('zhihu', 'posts')
        assert crawl_kwargs(posts, {'keyword': 'ai', 'full_body': ''})['full_body'] is True
        keep = next(f for f in FILE_FIELDS if f.key == 'keep_parts')
        assert keep.default is False
        assert keep.value_from({'keep_parts': '   '}) is False
        assert keep.value_from({'keep_parts': 'true'}) is True
        assert keep.value_from({'keep_parts': []}) is False
        assert crawl_kwargs(posts, {'keyword': 'ai', 'full_body': []})['full_body'] is True

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
        assert 'comment_preview' not in crawl_kwargs(_mode('douyin', 'author'), {'keyword': 'k'})

    def test_the_handler_is_not_an_argument(self):
        # `resume` is written by the executor from the store; a matrix field with
        # that name would let a saved workflow dictate where a crawl restarts.
        for cap in CAPABILITIES:
            for mode in cap.modes:
                keys = {f.key for f in mode.fields}
                assert 'resume' not in keys, f'{cap.platform}/{mode.key} declares a resume field'


class TestSelectsAreHeldToTheirOptions:
    """A ``select`` is a choice from a list the matrix owns, so a value off that list
    is not a variant of an answer — it is no answer, and every reader here treats
    "anything except the one value I special-case" as the default.

    The measurement that makes this real is ``board``: ``crawlers/core/video.py`` asks
    ``== 'ranking'`` and crawls 热门 for everything else, so ``'Popular'`` (a label, not
    a value), ``'rank'``, ``'ranking2'`` or a retired option in an old file all crawled
    the *other* board — with the run recorded as the one the node asked for. ``format``
    behaves the same way in reverse (only ``'json'`` is checked). The refusal belongs to
    validation because the panel cannot produce such a value: it builds its options from
    this very table, so only a hand-written or externally generated workflow gets here.
    """

    def test_the_selects_the_matrix_declares_are_the_ones_it_can_refuse(self):
        declared = {
            (cap.platform, mode.key, f.key)
            for cap in CAPABILITIES
            for mode in cap.modes
            for f in mode.fields
            if f.control == 'select' and f.key != 'account'
        }
        boards = {cell for cell in declared if cell[2] == 'board'}
        assert boards == {('bilibili', 'hot', 'board'), ('hongguo', 'hot', 'board')}, declared
        assert {key for _platform, _mode, key in declared} == {'board', 'backend'}, declared
        # 采集方式 is declared on every form the four shared builders produce, and on nothing else:
        # 红果短剧 (a desktop player) and 微信 (its own list walk) have no CatBus 交集, so a node
        # there declares no choice the executor could refuse. Declared — not declared-per-machine:
        # a declared field is what holds a stored value to its option list, and
        # ``GET /api/capabilities`` takes the field out on a machine that cannot run the backend.
        backends = {cell for cell in declared if cell[2] == 'backend'}
        # 红果's board form is built by the shared builder, so it declares the select like every other
        # board; its comment form builds its own field list (a desktop player asks for no browser
        # session and no external adapter) and declares nothing. Declaring the field even where this
        # machine cannot run it is the point: a declared field is what holds a stored value to its
        # option list, and the panel marks the unreachable choice disabled and named — the same shape
        # the mode select uses for a 红果 board on a Linux server, so a canvas restored from another
        # machine shows what it holds instead of falling back to option #0.
        assert ('hongguo', 'hot', 'backend') in backends
        # The shared file tail is the other one, and it is on every mode.
        assert [f.key for f in FILE_FIELDS if f.control == 'select'] == ['format']

    def test_the_account_selector_is_on_every_session_form_and_nowhere_else(self):
        """账号 is the cross-cutting select, so it is checked as its own population
        rather than folded into the board/sort enumeration: it belongs on exactly the
        modes that open a logged-in browser ON A PLATFORM THAT CAN HOLD A SESSION
        (a choice with no effect is the control the matrix rule forbids). WeChat is
        the edge the two sets share: its body-only crawl needs no cookie row at all
        (AGENTS red line), so it declares no account to pick."""
        from sessions.cookies import CookieManager

        with_account = {
            (cap.platform, mode.key)
            for cap in CAPABILITIES
            for mode in cap.modes
            if any(f.key == 'account' for f in mode.fields)
        }
        session = {
            (cap.platform, mode.key)
            for cap in CAPABILITIES
            for mode in cap.modes
            if mode.needs_session and CookieManager.is_supported(cap.platform)
        }
        assert with_account == session, with_account ^ session

    @pytest.mark.parametrize('value', ['popular', 'ranking'])
    def test_a_declared_option_is_accepted(self, value):
        assert unoffered_selections(_mode('bilibili', 'hot'), {'board': value}) == []

    @pytest.mark.parametrize('blank', [None, '', '   ', '\t'])
    def test_a_box_nobody_chose_is_the_declared_default_not_a_mistake(self, blank):
        """Same rule as an empty mode key: a canvas saved before the field existed must
        keep running, and the default it gets is the one the panel showed.
        """
        params = {'board': blank} if blank is not None else {}
        assert unoffered_selections(_mode('bilibili', 'hot'), params) == []

    @pytest.mark.parametrize(
        'wrong',
        [
            'Popular',  # the label the user sees, not the value stored
            'RANKING',
            'rank',
            'ranking2',
            'hot',  # another platform's word, which means nothing here
            '0',
            'false',
            '无',
            3,
            ['ranking'],
            {'value': 'ranking'},
        ],
    )
    def test_a_value_off_the_list_is_named_with_the_field_that_carries_it(self, wrong):
        found = unoffered_selections(_mode('bilibili', 'hot'), {'board': wrong})
        assert len(found) == 1, (wrong, found)
        field, value = found[0]
        assert field.key == 'board' and field.name_key == 'field.board'
        assert value == str(wrong).strip(), (wrong, value)

    def test_padding_is_not_a_mistake_because_the_crawler_never_sees_it(
        self,
    ):
        """``Field.value_from`` strips, so the executor receives ``'ranking'`` and the
        check has to agree with what actually runs — a name that is checked and a value
        that is used being different strings is the mistake this pair prevents.
        """
        assert unoffered_selections(_mode('bilibili', 'hot'), {'board': '  ranking  '}) == []
        assert crawl_kwargs(_mode('bilibili', 'hot'), {'board': '  ranking  '})['board'] == 'ranking'

    def test_the_case_variant_is_refused_rather_than_folded_into_an_option(self):
        """Folding ``'RANKING'`` to ``'ranking'`` would guess at a choice, and the
        storage value is a key, not a word the user typed."""
        assert unoffered_selections(_mode('bilibili', 'hot'), {'board': 'RANKING'})

    def test_the_file_format_is_checked_too_because_it_decides_what_hits_disk(self):
        mode = _mode('zhihu', 'posts')
        assert unoffered_selections(mode, {'format': 'csv'}) == []
        assert unoffered_selections(mode, {'format': 'json'}) == []
        for wrong in ('JSON', 'Json', 'xlsx', 'tsv', 'jsonl'):
            found = unoffered_selections(mode, {'format': wrong})
            assert [field.key for field, _value in found] == ['format'], wrong

    def test_a_mode_that_declares_no_board_cannot_be_blamed_for_one(self):
        """weibo has exactly one board, so a ``board`` key on its node is a leftover
        from another platform's node — and refusing it would send the user to a field
        the panel never showed them.
        """
        assert unoffered_selections(_mode('weibo', 'hot'), {'board': 'ranking'}) == []
        assert 'board' not in {f.key for f in _mode('weibo', 'hot').fields}

    def test_the_tail_can_be_left_off_for_a_caller_that_ignores_files(self):
        mode = _mode('zhihu', 'posts')
        assert unoffered_selections(mode, {'format': 'xlsx'}, with_files=False) == []

    def test_every_select_the_matrix_declares_names_its_field_in_both_console_languages(self):
        """The refusal prints the field's *word*, so a select without a backend name key
        would print ``{field}`` — or the storage key — at the user. This is the same
        mechanism 关键词 uses for a missing required field, and it is required of every
        select, not just the two that exist today.
        """
        import i18n

        selects = [f for f in FILE_FIELDS if f.control == 'select']
        for cap in CAPABILITIES:
            for mode in cap.modes:
                selects += [f for f in mode.fields if f.control == 'select']
        assert len(selects) >= 2, selects
        for field in selects:
            assert field.name_key, f'{field.key} declares no backend name'
            assert field.name_key in i18n._ZH and field.name_key in i18n._EN, field.name_key


class TestModeResolution:
    def test_each_platform_names_its_modes(self):
        # 热榜 sits between 作者 and 评论 on both platforms that publish one, and its
        # presence is a measurement (docs/crawler_notes.md), not a guess: xiaohongshu
        # has no board surface at all (its /hot redirects to the ordinary feed), so it
        # must NOT appear here. Douyin's board was the one still unsettled when this
        # test was written; it shipped once its own answer was measured end to end.
        assert mode_keys_for('zhihu') == ('posts', 'author', 'hot', 'comments')
        assert mode_keys_for('weibo') == ('posts', 'author', 'hot', 'comments')
        assert mode_keys_for('douyin') == ('author', 'hot', 'comments')
        assert mode_keys_for('hongguo') == ('hot', 'comments'), 'boards, plus the player-backed comment harvest'
        assert mode_keys_for('wechat') == ('posts',), 'WeChat has no comment adapter'
        assert 'hot' not in mode_keys_for('xiaohongshu'), '小红书 has no measurable board'

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
        assert keys[-4:] == ['part_size', 'format', 'keep_parts', 'part_timestamp']

    def test_the_file_block_never_reaches_the_crawler_call(self):
        """Every member of the shared tail decides how rows LEAVE the crawl — a filename,
        a shard size, a format. Handed to ``search()`` as an argument they would be
        swallowed by ``**_kwargs`` at best and shadow a real parameter at worst, so the
        executor reads them straight off the node and the call stays what the signature
        declares."""
        posts = _mode('weibo', 'posts')
        kwargs = crawl_kwargs(posts, {'keyword': 'k', 'part_size': 50, 'format': 'json', 'keep_parts': True})
        assert not {'part_size', 'format', 'keep_parts', 'part_timestamp'} & set(kwargs), sorted(kwargs)
        assert {'keyword', 'start_time', 'end_time'} <= set(kwargs), sorted(kwargs)

    def test_unknown_platform_offers_no_fields(self):
        assert fields_for('nope', 'posts') == ()
        assert declared_defaults('nope') == {}


class TestPayloadShape:
    """The browser builds its form from this dict, so its keys are an API."""

    def test_the_payload_is_json_ready_and_camel_cased(self):
        import json

        payload = json.loads(json.dumps(as_dict(), ensure_ascii=False))
        assert set(payload) == {'platforms', 'fileFields', 'backends'}
        first = payload['platforms'][0]
        # `profileRecommended` / `parallelRecommended` / `serialOnly` travel with the
        # platform, not the mode: running in a throwaway browser is punished per site, and
        # which shape to crawl in is a per-site verdict — the pre-run notice and the
        # advice panel (#181) read these, and the matrix is their only source.
        # `engines` is the platform's engine dimension, and `labelKey` lets a CatBus-only
        # platform name itself from the catalogue instead of the panel building `platform.<id>`.
        assert set(first) == {
            'platform',
            'labelKey',
            'engines',
            'modes',
            'profileRecommended',
            'region',
            'serialOnly',
            'parallelRecommended',
        }
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
            # The machine requirement, by token ('' when any host can run the mode). The verdict for this
            # host rides next to it as the payload's ``machine`` map, so the panel can grey a mode out and
            # the pre-run gate can refuse from one answer rather than two.
            'requires',
            # The engine dimension: which engines offer this function, and each pair's verdict
            # (runnable / reason / columns / identity). The panel filters the function list by the
            # selected engine and greys a pair it cannot run — it never keeps its own list.
            'engines',
            'cells',
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
        # `acceptsNames` rides along because the panel's own link check has to make the
        # same call the executor does: 红果's comment form takes a drama TITLE as input, and
        # a browser that flagged it would refuse a crawl the engine runs fine.
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
            'acceptsNames',
            'placeholder',
            'fedBy',
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
                    if field.control != 'select':
                        continue
                    if field.key == 'account':
                        # Its real options are per-machine (they come from the cookie
                        # files at payload time), so the STATIC matrix carries exactly one
                        # choice: the platform's own login, named ``default`` like any other
                        # account. It is not '' any more — one account with two spellings is
                        # what the uniform naming rule removed — and the label stays a
                        # cookies.* panel word because it names the cookie subsystem.
                        assert field.options == (('default', 'cookies.accountDefault'),)
                        assert field.default == 'default', 'a new node logs in as the platform itself'
                        continue
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

    def test_the_comment_modes_note_describes_what_their_window_would_show(self):
        """A note must not promise a window the executor no longer opens (#148).

        The comment node honours the run's 无头 choice for every platform now, so the two notes
        differ only in what a *windowed* run visibly does: a scrolled panel moves the feed
        (commentHint), a fetch panel reads inside one loaded page (commentFetchHint). Neither says
        a window is forced — that claim was removed with the forcing.
        """
        for platform in ('zhihu', 'xiaohongshu', 'douyin', 'twitter'):
            assert _mode(platform, 'comments').note_key == 'settings.commentHint', platform
        for platform in ('weibo', 'bilibili', 'youtube'):
            assert _mode(platform, 'comments').note_key == 'settings.commentFetchHint', platform


class TestCollectionKind:
    """`collects` is the matrix's answer to 「what does a visible window show」.

    It drives the panel's note wording (and is exported to the browser), so the values stay pinned
    against measurement. It is no longer an execution gate: since #148 a headless Chrome carries a
    desktop fingerprint and the comment node honours 无头 for every platform, so ``'fetch'`` and
    ``'dom_scroll'`` alike run headless when asked — the field only says what you will SEE if you
    did choose a window (a fetch panel sits on the loaded page; a scrolled one moves the feed).
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
        because it changes what the panel promises the user a visible window will show.
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
            # Measured the same way (one page load, then the site's own JSON). douyin's
            # board is ``'fetch'`` like the rest here: a window would just sit on the page
            # while the rows come from inside it, so it runs headless too — since #148 no
            # class carries ``never_headless`` to override that. ``collects`` describes what
            # the mode does on screen, and that is now the whole story.
            ('douyin', 'hot'),
            # 红果's four boards ship the finished list inside the document each page load
            # (``_ROUTER_DATA``), so a window would sit through a page load per board page
            # and show nothing a user could act on.
            ('hongguo', 'hot'),
            ('bilibili', 'comments'),
            ('youtube', 'posts'),
            ('youtube', 'author'),
            ('youtube', 'comments'),
        }, fetched

    def test_only_the_measured_board_answers_an_anonymous_browser(self):
        """`needs_session` is what stops the cookie gate refusing a crawl the site would
        have served. Exactly three modes are exempt, each for a measured reason, and a
        fourth False would be a claim nobody re-measured.

        ``weibo/hot`` is anonymous *while the platform can hold a session* (the board answers
        a visitor). ``wechat/posts`` has no session to have: wechat has never been in
        ``CookieManager.PLATFORMS``, carries no ``login_url``, and its article bodies are
        served to anyone — so demanding a cookie there refuses a crawl that cannot use one.
        ``hongguo/hot`` is the same shape as wechat's: the four boards are served to a
        fresh browser (measured 2026-10), and the platform has no ``login_url`` for a
        cookie to be valid on, so a session question here could only be answered "no".
        ``hongguo/comments`` asks the cookie gate nothing because the session is not
        this tool's to hold: the crawl drives the desktop player, which carries its own
        login (measured 2026-10-19: comment pages arrive with the player logged in and
        the tool never touches a cookie file).
        """
        anonymous = {(cap.platform, mode.key) for cap in CAPABILITIES for mode in cap.modes if not mode.needs_session}
        assert anonymous == {
            ('weibo', 'hot'),
            ('wechat', 'posts'),
            ('hongguo', 'hot'),
            ('hongguo', 'comments'),
        }, anonymous
        assert needs_session('weibo', 'hot') is False
        assert needs_session('weibo', 'posts') is True, 'the same platform, a different answer'
        assert needs_session('wechat', 'posts') is False
        assert needs_session('hongguo', 'hot') is False, 'all four boards answer a fresh browser (measured 2026-10)'
        assert needs_session('hongguo', 'comments') is False, "the session is the player's, not this tool's"
        assert needs_session('zhihu', 'hot') is True, 'the zhihu board is 401 without a session'
        # No answer is not evidence of anonymity: an unknown platform or mode keeps
        # the probe on.
        assert needs_session('kuaishou', 'hot') is True
        assert needs_session('weibo', 'nonsense') is True

    def test_a_mode_declares_what_its_window_would_show_by_its_field(self):
        """``collects`` is the single source of truth for what a window does on screen.

        The comment executor no longer forces a window onto any panel (#148: a headless Chrome
        carries a desktop fingerprint and even a scroll-only panel was measured serving rows
        headless), but the matrix still states what each crawl visibly does — a fetch panel reads
        from inside one loaded page, a scrolled one moves the feed. This pins that the wording is
        read from the field, never from a second list of platforms that would drift.
        """
        assert mode_for('weibo', 'comments').collects == 'fetch'
        assert mode_for('bilibili', 'hot').collects == 'fetch'
        assert mode_for('zhihu', 'comments').collects == 'dom_scroll'
        # douyin's author walk opens an in-page overlay per row, not a new page: it visibly moves,
        # so it is no ``fetch`` mode — but the honest name is ``modal_per_row``, since no page loads
        # per row any more (the per-row ``/video`` navigation was removed).
        assert mode_for('douyin', 'author').collects == 'modal_per_row'
        assert mode_for('douyin', 'author').collects != 'fetch'

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


class TestTheRecrawlSwitchIsOnEveryForm:
    """Every crawl that dedupes rows must offer the way back, on every one of its forms.

    Both streaming executors skip a row the ledger already holds, so a run without the
    checkbox ends in an empty table that reads as "the site has nothing more". The field is
    reached through the shared ``_posts_mode`` / ``_author_mode`` / ``_comment_mode`` helpers,
    which is exactly why a hand-written list of platforms would keep passing while the hole is
    open: 2026-09-26 found it on **all seven** comment forms (user-reported on weibo) and on
    wechat's hand-written posts form — three of the four mode shapes, none of them reachable by
    "check what `_posts_mode` builds". So this walks the matrix, not the helpers.
    """

    def test_every_crawl_mode_declares_the_field(self):
        missing = [
            f'{cap.platform}/{mode.key}'
            for cap in CAPABILITIES
            for mode in cap.modes
            if 'recrawl' not in {field.key for field in mode.fields}
        ]
        assert missing == [], f'these forms dedupe rows with no way to re-collect them: {missing}'

    def test_both_executors_that_stream_rows_actually_read_it(self):
        """A checkbox nothing reads is worse than no checkbox: it promises a repair.

        Checked as source text on purpose — the two executors are separate functions, and a
        future third one streaming rows would have to be added to this list, which is the
        kind of thing a passing test should make loud rather than miss.
        """
        from nodes.executors import comment as comment_exec
        from nodes.executors import source as source_exec

        for module, name in ((source_exec, 'execute_source_node'), (comment_exec, 'execute_comment_node')):
            body = inspect.getsource(getattr(module, name))
            assert "params.get('recrawl')" in body, f'{name} never reads 重新采集'
            assert 'forget_items' in body, f'{name} logs the switch but releases nothing'


class TestTheCommentTimeFilterIsReachable:
    """The backend already drops comments whose 评论时间 falls outside [comment_start,
    comment_end], but a capability with no field is one the user cannot reach: 2026-10 found
    weibo's DATA-SOURCE comment mode had the filter and no input (only the legacy standalone
    comment node hardcoded the two boxes). So every comments form must declare BOTH ends —
    walked off the matrix, not the helper, so a hand-written form cannot silently reopen the
    hole — and the comment executor must actually run the filter it presents."""

    def test_every_comments_mode_offers_both_ends_of_the_time_filter(self):
        missing = [
            f'{cap.platform}/{mode.key}'
            for cap in CAPABILITIES
            for mode in cap.modes
            if mode.handler == 'comments'
            and not {'comment_start', 'comment_end'} <= {field.key for field in mode.fields}
        ]
        assert missing == [], f'comment forms whose time filter has no input: {missing}'

    def test_the_comment_executor_reads_the_filter_it_presents(self):
        from nodes.executors import comment as comment_exec

        body = inspect.getsource(comment_exec.execute_comment_node)
        assert 'filter_comments_by_time' in body, 'the comment node renders a range nothing runs'


class TestFeed:
    """Which forms accept an upstream table column, and what that costs the matrix.

    A fed link list is the whole phase-1 feed: the comment engine and wechat's
    article reader already crawl one link per row, so feeding is only "where do the
    links come from". Keyword/author modes take a single scalar per crawl — feeding
    one would need a second per-row loop engine, and declaring `fed_by` there
    without that machinery would promise a crawl nothing runs. These tests pin the
    feedable set to exactly the link-list fields.
    """

    def test_every_feed_declaration_names_a_sibling_field_on_the_same_mode(self):
        # ``fed_by='input_column'`` points at the column-name box; a mode that declares
        # the pointer without the box would have a panel that cannot be filled and a
        # validation rule that can never be satisfied.
        bad = []
        for cap in CAPABILITIES:
            for mode in cap.modes:
                keys = {field.key for field in mode.fields}
                for field, col in feed_of(mode):
                    if col not in keys:
                        bad.append(f'{cap.platform}/{mode.key}: {field.key} fed_by {col!r} not on the form')
        assert bad == [], bad

    def test_the_feedable_set_is_exactly_the_link_list_modes(self):
        got = {f'{cap.platform}/{mode.key}' for cap in CAPABILITIES for mode in cap.modes if feed_of(mode)}
        want = {f'{cap.platform}/comments' for cap in CAPABILITIES if any(m.key == 'comments' for m in cap.modes)}
        want |= {'wechat/posts'}
        assert got == want, f'link modes without a feed, or scalar modes with one: {got ^ want}'

    def test_only_link_list_fields_may_be_fed(self):
        # Feeding a scalar would silently crawl only the LAST cell: the stored param is
        # one string, so each row's value would overwrite the previous one before the
        # single crawl call — a green run that paid for one link of a hundred.
        bad = [
            f'{cap.platform}/{mode.key}:{field.key}'
            for cap in CAPABILITIES
            for mode in cap.modes
            for field in mode.fields
            if field.fed_by and not field.is_link_list()
        ]
        assert bad == [], bad

    def test_the_column_box_is_on_every_feedable_form_and_nowhere_else(self):
        on = {
            f'{cap.platform}/{mode.key}'
            for cap in CAPABILITIES
            for mode in cap.modes
            if 'input_column' in {f.key for f in mode.fields}
        }
        feedable = {f'{cap.platform}/{mode.key}' for cap in CAPABILITIES for mode in cap.modes if feed_of(mode)}
        assert on == feedable, f'column box and feed declaration disagree: {on ^ feedable}'

    def test_the_column_name_never_reaches_the_crawler_method(self):
        # Wechat's search takes urls; the comment engine reads its own keys. An
        # ``input_column`` in crawl_kwargs would be an unexpected keyword argument —
        # a TypeError at crawl time for a name the crawler was never declared with.
        for cap in CAPABILITIES:
            for mode in cap.modes:
                if feed_of(mode):
                    assert 'input_column' not in crawl_kwargs(mode, {'input_column': '链接'})

    def test_a_fed_field_is_no_longer_required_but_an_unfed_one_still_is(self):
        mode = _mode('zhihu', 'comments')
        assert [f.key for f in required_missing(mode, {'urls': ''})] == ['urls']
        fed = fed_keys(mode, has_data_input=True)
        assert fed == frozenset({'urls'})
        assert required_missing(mode, {'urls': ''}, fed=fed) == []
        # A wired node that never named its column is still feed-EXPECTED (the textarea
        # must not be re-required behind the wire; validation names the blank column
        # itself). Without a data parent nothing is fed and the pasted box rules.
        assert fed_keys(mode, has_data_input=False) == frozenset()

    def test_feeding_does_not_change_what_the_crawler_is_called_with(self):
        # The fed list replaces params['urls'] in the EXECUTOR's copy; the matrix's
        # coercion of a real list must still pass through untouched (one opinion, no
        # re-splitting, no silent reordering between validation and the crawl).
        mode = _mode('zhihu', 'comments')
        args = crawl_kwargs(mode, {'urls': 'https://www.zhihu.com/question/1\nhttps://www.zhihu.com/question/2'})
        assert args['urls'] == [
            'https://www.zhihu.com/question/1',
            'https://www.zhihu.com/question/2',
        ]


class TestWhichLinesAreNames:
    """The one question a name-feeding mode has to answer, spelled exactly once.

    ``static/js/workflow.js`` decides the SAME thing for the panel from the payload's
    ``acceptsNames``. Both sides used a ``\\w``-style word class, and the two languages
    disagree about what that covers — Python's includes Chinese, JavaScript's does not —
    so a title holding a question mark and an equals sign was a LINK to the executor (and
    dropped by count) and a NAME to the panel (and blessed). One spelling per rule, pinned
    here for the server and in ``test_frontend_js`` for the browser.
    """

    @pytest.mark.parametrize(
        'cell',
        [
            'https://hongguoduanju.com/detail?series_id=7696063528179878937',
            '//hongguoduanju.com/detail?series_id=1',
            'hongguoduanju.com/detail?series_id=1',
            'detail?a=1&b=2',
        ],
    )
    def test_a_line_that_carries_a_link_shape_is_a_link(self, cell):
        assert is_url_cell(cell) is True

    @pytest.mark.parametrize(
        'cell',
        [
            '聚宝仙盆之杂灵根才是真BOSS',
            '测试剧',
            '我重扎过去成为太阳',
            # The divergence case: a name the OLD Python pattern read as a query.
            '我在八零年代？第=集',
            '  ',
            '',
            None,
        ],
    )
    def test_a_name_is_a_name_in_both_languages(self, cell):
        assert is_url_cell(cell) is False

    def test_only_the_mode_that_walks_the_client_declares_it_takes_names(self):
        assert names_also_accepted(mode_for('hongguo', 'comments')) is True
        for platform in ('zhihu', 'xiaohongshu', 'douyin', 'weibo', 'bilibili'):
            assert names_also_accepted(mode_for(platform, 'comments')) is False, (
                f'{platform} routes by domain only; a name there is a dropped line'
            )

    def test_a_mode_without_a_link_list_never_claims_to_take_names(self):
        assert names_also_accepted(mode_for('hongguo', 'hot_drama')) is False
        assert names_also_accepted(None) is False
