"""YouTube row readers — the shapes the live site answers, without a browser.

``crawlers/platforms/youtube/crawler.py`` reads innertube JSON rather than a rendered page, so its
whole risk is *interpreting* that JSON wrongly, and the mistakes are the quiet
kind: a rounded "1.2M views" written into a column that claims to be exact, a
duration label read as 3 seconds, a metadata row classified as a date because it
happened to sit at index 1.

Every fixture here is spelled the way the measured answers are spelled
(scratchpad/youtube_map.json, yt_author.json, yt_comment.json) including the two
shapes the site uses at once — ``videoRenderer`` on the search list and
``lockupViewModel`` on a channel tab — because a reader tested against only one
of them is a crawler that reports an empty channel.
"""

from datetime import datetime, timedelta

import pytest

from crawlers.engine import times
from crawlers.platforms.youtube.comments import parse_youtube_comments
from crawlers.platforms.youtube.crawler import (
    apply_player,
    channel_items,
    clock,
    duration_seconds,
    page_token,
    row_from_lockup,
    row_from_video_renderer,
    search_items,
    video_id_of,
    watch_url,
)

pytestmark = pytest.mark.unit

TOKEN = 'CgpRIvYDECgKQghhcG9zIiA'


def _site_now() -> datetime:
    """Now, on the clock a site prints its relative wording in, as a naive stamp.

    ``datetime.now()`` is the clock of the MACHINE — UTC on the CI runner, UTC+8 on this
    box — while "2 days ago" names the site's own zone, which ``crawlers.engine.times``
    pins to +08:00. Asking the host's clock made one fixture resolve eight hours apart
    and pass on this box only: AGENTS' "no test may pass just because of the machine it
    ran on". The zone is taken from the product rather than spelled again here, so the
    two can never drift apart.
    """
    return datetime.now(times._CST).replace(tzinfo=None)


def _continuation(token):
    return {'continuationItemRenderer': {'continuationEndpoint': {'continuationCommand': {'token': token}}}}


def _video_renderer(video_id, **over):
    card = {
        'videoId': video_id,
        'title': {'runs': [{'text': 'Python 入门教程'}, {'text': '（完整版）'}]},
        'ownerText': {
            'runs': [
                {
                    'text': '林粒粒呀',
                    'navigationEndpoint': {'browseEndpoint': {'browseId': 'UCpHMIMmvmBTfr-IefM2mu3A'}},
                }
            ]
        },
        'viewCountText': {'simpleText': '385,425 views'},
        'publishedTimeText': {'simpleText': '1 year ago'},
        'lengthText': {
            'accessibility': {'accessibilityData': {'label': '3 hours, 10 minutes, 59 seconds'}},
            'simpleText': '3:10:59',
        },
        'thumbnail': {'thumbnails': [{'url': 'small.jpg'}, {'contentUrl': 'https://i.ytimg.com/vi/x/hq720.jpg'}]},
        'detailedMetadataSnippets': [{'snippetText': {'runs': [{'text': '一小时讲完全部语法'}]}}],
    }
    card.update(over)
    return card


def _lockup(video_id, parts, **over):
    item = {
        'contentId': video_id,
        'metadata': {
            'lockupMetadataViewModel': {
                'title': {'content': 'James Web 发射前的最后检查'},
                'metadata': {
                    'contentMetadataViewModel': {
                        'metadataRows': [{'metadataParts': [{'text': {'content': text}} for text in parts]}]
                    }
                },
            }
        },
        'contentImage': {
            'thumbnailViewModel': {
                'image': {'sources': [{'url': 'https://i.ytimg.com/vi/y/hq720.jpg'}]},
                'overlays': [
                    {
                        'thumbnailBottomOverlayViewModel': {
                            'badges': [
                                {
                                    'thumbnailBadgeViewModel': {
                                        'text': '5:33',
                                        'rendererContext': {'accessibilityContext': {'label': '5 minutes, 33 seconds'}},
                                    }
                                }
                            ]
                        }
                    }
                ],
            }
        },
    }
    item.update(over)
    return item


