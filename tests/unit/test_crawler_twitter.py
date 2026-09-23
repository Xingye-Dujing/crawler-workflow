"""X (twitter): the row readers and the comment-router's host rule.

Both are pure — the crawl itself is exercised against a fake driver in
``tests/integration/test_twitter_crawler.py`` and for real in the live tier — and
both were written against shapes measured on the live site
(``scratchpad/x_map.json``, ``x_detail.json``), which is why the fixtures below
look like the site rather than like a convenience:

* counters arrive as **one sentence** on a ``[role="group"]`` element, with
  ``1.1M views`` in it — the shared 万/K/M parser is what turns that into
  1100000, and a ``\\d+`` regex would have stored 1;
* the publish time only exists as ISO UTC; the label a person sees is relative
  and would put a different moment in the same column per read;
* a card carries ``/Lowes/status/209…/analytics`` among its links, so an
  unanchored status-id pattern steals the wrong permalink;
* the comment router matches **hosts**, not substrings: ``x.com`` is a substring
  of ``max.com``, and a link routed by substring would be crawled as the wrong
  platform and arrive labelled with the wrong site.
"""

import re

import pytest

from crawl_capabilities import CAPABILITIES, crawl_kwargs, mode_for, required_missing
from crawlers.comments import parse_twitter_replies
from crawlers.twitter import (
    TwitterCrawler,
    handle_of,
    iso_stamp,
    parse_counters,
    permalink,
    row_from_card,
    split_author,
    tweet_id_of,
)
from utils.helpers import platform_for

pytestmark = pytest.mark.unit

GROUP = '1887 replies, 7746 reposts, 49483 likes, 6045 bookmarks, 1.1M views'


def card(**over):
    """One extracted card, in the shape the in-page script returns."""
    data = {
        'text': 'curious how this holds once people outside the team try it.',
        'user': 'Lisa\n@devtrotter_fr\n·\n13s',
        'iso': '2026-09-23T09:22:37.000Z',
        'link': '/devtrotter_fr/status/2102690087062348280',
        'tweetId': '2102690087062348280',
        'images': [],
        'video': False,
        'quote': False,
        'card': False,
        'poll': False,
        'labels': {
            'group': GROUP,
            'reply': '1887 Replies. Reply',
            'retweet': '7746 reposts. Repost',
            'like': '49483 Likes. Like',
        },
    }
    data.update(over)
    return data


def js_pattern(script: str, call: str) -> re.Pattern:
    """The JS regex literal that *call* uses inside *script*, as a Python pattern.

    Two translations are needed, because the script in the crawler is the code the
    *browser* runs: ``\\/`` is an escaped slash in a JS literal and a plain one in
    Python, and the literal ends at its first unescaped slash outside a ``[...]``
    class (``[^/]+`` therefore does not close it).
    """
    at = script.index(call) + len(call)
    assert script[at] == '/', f'{call} no longer matches a regex literal'
    end = at + 1
    depth = 0
    while end < len(script):
        char = script[end]
        if char == '\\':
            end += 2
            continue
        if char == '[':
            depth += 1
        elif char == ']':
            depth -= 1
        elif char == '/' and not depth:
            break
        end += 1
    return re.compile(script[at + 1 : end].replace('\\/', '/'))


class TestCounters:
    def test_the_group_sentence_carries_every_count(self):
        counters = parse_counters({'group': GROUP})
        assert counters == {'评论数': 1887, '转发数': 7746, '点赞数': 49483, '收藏数': 6045, '浏览数': 1100000}

    def test_a_compact_view_count_is_not_read_as_one(self):
        # ``\d+`` would return 1 for "1.1M views"; the whole figure is the point.
        assert parse_counters({'group': '3 views'})['浏览数'] == 3
        assert parse_counters({'group': '2.2万 reposts'})['转发数'] == 22000

    def test_the_per_button_labels_are_the_fallback(self):
        buttons = {'reply': '0 Replies. Reply', 'like': '12 Likes. Like', 'retweet': '3 reposts. Repost'}
        counters = parse_counters(buttons)
        assert counters['评论数'] == 0 and counters['点赞数'] == 12 and counters['转发数'] == 3
        # Nothing said 浏览数, and an invented zero is honest here: the button
        # only exists on rows the site chose to show views for.
        assert counters['浏览数'] == 0

    def test_an_empty_label_set_yields_zeros_not_an_error(self):
        assert parse_counters({})['点赞数'] == 0
        assert parse_counters(None)['评论数'] == 0


