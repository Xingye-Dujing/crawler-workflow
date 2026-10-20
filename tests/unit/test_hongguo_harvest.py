"""The 红果 comment harness driven against a hand-written capture file.

The harness's two machine-bound seams — ``_ensure_stack`` (mitmdump + player) and
``_title_for`` (the web detail page) — are replaced here, so everything that is
*logic* runs in the fast tier: the JSONL tailer, per-episode walking, floor
numbering across groups, the reply inbox, the danmaku filter, the U1 end license,
the stalled-scroll retry that keeps a 698-comment thread from coming home as 20
rows, and every refusal by its own name. The process half itself is device/live tier.
"""

import json
import os
import time

import pytest

import i18n
from crawlers.base import UNDER_TARGET, CrawlerStopped
from crawlers.comments_base import DEAD, OK
from crawlers.hongguo_harvest import (
    HongguoCommentHarness,
    PlayerUI,
    TreeColdError,
    _norm_title,
    _same_drama,
    is_expand_control,
)

pytestmark = pytest.mark.unit

ARTICLE = 'https://hongguoduanju.com/detail?series_id=7696063528179878937'
NAME_FED = '测试剧'
GROUP = '7696074722013875224'
BOOK = '7696063528179878937'


def _entry(cid, text, ts, *, group=GROUP, digg=0, replies=0, danmaku=False):
    common = {
        'comment_type': 0,
        'content': {'text': text},
        'create_timestamp': ts,
        'group_id': group,
        'service_id': 0 if danmaku else 20,
        'status': 0 if danmaku else 1,
        'user_info': {},
    }
    expand = {'book_id': BOOK}
    if danmaku:
        expand['danmaku_activity_info'] = {'activity_id': '1', 'activity_name': '弹幕活动'}
    comment = {
        'comment_id': cid,
        'common': common,
        'expand': expand,
        'stat': {'digg_count': digg, 'reply_count': replies},
    }
    return {'comment': comment, 'data_type': 4}


def _envelope(entries, total=1, has_more=False):
    return {
        'code': 0,
        'data': {
            'common_list_info': {'cursor': '', 'has_more': has_more, 'total': total},
            'data_list': entries,
        },
    }


def _record(entries=None, *, kind='comment', group=GROUP, total=1, has_more=False, req='', book=BOOK, as_dict=False):
    entries = entries if entries is not None else [_entry('7001', '第一', 1792313924)]
    payload = _envelope(entries, total=total, has_more=has_more)
    for item in entries:
        if isinstance(item, dict) and isinstance(item.get('comment'), dict):
            item['comment'].setdefault('expand', {})['book_id'] = book
    record = {'ts': 0.0, 'kind': kind, 'group_id': group, 'url': 'https://x.test/', 'req_body': req, 'payload': payload}
    return record if as_dict else json.dumps(record)


class _FakeUI:
    """The player, as far as the harness cares: opens, switches, and lands pages.

    ``cold_times`` raises :class:`TreeColdError` that many times before answering, and
    ``wakes`` says whether the re-ask that follows finds a walkable page — the two
    halves of the measured difference between "this drama is not in the client" and
    "the client would not wake at all".
    """

    def __init__(
        self,
        opened=True,
        second_page_lines=(),
        cold_times=0,
        wakes=True,
        scroll_ok=True,
        screen_title='',
    ):
        self.opened = opened
        self.switches = 0
        self.closes = 0
        self.second_page_lines = list(second_page_lines)
        self.cold_times = cold_times
        self.wakes = wakes
        self.scroll_ok = scroll_ok
        self.scroll_attempts = []
        self.expands = 0
        # What the player prints as the drama on stage. Blank by default: a cold tree says
        # NOTHING (measured: 0 controls), and the walk must then lean on the traffic gate
        # rather than invent a refusal out of silence.
        self.screen_title = screen_title
        self.target = None  # the capture file, set by _harness()

    def screen_drama_title(self):
        return self.screen_title

    def open_drama(self, _title):
        if self.cold_times:
            self.cold_times -= 1
            raise TreeColdError('tree cold')
        return self.opened

    def wait_content(self, seconds=60.0):
        return object() if self.wakes else None

    def next_episode(self):
        self.switches += 1
        if self.second_page_lines:
            with open(self.target, 'a', encoding='utf-8') as handle:
                for line in self.second_page_lines:
                    handle.write(line + '\n')
        return True

    def close_comments(self):
        self.closes += 1
        return True

    def open_comments(self):
        return True

    def scroll_drawer(self, attempt=0):
        self.scroll_attempts.append(attempt)
        return self.scroll_ok

    def expand_replies(self, max_clicks=40):
        self.expands += 1
        return 0


def _harness(tmp_path, ui=None, capture_lines=(), params=None):
    capture = tmp_path / 'capture.jsonl'
    with open(capture, 'w', encoding='utf-8') as handle:
        for line in capture_lines:
            handle.write(line + '\n')
    said = []
    ui = ui or _FakeUI()
    ui.target = str(capture)
    harness = HongguoCommentHarness(
        params={'episode_count': 1, 'harvest_timeout': 10, 'include_replies': True, **(params or {})},
        log=said.append,
        abort=lambda: False,
        ui=ui,
        capture_path=str(capture),
    )
    harness._ensure_stack = lambda: None  # the process seam: no mitmdump, no player
    harness._titles[ARTICLE] = '测试剧'  # the title seam: no web fetch in the fast tier
    return harness, said