class TestWatchLinkAndId:
    @pytest.mark.parametrize(
        ('url', 'expected'),
        [
            ('https://www.youtube.com/watch?v=9Hku_7e-JSk', '9Hku_7e-JSk'),
            ('https://www.youtube.com/watch?v=9Hku_7e-JSk&t=42s', '9Hku_7e-JSk'),
            ('https://youtu.be/9Hku_7e-JSk', '9Hku_7e-JSk'),
            ('https://www.youtube.com/shorts/abcdefghijk', 'abcdefghijk'),
            ('https://www.youtube.com/live/abcdefghijk?feature=share', 'abcdefghijk'),
            ('https://www.youtube.com/embed/abcdefghijk', 'abcdefghijk'),
            ('9Hku_7e-JSk', '9Hku_7e-JSk'),
            ('https://www.youtube.com/@NASA/videos', ''),
            ('', ''),
        ],
    )
    def test_one_column_of_link_shapes(self, url, expected):
        # A person pastes whatever their share sheet gave them, and a link the
        # reader cannot resolve becomes a silently skipped row.
        assert video_id_of(url) == expected

    def test_the_link_built_back_is_the_one_the_site_serves(self):
        assert watch_url('9Hku_7e-JSk') == 'https://www.youtube.com/watch?v=9Hku_7e-JSk'
        assert video_id_of(watch_url('9Hku_7e-JSk')) == '9Hku_7e-JSk'

    def test_no_id_no_link(self):
        assert watch_url('') == ''


class TestClockAndDuration:
    def test_clock_formatting(self):
        assert clock(59) == '0:59'
        assert clock(4259) == '1:10:59'
        assert clock(0) == '0:00'

    @pytest.mark.parametrize(
        ('node', 'expected'),
        [
            ({'simpleText': '3:10:59'}, 11459),
            ({'accessibility': {'accessibilityData': {'label': '3 hours, 10 minutes, 59 seconds'}}}, 11459),
            # A label that names only one or two units: each number is scaled by its own unit,
            # never by its position in a clock face (which read “1 hour” as one second).
            ({'accessibility': {'accessibilityData': {'label': '1 hour'}}}, 3600),
            ({'accessibility': {'accessibilityData': {'label': '2 hours, 30 minutes'}}}, 9000),
            ({'accessibility': {'accessibilityData': {'label': '3小时10分59秒'}}}, 11459),
            ({'text': '5:33'}, 333),
            (
                {
                    'text': '5:33',
                    'rendererContext': {'accessibilityContext': {'label': '5 minutes, 33 seconds'}},
                },
                333,
            ),
            ({'simpleText': '101:23:45'}, 365025),
            ({'simpleText': 'SHORTS'}, 0),
            (None, 0),
        ],
    )
    def test_a_badge_is_read_as_a_duration_not_as_its_first_number(self, node, expected):
        # ``3 hours, 10 minutes`` starts with 3; a reader that grabbed the first
        # integer would file a three-hour lecture as three seconds and every
        # average-duration chart downstream would be quietly wrong.
        assert duration_seconds(node) == expected