class TestAuthorAndTime:
    def test_the_handle_is_the_stable_half_of_the_author_block(self):
        name, handle = split_author('Lisa\n@devtrotter_fr\n·\n13s')
        assert name == 'Lisa' and handle == '@devtrotter_fr'

    def test_a_display_name_containing_the_marker_is_not_the_handle(self):
        name, handle = split_author('真@野\n@Xingye585\n·\n15h')
        assert handle == '@Xingye585'
        assert name == '真@野', 'the first line is the display name even when it holds an @'

    def test_a_two_line_block_still_yields_both(self):
        name, handle = split_author('OpenAI\n@OpenAI')
        assert name == 'OpenAI' and handle == '@OpenAI'

    def test_iso_is_stored_as_a_utc_minute_not_as_a_relative_label(self):
        assert iso_stamp('2026-09-23T09:21:41.000Z') == '2026-09-23 09:21'
        assert iso_stamp('') == ''
        # Anything the site did not spell as a timestamp is passed through: the
        # column must not silently become a date the crawler invented.
        assert iso_stamp('Streamed live') == 'Streamed live'


class TestPermalinkAndId:
    def test_the_analytics_link_is_not_the_permalink(self):
        # Measured on a real card: /Lowes/status/209…/analytics is also present,
        # and taking the first /status/ match would store an analytics URL as the
        # post's own link (and its id as "…/analytics").
        row = row_from_card(card(link='/Lowes/status/2098015709662167492/analytics', tweetId='2098015709662167492'))
        assert row['链接'] == 'https://x.com/Lowes/status/2098015709662167492'

    def test_relative_links_are_made_absolute(self):
        assert permalink('/OpenAI/status/1') == 'https://x.com/OpenAI/status/1'
        assert permalink('https://x.com/a/status/2') == 'https://x.com/a/status/2'

    @pytest.mark.parametrize(
        ('url', 'expected'),
        [
            ('https://x.com/OpenAI/status/2102460975790137662', '2102460975790137662'),
            ('https://twitter.com/OpenAI/status/123?s=20', '123'),
            ('2102460975790137662', '2102460975790137662'),
            ('https://x.com/OpenAI', ''),
            ('', ''),
        ],
    )
    def test_one_id_per_link_spelling(self, url, expected):
        assert tweet_id_of(url) == expected

    @pytest.mark.parametrize(
        ('typed', 'expected'),
        [
            ('@OpenAI', 'OpenAI'),
            ('OpenAI', 'OpenAI'),
            ('https://x.com/OpenAI', 'OpenAI'),
            ('https://x.com/OpenAI/with_replies', 'OpenAI'),
            ('https://twitter.com/OpenAI/status/123', 'OpenAI'),
            ('https://x.com/home', ''),
            ('', ''),
        ],
    )
    def test_a_pasted_profile_is_one_handle(self, typed, expected):
        assert handle_of(typed) == expected


