"""The 红果 comment harness driven against a hand-written capture file.

The harness's two machine-bound seams — ``_ensure_stack`` (mitmdump + player) and
``_title_for`` (the web detail page) — are replaced here, so everything that is
*logic* runs in the fast tier: the JSONL tailer, per-episode walking, floor
numbering across groups, the reply inbox, the danmaku filter, the U1 end license,
and every refusal by its own name. The process half itself is device/live tier.
"""

import json
import os

import pytest

import i18n
from crawlers.base import UNDER_TARGET, CrawlerStopped
from crawlers.comments_base import DEAD, OK
from crawlers.hongguo_harvest import HongguoCommentHarness

pytestmark = pytest.mark.unit

ARTICLE = 'https://hongguoduanju.com/detail?series_id=7696063528179878937'
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


def _record(entries=None, *, kind='comment', group=GROUP, total=1, has_more=False, req='', book=BOOK):
    entries = entries if entries is not None else [_entry('7001', '第一', 1792313924)]
    payload = _envelope(entries, total=total, has_more=has_more)
    for item in entries:
        if isinstance(item, dict) and isinstance(item.get('comment'), dict):
            item['comment'].setdefault('expand', {})['book_id'] = book
    return json.dumps(
        {'ts': 0.0, 'kind': kind, 'group_id': group, 'url': 'https://x.test/', 'req_body': req, 'payload': payload}
    )


class _FakeUI:
    """The player, as far as the harness cares: opens, switches, and lands pages."""

    def __init__(self, opened=True, second_page_lines=()):
        self.opened = opened
        self.switches = 0
        self.second_page_lines = list(second_page_lines)
        self.target = None  # the capture file, set by _harness()

    def open_drama(self, _title):
        return self.opened

    def next_episode(self):
        self.switches += 1
        if self.second_page_lines:
            with open(self.target, 'a', encoding='utf-8') as handle:
                for line in self.second_page_lines:
                    handle.write(line + '\n')
        return True

    def open_comments(self):
        return True

    def scroll_drawer(self):
        return False

    def expand_replies(self):
        return False


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

    def test_a_page_of_another_drama_is_refused_by_name_not_kept(self, tmp_path):
        lines = [_record(entries=[_entry('7001', '错剧', 1792313924)], book='0000000000000000000')]
        harness, said = _harness(tmp_path, capture_lines=lines, params={'harvest_timeout': 5})
        rows, status = harness.crawl_hongguo(ARTICLE, 0)
        assert (rows, status) == ([], DEAD)
        named = i18n.t('crawl.hg.cmt.groupMismatch', got='0000000000000000000', want='7696063528179878937')
        assert any(named in line for line in said)

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
        ui.scroll_drawer = lambda: True
        rows, status = harness.crawl_hongguo(ARTICLE, 0)
        assert status == OK
        ids = [r['评论ID'] for r in rows]
        assert ids.count('7001') == 1, 'the same comment from two pages merges to one row'
        assert set(ids) == {'7001', '7002', '7003'}
        assert harness.end_reason == 'site_end', 'kept 3 of total 3 — now the arithmetic licenses it'

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