class TestSearchRow:
    def test_a_card_becomes_a_row(self):
        row = row_from_video_renderer(_video_renderer('9Hku_7e-JSk'))
        assert row['标题'] == 'Python 入门教程（完整版）'
        assert row['作者'] == '林粒粒呀'
        assert row['正文'] == '一小时讲完全部语法'
        assert row['链接'] == 'https://www.youtube.com/watch?v=9Hku_7e-JSk'
        assert row['播放数'] == 385425
        assert row['时长'] == '3:10:59'
        assert row['时长秒'] == 11459
        assert row['频道ID'] == 'UCpHMIMmvmBTfr-IefM2mu3A'
        assert row['图片链接'] == 'https://i.ytimg.com/vi/x/hq720.jpg'

    def test_a_card_which_only_uses_the_short_form_still_reads(self):
        card = _video_renderer('abc', viewCountText={'simpleText': '1.2万次观看'})
        assert row_from_video_renderer(card)['播放数'] == 12000

    def test_the_list_cannot_know_the_like_count_and_says_so_with_zero(self):
        # 0 here means "not in this answer"; the player call is what fills it, and
        # a reader that left a None would make every spreadsheet column empty.
        assert row_from_video_renderer(_video_renderer('abc'))['点赞数'] == 0

    def test_a_card_without_an_id_is_dropped_not_emitted(self):
        assert search_items({'contents': {'videoRenderer': {'title': {'simpleText': 'no id'}}}}) == []


class TestChannelRow:
    """``发布时间`` is the site's own wording, resolved at read time.

    ``publishedTimeText`` is relative on anything fresh ('2 days ago'), and a relative word
    stored in a table means a different date tomorrow — so it is converted the moment it is
    read, which is the only moment that conversion is possible. What these tests can assert
    is therefore the RESOLVED instant, computed against the same clock — the site's own
    zone (``_site_now``), never the host's ``datetime.now()``, which is eight hours behind
    on a UTC CI runner.
    """

    @staticmethod
    def _assert_relative_to_now(value, days):
        moment = datetime.strptime(value, '%Y-%m-%d %H:%M')
        expected = _site_now() + timedelta(days=days)
        assert abs((moment - expected).total_seconds()) <= 300, f'{value} is not ~{days} day(s) ago'

    def test_a_lockup_becomes_a_row(self):
        row = row_from_lockup(_lockup('yMoGiIeDH9s', ['1.2M views', '2 days ago']))
        assert row['视频ID'] == 'yMoGiIeDH9s'
        assert row['标题'] == 'James Web 发射前的最后检查'
        assert row['播放数'] == 1200000
        self._assert_relative_to_now(row['发布时间'], -2)
        assert row['时长'] == '5:33'
        assert row['时长秒'] == 333
        assert row['链接'].endswith('/watch?v=yMoGiIeDH9s')

    def test_the_metadata_rows_are_classified_not_positional(self):
        # The site puts the date first on some surfaces. Reading index 0 as the
        # view count would file "2 days ago" into 播放数 as parse_count's 2.
        swapped = row_from_lockup(_lockup('abc', ['2 days ago', '1.2M views']))
        assert swapped['播放数'] == 1200000
        self._assert_relative_to_now(swapped['发布时间'], -2)

    def test_a_chinese_label_is_understood_too(self):
        row = row_from_lockup(_lockup('abc', ['3.5万次观看', '1 天前']))
        assert row['播放数'] == 35000
        self._assert_relative_to_now(row['发布时间'], -1)

    def test_a_wording_the_resolver_does_not_know_is_left_alone(self):
        """The half that protects the column. This cell is chosen BECAUSE it says "ago", so
        the extractor keeps it — and the resolver does not recognise a wording that leads
        with a word instead of a number, so it is handed on exactly as the site wrote it."""
        row = row_from_lockup(_lockup('abc', ['1.2M views', 'Premiered 2 months ago']))
        assert row['发布时间'] == 'Premiered 2 months ago'

    def test_no_views_at_all_is_zero_and_not_a_guess(self):
        assert row_from_lockup(_lockup('abc', ['2 days ago']))['播放数'] == 0