class TestRow:
    def test_a_card_becomes_a_row(self):
        row = row_from_card(card())
        assert row['发布者'] == 'Lisa'
        assert row['发布者ID'] == '@devtrotter_fr'
        assert row['用户链接'] == 'https://x.com/devtrotter_fr'
        assert row['发布时间'] == '2026-09-23 09:22'
        assert row['正文'].startswith('curious')
        assert row['点赞数'] == 49483 and row['浏览数'] == 1100000
        assert row['推文ID'] == '2102690087062348280'
        # No platform stamps its rows with the keyword that found them, and 作者
        # mode has no keyword to stamp: provenance lives in the run record.
        assert '关键词' not in row

    def test_topics_are_pulled_out_of_the_text_as_their_own_column(self):
        row = row_from_card(card(text='try #GPT6 and ＃openai now'))
        assert row['话题'] == 'GPT6 | openai'

    def test_media_flags_are_counts_and_not_booleans(self):
        row = row_from_card(card(images=['a.jpg', 'b.jpg'], video=True, quote=True))
        assert row['图片数'] == 2 and row['图片链接'] == 'a.jpg | b.jpg'
        assert row['视频数'] == 1 and row['是否引用'] == '1'

    def test_a_card_without_a_status_id_is_dropped(self):
        assert row_from_card(card(link='', tweetId='')) is None
        assert row_from_card({}) is None
        assert row_from_card(None) is None

    def test_a_photo_post_with_no_caption_is_a_row_and_not_an_empty_one(self):
        """Measured on the live site: a caption-less photo post has **no**
        ``div[data-testid="tweetText"]`` node at all, so the extractor's text is
        empty while the card holds a real image. Such a post is what the user
        searched for; a reader that required 正文 would lose it, and one that
        invented a caption would be writing data the site never sent.
        """
        photo = 'https://pbs.twimg.com/media/HS5vEtcXkAAFgIa?format=jpg&name=900x900'
        row = row_from_card(card(text='', images=[photo], labels={'group': '3 views'}))
        assert row['正文'] == ''
        assert row['图片数'] == 1 and row['图片链接'] == photo
        assert row['浏览数'] == 3 and row['链接'].endswith(row['推文ID'])

    def test_a_card_with_no_body_at_all_is_dropped(self):
        """Measured on X's own permalink: a card that is only a header, a
        timestamp, "812 views" and five zeroed buttons — no text node, no photo,
        no video, no link card. It has a real address, and nothing else: every
        downstream node would read the row as empty, so keeping it is how a crawl
        looks finished while having collected nothing.
        """
        stub = card(text='', images=[], labels={'group': '812 views'})
        assert row_from_card(stub) is None
        # The same card with any one body part is kept, because that part is the data.
        assert row_from_card(dict(stub, video=True)) is not None
        assert row_from_card(dict(stub, quote=True)) is not None
        assert row_from_card(dict(stub, card=True)) is not None
        assert row_from_card(dict(stub, poll=True)) is not None

    def test_a_retweet_card_is_still_a_row_because_its_counts_are_its_own(self):
        # A repost renders as a card with the original tweet's text and its own
        # id; dropping it would hide the thing the user searched for.
        row = row_from_card(card(text='boosted original', user='News\n@newsdaily\n·\n2h'))
        assert row['发布者ID'] == '@newsdaily' and row['正文'] == 'boosted original'


class TestReplyRows:
    """``parse_twitter_replies`` gets the extracted dicts of a permalink page.

    A tweet's own page renders the root post as its first card, so the reader is
    handed all three and the root is the argument that drops it.
    """

    ROOT = '2102690087062348280'
    PAGE = f'https://x.com/OpenAI/status/{ROOT}'

    def cards(self):
        return [
            card(),  # the root post
            card(text='first reply', tweetId='900', link='/someone/status/900', user='A\n@a\n·\n1h'),
            card(text='second reply', tweetId='901', link='/someone/status/901', user='B\n@b\n·\n2h'),
        ]

    def test_the_root_post_is_left_out(self):
        rows = parse_twitter_replies(self.cards(), self.PAGE, self.ROOT)
        assert [row['评论ID'] for row in rows] == ['900', '901']

    def test_a_reply_becomes_a_comment_row(self):
        rows = parse_twitter_replies(self.cards(), self.PAGE, self.ROOT)
        first = rows[0]
        assert first['平台'] == 'twitter'
        assert first['文章URL'] == self.PAGE
        assert first['评论者'] == '@a' and first['评论者昵称'] == 'A'
        assert first['评论内容'] == 'first reply'
        assert first['评论时间'] == '2026-09-23 09:22'
        assert first['点赞数'] == 49483

    def test_an_empty_page_is_no_rows_rather_than_an_error(self):
        assert parse_twitter_replies([], 'https://x.com/a/status/1', '1') == []
        assert parse_twitter_replies([{}], 'https://x.com/a/status/1', '1') == []


