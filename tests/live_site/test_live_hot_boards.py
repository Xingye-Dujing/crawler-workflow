"""Live hot boards for 微博热搜, 知乎热榜 and 抖音热榜 — the boards shipped on measurement.

Each assertion here is a contract about *behaviour*, taken from what the answer itself
reports, because a board's size and its moment-to-moment contents are the site's to
decide (measured 2026-09: weibo ~52 rows, zhihu exactly 30, douyin ~51; all three
reshuffle hourly). What must not vary is the shape:

* **one request per board.** Both endpoints ignore every paging parameter (measured on
  zhihu: ``limit=100``/``offset=30``/``page=2``/a cursor each returned the SAME 30 ids),
  so a second request is a replay paid for with wall risk — the exact failure the
  bilibili case pins for the other platform;
* **heat is a real number,** not a rounded 万 label and not a zero filling a column the
  answer cannot fill;
* **the columns are the ones the answer fills.** Zhihu's payload carries an author that
  is the literal 「用户」 on every row and a 评论数 that is 0 on every row, so those
  columns are asserted ABSENT — their presence would mean someone re-added a lie;
* **a refusal is named.** A session zhihu holds at the sign-in page must raise, not
  return an empty table that reads as "nothing is hot today".

No skip and no xfail: weibo's board needs no cookie (measured in an anonymous session
too), while zhihu's and douyin's are gated on the cookie the tier already carries — a
missing answer is a fact this test reports in red, and douyin's refusal arrives named
(验证码中间页) rather than as an empty board.
"""

import re
from urllib.parse import quote

import pytest

pytestmark = [pytest.mark.live_site, pytest.mark.live_cn, pytest.mark.enable_socket]


def _assert_topic_rows(rows, minimum):
    assert len(rows) >= minimum, f'the board gave {len(rows)} rows, below the {minimum} this mode must reach'
    words = [str(row['标题']) for row in rows]
    assert len(set(words)) == len(words), f'the board repeated a topic: {words}'
    for row in rows:
        assert row['标题'].strip(), f'a row without its topic word: {row}'
        # NOT "话题 always reads #…#": measured, the board mixes entries whose
        # word_scheme is the bare word (a 非话题 entry, topic_flag '0'). What has to
        # hold is that the column is the site's own scheme string and the link asks
        # for exactly that -- the hash form is content the board decides.
        assert row['话题'].strip('#') == row['标题'].strip('#'), f'话题 and 标题 disagree: {row}'
        assert quote(row['话题']) in row['链接'], f'the link does not search for this row: {row}'
        assert isinstance(row['热度'], int) and row['热度'] > 0, f'热度 must be a real figure: {row}'
        assert row['链接'].startswith('https://s.weibo.com/weibo?q='), f'the row leads somewhere else: {row}'
        assert str(row['排名']).isdigit(), f'排名 is not a position: {row}'


def test_weibos_hot_board_answers_once_with_exact_figures(live_crawler):
    # `use_profile=False` is the measured shape, not a convenience: the board answered
    # a planted-cookie throwaway browser, the profile AND an anonymous session, and the
    # throwaway is what the product itself runs when 本次不用 is answered.
    crawler = live_crawler('weibo', use_profile=False)
    try:
        rows = crawler.hot(target_count=200)
        asked = [url for url in crawler.requests if 'hotSearch' in url]
    finally:
        crawler.close()
    _assert_topic_rows(rows, minimum=20)
    assert asked == [crawler.HOT_API] or len(asked) == 1, f'the board was asked {len(asked)} times: {asked}'
    # The ask was 200 and the board is what it is: the walk must have stopped at the
    # board rather than padding or re-requesting, so rows never exceed what was given.
    assert len(rows) == len(set(row['标题'] for row in rows))


def test_zhihus_hot_board_ships_only_the_columns_its_answer_fills(live_crawler):
    # Measured in a headless throwaway session with the planted cookie: the same 30
    # rows the visible window gets, so the case asks for exactly that shape.
    crawler = live_crawler('zhihu', use_profile=False)
    try:
        try:
            rows = crawler.hot(target_count=10)
            refused = None
        except RuntimeError as wall:
            # A session the site holds at the sign-in page is the measured anonymous
            # answer; it must be NAMED, and naming it is this tier's pass condition.
            rows, refused = [], str(wall)
        asked = [url for url in crawler.requests if 'hot-lists' in url]
    finally:
        crawler.close()
    if refused is not None:
        assert '登录' in refused or 'hotWall' in refused or 'sign' in refused.lower(), (
            f'the refusal has to say which wall it hit: {refused}'
        )
        assert asked == [], f'a walled session must not pay for the endpoint: {asked}'
        return
    assert len(rows) >= 10, f'the board gave {len(rows)} rows'
    assert len(asked) == 1, f'the board was asked {len(asked)} times: {asked}'
    for row in rows:
        assert re.match(r'^https://www\.zhihu\.com/question/\d+$', row['链接']), f'the link was not rewritten: {row}'
        assert isinstance(row['热度'], int) and row['热度'] > 0, f'热度 lost the 万 expansion: {row}'
        assert isinstance(row['回答数'], int) and row['回答数'] >= 0, f'回答数 is not a count: {row}'
        assert '作者' not in row and '评论数' not in row, (
            f'the payload answers these with 用户 / 0 on every row, so they are not data: {sorted(row)}'
        )
    ids = [row['链接'].rsplit('/', 1)[-1] for row in rows]
    assert len(set(ids)) == len(ids), f'the board repeated a question: {ids}'
    assert [row['排名'] for row in rows] == sorted(row['排名'] for row in rows), '排名 is not the board order'