class TestPaging:
    def test_the_longest_marked_pager_wins_over_the_tokens_beside_it(self):
        payload = {
            'onResponseReceivedActions': [
                {'reloadContinuationItemsCommand': {'continuationItems': [_continuation('shortmenu')]}}
            ],
            'contents': {
                # Two pagers the markup marks as "load more of this list": the grid
                # one is long, a chip bar's is short. The grid is what continues.
                'a': [_continuation('GRID' * 40)],
                'b': [_continuation('CHIP')],
            },
        }
        assert page_token(payload) == 'GRID' * 40

    def test_a_token_the_markup_does_not_mark_is_not_a_pager(self):
        # Paging with an unmarked token answers an empty page, and the crawl would
        # report "this list has no more rows" — a claim about the site, made by a
        # cursor nobody promised.
        assert page_token({'contents': [{'continuationCommand': {'token': 'MENU'}}]}) == ''
        assert page_token({'contents': [{'videoRenderer': {'videoId': 'a'}}]}) == ''

    def test_channel_items_falls_back_when_the_shape_changes(self):
        legacy = {'contents': {'videoRenderer': _video_renderer('abc')}}
        assert [row['视频ID'] for row in channel_items(legacy)] == ['abc']

    def test_lockups_win_when_both_are_present(self):
        both = {
            'x': [{'lockupViewModel': _lockup('L', ['1 views', '1 days ago'])}, {'videoRenderer': _video_renderer('V')}]
        }
        assert [row['视频ID'] for row in channel_items(both)] == ['L']


class TestPlayerFacts:
    def payload(self, **over):
        player = {
            'videoDetails': {
                'videoId': '9Hku_7e-JSk',
                'title': 'Python 入门教程（完整版）',
                'author': '林粒粒呀',
                'channelId': 'UCpHMIMmvmBTfr-IefM2mu3A',
                'viewCount': '385425',
                'shortDescription': '全片时间表在简介里。\n#python',
                'lengthSeconds': '11459',
                'isLiveContent': False,
            },
            'microformat': {
                'playerMicroformatRenderer': {
                    'likeCount': '10471',
                    'publishDate': '2025-02-28T08:00:10-08:00',
                    'category': 'Education',
                }
            },
        }
        for key, value in over.items():
            player[key].update(value)
        return player

    def test_exact_figures_reach_the_row(self):
        row = apply_player({'视频ID': '9Hku_7e-JSk'}, self.payload())
        assert row['播放数'] == 385425
        assert row['点赞数'] == 10471
        assert row['发布时间'] == '2025-02-28 08:00'
        assert row['分类'] == 'Education'
        assert row['时长秒'] == 11459
        assert row['时长'] == '3:10:59'
        assert row['作者'] == '林粒粒呀'
        assert row['正文'].startswith('全片时间表')

    def test_the_rounded_list_figure_is_kept_when_the_answer_lacks_one(self):
        row = row_from_video_renderer(_video_renderer('abc'))
        apply_player(row, {'videoDetails': {}, 'microformat': {}})
        assert row['播放数'] == 385425

    def test_no_comment_count_is_invented(self):
        # The player answer does not carry one; a 0 in that column would read as
        # "this video has no comments" rather than "not asked".
        assert '评论数' not in apply_player({'视频ID': 'abc'}, self.payload())

    def test_a_live_video_is_marked(self):
        row = apply_player({'视频ID': 'abc'}, self.payload(videoDetails={'isLiveContent': True}))
        assert row['是否直播'] == '1'

    def test_the_channel_link_follows_the_id_it_came_with(self):
        row = apply_player({'视频ID': 'abc'}, self.payload())
        assert row['频道链接'] == 'https://www.youtube.com/channel/UCpHMIMmvmBTfr-IefM2mu3A'