class TestHostRouting:
    """The comment router matches hosts, because a substring is not a host."""

    @pytest.mark.parametrize(
        ('url', 'expected'),
        [
            ('https://x.com/OpenAI/status/1', 'twitter'),
            ('https://mobile.x.com/OpenAI/status/1', 'twitter'),
            ('https://twitter.com/i/status/1', 'twitter'),
            ('https://t.co/abc', ''),
            ('https://max.com/OpenAI/status/1', ''),
            ('https://evil.example/weibo.com/x', ''),
            ('https://x.com.evil.test/OpenAI', ''),
            ('https://www.youtube.com/watch?v=abc', 'youtube'),
            ('https://youtu.be/abc', 'youtube'),
            ('https://v.douyin.com/abc/', 'douyin'),
            ('https://www.zhihu.com/question/1', 'zhihu'),
            ('not a url', ''),
            ('', ''),
        ],
    )
    def test_one_answer_per_link(self, url, expected):
        assert platform_for(url) == expected

    def test_the_x_platform_is_named_the_same_everywhere(self):
        """One id across the registry, the matrix and the router.

        The matrix's platform id, the crawler registry key and the router's answer
        have to be the same string, because each is looked up by a different one
        and a mismatch reads as "this link is unsupported" on a site that works.
        """
        from crawlers import CRAWLERS, is_crawlable

        assert platform_for('https://x.com/a/status/1') == 'twitter'
        assert any(cap.platform == 'twitter' for cap in CAPABILITIES)
        assert CRAWLERS['twitter'] is TwitterCrawler and is_crawlable('twitter')


class TestMatrixEntry:
    def test_the_card_reader_refuses_a_link_that_is_not_the_post(self):
        """The in-page extractor must match the status link to its end.

        The reader runs in the browser, so nothing on the Python side executes it
        and a source-substring check would break on nothing but luck. Compiling
        the literal out of the shipped script and matching sample hrefs against it
        is the only way the anchor can be lost and *seen* — without it, a card's
        ``/status/<id>/analytics`` link becomes the row's 推文ID and the user gets
        a page that does not open.
        """
        from crawlers.twitter import EXTRACT_CARD_JS, WINDOW_LINKS_JS

        status = js_pattern(EXTRACT_CARD_JS, 'h.match(')
        assert status.fullmatch('/OpenAI/status/2102460975790137662')
        assert status.fullmatch('/OpenAI/status/2102460975790137662/')
        assert not status.fullmatch('/OpenAI/status/2102460975790137662/analytics')
        assert not status.fullmatch('/OpenAI/status/abc')
        # The window read is deliberately unanchored at the end (it only needs the
        # id), but it must still refuse a profile link that carries no status.
        window = js_pattern(WINDOW_LINKS_JS, 'h.match(')
        assert window.match('/OpenAI/status/123/analytics').group(1) == '123'
        assert not window.match('/OpenAI/with_replies')

    def test_the_three_modes_are_offered_in_the_panel_order(self):
        from crawl_capabilities import mode_keys_for

        assert mode_keys_for('twitter') == ('posts', 'author', 'comments')

    def test_the_author_mode_asks_for_an_author_not_a_keyword(self):
        mode = mode_for('twitter', 'author')
        assert [f.key for f in mode.fields][:2] == ['author', 'target_count']
        assert [f.key for f in required_missing(mode, {})] == ['author']
        assert required_missing(mode, {'author': '@OpenAI'}) == []

    def test_the_keyword_mode_still_costs_a_keyword(self):
        assert [f.key for f in required_missing(mode_for('twitter', 'posts'), {'author': '@x'})] == ['keyword']

    def test_the_crawl_is_called_with_the_declared_arguments(self):
        mode = mode_for('twitter', 'author')
        kwargs = crawl_kwargs(mode, {'author': '@OpenAI', 'target_count': '20'})
        assert kwargs == {'author': '@OpenAI', 'target_count': 20}

    def test_an_unknown_author_mode_key_falls_back_to_posts(self):
        assert mode_for('twitter', 'nonsense').key == 'posts'

    def test_the_crawler_class_offers_both_handlers(self):
        assert callable(TwitterCrawler.search) and callable(TwitterCrawler.author)

    def test_x_is_visible_window_only(self):
        """Measured: a headless browser gets a login sheet on search and a 403 on
        a profile, so the flag that makes the executor buy a real window must not
        be able to drift back to False without a test noticing."""
        assert TwitterCrawler.never_headless is True
        assert TwitterCrawler.supports_crawl is True
        assert TwitterCrawler.domain == 'x.com'
