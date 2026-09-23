"""YouTube row readers — the shapes the live site answers, without a browser.

``crawlers/youtube.py`` reads innertube JSON rather than a rendered page, so its
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

import pytest

from crawlers.comments import parse_youtube_comments
from crawlers.youtube import (
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
    def test_a_lockup_becomes_a_row(self):
        row = row_from_lockup(_lockup('yMoGiIeDH9s', ['1.2M views', '2 days ago']))
        assert row['视频ID'] == 'yMoGiIeDH9s'
        assert row['标题'] == 'James Web 发射前的最后检查'
        assert row['播放数'] == 1200000
        assert row['发布时间'] == '2 days ago'
        assert row['时长'] == '5:33'
        assert row['时长秒'] == 333
        assert row['链接'].endswith('/watch?v=yMoGiIeDH9s')

    def test_the_metadata_rows_are_classified_not_positional(self):
        # The site puts the date first on some surfaces. Reading index 0 as the
        # view count would file "2 days ago" into 播放数 as parse_count's 2.
        swapped = row_from_lockup(_lockup('abc', ['2 days ago', '1.2M views']))
        assert swapped['播放数'] == 1200000
        assert swapped['发布时间'] == '2 days ago'

    def test_a_chinese_label_is_understood_too(self):
        row = row_from_lockup(_lockup('abc', ['3.5万次观看', '1 天前']))
        assert row['播放数'] == 35000
        assert row['发布时间'] == '1 天前'

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
        first, second = rows
        assert first['平台'] == 'youtube'
        assert first['评论者'] == '@yunguchaxiang'
        assert first['评论者主页'] == 'https://www.youtube.com/@yunguchaxiang'
        assert first['评论内容'].startswith('做大叔')
        assert first['评论时间'] == '1 year ago'
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