class TestCommentRows:
    def payload(self):
        return {
            'onResponseReceivedEndpoints': [
                {
                    'appendContinuationItemsAction': {
                        'continuationItems': [
                            {
                                'commentThreadRenderer': {
                                    'commentViewModel': {
                                        'commentViewModel': {
                                            'comment': {
                                                'commentEntityPayload': {
                                                    'author': {
                                                        'displayName': '@yunguchaxiang',
                                                        'channelId': 'UCza4OroCVzEe2ObjTNM6hZA',
                                                        'channelCommand': {
                                                            'innertubeCommand': {
                                                                'browseEndpoint': {
                                                                    'canonicalBaseUrl': '/@yunguchaxiang'
                                                                }
                                                            }
                                                        },
                                                        'isCreator': False,
                                                    },
                                                    'properties': {
                                                        'commentId': 'UgxZn0T0WJhVx7C5X054AaABAg',
                                                        'content': {'content': '做大叔的年龄看完了，很好！'},
                                                        'publishedTime': '1 year ago',
                                                        'replyLevel': 0,
                                                    },
                                                    'toolbar': {
                                                        'likeCountNotliked': '56',
                                                        'replyCount': '2',
                                                        # The a11y sentence is the last-resort source of the
                                                        # count; it is only read when both numeric fields miss.
                                                        'likeButtonA11y': 'Like this comment along with 56 others',
                                                    },
                                                }
                                            }
                                        }
                                    }
                                }
                            },
                            {
                                'commentThreadRenderer': {
                                    'commentViewModel': {
                                        'comment': {
                                            'commentEntityPayload': {
                                                'author': {'displayName': '@creator', 'isCreator': True},
                                                'properties': {
                                                    'commentId': 'UgxSECOND',
                                                    'content': {'content': '作者回复：谢谢'},
                                                    'publishedTime': '2 天前',
                                                    'replyLevel': 1,
                                                },
                                                'toolbar': {'likeCountLiked': '7'},
                                            }
                                        }
                                    }
                                }
                            },
                        ]
                    }
                }
            ]
        }

    def test_two_comments_become_two_rows(self):
        rows = parse_youtube_comments(self.payload(), 'https://www.youtube.com/watch?v=9Hku_7e-JSk')
        assert len(rows) == 2
        first = rows[0]
        assert first['平台'] == 'youtube'
        assert first['评论者'] == '@yunguchaxiang'
        assert first['评论者主页'] == 'https://www.youtube.com/@yunguchaxiang'
        assert first['评论内容'].startswith('做大叔')
        # '1 year ago' resolved at read time; asserted against the same clock.
        moment = datetime.strptime(first['评论时间'], '%Y-%m-%d %H:%M')
        assert abs((moment - (_site_now() - timedelta(days=365))).total_seconds()) <= 300
        assert first['点赞数'] == 56
        assert first['回复数'] == 2
        assert first['楼层'] == 1
        assert first['评论ID'] == 'UgxZn0T0WJhVx7C5X054AaABAg'
        assert first['视频ID'] == '9Hku_7e-JSk'

    def test_a_reply_is_numbered_and_flagged_as_the_creators(self):
        second = parse_youtube_comments(self.payload(), 'https://youtu.be/x')[1]
        assert second['楼层'] == 2
        assert second['是否作者回复'] == '1'
        assert second['点赞数'] == 7

    def test_an_empty_answer_is_no_rows_rather_than_an_error(self):
        assert parse_youtube_comments({}, 'https://youtu.be/x') == []
        assert parse_youtube_comments({'x': None}, 'https://youtu.be/x') == []

    def test_the_comment_id_is_what_identifies_a_row(self):
        # 评论时间 is relative prose on this site, so a resumed walk keyed on
        # (author, text, time) could re-store the same comment after a day.
        rows = parse_youtube_comments(self.payload(), 'https://youtu.be/x')
        assert {row['评论ID'] for row in rows} == {'UgxZn0T0WJhVx7C5X054AaABAg', 'UgxSECOND'}


class _YtWalkSession:
    """The surface the YouTube walk uses, enough to drive it without a browser."""

    def __init__(self):
        self.driver = object()
        self.blocked = []
        self.logged = []

    def get(self, url):
        pass

    def body_head(self):
        return ''

    def log(self, message):
        self.logged.append(message)

    def mark_blocked(self):
        self.blocked.append(True)

    def mark_unproven(self, url):
        self.unproven = getattr(self, 'unproven', []) + [url]

    def nap(self, seconds):
        pass

    def may_stop(self):
        return False


