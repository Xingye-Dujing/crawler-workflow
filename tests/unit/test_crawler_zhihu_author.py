"""The pure half of zhihu's 某作者的作品 mode: how an author is addressed.

The mode exists because the profile page turns out to be crawlable (measured 2026-09:
``/people/<token>/answers`` holds 39 ``.ContentItem`` rows and 79 after scrolling),
and it is *addressed* by a token for a reason that only measurement found: an answer
permalink carries 86 anchors and not one of them is a link to the author's profile.
So a display name cannot be resolved into a page, and the panel asks for the link the
user can actually copy. These helpers are the whole of that translation, so each is
pinned without a browser.
"""

import pytest

from crawl_capabilities import crawl_kwargs, mode_for, required_missing
from crawlers.zhihu import ZhihuCrawler, zhihu_item_link, zhihu_item_meta, zhihu_profile_token

pytestmark = pytest.mark.unit


class TestProfileToken:
    @pytest.mark.parametrize(
        ('typed', 'expected'),
        [
            ('zshu-83', 'zshu-83'),
            ('  @zshu-83  ', 'zshu-83'),
            ('https://www.zhihu.com/people/zshu-83', 'zshu-83'),
            ('https://www.zhihu.com/people/zshu-83/', 'zshu-83'),
            ('https://www.zhihu.com/people/zshu-83/answers', 'zshu-83'),
            ('//www.zhihu.com/people/zshu-83?tab=answers', 'zshu-83'),
            ('https://www.zhihu.com/people/zshu-83/activities', 'zshu-83'),
            ('', ''),
            ('   ', ''),
            ('/', ''),
        ],
    )
    def test_one_answer_per_spelling(self, typed, expected):
        assert zhihu_profile_token(typed) == expected

    def test_a_link_to_the_wrong_page_refuses_rather_than_guessing(self):
        """The clipboard usually holds an answer or question URL, which carries no
        profile token at all. Taking its first path segment would open
        ``/people/https:`` and then report the author as having published nothing —
        an empty answer invented out of a paste mistake. Refusing names the real fix.
        """
        assert zhihu_profile_token('https://www.zhihu.com/question/504996154/answer/20761') == ''
        assert zhihu_profile_token('https://zhuanlan.zhihu.com/p/789') == ''
        assert zhihu_profile_token('/question/123') == ''

    def test_only_a_people_url_yields_a_token_from_a_link(self):
        assert zhihu_profile_token('https://www.zhihu.com/people/da-wei-lu-yi-si-18/posts') == 'da-wei-lu-yi-si-18'


class TestItemMeta:
    def test_the_tracking_payload_is_read_as_data(self):
        raw = '{"authorName":"Zeta","itemId":"2084336655389954504","title":"老默","type":"answer"}'
        meta = zhihu_item_meta(raw)
        assert meta['authorName'] == 'Zeta' and meta['type'] == 'answer'

    @pytest.mark.parametrize('raw', ['', None, 'not json', '{"a":[1,2}', '[1,2,3]', '42'])
    def test_a_page_that_speaks_differently_yields_nothing(self, raw):
        # The attribute is the site's own; a build that drops it must cost a column,
        # not the row.
        assert zhihu_item_meta(raw) == {}

    def test_the_link_is_built_from_the_kind_the_page_names(self):
        assert (
            zhihu_item_link({'type': 'answer', 'itemId': '456', 'questionId': '123'})
            == 'https://www.zhihu.com/question/123/answer/456'
        )
        assert zhihu_item_link({'type': 'article', 'itemId': '789'}) == 'https://www.zhihu.com/p/789'
        assert zhihu_item_link({'type': 'zvideo', 'itemId': '7'}) == '', 'no kind nobody has verified is guessed at'
        assert zhihu_item_link({}) == ''


class TestMatrixEntry:
    def test_zhihu_offers_the_author_mode_between_posts_and_comments(self):
        from crawl_capabilities import mode_keys_for

        assert mode_keys_for('zhihu') == ('posts', 'author', 'comments')

    def test_the_author_mode_asks_for_the_profile_token(self):
        mode = mode_for('zhihu', 'author')
        author = mode.fields[0]
        assert author.key == 'author' and author.required
        # The hint is the only place a user learns that a display name will not do.
        assert author.hint_key == 'settings.authorHintZhihu'
        assert 'people' in author.placeholder

    def test_an_author_field_of_nothing_is_refused_before_the_browser(self):
        mode = mode_for('zhihu', 'author')
        assert [f.key for f in required_missing(mode, {})] == ['author']
        assert required_missing(mode, {'author': 'zshu-83'}) == []

    def test_the_crawl_is_called_with_the_declared_arguments(self):
        kwargs = crawl_kwargs(mode_for('zhihu', 'author'), {'author': '@zshu-83', 'target_count': '20'})
        assert kwargs == {'author': '@zshu-83', 'target_count': 20}

    def test_the_class_offers_the_handler_the_matrix_names(self):
        assert callable(ZhihuCrawler.author) and callable(ZhihuCrawler.search)

    def test_a_blank_author_costs_no_navigation(self, monkeypatch):
        from crawlers.base import Crawler

        monkeypatch.setattr(Crawler, '_create_driver', lambda self, *a, **k: None)
        with pytest.raises(ValueError):
            ZhihuCrawler(headless=True).author('   ')