class TestWalk:
    def test_one_page_one_episode_is_the_site_attested_end(self, tmp_path):
        lines = [_record(entries=[_entry('7001', '第一', 1792313924), _entry('7002', '第二', 1792313925)], total=2)]
        harness, _said = _harness(tmp_path, capture_lines=lines)
        rows, status = harness.crawl_hongguo(ARTICLE, 0)
        assert status == OK
        assert [r['评论ID'] for r in rows] == ['7001', '7002']
        assert harness.end_reason == 'site_end'
        assert harness.target_total == 2

    def test_the_danmaku_page_still_ends_clean_when_every_real_row_is_kept(self, tmp_path):
        lines = [
            _record(
                entries=[_entry('11114', '发个弹幕', 0, danmaku=True), _entry('7003', '真评', 1792313924)],
                total=1,
            )
        ]
        harness, said = _harness(tmp_path, capture_lines=lines)
        rows, status = harness.crawl_hongguo(ARTICLE, 0)
        assert status == OK and [r['评论ID'] for r in rows] == ['7003']
        assert any(i18n.t('crawl.hg.cmt.danmakuSkipped', n=1) in line for line in said)
        assert harness.end_reason == 'site_end'

    def test_two_episodes_walk_and_floors_never_repeat(self, tmp_path):
        page2 = [_record(group='9999', entries=[_entry('8001', '第二集', 1792313924)])]
        ui = _FakeUI(second_page_lines=page2)
        lines = [_record(entries=[_entry('7001', '第一集', 1792313924)])]
        harness, _said = _harness(tmp_path, ui=ui, capture_lines=lines, params={'episode_count': 2})
        rows, status = harness.crawl_hongguo(ARTICLE, 0)
        assert status == OK
        assert [r['评论ID'] for r in rows] == ['7001', '8001']
        assert [r['楼层'] for r in rows] == [1, 2], 'the second episode continues the numbering'
        assert ui.switches == 1
        assert harness.end_reason == 'site_end'

    def test_a_second_page_that_names_another_drama_is_refused_by_name_not_kept(self, tmp_path):
        # Corrected 2026-10-20 from a kept capture. This case used to refuse the FIRST page by
        # comparing its book against the LINK's series_id — and those are different id spaces
        # for one and the same drama (web 7696437705822981182, client 7697823071830297624), so
        # that rule would have refused every page a link-fed walk asked for correctly. The
        # reference is now the first page's own book, and what gets refused is a LATER page
        # naming a different one — the measured drift.
        first = _record(entries=[_entry('7001', '第一', 1792313924)], book=BOOK)
        stranger = _record(
            entries=[_entry('7002', '错剧', 1792313925)], group='8888888888888888888', book='9999999999999999999'
        )
        harness, said = _harness(
            tmp_path,
            capture_lines=[first, stranger],
            params={'harvest_timeout': 5, 'episode_count': 2, 'include_replies': False},
        )
        rows, status = harness.crawl_hongguo(ARTICLE, 0)
        assert status == OK, 'the rows that do answer to the drama are still handed over'
        assert [r['评论ID'] for r in rows] == ['7001'], 'a stranger drama’s page is not this table'
        named = i18n.t('crawl.hg.cmt.groupMismatch', got='9999999999999999999', want=BOOK)
        assert any(named in line for line in said), said
        assert harness.skipped_targets == ['测试剧'], 'a drama that drifted away mid-walk is not finished'
        assert harness.end_reason == UNDER_TARGET

    def test_the_node_limit_caps_the_walk_and_licenses_the_end(self, tmp_path):
        lines = [_record(entries=[_entry('7001', '甲', 1792313924), _entry('7002', '乙', 1792313925)], total=2)]
        harness, _said = _harness(tmp_path, capture_lines=lines)
        rows, status = harness.crawl_hongguo(ARTICLE, 1)
        assert status == OK and len(rows) == 1
        # The user stopped it, the site did not run out — and that is 'capped', a
        # licensed end, NOT the convicted short: 采满所求 is a finished node.
        assert harness.end_reason == 'capped'

    def test_reply_pages_link_to_the_parent_floor(self, tmp_path):
        lines = [
            _record(entries=[_entry('7001', '主评论', 1792313924, replies=1)]),
            _record(
                kind='reply',
                group='ignored',
                req=json.dumps({'comment_id': '7001'}),
                entries=[_entry('9001', '子回复', 1792313930)],
            ),
        ]
        harness, _said = _harness(tmp_path, capture_lines=lines)
        rows, status = harness.crawl_hongguo(ARTICLE, 0)
        assert status == OK
        kid = next(r for r in rows if r['评论ID'] == '9001')
        assert kid['父楼层'] == 1, 'the reply hangs under the floor its parent was given'

    def test_has_more_false_with_a_larger_total_is_not_site_end(self, tmp_path):
        # The measured 2026-10-19 lie: page 1 of an 800-comment thread answers
        # has_more=false (the cursor window is done, the thread is not). The
        # license must read the arithmetic — kept vs the site's own total.
        lines = [
            _record(
                entries=[_entry(f'7{i:03d}', f'评{i}', 1792313924) for i in range(20)],
                total=800,
                has_more=False,
            )
        ]
        harness, _said = _harness(tmp_path, capture_lines=lines)
        rows, status = harness.crawl_hongguo(ARTICLE, 0)
        assert status == OK and len(rows) == 20
        assert harness.end_reason == UNDER_TARGET
        assert harness.target_total == 800

    def test_two_pages_of_one_group_merge_without_double_counting(self, tmp_path):
        shared = _entry('7001', '重复', 1792313924)
        lines = [
            _record(entries=[shared, _entry('7002', '甲', 1792313925)], total=3),
            _record(entries=[_entry('7001', '重复', 1792313924), _entry('7003', '乙', 1792313926)], total=3),
        ]
        ui = _FakeUI(second_page_lines=[])
        harness, _said = _harness(tmp_path, ui=ui, capture_lines=lines)
        # scroll answers True so the kept<total loop runs against the second page
        ui.scroll_drawer = lambda attempt=0: True
        rows, status = harness.crawl_hongguo(ARTICLE, 0)
        assert status == OK
        ids = [r['评论ID'] for r in rows]
        assert ids.count('7001') == 1, 'the same comment from two pages merges to one row'
        assert set(ids) == {'7001', '7002', '7003'}
        assert harness.end_reason == 'site_end', 'kept 3 of total 3 — now the arithmetic licenses it'

    def test_a_silent_scroll_is_asked_again_before_the_thread_is_given_up(self, tmp_path):
        # The measured loss this retry exists for: a page that did not answer the first
        # wheel was read as the end of a 698-comment thread, and the run shipped 20 rows.
        # Two silences are now answered louder, and a thread that fills afterwards is
        # licensed as whole.
        page1 = _record(entries=[_entry(f'7{i:03d}', f'评{i}', 1792313924) for i in range(20)], total=22, as_dict=True)
        page2 = _record(
            entries=[_entry('7100', '补甲', 1792314024), _entry('7101', '补乙', 1792314025)], total=22, as_dict=True
        )
        harness, _said = _harness(tmp_path, capture_lines=[])
        ui = harness.ui
        answers = iter([page1, None, None, page2])
        harness._await_page = lambda *args, **kwargs: next(answers)
        rows, status = harness.crawl_hongguo(ARTICLE, 0)
        assert status == OK and len(rows) == 22
        assert harness.end_reason == 'site_end', 'kept reached what the site counted'
        assert ui.scroll_attempts == [0, 1, 2], 'each silence is answered with a louder attempt'

    def test_a_thread_that_stays_silent_is_named_as_incomplete(self, tmp_path):
        page1 = _record(entries=[_entry(f'7{i:03d}', f'评{i}', 1792313924) for i in range(20)], total=698, as_dict=True)
        harness, said = _harness(tmp_path, capture_lines=[])
        answers = iter([page1, None, None, None])
        harness._await_page = lambda *args, **kwargs: next(answers)
        rows, status = harness.crawl_hongguo(ARTICLE, 0)
        assert status == OK and len(rows) == 20, 'the partial data is kept, never thrown away'
        assert harness.end_reason == UNDER_TARGET and harness.target_total == 698
        # The missing count is its own number because the ROW total is not a fair
        # denominator: reply rows ride in the table over no episode's printed total.
        assert harness.shortfall == 678, harness.shortfall
        named = i18n.t('crawl.hg.cmt.episodeShort', title='测试剧', ep=1, have=20, site_total=698)
        assert any(named in line for line in said), 'the shortfall names its episode'

    def test_stop_is_honoured_between_episodes(self, tmp_path):
        page2 = [_record(group='9999', entries=[_entry('8001', '第二集', 1792313924)])]
        ui = _FakeUI(second_page_lines=page2)
        lines = [_record(entries=[_entry('7001', '第一集', 1792313924)])]
        harness, _said = _harness(tmp_path, ui=ui, capture_lines=lines, params={'episode_count': 3})
        original = harness._await_page

        def aborting_after_one(*args, **kwargs):
            harness._abort = lambda: True
            return original(*args, **kwargs)

        harness._await_page = aborting_after_one
        with pytest.raises(CrawlerStopped):
            harness.crawl_hongguo(ARTICLE, 0)