class TestYouTubeWalkMarksMidWalkRefusal:
    def test_a_refusal_after_rows_landed_is_blocked_and_pins_the_cursor(self, monkeypatch):
        """A risk page on page two is unproven even though page one's rows are stored.

        The old tail only marked blocked when ``not rows``, so a refusal mid-thread was
        laundered into OK: url_index advanced and 继续 could never recover the gap.
        """
        from crawlers.commenting.protocol import BLOCKED
        from crawlers.platforms.youtube import comments as yt_comments
        from crawlers.platforms.youtube import crawler as yt_crawler
        from crawlers.platforms.youtube import innertube

        continuations = {'n': 0}

        def fake_call(driver, method, key, context, params):
            if 'videoId' in params:
                return {'watch': True}
            continuations['n'] += 1
            # Selection fetch and the pager's first round answer with rows; page two is a refusal.
            if continuations['n'] <= 2:
                return {'commentEntityPayload': [1], 'ids': ['c1', 'c2']}
            return {'refused': True}

        monkeypatch.setattr(innertube, 'call', fake_call)
        monkeypatch.setattr(innertube, 'ready', lambda driver: ('key', {}))
        monkeypatch.setattr(innertube, 'refused', lambda payload: bool(payload and payload.get('refused')))
        monkeypatch.setattr(innertube, 'pager_tokens', lambda watch: ['TOKEN'])
        monkeypatch.setattr(innertube, 'pager_of', lambda payload, marker: 'NEXT')
        monkeypatch.setattr(yt_crawler, 'video_id_of', lambda url: 'abc')
        monkeypatch.setattr(yt_comments, 'collect', lambda payload, key: payload.get(key) or [])
        monkeypatch.setattr(
            yt_comments,
            'parse_youtube_comments',
            lambda payload, url: [{'评论ID': rid} for rid in payload.get('ids', [])],
        )

        session = _YtWalkSession()
        rows, status = yt_comments.walk(session, 'https://www.youtube.com/watch?v=abc', 0)
        assert status == BLOCKED, status
        assert [row['评论ID'] for row in rows] == ['c1', 'c2'], 'rows read before the refusal survive'
        assert session.blocked == [True], 'a mid-walk refusal must mark the session blocked'

    def test_a_pager_that_never_answers_does_not_claim_the_thread_is_empty(self, monkeypatch):
        """An offered pager that pages no comment list is OUR walk failing, not 无评论."""
        from crawlers.commenting.protocol import OK
        from crawlers.platforms.youtube import comments as yt_comments
        from crawlers.platforms.youtube import crawler as yt_crawler
        from crawlers.platforms.youtube import innertube

        def fake_call(driver, method, key, context, params):
            if 'videoId' in params:
                return {'watch': True}
            return {}

        monkeypatch.setattr(innertube, 'call', fake_call)
        monkeypatch.setattr(innertube, 'ready', lambda driver: ('key', {}))
        monkeypatch.setattr(innertube, 'refused', lambda payload: False)
        monkeypatch.setattr(innertube, 'pager_tokens', lambda watch: ['TOKEN'])
        monkeypatch.setattr(innertube, 'pager_of', lambda payload, marker: '')
        monkeypatch.setattr(yt_crawler, 'video_id_of', lambda url: 'abc')
        monkeypatch.setattr(yt_comments, 'collect', lambda payload, key: [])

        session = _YtWalkSession()
        rows, status = yt_comments.walk(session, 'https://www.youtube.com/watch?v=abc', 0)
        assert rows == []
        assert status == OK, 'an unproven walk is not a refusal by the site'
        assert getattr(session, 'unproven', []) == ['https://www.youtube.com/watch?v=abc']
        assert session.logged, 'the console must say the link was not proven'
