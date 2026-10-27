"""What douyin's published strings mean, and the rows they turn into — no browser, no page.

The crawler answers "how do I get this answer" (open, wait, scroll, click the overlay). This module
answers the other question, "what does this field say", and it is separable because every rule in it
was measured on a *value*, not on an interaction: which id shape addresses a creator, why a ``0`` on
the hot board is not the same statement as a blank, why a relative 「3天前」 may be filed from one cell
and refused from another.

Keeping it here is also what makes those rules testable without a driver —
``tests/integration/test_douyin_crawler.py`` exercises them as plain functions. A copy of this logic
inside a method would need a browser to be checked at all, and the refusals below are exactly the
kind that must not be discovered on a live crawl.
"""

import re
from urllib.parse import quote

from crawlers.core.video import _stamp
from crawlers.engine import times
from crawlers.engine.counters import parse_count

#: A video id, as it appears in ``/video/<id>``, ``?modal_id=<id>`` or a pasted share link.
_VIDEO_ID_RE = re.compile(r'/video/(\d{15,20})')
_MODAL_ID_RE = re.compile(r'[?&]modal_id=(\d{15,20})')

#: A full calendar date with a four-digit year: 2025年11月12日, 2026-08-04, 2026/8/4, 2026.8.4.
#: Anchored at the start of a segment so trailing tags/prose are not captured.
_DATE_RE = re.compile(r'^(\d{4}\s*[年./-]\s*\d{1,2}\s*[月./-]\s*\d{1,2}\s*日?)')


def video_id(url: str) -> str:
    """The aweme id from a video URL, a share link or a bare id."""
    text = str(url or '').strip()
    if re.fullmatch(r'\d{15,20}', text):
        return text
    match = _VIDEO_ID_RE.search(text) or _MODAL_ID_RE.search(text)
    return match.group(1) if match else ''


def sec_uid(value: str) -> str:
    """The ``sec_uid`` a profile link (or a pasted token) identifies.

    Douyin addresses a creator by this opaque token only — ``/user/<numeric uid>``
    is not a route on the web app — and the token is handed out on every video page
    as ``a[href*="/user/"]``, so a pasted profile link is the thing a user can
    actually bring here. A bare token is accepted on its shape (long, no spaces):
    a display name is what people try first and it addresses nobody, and opening a
    guessed profile would report "this account posted nothing" about a page that
    belongs to someone else.
    """
    text = str(value or '').strip()
    if not text:
        return ''
    from_link = re.search(r'/user/([A-Za-z0-9_.-]{10,})', text)
    if from_link:
        return from_link.group(1)
    return text if re.fullmatch(r'[A-Za-z0-9_.-]{30,}', text) else ''


def published(value):
    """The site's own figure, or blank when it published none.

    ``as_index`` would answer 0 for a missing value, and on this board 0 is a claim:
    the pinned top entry really is published as ``0`` at one hour and ``null`` at
    another (measured twice the same day), so only a blank says "the site gave no
    number here" without also saying it counted one.
    """
    return value if isinstance(value, int) and not isinstance(value, bool) else ''


def hot_row(item: dict, rank: int) -> dict | None:
    """One board entry, flattened by what the answer actually publishes.

    ``word`` is both the title and the topic on this site — weibo publishes a separate
    ``#…#`` form and douyin does not, so 话题 is not invented as a second column of the
    same text. ``position`` is the site's own rank and it is **absent** on the pinned
    entry, which is why the caller's index is only a fallback. The link is the address
    the board's own anchors use: ``/hot/<sentence_id>/<word>``, verified today against
    four DOM hrefs and the ids in the same answer.
    """
    word = str(item.get('word') or '').strip()
    sentence = str(item.get('sentence_id') or '').strip()
    if not word or not sentence:
        return None
    return {
        '排名': published(item.get('position')) or rank,
        '标题': word,
        '热度': published(item.get('hot_value')),
        '观看数': published(item.get('view_count')),
        '视频数': published(item.get('video_count')),
        '讨论视频数': published(item.get('discuss_video_count')),
        '发布时间': _stamp(item.get('event_time')),
        '链接': f'https://www.douyin.com/hot/{sentence}/{quote(word)}',
    }


def clean_publish(value) -> str:
    """「发布时间：2026-08-04 16:32」 → 「2026-08-04 16:32」, and a relative word resolved.

    This cell is labelled 发布时间 by the page itself, so its content IS a time — including
    the relative wording it uses for a very recent video, which ``times.absolute`` turns into
    a date. Not to be confused with :func:`publish_from_info`, whose ``·``-split segment is not
    a dedicated time node and therefore keeps refusing relative words: there we cannot be sure
    the token is a time at all.
    """
    text = str(value or '')
    stripped = text.split('：')[-1].strip() if '：' in text else text.strip()
    return times.absolute(stripped)


def publish_from_info(info: str) -> str:
    """The publish date out of ``video-info`` (``@作者 · 2025年11月12日 #标签…``) — or blank.

    The overlay has no dedicated publish-time node and its date is coarser than the standalone
    page. This accepts ONLY a year-bearing calendar date at the start of a segment; a hashtag
    (``#2025年高考``), a relative word (``刚刚``/``3天前``) or a year-less fragment (``2月25日``)
    is left out rather than filed as a timestamp — a half-token that sorts as a date is exactly
    the "right column name, wrong value" the repo refuses elsewhere.
    """
    for part in str(info or '').split('·'):
        token = part.strip()
        if token.startswith('#'):
            continue
        match = _DATE_RE.match(token)
        if match:
            return re.sub(r'\s+', '', match.group(1))[:40]
    return ''


def author_from_related(related: str) -> tuple:
    """Pull the author block out of the related-videos panel.

    It is the only place the web player names the author with its follower
    count, and the line is unpunctuated (``泫九粉丝167.0万获赞1157.5万关注``), so
    the split is on the two labels rather than on positions that shift with the
    episode list.
    """
    match = re.search(r'^(.*?)粉丝([\d.]+[万千]?)获赞([\d.]+[万千]?)', related.strip())
    if not match:
        return '', 0, 0
    return match.group(1).strip(), parse_count(match.group(2)), parse_count(match.group(3))