class TestRefusals:
    def test_silence_within_the_budget_is_dead_and_named(self, tmp_path):
        harness, said = _harness(tmp_path, capture_lines=[], params={'harvest_timeout': 5})
        rows, status = harness.crawl_hongguo(ARTICLE, 0)
        assert (rows, status) == ([], DEAD)
        assert any(i18n.t('crawl.hg.cmt.noTraffic', seconds=5, title='测试剧') in line for line in said)

    def test_a_drama_the_player_cannot_open_is_dead_not_empty(self, tmp_path):
        harness, said = _harness(tmp_path, ui=_FakeUI(opened=False), capture_lines=[_record()])
        rows, status = harness.crawl_hongguo(ARTICLE, 0)
        assert (rows, status) == ([], DEAD)
        assert any(i18n.t('crawl.hg.cmt.dramaNotFound', title='测试剧') in line for line in said)
        # Counted, not just logged: a feed of ten dramas that opened nine is a partial
        # table, and the engine's own gate reads this list to refuse the node by name.
        assert harness.skipped_targets == ['测试剧']
        assert harness.end_reason == UNDER_TARGET

    def test_a_link_without_a_series_id_dies_before_any_process(self, tmp_path):
        harness, said = _harness(tmp_path, capture_lines=[])
        rows, status = harness.crawl_hongguo('https://example.com/nothing', 0)
        assert (rows, status) == ([], DEAD)
        assert any(i18n.t('crawl.hg.cmt.titleMissing', url='https://example.com/nothing') in line for line in said)

    def test_a_missing_player_is_refused_by_name(self, tmp_path, monkeypatch):
        import crawlers.hongguo_harvest as harvest_module

        monkeypatch.setattr(harvest_module, 'find_player', lambda: '')
        monkeypatch.setattr(harvest_module, 'find_mitmdump', lambda: 'C:/fake/mitmdump.exe')
        harness, _said = _harness(tmp_path, capture_lines=[])
        del harness._ensure_stack  # drop the seam: run the real stack gate
        with pytest.raises(ValueError) as caught:
            harness.crawl_hongguo(ARTICLE, 0)
        assert i18n.t('crawl.hg.cmt.noPlayer', path='') in str(caught.value)


class TestClose:
    def test_close_without_processes_is_safe_and_sweeps_the_capture(self, tmp_path):
        harness, _said = _harness(tmp_path, capture_lines=[])
        capture = harness._capture
        harness.close()
        assert not os.path.exists(capture)

    def test_the_harness_poses_as_a_crawler_for_the_reaper(self):
        # _close_login_browser reads .driver first: None must be a plain attribute,
        # not a lazily-raising property, and the wall flags must exist to be False.
        harness = HongguoCommentHarness()
        assert harness.driver is None
        assert harness.risk_blocked is False
        assert harness.login_wall is False


class TestFeedingByName:
    """A 剧名 fed from an upstream column walks the CLIENT — the two rankings answer to
    different authorities, and matching a web row to a client card by hand is what used to
    lose dramas the player had on screen the whole time."""

    def test_a_fed_name_harvests_without_any_web_page(self, tmp_path):
        lines = [_record(entries=[_entry('7001', '第一', 1792313924)])]
        harness, _said = _harness(tmp_path, capture_lines=lines)
        rows, status = harness.crawl_hongguo(NAME_FED, 0)
        assert status == OK
        assert rows[0]['剧名'] == NAME_FED
        assert rows[0]['文章URL'] == '', 'no web page was opened, so no link is invented'
        assert rows[0]['集序号'] == 1 and rows[0]['分集ID'] == GROUP

    def test_the_first_page_of_a_name_fed_walk_becomes_its_reference(self, tmp_path):
        # A fed 剧名 names no series_id, so the walk has nothing to check pages against —
        # until the first page's own book is remembered. Without that, a name-fed drama
        # could quietly absorb another drama's comments.
        harness, said = _harness(tmp_path, capture_lines=[_record(book='9999999999999999999')])
        hit = harness._await_page('', 5)
        assert hit is not None
        assert harness._current_book == '9999999999999999999'
        # Asserted on the ID, not on a key: the 错剧 guard is the ONLY line in this walk that
        # prints a book id, so 「no line names this book」 is the same claim as 「the guard did
        # not fire」. Matching the literal key inside LOCALIZED text could never fail — the
        # rendered sentence is 「收到的评论页属于 … 」 and contains no such word, so the old
        # assertion passed with the guard deleted.
        assert not any('9999999999999999999' in line for line in said), said

    def test_a_second_page_from_another_drama_is_refused_by_name(self, tmp_path):
        harness, said = _harness(tmp_path, capture_lines=[], params={'harvest_timeout': 5})
        harness._current_book = '9999999999999999999'
        stranger = _record(entries=[_entry('7002', '乙', 1792313925)], group='8888', book='8888888888888888888')
        with open(harness._capture, 'a', encoding='utf-8') as handle:
            handle.write(stranger + '\n')
        assert harness._await_page('', 5, allow_repeat=True) is None
        named = i18n.t('crawl.hg.cmt.groupMismatch', got='8888888888888888888', want='9999999999999999999')
        assert any(named in line for line in said)


class TestTreeColdError:
    """A tree that will not wake is an environment fact, not a missing drama — and it must
    never fail a node that has nine more dramas to try (measured: it did exactly that)."""

    def test_a_tree_that_stays_cold_steps_aside_by_name(self, tmp_path):
        ui = _FakeUI(cold_times=5, wakes=False)
        harness, said = _harness(tmp_path, ui=ui, capture_lines=[_record()])
        rows, status = harness.crawl_hongguo(ARTICLE, 0)
        assert (rows, status) == ([], DEAD)
        assert harness.skipped_targets == ['测试剧']
        assert harness.end_reason == UNDER_TARGET
        assert any(i18n.t('crawl.hg.cmt.dramaSkipped', title='测试剧') in line for line in said)

    def test_a_tree_that_wakes_on_the_second_ask_harvests(self, tmp_path):
        ui = _FakeUI(cold_times=1)
        lines = [_record(entries=[_entry('7001', '第一', 1792313924)])]
        harness, _said = _harness(tmp_path, ui=ui, capture_lines=lines)
        rows, status = harness.crawl_hongguo(ARTICLE, 0)
        assert status == OK and len(rows) == 1
        assert harness.skipped_targets == [] and harness.end_reason == 'site_end'

    def test_a_tree_cold_through_every_attempt_is_never_called_a_missing_drama(self, tmp_path):
        """A probe that momentarily finds 推荐 is not the tree answering the search.

        Both attempts raised :class:`TreeColdError`, and the old code fell out of the loop
        as ``'notfound'`` — printing 「搜不到这部剧」 and sending the user to look for a drama
        that was never the problem. The rule: a tree that never wakes is its OWN refusal.
        """
        ui = _FakeUI(cold_times=5, wakes=True)
        harness, said = _harness(tmp_path, ui=ui, capture_lines=[_record()])
        rows, status = harness.crawl_hongguo(ARTICLE, 0)
        assert (rows, status) == ([], DEAD)
        assert any(i18n.t('crawl.hg.cmt.dramaSkipped', title='测试剧') in line for line in said), said
        assert not any(i18n.t('crawl.hg.cmt.dramaNotFound', title='测试剧') in line for line in said), said


