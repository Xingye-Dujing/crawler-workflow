"""Live 红果短剧 comment harvest: the real player, the real proxy, one drama, two episodes.

This tier spends the user's desktop and is never to be run unattended: the player
must be LOGGED IN (its own account, not a cookie this tool holds), the mitm root
certificate lands in the CURRENT USER's trusted-root store on first run (the
``harvest_auto_install_ca`` setting, silent PowerShell path — measured 2026-10-19),
and a player window the user left open makes the node REFUSE (it never kills what
it did not start). The drama is the first work of the hot board, read from the
board document itself, so the target is the site's to decide, not a pinned id that
rots when the ranking turns.

Two-sided assertion, as every live case here: the denominator is the ``total`` the
comment page PRINTS for its own episode — a harvest that kept more than the site
claims is corruption, and a ``site_end`` that kept less is a lie.
"""

import html as htmllib
import json
import os
import re
from pathlib import Path

import pytest
import requests

import settings_store
from crawlers import hongguo
from crawlers.base import UNDER_TARGET
from crawlers.comments_base import OK
from crawlers.comments_hongguo import hg_page_title, hg_series_id
from crawlers.hongguo_harvest import HongguoCommentHarness, find_mitmdump, find_player

pytestmark = [pytest.mark.live_site, pytest.mark.live_cn, pytest.mark.enable_socket]

_TIMEOUT = 120  # one real episode page, generously


def _configure_player() -> str:
    """Resolve the player exe for THIS run and put it into the (throwaway) settings store.

    The suite isolates ``settings_store`` to a tmp root, so the user's real
    ``data/settings.json`` is invisible to ``find_player`` — the live tier runs on his
    desktop precisely to use that file, so it is read here READ-ONLY as a fallback and
    copied into the isolated store the harness will consult.
    """
    path = find_player()
    if not path:
        real = Path(__file__).resolve().parents[2] / 'data' / 'settings.json'
        try:
            candidate = str(json.loads(real.read_text(encoding='utf-8')).get('hongguo_player_path') or '')
        except (OSError, ValueError):
            candidate = ''
        if candidate and os.path.isfile(candidate):
            settings_store.save_settings({'hongguo_player_path': candidate})
            path = candidate
    return path


def _first_board_link() -> str:
    """The hot board's rank-1 detail link, from the streamed payload in the document.

    The board data lands as a ``mergeLoaderData`` patch inside the HTML (measured —
    the initial ``_ROUTER_DATA`` carries only the placeholder), so no browser is
    needed to pick the target; the crawl itself still never speaks to the web for
    comments. The CDN serves at least two document variants (measured 352,113 and
    342,093 bytes within seconds) and only one carries the rank patch, so the read
    is retried a bounded number of times before the target is called unavailable.
    """
    for _attempt in range(4):
        reply = requests.get(
            f'{hongguo.BASE}/rank/hot-drama',
            timeout=30,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'},
        )
        reply.raise_for_status()
        for match in re.finditer(r'data-fn-name="mergeLoaderData" data-fn-args="([^"]+)"', reply.text):
            args = json.loads(htmllib.unescape(match.group(1)))
            for patch in args[1]:
                raw = (patch.get('routerDataFnArgs') or [''])[0]
                if 'rankList' not in raw:
                    continue
                board = json.loads(raw)
                rows = board.get('rankList') or []
                if rows:
                    href = str(rows[0].get('href') or '')
                    return href if href.startswith('http') else hongguo.BASE + href
    # No skip here: a board that carried no rank payload is a CRAWL RESULT, and the live
    # tier may only be skipped for an environment precondition (pinned by test_test_tiers).
    raise AssertionError('the hot board carried no rank payload in four tries')