def test_douyins_hot_board_is_read_once_from_a_url_the_crawler_authors(live_crawler):
    """Measured 2026-09-25 (``scratchpad/douyin_hot_static.json``, two runs): asked from
    inside a loaded ``/hot`` document with a URL built out of public literals — no
    ``a_bogus``, no ``msToken``, no ``webid`` — the endpoint answers ``status_code=0``
    with 51 entries, four repeats in a row, each carrying ``hot_value`` and
    ``view_count``. What is asserted below is therefore the *shape*: the count and the
    hour are the site's, and the pinned top entry is published with a 0 heat today.

    ``use_profile=False`` is the measured session, not a convenience: the tool's own
    douyin profile was answered the captcha interstitial, while a cookie-planted
    throwaway browser read the board (the slider the user cleared lives in his own
    Chrome, which is a different profile directory).
    """
    crawler = live_crawler('douyin', use_profile=False)
    try:
        rows = crawler.hot(target_count=200)
        asked = [url for url in crawler.requests if 'hot/search/list' in url]
    finally:
        crawler.close()

    assert len(rows) >= 20, f'the douyin board gave {len(rows)} rows; it publishes ~51'
    assert len(asked) == 1, f'the board was asked {len(asked)} times: one answer IS the board'
    assert asked[0] == crawler.HOT_API, 'the crawler did not author the URL it asked with'
    assert len(rows) <= 60, f'more rows than the board holds means a replay: {len(rows)}'

    words = [str(row['标题']) for row in rows]
    assert len(set(words)) == len(words), f'the board repeated a topic: {words}'
    links = [row['链接'] for row in rows]
    assert len(set(links)) == len(links), 'two topics share one link, so one of them is wrong'
    figures = 0
    for row in rows:
        assert row['标题'].strip(), f'a row without its topic word: {row}'
        assert row['链接'].startswith('https://www.douyin.com/hot/'), f'the row leads elsewhere: {row}'
        # The address the board's own anchors use: /hot/<sentence_id>/<词>. The word is
        # percent-encoded inside it, so the check is on the encoded form.
        assert quote(row['标题']) in row['链接'], f'the link is not this topic: {row}'
        assert isinstance(row['排名'], int) and row['排名'] >= 1, f'排名 is not a position: {row}'
        # Shape, never value: a 0 the site published is truth, a 0 filled in for a
        # missing figure is the lie this tier has been burned by.
        for column in ('热度', '观看数', '视频数', '讨论视频数'):
            assert row[column] == '' or isinstance(row[column], int), f'{column} is neither blank nor int: {row}'
        figures += 1 if isinstance(row['观看数'], int) else 0
        assert row['发布时间'] == '' or re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', row['发布时间']), row
    assert figures, f'no row carried 观看数 — the params that carry it were dropped: {rows[:2]}'
    assert '话题' not in rows[0], 'douyin publishes one word per entry; a 话题 column repeats it'


def test_every_board_mode_is_offered_by_the_matrix_with_no_required_field():
    """The panel builds a source node from the matrix, so a board mode that demanded a
    keyword would be an unusable node — and a platform with one board must not offer a
    choice of boards."""
    import crawl_capabilities as caps

    for platform in ('weibo', 'zhihu', 'douyin'):
        mode = caps.mode_for(platform, 'hot')
        assert mode is not None and mode.handler == 'hot', platform
        assert not [field for field in mode.fields if field.required], f'{platform} 热榜 demands a field: {mode.fields}'
        board = [field for field in mode.fields if field.key == 'board']
        assert not board, f'{platform} has one board but offers a choice: {board}'
    assert caps.mode_for('bilibili', 'hot') is not None, 'the shipped template mode must stay'
    assert [field.key for field in caps.mode_for('bilibili', 'hot').fields if field.key == 'board'], (
        'bilibili publishes two boards; its choice is the reason the field exists'
    )