class TestReplyDedupe:
    def test_the_same_child_list_expanded_twice_stays_one_row(self, tmp_path):
        # Expanding every thread on every episode pass means the player refires the same
        # reply/list; a child counted twice inflates 楼层 and the table's own size.
        child = _record(
            kind='reply',
            group=GROUP,
            req=json.dumps({'comment_id': '7001'}),
            entries=[_entry('9001', '子', 1792313930)],
        )
        lines = [_record(entries=[_entry('7001', '主评论', 1792313924, replies=1)]), child, child, child]
        harness, _said = _harness(tmp_path, capture_lines=lines)
        rows, status = harness.crawl_hongguo(ARTICLE, 0)
        assert status == OK
        kids = [r for r in rows if r['评论ID'] == '9001']
        assert len(kids) == 1, 'a repeated reply page merges to one row'
        assert kids[0]['集序号'] == 1, 'a child inherits its thread episode'
        assert kids[0]['父楼层'] == 1


class TestMatchRules:
    """The two pure rules that each cost data once, pinned without a desktop."""

    @pytest.mark.parametrize(
        'name, expands',
        [
            ('展开2条回复', True),
            ('展开 12 条回复', True),
            ('查看更多回复', True),
            ('回复', False),
            ('回复 3', False),
            ('热门回复', False),
            ('💬 反馈', False),
            ('', False),
        ],
    )
    def test_only_an_expand_link_is_clicked(self, name, expands):
        assert is_expand_control(name) is expands, 'a bare 回复 opens the composer and stalls the drawer'

    @pytest.mark.parametrize(
        'want, card, same',
        [
            ('聚宝仙盆之杂灵根才是真BOSS', '《聚宝仙盆之杂灵根才是真BOSS 第十四季》', True),
            ('聚宝仙盆之杂灵根才是真BOSS', '聚宝仙盆之杂灵根才是真BOSS', True),
            ('赘婿归来', '赘婿', False),
            ('花', '聚宝仙盆', False),
            ('繁花', '繁花', True),
            ('测试剧', '', False),
        ],
    )
    def test_a_card_names_the_drama_only_when_it_really_is_it(self, want, card, same):
        assert _same_drama(_norm_title(want), card) is same, 'containment put another drama in this table'


class _AnyRect:
    """A control that is somewhere: the tree matchers only ask whether it has a width."""

    def width(self):
        return 100


class TestReplyDenominator:
    """An expanded child thread prints its OWN total, and that number is a debt.

    The walk clicks 展开 once per thread and never pages a child list, so a thread the site
    counts at 200 children can come home with 20 while every COMMENT group is exactly full —
    which is precisely the license 「site_end」 must not be given.
    """

    def _child(self, *, total, cids):
        return _record(
            kind='reply',
            req=json.dumps({'comment_id': '7001'}),
            entries=[_entry(cid, f'子{cid}', 1792313930 + i) for i, cid in enumerate(cids)],
            total=total,
        )

    def test_a_short_child_thread_is_named_and_loses_the_license(self, tmp_path):
        lines = [
            _record(entries=[_entry('7001', '主评论', 1792313924, replies=5)], total=1),
            self._child(total=5, cids=('9001', '9002')),
        ]
        harness, said = _harness(tmp_path, capture_lines=lines)
        rows, status = harness.crawl_hongguo(ARTICLE, 0)
        assert status == OK and len(rows) == 3, 'the rows that DID arrive stay in the table'
        assert harness.shortfall == 3, f'the owed children are counted as a gap: {harness.shortfall}'
        assert harness.end_reason == UNDER_TARGET, 'a thread short of its own total is not the site end'
        named = i18n.t('crawl.hg.cmt.replyShort', floor=1, have=2, site_total=5)
        assert any(named in line for line in said), said

    def test_a_child_thread_delivered_in_full_keeps_the_license(self, tmp_path):
        lines = [
            _record(entries=[_entry('7001', '主评论', 1792313924, replies=2)], total=1),
            self._child(total=2, cids=('9001', '9002')),
        ]
        harness, _said = _harness(tmp_path, capture_lines=lines)
        rows, status = harness.crawl_hongguo(ARTICLE, 0)
        assert status == OK and len(rows) == 3
        assert harness.shortfall == 0 and harness.end_reason == 'site_end'


class TestCountedEndings:
    """Every way a walk can end with nothing must feed the two tail gates.

    Each of these used to answer ``([], DEAD)`` and nothing more: no ``_mark_short``, no
    ``skipped_targets`` — so a five-drama feed whose third drama a player popup blocked
    settled 「正常」 over four, and one drama fed with no traffic at all settled DONE on an
    EMPTY table. The doctrine the skip path adopted says a hole is named, and these were
    siblings of it left uncounted.
    """

    def test_a_target_that_prints_no_title_is_counted(self, tmp_path):
        harness, _said = _harness(tmp_path, capture_lines=[_record()])
        harness._title_for = lambda _url: ''
        rows, status = harness.crawl_hongguo('https://hongguoduanju.com/detail?series_id=123', 0)
        assert (rows, status) == ([], DEAD)
        assert harness.skipped_targets == ['https://hongguoduanju.com/detail?series_id=123']
        assert harness.end_reason == UNDER_TARGET

    def test_a_bare_series_id_is_promoted_to_the_page_that_names_it(self, tmp_path):
        # The advertised 「a bare series_id」 input used to be handed to the web reader as a
        # URL, which answers with no title — so the supported shape was unreachable by
        # construction and refused every time.
        asked = []
        harness, _said = _harness(tmp_path, capture_lines=[_record()])

        def fake_title(url):
            asked.append(url)
            return '测试剧'

        harness._title_for = fake_title
        rows, status = harness.crawl_hongguo(BOOK, 0)
        assert asked == [f'https://hongguoduanju.com/detail?series_id={BOOK}']
        assert status == OK and len(rows) == 1
        assert rows[0]['文章URL'] == f'https://hongguoduanju.com/detail?series_id={BOOK}'

    def test_a_drama_that_answers_no_traffic_at_all_is_counted(self, tmp_path):
        harness, _said = _harness(tmp_path, capture_lines=[], params={'harvest_timeout': 5})
        rows, status = harness.crawl_hongguo(ARTICLE, 0)
        assert (rows, status) == ([], DEAD)
        assert harness.skipped_targets == ['测试剧'], 'a popup-blocked drama is a named hole, not silence'
        assert harness.end_reason == UNDER_TARGET


class TestOneLinePerGap:
    def test_a_stalled_episode_is_named_once(self, tmp_path):
        """The stall that ended the thread and the end-of-drama check describe ONE gap.

        Both fire on the same group with the same numbers, and 「一条故障一行」 is the rule:
        the second line reads as a second problem the user then goes looking for.
        """
        page1 = _record(entries=[_entry('7001', '主评论', 1792313924)], total=5, has_more=True, as_dict=True)
        harness, said = _harness(tmp_path, capture_lines=[], params={'include_replies': False})
        answers = iter([page1, None, None, None])
        harness._await_page = lambda *args, **kwargs: next(answers)
        rows, status = harness.crawl_hongguo(ARTICLE, 0)
        assert status == OK and len(rows) == 1
        short_lines = [line for line in said if '不完整' in line]
        assert len(short_lines) == 1, f'one gap printed {len(short_lines)} lines: {short_lines}'
        assert harness.end_reason == UNDER_TARGET and harness.shortfall == 4