def _detail_title(link: str) -> str:
    """The drama name the WEB detail page prints — the name a board row corresponds to.

    Read here so the name-fed case asks the client for a drama the site actually ranks
    first, rather than for a title somebody typed.
    """
    reply = requests.get(link, timeout=_TIMEOUT, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    reply.raise_for_status()
    return hg_page_title(reply.text)


def test_one_drama_two_episodes_harvest_real_comments():
    if not _configure_player():
        pytest.skip('红果播放器未配置（settings hongguo_player_path）—— live 层专属')
    if not find_mitmdump():
        pytest.skip('mitmproxy 未安装（requirements-optional.txt）—— live 层专属')
    link = _first_board_link()
    assert hg_series_id(link), f'board link names no series: {link}'
    said = []
    harness = HongguoCommentHarness(
        params={'episode_count': 2, 'harvest_timeout': _TIMEOUT, 'include_replies': True},
        log=said.append,
        abort=lambda: False,
    )
    try:
        # A bounded ask (40 rows): the arithmetic licenses (kept vs the site's
        # total, merge dedupe, UNDER_TARGET) are pinned in the unit tier; this
        # case proves the CHAIN — proxy, player, navigation, drawer, capture.
        rows, status = harness.crawl_hongguo(link, 40)
    finally:
        harness.close()
    assert status == OK, f'the harvest refused: {said[-3:]}'
    assert rows, f'no comment rows; console said: {said}'
    ids = [str(row['评论ID']) for row in rows]
    assert len(set(ids)) == len(ids), '评论ID is the row identity; it must not repeat'
    for row in rows:
        assert str(row['评论内容']).strip(), row
        assert row['平台'] == 'hongguo' and row['文章URL'] == link, row
        assert row['评论时间'] >= '20', row  # an epoch that never became a stamp would sort nowhere
    total = harness.target_total
    assert total and len(rows) <= total, f'kept {len(rows)} rows over a site total of {total}'
    # Every exit must be a NAMED one: the user's cap, the site's own end, or the
    # convicted short — never silence over a thin table.
    assert harness.end_reason in ('capped', 'site_end', UNDER_TARGET), f'unnamed end: {harness.end_reason!r}'
    if harness.end_reason == 'site_end':
        assert len(rows) == total, f'site_end claims the walk is whole: {len(rows)} kept of {total}'
    # The drama's own words, measured from the real payload: a table of ids nobody can
    # read is not a 短剧 table, and 集序号 outside the walked range would mean the walker
    # labelled a page it never stood on.
    for row in rows:
        assert str(row['剧名']).strip(), f'a harvested row carries no drama name: {row}'
        assert 1 <= int(row['集序号']) <= 2, f'episode index outside the walk: {row}'
        assert str(row['分集ID']).strip(), f'a comment row names no episode thread: {row}'


def test_a_drama_title_walks_the_players_own_board():
    """The client is its own authority: fed a bare 剧名, the walk finds the card in the
    player's 排行榜 without ever asking the website. Measured as the reason this exists —
    the web board and the client's boards are two different rankings, and a link-fed walk
    can search the client for a drama the client does not list."""
    if not _configure_player():
        pytest.skip('红果播放器未配置（settings hongguo_player_path）—— live 层专属')
    if not find_mitmdump():
        pytest.skip('mitmproxy 未安装（requirements-optional.txt）—— live 层专属')
    link = _first_board_link()
    title = _detail_title(link)
    assert title, f'the detail page printed no drama name for {link}'
    said = []
    harness = HongguoCommentHarness(
        params={'episode_count': 1, 'harvest_timeout': _TIMEOUT, 'include_replies': False},
        log=said.append,
        abort=lambda: False,
    )
    try:
        # One episode, 20 rows: the point is the ENTRY (name → client card → drawer), not
        # the depth, and every second of this spends the user's desktop.
        rows, status = harness.crawl_hongguo(title, 20)
    finally:
        harness.close()
    assert status == OK, f'the name-fed walk refused: {said[-3:]}'
    assert rows, f'no rows for {title}; console said: {said}'
    for row in rows:
        assert row['剧名'] == title, f'a name-fed row must carry the name the walk asked for: {row}'
        assert row['文章URL'] == '', f'no web page was opened, so no link may appear: {row}'
        assert int(row['集序号']) == 1, row
    assert harness.skipped_targets == [], f'the client would not open the drama it listed: {harness.skipped_targets}'