class TestChildPagesCarryTheirOwnDrama:
    def test_a_late_child_page_is_stamped_with_the_drama_that_asked_for_it(self, tmp_path):
        """Attribution travels with the PAGE, not with whatever the walk is standing on next.

        Expanding fires up to forty requests and the per-episode grace is short, so a child
        page can land after its own drama's last drain. Read then, it is stamped with the
        NEXT drama's 剧名 and 文章URL — a corrupted table, which this repo counts as worse
        than a missing row.
        """
        harness, _said = _harness(tmp_path)
        record = json.loads(
            _record(
                kind='reply',
                req=json.dumps({'comment_id': '7001'}),
                entries=[_entry('9001', '子', 1792313930)],
            )
        )
        record['_stamp'] = ('https://hongguoduanju.com/detail?series_id=111', '旧剧', 2)
        harness._floors_by_cid['7001'] = 7
        harness._reply_inbox.append(record)
        rows, _refused = harness._harvest_replies('', '新剧', 5)
        assert rows[0]['剧名'] == '旧剧', 'the next walk does not get to rename another drama rows'
        assert rows[0]['文章URL'] == 'https://hongguoduanju.com/detail?series_id=111'
        assert rows[0]['集序号'] == 2, 'the episode its own drawer was open on, not the one now playing'
        assert rows[0]['父楼层'] == 7

    def test_an_unstamped_page_still_falls_back_to_the_walk(self, tmp_path):
        harness, _said = _harness(tmp_path)
        record = json.loads(
            _record(
                kind='reply',
                req=json.dumps({'comment_id': '7001'}),
                entries=[_entry('9002', '子', 1792313931)],
            )
        )
        harness._reply_inbox.append(record)
        rows, _refused = harness._harvest_replies('', '新剧', 4)
        assert rows[0]['剧名'] == '新剧' and rows[0]['集序号'] == 4


class TestSwitchesAreRead:
    def test_a_text_false_for_include_replies_never_clicks_expand(self, tmp_path):
        ui = _FakeUI()
        lines = [_record(entries=[_entry('7001', '主评论', 1792313924, replies=3)])]
        harness, _said = _harness(tmp_path, ui=ui, capture_lines=lines, params={'include_replies': 'false'})
        rows, status = harness.crawl_hongguo(ARTICLE, 0)
        assert status == OK and len(rows) == 1
        assert ui.expands == 0, "「包含子回复」 says off; bool('false') is True and clicked every thread open"

    def test_a_drama_cut_by_the_limit_does_not_convict_the_rest(self, tmp_path):
        """评论上限 is a request, not a failure — and it is not a shortfall either."""
        lines = [_record(entries=[_entry('7001', '第一', 1792313924), _entry('7002', '第二', 1792313925)], total=2)]
        harness, _said = _harness(tmp_path, capture_lines=lines, params={'include_replies': False})
        rows, status = harness.crawl_hongguo(ARTICLE, 1)
        assert status == OK and len(rows) == 1, 'the limit truncates the table, it does not fail it'
        assert harness.end_reason == 'capped', harness.end_reason
        assert harness.shortfall == 0, 'the gap the user asked for is not a hole in the table'


class TestStopInterruptsTheWaiting:
    """A cold tree costs minutes per drama, and 停止 has to answer inside that."""

    def test_a_content_wait_answers_stop_without_reading_the_tree(self):
        ui = PlayerUI(log=lambda _m: None, abort=lambda: True)
        ui.window = lambda: None
        with pytest.raises(CrawlerStopped):
            ui.wait_content(seconds=30)

    def test_a_find_until_answers_stop_instead_of_burning_its_budget(self):
        ui = PlayerUI(log=lambda _m: None, abort=lambda: True)
        ui.window = lambda: None
        with pytest.raises(CrawlerStopped):
            ui._find_until('排行榜', 'ButtonControl', seconds=30)

    def test_an_open_drama_does_not_swallow_stop_as_a_miss(self):
        # ``open_drama`` ends in a bare ``except Exception: return False``, which is exactly
        # how a Stop became 「搜不到这部剧」 and then a named skipped drama in the tail refusal.
        ui = PlayerUI(log=lambda _m: None, abort=lambda: True)
        ui.window = lambda: None
        with pytest.raises(CrawlerStopped):
            ui.open_drama('测试剧')

    def test_a_stop_on_the_open_is_not_filed_as_a_missing_drama(self, tmp_path):
        harness, _said = _harness(tmp_path, capture_lines=[_record()])
        harness._abort = lambda: True
        with pytest.raises(CrawlerStopped):
            harness.crawl_hongguo(ARTICLE, 0)
        assert harness.skipped_targets == [], 'the user stopped; nobody searched for a drama and failed'


class TestBoardSwitcherIsOpenedFirst:
    """The list of boards is the client's answer, read from the opened switcher."""

    def test_the_switcher_is_opened_before_the_page_is_read(self):
        events = []
        ui = PlayerUI(log=lambda _m: None)
        ui._board_toggle = lambda: (events.append('toggle'), object())[1]
        ui._click = lambda _ctrl: (events.append('click'), True)[1]
        ui._visible_boards = lambda: (events.append('read'), ['热播榜', '必看榜', '新剧榜'])[1]
        assert ui._board_labels() == ['热播榜', '必看榜', '新剧榜']
        assert events == ['toggle', 'click', 'read'], events

    def test_a_closed_page_that_shares_one_name_with_a_board_is_not_the_library(self):
        """One tab named like a board satisfies the same pattern as the whole list.

        Trusting that read first returned a one-name list, the switcher never opened, and
        every drama on another board was refused as 「搜不到这部剧」 — the miss this walk
        exists to fix, reimposed by its own shortcut.
        """
        state = {'switcher_open': False}
        ui = PlayerUI(log=lambda _m: None)
        ui._board_toggle = lambda: object()

        def _click(_ctrl):
            state['switcher_open'] = True
            return True

        def _read():
            return ['热播榜', '必看榜', '新剧榜'] if state['switcher_open'] else ['剧场']

        ui._click = _click
        ui._visible_boards = _read
        assert ui._board_labels() == ['热播榜', '必看榜', '新剧榜']

    def test_a_switcher_that_will_not_open_falls_back_to_the_visible_tabs(self):
        ui = PlayerUI(log=lambda _m: None)
        ui._board_toggle = lambda: None
        ui._visible_boards = lambda: ['热播榜']
        assert ui._board_labels() == ['热播榜']

    def test_a_board_already_on_screen_is_clicked_without_opening_the_switcher(self):
        # The list is read by walking every board in it, so opening the popup once per board
        # would close the previous one mid-read (measured: the walk re-clicked the toggle and
        # lost the board it had just switched to).
        events = []
        ui = PlayerUI(log=lambda _m: None)
        ui.collect = lambda max_depth=20: [('必看榜', 'ButtonControl', '必看榜', _AnyRect())]

        def _click(ctrl):
            events.append(ctrl)
            return True

        ui._click = _click
        ui._board_toggle = lambda: (_ for _ in ()).throw(AssertionError('the switcher must stay shut'))
        assert ui._pick_board('必看榜') is True
        assert events == ['必看榜']

    def test_a_board_not_on_screen_opens_the_switcher_and_then_picks_it(self):
        events = []
        ui = PlayerUI(log=lambda _m: None)
        state = {'popup': False}

        def _collect(max_depth=20):
            names = ['热播榜'] + (['必看榜', '新剧榜'] if state['popup'] else [])
            return [(n, 'ButtonControl', n, _AnyRect()) for n in names]

        def _click(ctrl):
            events.append(ctrl)
            if ctrl is ui._board_toggle_return:
                state['popup'] = True
            return True

        ui.collect = _collect
        ui._board_toggle_return = object()
        ui._board_toggle = lambda: ui._board_toggle_return
        ui._click = _click
        assert ui._pick_board('新剧榜') is True
        assert events == [ui._board_toggle_return, '新剧榜'], events

    def test_a_board_the_client_never_lists_is_not_clicked_at_all(self):
        # Refusing to click is what makes the caller name the drama as missing rather than
        # harvesting some other board and calling it this one.
        ui = PlayerUI(log=lambda _m: None)
        ui.collect = lambda max_depth=20: [('热播榜', 'ButtonControl', '热播榜', _AnyRect())]
        ui._board_toggle = lambda: None
        assert ui._pick_board('不存在的榜') is False
        assert ui._board_option('热播榜') == '热播榜'
        assert ui._board_option('不存在的榜') is None


class TestIdentityFromTheRequest:
    """Which drama a page belongs to is read off the REQUEST the player sent.

    Measured 2026-10-20 on a kept capture: a page's ROWS print ``expand.book_id == "0"``,
    so grading the payload waves another drama's thread into this table — that run kept 30
    rows of book ``7615465407347952664`` under the fed 剧名 and stamped them 集序号 1. Every
    request, comment or reply, carries ``business_param.book_id``.
    """

    FOREIGN = '7615465407347952664'

    def _req(self, book, **extra):
        return json.dumps({'aid': 8662, 'business_param': {'book_id': book}, **extra})

    def test_a_page_whose_rows_print_0_but_asks_another_drama_is_refused(self, tmp_path):
        harness, said = _harness(tmp_path, capture_lines=[])
        harness._current_book = BOOK
        stranger = _record(
            entries=[_entry('7777', '别人家的评论', 1792313999)], group='9999', book='0', req=self._req(self.FOREIGN)
        )
        with open(harness._capture, 'a', encoding='utf-8') as handle:
            handle.write(stranger + '\n')
        assert harness._await_page('', 5) is None, 'the payload alone would have accepted this page'
        assert harness._drift_book == self.FOREIGN
        assert any(i18n.t('crawl.hg.cmt.groupMismatch', got=self.FOREIGN, want=BOOK) in line for line in said)

    def test_the_request_book_becomes_the_reference_when_the_payload_names_nothing(self, tmp_path):
        harness, said = _harness(tmp_path, capture_lines=[])
        page = _record(entries=[_entry('7001', '第一', 1792313924)], book='0', req=self._req(BOOK))
        with open(harness._capture, 'a', encoding='utf-8') as handle:
            handle.write(page + '\n')
        hit = harness._await_page('', 5)
        assert hit is not None
        assert harness._current_book == BOOK, 'the identity came from the request, not a zero-valued row'
        assert not any(BOOK in line and '而不是' in line for line in said)

    def test_a_web_series_id_is_never_compared_with_a_client_book_id(self, tmp_path):
        # Measured: the SAME drama is series_id=7696437705822981182 on the web page and
        # book_id=7697823071830297624 in the client. Two id spaces — so a link-fed walk must
        # take its reference from the first page's own book, or every page it asked for
        # correctly would be refused.
        harness, said = _harness(tmp_path, capture_lines=[])
        web_series = '7696437705822981182'
        client_book = '7697823071830297624'
        page = _record(entries=[_entry('7001', '第一', 1792313924)], book='0', req=self._req(client_book))
        with open(harness._capture, 'a', encoding='utf-8') as handle:
            handle.write(page + '\n')
        hit = harness._await_page(web_series, 5)
        assert hit is not None, 'a link-fed walk must not refuse its own drama over an id-space difference'
        assert harness._current_book == client_book
        assert not any('而不是' in line for line in said), said

    def test_a_child_page_from_another_drama_never_reaches_the_inbox(self, tmp_path):
        harness, _said = _harness(tmp_path, capture_lines=[])
        harness._current_book = BOOK
        foreign_reply = _record(
            kind='reply',
            group='7620733881692750616',
            entries=[_entry('9001', '别人家的回复', 1792313999, group='7615470196337151038')],
            req=self._req(self.FOREIGN, comment_id='7620733881692750616'),
        )
        with open(harness._capture, 'a', encoding='utf-8') as handle:
            handle.write(foreign_reply + '\n')
        assert harness._await_page('', 5) is None
        assert harness._reply_inbox == [], 'a stranger drama’s replies stamped with our name is corruption'

    def test_the_walk_stops_and_names_the_drama_when_the_feed_moves_on(self, tmp_path):
        """The measured drift: our episode 1, then every page belongs to the previous show."""
        our_page = _record(entries=[_entry('7001', '第一', 1792313924)], req=self._req(BOOK))
        foreign_page = _record(
            entries=[_entry(f'9{i:03d}', f'别人{i}', 1792314000 + i) for i in range(30)],
            group='7615470192985902142',
            total=30,
            book='0',
            req=self._req(self.FOREIGN),
        )
        ui = _FakeUI(second_page_lines=[foreign_page])
        harness, said = _harness(
            tmp_path,
            ui=ui,
            capture_lines=[our_page],
            params={'episode_count': 3, 'include_replies': False, 'harvest_timeout': 5},
        )
        rows, status = harness.crawl_hongguo(ARTICLE, 0)
        assert status == OK, 'the rows it legitimately kept are still handed over'
        assert len(rows) == 1, f'the drifted feed contributed rows to this table: {len(rows)}'
        assert {r['分集ID'] for r in rows} == {GROUP}, 'only our own episode is in the table'
        assert harness.skipped_targets == ['测试剧'], 'a drama walked 1 of 3 is not a finished crawl'
        assert harness.end_reason == UNDER_TARGET
        assert any(
            i18n.t('crawl.hg.cmt.feedDrifted', title='测试剧', ep=2, book=self.FOREIGN) in line for line in said
        ), said

    def test_a_child_pages_episode_is_read_from_its_body_not_its_path(self, tmp_path):
        # A reply record's group_id is the PARENT COMMENT id (the path is reply/list/{cid}),
        # so 集序号 has to come from the parent comment's own group_id in the payload.
        harness, _said = _harness(tmp_path)
        episode_group = '7615470196337151038'
        harness._ep_of_group[episode_group] = 4
        record = {
            'kind': 'reply',
            'group_id': '7620733881692750616',
            'req_body': self._req(BOOK, comment_id='7620733881692750616'),
            'payload': {
                'data': {
                    'comment': {'comment_id': '7620733881692750616', 'common': {'group_id': episode_group}},
                    'comment_list_info': {'total': 1, 'has_more': False, 'cursor': ''},
                    'reply_list': [
                        {
                            'Common': {
                                'content': {'text': '子'},
                                'create_timestamp': 1792313930,
                                'group_id': episode_group,
                                'user_info': {'base_info': {'user_name': '甲'}},
                            },
                            'reply_id': '9001',
                            'reply_to_comment_id': '7620733881692750616',
                            'stat': {'digg_count': 0, 'reply_count': 0},
                        }
                    ],
                }
            },
        }
        assert harness._reply_episode_group(record) == episode_group
        harness._reply_inbox.append(record)
        rows, _refused = harness._harvest_replies('', '某剧', 1)
        assert rows and rows[0]['集序号'] == 4, 'the thread’s real episode, not the one being played'
        assert rows[0]['评论ID'] == '9001'
        assert harness.shortfall == 0 and harness._reply_progress['7620733881692750616']['kept'] == 1


class TestScreenFacts:
    """The player names the drama on stage; the walk asks BEFORE it harvests.

    Measured 2026-10-20 on a UIA dump taken WHILE the comment drawer was open: exactly one
    ``TextControl`` named ``@剧名`` is present (453 controls in the warm tree), and it prints the
    drama's BASE name — the season suffix the board's title carries is not on screen. The
    ``N / M`` counter visible on the video page is NOT in that tree, so the walk does not
    pretend to verify its episode position from the screen: ``第N集`` does appear there, but
    what it numbers was never established, and a gate built on that guess would refuse dramas
    it was harvesting correctly.
    """

    def test_the_header_names_the_drama_and_nothing_else_answers(self):
        ui = PlayerUI(log=lambda _m: None)
        ui.collect = lambda max_depth=20: [
            (object(), 'TextControl', '1 / 10+', _AnyRect()),
            (object(), 'TextControl', '第1集', _AnyRect()),
            (object(), 'TextControl', '@穿成傀儡皇帝，反手整顿朝堂', _AnyRect()),
            (object(), 'ButtonControl', '@不是文本控件', _AnyRect()),
        ]
        assert ui.screen_drama_title() == '穿成傀儡皇帝，反手整顿朝堂'

    def test_a_second_at_prefixed_text_is_not_taken_for_the_header(self):
        # A 弹幕 or reply that opens with "@昵称" is a TextControl too, and tree order puts it
        # BEFORE the header. Picking the first @ would report a stranger's comment as the drama
        # on stage; not exactly one @ means the tree did not uniquely say which show this is.
        ui = PlayerUI(log=lambda _m: None)
        ui.collect = lambda max_depth=20: [
            (object(), 'TextControl', '@张三 这剧情太离谱了', _AnyRect()),
            (object(), 'TextControl', '@穿成傀儡皇帝，反手整顿朝堂', _AnyRect()),
        ]
        assert ui.screen_drama_title() == '', 'two @-prefixed texts is no single answer'

    def test_a_cold_tree_says_nothing_and_that_is_not_a_refusal(self, tmp_path):
        # Measured cold state: the tree held ZERO controls. Silence is no evidence either way,
        # so the harvest proceeds and the traffic gate stays underneath it.
        ui = PlayerUI(log=lambda _m: None)
        ui.collect = lambda max_depth=20: []
        assert ui.screen_drama_title() == ''
        harness, said = _harness(tmp_path, ui=_FakeUI(), capture_lines=[_record()])
        rows, status = harness.crawl_hongguo(ARTICLE, 0)
        assert status == OK and len(rows) == 1
        mismatch = i18n.t('crawl.hg.cmt.screenMismatch', want='测试剧', have='')
        assert not any(mismatch in line for line in said), said
        assert not harness.skipped_targets, 'a cold tree must not count the drama as skipped'

    def test_a_first_header_that_names_the_previous_drama_is_re_asked_not_believed(self, tmp_path):
        # The header prints whatever is on stage, and the browse page keeps naming the PREVIOUS
        # show for a moment after a card click. One foreign read must not discard a drama the
        # user already paid to open — the gate re-asks, and the second read names ours.
        reads = {'n': 0}

        def stale_then_ours():
            reads['n'] += 1
            return '别的剧' if reads['n'] == 1 else '测试剧'

        ui = _FakeUI()
        ui.screen_drama_title = stale_then_ours
        harness, said = _harness(tmp_path, ui=ui, capture_lines=[_record()], params={'harvest_timeout': 5})
        rows, status = harness.crawl_hongguo(ARTICLE, 0)
        assert status == OK and len(rows) == 1, f'a stale repaint read threw away the drama: {said}'
        assert not harness.skipped_targets
        assert reads['n'] >= 2, 'the suspicious read was re-asked, not concluded on'

    def test_a_short_base_name_on_screen_does_not_false_refuse_a_longer_request(self, tmp_path):
        # _same_drama floors its prefix at 4 to keep 斗罗大陆 off 斗罗大陆 第二季; the screen gate
        # cannot use that floor, because the header is often the short BASE name (赘婿) while the
        # request carries the season (赘婿归来). A wrong 'drifted' here loses a whole drama.
        ui = _FakeUI(screen_title='赘婿')
        harness, said = _harness(tmp_path, ui=ui, capture_lines=[_record()], params={'harvest_timeout': 5})
        rows, status = harness.crawl_hongguo('赘婿归来', 0)
        assert status == OK and len(rows) == 1, f'the short base name on screen read as another drama: {said}'
        assert rows[0]['剧名'] == '赘婿归来'

    def test_a_switch_that_stops_landing_counts_the_drama_as_unfinished(self, tmp_path):
        # ↓ failing is invisible to shortfall: the never-reached episodes print no site total, so
        # with episode 1 full the table can satisfy len(rows) >= target_total and the node would
        # settle 「正常」 over a 1-of-3 walk. The failed switch must name the hole itself.
        ui = _FakeUI()
        ui.next_episode = lambda: False
        harness, _said = _harness(
            tmp_path,
            ui=ui,
            capture_lines=[_record()],
            params={'episode_count': 3, 'harvest_timeout': 5, 'include_replies': False},
        )
        rows, status = harness.crawl_hongguo(ARTICLE, 0)
        assert status == OK and [r['评论ID'] for r in rows] == ['7001'], 'episode 1 was ours and stays'
        assert harness.skipped_targets == ['测试剧'], 'a key that stopped landing is a named hole'
        assert harness.end_reason == UNDER_TARGET

    def test_the_screen_may_name_the_base_title_without_the_season_suffix(self, tmp_path):
        # Measured on the real player: a walk asked for 「聚宝仙盆之杂灵根才是真BOSS第十四季」
        # read the header as 「聚宝仙盆之杂灵根才是真BOSS」. Equality would false-refuse a drama
        # that opened correctly, which is the opposite of why this check exists.
        long_ui = _FakeUI(screen_title='聚宝仙盆之杂灵根才是真BOSS')
        harness, said = _harness(tmp_path, ui=long_ui, capture_lines=[_record()])
        rows, status = harness.crawl_hongguo('聚宝仙盆之杂灵根才是真BOSS第十四季', 0)
        assert status == OK and len(rows) == 1, f'the base name on screen read as another drama: {said}'
        assert rows[0]['剧名'] == '聚宝仙盆之杂灵根才是真BOSS第十四季', 'the row keeps the name it was fed'

    def test_a_card_that_lands_on_another_drama_harvests_nothing(self, tmp_path):
        ui = _FakeUI(screen_title='别的剧')
        harness, said = _harness(tmp_path, ui=ui, capture_lines=[_record()], params={'harvest_timeout': 5})
        rows, status = harness.crawl_hongguo(ARTICLE, 0)
        assert (rows, status) == ([], DEAD), 'the wrong show is caught before its rows are read'
        assert harness.skipped_targets == ['测试剧'] and harness.end_reason == UNDER_TARGET
        assert any(i18n.t('crawl.hg.cmt.screenMismatch', want='测试剧', have='别的剧') in line for line in said), said

    def test_a_switch_onto_another_drama_stops_the_walk_and_keeps_what_is_ours(self, tmp_path):
        page2 = _record(group='9999', entries=[_entry('8001', '第二集', 1792313924)])
        ui = _FakeUI(second_page_lines=[page2])
        state = {'switched': False}
        real_switch = ui.next_episode

        def next_episode():
            state['switched'] = True
            return real_switch()

        ui.next_episode = next_episode
        ui.screen_drama_title = lambda: '别的剧' if state['switched'] else '测试剧'
        harness, said = _harness(
            tmp_path,
            ui=ui,
            capture_lines=[_record()],
            params={'episode_count': 3, 'harvest_timeout': 5, 'include_replies': False},
        )
        rows, status = harness.crawl_hongguo(ARTICLE, 0)
        assert status == OK and [r['评论ID'] for r in rows] == ['7001'], 'episode 1 was ours and stays'
        assert state['switched'] and ui.switches == 1, 'the switch was asked before the screen was'
        assert harness.skipped_targets == ['测试剧'], 'a drama left at 1 of 3 is not a finished crawl'
        assert harness.end_reason == UNDER_TARGET
        assert any(i18n.t('crawl.hg.cmt.screenMismatch', want='测试剧', have='别的剧') in line for line in said), said

    def test_the_same_drama_is_counted_as_unfinished_only_once(self, tmp_path):
        # Three paths can name the same hole (no title, cold tree, drifted screen); the tail
        # refusal prints this list with a count, so a duplicate would report one hole as two.
        ui = _FakeUI(cold_times=99, wakes=True)
        harness, _said = _harness(tmp_path, ui=ui, capture_lines=[_record()])
        harness.crawl_hongguo(ARTICLE, 0)
        harness._count_unfinished('测试剧')
        harness._count_unfinished('测试剧')
        assert harness.skipped_targets == ['测试剧'], harness.skipped_targets


class TestCardMatching:
    """The card the walk opens is the card that NAMES the drama, exactly, if one exists."""

    ITEMS = [
        (object(), 'TextControl', '斗罗大陆', _AnyRect()),
        ('season-one-play', 'ButtonControl', '▶ 播放', _AnyRect()),
        (object(), 'TextControl', '斗罗大陆 第二季', _AnyRect()),
        ('season-two-play', 'ButtonControl', '▶ 播放', _AnyRect()),
    ]

    def test_the_exact_card_wins_over_the_sibling_that_starts_the_same(self):
        ui = PlayerUI(log=lambda _m: None)
        ui.collect = lambda max_depth=20: list(self.ITEMS)
        assert ui._play_for_title('斗罗大陆 第二季') == 'season-two-play'

    def test_a_request_that_matches_nothing_exactly_still_takes_the_prefix_card(self):
        ui = PlayerUI(log=lambda _m: None)
        ui.collect = lambda max_depth=20: [
            (object(), 'TextControl', '聚宝仙盆之杂灵根才是真BOSS 第十四季', _AnyRect()),
            ('play', 'ButtonControl', '▶ 播放', _AnyRect()),
        ]
        assert ui._play_for_title('聚宝仙盆之杂灵根才是真BOSS') == 'play'

    def test_a_card_with_no_match_opens_nothing(self):
        ui = PlayerUI(log=lambda _m: None)
        ui.collect = lambda max_depth=20: list(self.ITEMS)
        assert ui._play_for_title('完全另一部剧') is None


class TestWaitsCompressed:
    """The two dead waits the user reported are gone — both are Hongguo-only."""

    def test_a_tree_that_goes_cold_mid_board_walk_bails_instead_of_grinding(self, monkeypatch):
        # Measured cost of NOT doing this: the board walk slept through every board × every
        # scroll against a tree that had re-frozen to 0 controls (~110 s of dead waiting).
        from crawlers import hongguo_harvest as hh

        monkeypatch.setattr(hh.time, 'sleep', lambda *_a, **_k: None)
        ui = PlayerUI(log=lambda _m: None, abort=lambda: False)
        ui.wait_content = lambda seconds=60.0: object()
        ui._find_until = lambda *a, **k: object()
        ui._click = lambda ctrl: True
        ui._board_labels = lambda: ['总榜', '必看榜', '热播榜', '推荐榜', 'AI剧']
        ui._pick_board = lambda label: True
        reads = {'collect': 0}

        def cold_collect(max_depth=20):
            reads['collect'] += 1
            return []

        ui.collect = cold_collect

        def no_scroll(*_a, **_k):
            raise AssertionError('scrolled a board after the tree was already cold')

        ui._ensure_library = no_scroll
        with pytest.raises(TreeColdError):
            ui.open_drama('测试剧')
        assert reads['collect'] == 1, 'bailed on the first cold read, not after walking every board'

    def test_await_page_returns_as_soon_as_the_drift_is_proven(self, tmp_path):
        # The page after the reference proves the feed left the drama; keeping the rest of the
        # window open would wait out harvest_timeout on pages the identity gate already discards.
        foreign = '9999999999999999999'
        line = _record(group='7777', book=foreign, entries=[_entry('7099', '别剧', 1792313999)])
        harness, _said = _harness(tmp_path, ui=_FakeUI(), capture_lines=[line])
        harness._current_book = BOOK  # an earlier page of ours fixed the reference already
        started = time.monotonic()
        result = harness._await_page('', 60)  # a 60 s window that must NOT be paid
        waited = time.monotonic() - started
        assert result is None
        assert harness._drift_book == foreign
        assert waited < 5, f'a proven drift should return at once, waited {waited:.1f}s'


class _RowRect:
    """A rect that carries a vertical position, for the header-anchored drawer close."""

    def __init__(self, top, width=100, left=0):
        self.top = top
        self.left = left
        self._w = width

    def width(self):
        return self._w


class TestDrawerClose:
    """Closing the drawer before ↓ must click the drawer's own 关闭 — never the window chrome."""

    @staticmethod
    def _drawer_tree():
        # Copied from the measured drawer dump: a zero-width window 关闭, the titlebar 关闭 at
        # y≈197, the 评论 header at y≈326 and ITS close at y≈321 (same row), plus a reply link.
        return [
            (object(), 'ButtonControl', '关闭', _RowRect(0, width=0)),
            (object(), 'ButtonControl', '最小化', _RowRect(195)),
            ('titlebar-close', 'ButtonControl', '关闭', _RowRect(197)),
            (object(), 'TextControl', '评论 · 3076', _RowRect(326)),
            ('drawer-close', 'ButtonControl', '关闭', _RowRect(321)),
            (object(), 'ButtonControl', '展开 8 条回复 ▾', _RowRect(1166)),
        ]

    def test_the_close_is_the_drawer_button_sharing_the_comment_header_row(self):
        clicked = []
        ui = PlayerUI(log=lambda _m: None)
        ui.collect = lambda max_depth=20: list(self._drawer_tree())
        ui._click = lambda ctrl: clicked.append(ctrl) or True
        assert ui.close_comments() is True
        assert clicked == ['drawer-close'], 'clicked the drawer close, not the titlebar/window one'

    def test_no_comment_header_means_the_drawer_is_not_open_and_nothing_is_clicked(self):
        clicked = []
        ui = PlayerUI(log=lambda _m: None)
        ui.collect = lambda max_depth=20: [
            ('titlebar-close', 'ButtonControl', '关闭', _RowRect(197)),
            (object(), 'TextControl', '@测试剧', _RowRect(1071)),
        ]
        ui._click = lambda ctrl: clicked.append(ctrl) or True
        assert ui.close_comments() is False
        assert clicked == [], 'no 评论 header → never a click that could quit the player'

    def test_the_walk_closes_the_drawer_once_per_episode_switch(self, tmp_path):
        page2 = _record(group='9999', entries=[_entry('8001', '第二集', 1792313924)])
        ui = _FakeUI(second_page_lines=[page2])
        harness, _said = _harness(
            tmp_path,
            ui=ui,
            capture_lines=[_record()],
            params={'episode_count': 2, 'harvest_timeout': 5, 'include_replies': False},
        )
        harness.crawl_hongguo(ARTICLE, 0)
        assert ui.switches == 1 and ui.closes == 1, 'one drawer close, handed back before the one ↓'
