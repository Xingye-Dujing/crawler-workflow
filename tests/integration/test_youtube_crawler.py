"""YouTube and X crawls against a fake driver — the transport contract, no browser.

What the live probes measured is what this file keeps honest:

* the crawl navigates **once** and every list after that is a JSON round trip, so
  a regression that re-introduces a page load per row shows up here as an extra
  entry in ``visited``;
* the pager adopts **the token the answer carried**, and on this API the first
  continuation token of a watch answer is the comment pager while the long ones
  are menus — picking by length would read a video with 20 comments as having
  none, which is a result, not an error, and would never be questioned;
* a risk-control page is refused loudly: 0 rows from a blocked session must not
  print the same console line as 0 rows from a keyword nobody searched;
* a resumed run hands its cursor back and must not re-request a page whose rows
  the ledger already has.

The ids and payload shapes are copied from the measured answers
(scratchpad/youtube_map.json, yt_author.json, yt_comment.json), including the id
pattern: a fixture id that is not shaped like a real one hides a reader bug.
"""

import pytest

import crawlers.base as base_module
from crawlers.base import Crawler
from crawlers.comments import OK, CommentSession
from crawlers.youtube import YouTubeCrawler

pytestmark = pytest.mark.unit

VIDEO_A = '9Hku_7e-JSk'
VIDEO_B = 'SGVxZ4idYvc'
VIDEO_C = '11ZbXP1kjBs'
CHANNEL = 'UCpHMIMmvmBTfr-IefM2mu3A'
MENU_TOKEN = 'M' * 1112


def card(video_id, views='1.2K views'):
    return {
        'videoRenderer': {
            'videoId': video_id,
            'title': {'runs': [{'text': f'视频 {video_id}'}]},
            'ownerText': {
                'runs': [{'text': '林粒粒呀', 'navigationEndpoint': {'browseEndpoint': {'browseId': CHANNEL}}}]
            },
            'viewCountText': {'simpleText': views},
            'publishedTimeText': {'simpleText': '2 days ago'},
            'lengthText': {'simpleText': '10:20'},
        }
    }


def lockup(video_id):
    return {
        'lockupViewModel': {
            'contentId': video_id,
            'metadata': {
                'lockupMetadataViewModel': {
                    'title': {'content': f'作品 {video_id}'},
                    'metadata': {
                        'contentMetadataViewModel': {
                            'metadataRows': [
                                {
                                    'metadataParts': [
                                        {'text': {'content': '9.1K views'}},
                                        {'text': {'content': '3 周前'}},
                                    ]
                                }
                            ]
                        }
                    },
                }
            },
            'contentImage': {'thumbnailViewModel': {'image': {'sources': [{'url': 't.jpg'}]}}},
        }
    }


def player(video_id, views='385425', likes='10471', author='林粒粒呀'):
    return {
        'videoDetails': {
            'videoId': video_id,
            'author': author,
            'channelId': CHANNEL,
            'viewCount': views,
            'shortDescription': '简介全文',
            'lengthSeconds': '620',
        },
        'microformat': {'playerMicroformatRenderer': {'likeCount': likes, 'publishDate': '2025-03-01T00:00:00Z'}},
    }


def search_page(cards, token=None):
    contents = [{'itemSectionRenderer': {'contents': cards}}]
    if token:
        contents.append(
            {'continuationItemRenderer': {'continuationEndpoint': {'continuationCommand': {'token': token}}}}
        )
    return {
        'contents': {
            'twoColumnSearchResultsRenderer': {'primaryContents': {'sectionListRenderer': {'contents': contents}}}
        }
    }


def browse_page(items, token=None):
    contents = list(items)
    if token:
        contents.append(
            {'continuationItemRenderer': {'continuationEndpoint': {'continuationCommand': {'token': token}}}}
        )
    return {
        'contents': {
            'twoColumnBrowseResultsRenderer': {
                'tabs': [{'tabRenderer': {'content': {'richGridRenderer': {'contents': contents}}}}]
            }
        }
    }


def comment_page(indexes, token=None):
    """One comment round, shaped the way the answer actually is.

    Three kinds of continuation token live in it, and only one pages the list:
    the sort menu's two (each answers **page one again**), one nested inside every
    thread that has replies (pages that thread), and the list's own trailing pager.
    A fixture without the decoys would pass with any naive rule.
    """
    items = []
    for i in indexes:
        thread = {
            'commentThreadRenderer': {
                'comment': {
                    'commentEntityPayload': {
                        'author': {'displayName': f'@user{i}', 'channelId': CHANNEL},
                        'properties': {
                            'commentId': f'cid{i}',
                            'content': {'content': f'评论 {i}'},
                            'publishedTime': f'{i} 天前',
                        },
                        'toolbar': {'likeCountNotliked': str(i)},
                    }
                }
            }
        }
        if i % 5 == 1:
            # A thread with replies carries its own pager, deeper in the tree.
            reply_pager = {
                'continuationItemRenderer': {'continuationEndpoint': {'continuationCommand': {'token': f'REPLY{i}'}}}
            }
            replies = {'commentRepliesRenderer': {'subThreads': [reply_pager]}}
            thread['commentThreadRenderer']['replies'] = replies
        items.append(thread)
    if token:
        # The list's own pager, as the last element of the same continuationItems.
        items.append({'continuationItemRenderer': {'continuationEndpoint': {'continuationCommand': {'token': token}}}})
    decoy = {
        'commentsHeaderRenderer': {
            'sortMenu': {
                'sortFilterSubMenuRenderer': {
                    'subMenuItems': [
                        {'serviceEndpoint': {'continuationCommand': {'token': 'SORT' * 20}}},
                        {'serviceEndpoint': {'continuationCommand': {'token': 'NEWEST' * 20}}},
                    ]
                }
            }
        }
    }
    return {
        'onResponseReceivedEndpoints': [
            {'reloadContinuationItemsCommand': {'continuationItems': [decoy]}},
            {'reloadContinuationItemsCommand': {'continuationItems': items}},
        ]
    }


class FakeDriver:
    """Answers the two scripts the crawler uses, from queued payloads.

    A queue is keyed ``endpoint:subject``, where the subject is whatever
    identifies the request — the keyword, the video id, the channel id or the
    continuation token — with a bare ``endpoint`` as the fallback. An unkeyed
    request answers as an empty page, so a crawler that asks for something the
    fixture never promised stops instead of looping.
    """

    def __init__(self, answers=None, config=None, initial=None, refusal='', body=''):
        self.answers = dict(answers or {})
        self.config = (
            config
            if config is not None
            else {'key': 'AIza-quzzz', 'context': {'client': {'clientName': 'WEB', 'gl': 'US'}}}
        )
        self.initial = initial or {}
        self.refusal = refusal
        self.visited = []
        self.calls = []
        self.current_url = 'https://www.youtube.com/'
        self.body = body
        self.script_timeout = None

    def get(self, url):
        self.visited.append(url)
        self.current_url = url

    def find_element(self, by, selector):
        return type('El', (), {'text': self.body})()

    def execute_script(self, script, *args):
        if 'INNERTUBE_API_KEY' in script:
            return self.config
        if 'ytInitialData' in script:
            return self.initial
        return None

    def set_script_timeout(self, seconds):
        self.script_timeout = seconds

    def execute_async_script(self, script, url, body):
        self.calls.append((url, body))
        endpoint = url.split('/v1/')[1].split('?')[0]
        subject = body.get('continuation') or body.get('videoId') or body.get('query') or body.get('browseId') or ''
        queue = self.answers.get(f'{endpoint}:{subject}') or self.answers.get(endpoint) or []
        payload = queue.pop(0) if len(queue) > 1 else (queue[0] if queue else {})
        # A queued ``{'_refuse': …}`` answers as the risk page for that one call,
        # which is how a refusal *mid-walk* is told apart from one at the door.
        if isinstance(payload, dict) and payload.get('_refuse'):
            return {'status': 429, 'ms': 1, 'json': None, 'head': str(payload['_refuse'])}
        if self.refusal:
            return {'status': 429, 'ms': 1, 'json': None, 'head': self.refusal}
        return {'status': 200, 'ms': 1, 'json': payload, 'head': ''}

    def quit(self):
        pass


@pytest.fixture
def make_crawler(monkeypatch):
    monkeypatch.setattr(base_module.time, 'sleep', lambda s: None)

    def _make(driver):
        def fake_create(self, *args, **kwargs):
            self.driver = driver

        monkeypatch.setattr(Crawler, '_create_driver', fake_create)
        return YouTubeCrawler(headless=True)

    return _make


def card_row(video_id):
    return {'视频ID': video_id, '标题': 'x', '链接': f'https://www.youtube.com/watch?v={video_id}'}


class TestSearchWalk:
    def test_one_navigation_then_json(self, make_crawler):
        driver = FakeDriver(
            {
                'search:人工智能': [search_page([card(VIDEO_A), card(VIDEO_B)], token='PAGE2')],
                'search:PAGE2': [search_page([card(VIDEO_C)])],
                'player': [player(VIDEO_A), player(VIDEO_B), player(VIDEO_C)],
            }
        )
        crawler = make_crawler(driver)
        rows = crawler.search('人工智能', target_count=10)
        assert [row['视频ID'] for row in rows] == [VIDEO_A, VIDEO_B, VIDEO_C]
        assert driver.visited == ['https://www.youtube.com/'], 'the crawl must not navigate per page'

    def test_facts_add_exactly_one_player_call_per_row(self, make_crawler):
        driver = FakeDriver(
            {'search:kw': [search_page([card(VIDEO_A), card(VIDEO_B)])], 'player': [player(VIDEO_A), player(VIDEO_B)]}
        )
        crawler = make_crawler(driver)
        rows = crawler.search('kw', target_count=5)
        assert {row['点赞数'] for row in rows} == {10471}
        assert [call[0].split('/v1/')[1].split('?')[0] for call in driver.calls] == ['search', 'player', 'player']

    def test_facts_off_is_the_fast_path_and_keeps_the_rounded_figure(self, make_crawler):
        driver = FakeDriver({'search:kw': [search_page([card(VIDEO_A, views='1.2K views')])]})
        crawler = make_crawler(driver)
        rows = crawler.search('kw', target_count=5, with_facts=False)
        assert rows[0]['播放数'] == 1200 and rows[0]['点赞数'] == 0
        assert not any('player' in call[0] for call in driver.calls)

    def test_the_target_stops_the_walk_inside_a_page(self, make_crawler):
        driver = FakeDriver(
            {
                'search:kw': [search_page([card(VIDEO_A), card(VIDEO_B), card(VIDEO_C)], token='PAGE2')],
                'player': [player(VIDEO_A)],
            }
        )
        crawler = make_crawler(driver)
        assert len(crawler.search('kw', target_count=2)) == 2

    def test_a_resumed_run_adopts_the_rows_it_already_paid_for(self, make_crawler):
        driver = FakeDriver(
            {'search:kw': [search_page([card(VIDEO_A), card(VIDEO_B)])], 'player': [player(VIDEO_A), player(VIDEO_B)]}
        )
        crawler = make_crawler(driver)
        crawler.seed([card_row(VIDEO_A)])
        rows = crawler.search('kw', target_count=3, resume={'ids': [VIDEO_A], 'token': ''})
        # A: already in the table, and NOT re-emitted as a second row.
        assert [row['视频ID'] for row in rows] == [VIDEO_A, VIDEO_B]

    def test_a_resumed_run_starts_at_the_cursor_it_left(self, make_crawler):
        driver = FakeDriver({'search:PAGE2': [search_page([card(VIDEO_C)])], 'player': [player(VIDEO_C)]})
        crawler = make_crawler(driver)
        rows = crawler.search('kw', target_count=5, resume={'ids': [VIDEO_A, VIDEO_B], 'token': 'PAGE2'})
        assert [row['视频ID'] for row in rows] == [VIDEO_C]
        assert not any('search:kw' in str(call) for call in driver.calls)

    def test_the_cursor_records_the_token_and_the_ids(self, make_crawler):
        marked = []
        driver = FakeDriver(
            {
                'search:kw': [search_page([card(VIDEO_A)], token='PAGE2')],
                'search:PAGE2': [search_page([])],
                'player': [player(VIDEO_A)],
            }
        )
        crawler = make_crawler(driver)
        crawler.set_cursor_sink(marked.append)
        crawler.set_sink(lambda row: True)
        crawler.search('kw', target_count=5)
        assert marked[-1]['token'] == 'PAGE2'
        assert marked[-1]['ids'] == [VIDEO_A]
        assert marked[-1]['done'] == 1

    def test_a_blocked_session_is_refused_rather_than_reported_as_no_results(self, make_crawler):
        driver = FakeDriver({}, refusal='Our systems have detected unusual traffic')
        crawler = make_crawler(driver)
        with pytest.raises(RuntimeError):
            crawler.search('kw', target_count=5)
        assert crawler.login_wall is True

    def test_a_page_that_never_offered_its_config_is_an_error_not_an_empty_crawl(self, make_crawler):
        driver = FakeDriver({}, config={'key': '', 'context': None})
        crawler = make_crawler(driver)
        with pytest.raises(RuntimeError):
            crawler.search('kw', target_count=5)

    def test_an_empty_search_is_zero_rows_and_stays_a_success(self, make_crawler):
        driver = FakeDriver({'search:kw': [search_page([])]})
        crawler = make_crawler(driver)
        assert crawler.search('kw', target_count=5) == []

    def test_a_replaying_pager_ends_the_walk(self, make_crawler):
        """The server keeps handing out a cursor that repeats the same page."""
        same = search_page([card(VIDEO_A)], token='PAGE2')
        driver = FakeDriver({'search:kw': [same], 'search:PAGE2': [same], 'player': [player(VIDEO_A)]})
        crawler = make_crawler(driver)
        rows = crawler.search('kw', target_count=50)
        assert len(rows) == 1
        assert len(driver.calls) < 60, 'the walk kept paying for a page that added nothing'


def watch_answer(tokens):
    """A watch answer advertising these continuation tokens, in this order."""
    return {'frameworkUpdates': {'mutations': [{'continuationCommand': {'token': token}} for token in tokens]}}


def channel_document(items, token=None, name='NASA'):
    """The loaded ``/@NASA/videos`` document: metadata, grid, and its own pager.

    The author mode reads page one out of this rather than asking ``browse`` for
    the tab — measured, that request returns the channel HOME (3.7 MB of shelves,
    other channels' videos among them) instead of the tab the URL named.
    """
    document = browse_page(items, token=token)
    document['metadata'] = {'channelMetadataRenderer': {'externalId': CHANNEL, 'title': {'runs': [{'text': name}]}}}
    return document


class TestAuthorWalk:
    def test_the_channel_page_is_visited_once_and_the_grid_pages_by_json(self, make_crawler):
        driver = FakeDriver(
            {
                'browse:PAGE2': [browse_page([lockup(VIDEO_B)])],
                'player': [player(VIDEO_A, author='NASA'), player(VIDEO_B, author='NASA')],
            },
            initial=channel_document([lockup(VIDEO_A)], token='PAGE2'),
        )
        crawler = make_crawler(driver)
        rows = crawler.author('@NASA', target_count=5)
        assert [row['视频ID'] for row in rows] == [VIDEO_A, VIDEO_B]
        assert rows[0]['作者'] == 'NASA'
        assert rows[0]['频道ID'] == CHANNEL
        assert driver.visited == ['https://www.youtube.com/@NASA/videos']

    def test_the_tab_is_never_requested_through_browse(self, make_crawler):
        """One navigation, and the first page comes out of the document.

        The tab is the one thing on a channel that ``browse`` gets wrong (it answers
        the home shelf), so a regression to asking for it by id+params would put
        another channel's videos in this table and read as a wide, working crawl.
        """
        driver = FakeDriver({'player': [player(VIDEO_A, author='NASA')]}, initial=channel_document([lockup(VIDEO_A)]))
        crawler = make_crawler(driver)
        rows = crawler.author('@NASA', target_count=3)
        assert len(rows) == 1
        assert not any('/browse' in call[0] for call in driver.calls), [call[0] for call in driver.calls]

    def test_the_videos_own_author_beats_the_page_title(self, make_crawler):
        """A collab or a re-upload names its own author; the tab title does not.

        The channel page's title is only the fallback for a row the player call
        could not reach — letting it overwrite a real answer would relabel every
        video on the channel as the channel.
        """
        driver = FakeDriver(
            {'player': [player(VIDEO_A, author='Someone Else')]},
            initial=channel_document([lockup(VIDEO_A)]),
        )
        crawler = make_crawler(driver)
        assert crawler.author('@NASA', target_count=5)[0]['作者'] == 'Someone Else'

    def test_a_row_keeps_the_page_title_when_the_answer_has_no_author(self, make_crawler):
        driver = FakeDriver({'player': [{'videoDetails': {}}]}, initial=channel_document([lockup(VIDEO_A)]))
        crawler = make_crawler(driver)
        assert crawler.author('@NASA', target_count=5)[0]['作者'] == 'NASA'

    @pytest.mark.parametrize(
        ('typed', 'expected'),
        [
            ('@NASA', 'https://www.youtube.com/@NASA/videos'),
            ('NASA', 'https://www.youtube.com/@NASA/videos'),
            ('UCpHMIMmvmBTfr-IefM2mu3A', f'https://www.youtube.com/channel/{CHANNEL}/videos'),
            ('https://www.youtube.com/@NASA', 'https://www.youtube.com/@NASA/videos'),
            (
                'https://www.youtube.com/channel/UCpHMIMmvmBTfr-IefM2mu3A/features',
                f'https://www.youtube.com/channel/{CHANNEL}/videos',
            ),
            ('https://www.youtube.com/user/nasajpl', 'https://www.youtube.com/@nasajpl/videos'),
            ('https://www.youtube.com/results?search_query=nasa', ''),
            ('', ''),
        ],
    )
    def test_what_a_person_types_becomes_one_address(self, typed, expected):
        assert YouTubeCrawler.channel_videos_url(typed) == expected

    def test_a_resumed_author_run_reopens_the_pager_not_the_tab(self, make_crawler):
        """The cursor is a continuation token, and a tab has no second page."""
        driver = FakeDriver(
            {
                'browse:PAGE2': [browse_page([lockup(VIDEO_B)])],
                'player': [player(VIDEO_B, author='NASA')],
            },
            initial=channel_document([lockup(VIDEO_A)], token='PAGE2'),
        )
        crawler = make_crawler(driver)
        crawler.seed([card_row(VIDEO_A)])
        rows = crawler.author('@NASA', target_count=5, resume={'token': 'PAGE2', 'ids': [VIDEO_A]})
        assert [row['视频ID'] for row in rows] == [VIDEO_A, VIDEO_B]
        pagers = [call[1].get('continuation') for call in driver.calls if '/browse' in call[0]]
        assert pagers == ['PAGE2'], f'the tab was re-read after a resume: {pagers}'

    def test_a_page_that_is_not_a_channel_is_an_error(self, make_crawler):
        driver = FakeDriver({}, initial={'metadata': {}})
        crawler = make_crawler(driver)
        with pytest.raises(RuntimeError):
            crawler.author('@whatever', target_count=5)

    def test_an_empty_video_tab_is_said_rather_than_returned_as_zero_rows(self, make_crawler):
        driver = FakeDriver({}, initial=channel_document([]))
        crawler = make_crawler(driver)
        with pytest.raises(RuntimeError):
            crawler.author('@NASA', target_count=5)

    def test_an_empty_author_field_costs_no_browser_time(self, make_crawler):
        driver = FakeDriver({})
        crawler = make_crawler(driver)
        with pytest.raises(RuntimeError):
            crawler.author('   ', target_count=5)
        assert driver.visited == []


class TestDetailAndComments:
    def test_one_link_answers_one_row(self, make_crawler):
        driver = FakeDriver({'player:9Hku_7e-JSk': [player(VIDEO_A)]})
        crawler = make_crawler(driver)
        row = crawler.get_detail(f'https://youtu.be/{VIDEO_A}')
        assert row['视频ID'] == VIDEO_A and row['点赞数'] == 10471

    def test_a_link_with_no_video_id_answers_nothing(self, make_crawler):
        crawler = make_crawler(FakeDriver({}))
        assert crawler.get_detail('https://www.youtube.com/@NASA') is None

    def test_a_video_with_no_player_answer_is_no_row(self, make_crawler):
        crawler = make_crawler(FakeDriver({}))
        assert crawler.get_detail(f'https://youtu.be/{VIDEO_A}') is None


class TestCommentWalk:
    """``CommentSession.crawl_youtube`` — the shared comment engine's adapter."""

    @pytest.fixture
    def session_maker(self, monkeypatch):
        monkeypatch.setattr(base_module.time, 'sleep', lambda s: None)

        def _make(driver):
            def fake_create(self, *args, **kwargs):
                self.driver = driver

            monkeypatch.setattr(Crawler, '_create_driver', fake_create)
            crawler = YouTubeCrawler(headless=True)
            return CommentSession(crawler.driver, log=lambda m: None, nap=lambda s: None)

        return _make

    def test_the_first_token_that_yields_comments_is_the_pager(self, session_maker):
        driver = FakeDriver(
            {
                # Measured order on a real watch page: the comment pager first, the
                # 1112-character menu token after it — and the menu one answers with
                # no comments at all.
                f'next:{VIDEO_A}': [watch_answer(['C1', MENU_TOKEN])],
                'next:C1': [comment_page([1, 2, 3], token='C2')],
                'next:C2': [comment_page([4, 5])],
            }
        )
        session = session_maker(driver)
        rows, status = session.crawl_youtube(f'https://www.youtube.com/watch?v={VIDEO_A}', limit=0)
        assert status == OK
        assert [row['评论ID'] for row in rows] == ['cid1', 'cid2', 'cid3', 'cid4', 'cid5']
        assert rows[0]['平台'] == 'youtube' and rows[0]['点赞数'] == 1

    def test_the_walk_stops_at_the_declared_limit(self, session_maker):
        driver = FakeDriver(
            {
                f'next:{VIDEO_A}': [watch_answer(['C1'])],
                'next:C1': [comment_page(list(range(1, 21)), token='C2')],
            }
        )
        session = session_maker(driver)
        rows, status = session.crawl_youtube(f'https://youtu.be/{VIDEO_A}', limit=5)
        assert status == OK and len(rows) == 5

    def test_a_sort_menu_token_is_never_paged_with(self, session_maker):
        """The regression this walk actually shipped with, pinned.

        Both sort tokens answer the same first page, so following one looks
        identical to a comment section that ended at twenty: no error, no
        duplicate, and a table that quietly stops growing.
        """
        asked = []

        class Driver(FakeDriver):
            def execute_async_script(self, script, url, body):
                asked.append(str((body or {}).get('continuation') or ''))
                return super().execute_async_script(script, url, body)

        driver = Driver(
            {
                f'next:{VIDEO_A}': [watch_answer(['C1'])],
                'next:C1': [comment_page(list(range(1, 21)), token='C2')],
                'next:C2': [comment_page(list(range(21, 41)))],
            }
        )
        session = session_maker(driver)
        rows, status = session.crawl_youtube(f'https://youtu.be/{VIDEO_A}', limit=0)
        assert status == OK and len(rows) == 40
        assert not [token for token in asked if token.startswith(('SORT', 'NEWEST'))], asked

    def test_a_video_whose_comments_are_off_is_an_empty_answer_not_a_failure(self, session_maker):
        driver = FakeDriver({f'next:{VIDEO_A}': [watch_answer(['C1'])], 'next:C1': [{}]})
        session = session_maker(driver)
        rows, status = session.crawl_youtube(f'https://youtu.be/{VIDEO_A}', limit=0)
        assert status == OK and rows == []

    def test_a_refusal_before_any_comment_is_blocked(self, session_maker):
        driver = FakeDriver({f'next:{VIDEO_A}': [watch_answer(['C1'])], 'next:C1': [{'_refuse': 'captcha page'}]})
        session = session_maker(driver)
        rows, status = session.crawl_youtube(f'https://youtu.be/{VIDEO_A}', limit=0)
        assert rows == [] and status == 'blocked'

    def test_a_refusal_after_some_comments_keeps_what_was_read(self, session_maker):
        driver = FakeDriver(
            {
                f'next:{VIDEO_A}': [watch_answer(['C1'])],
                'next:C1': [comment_page([1, 2], token='C2')],
                'next:C2': [{'_refuse': 'captcha page'}],
            }
        )
        session = session_maker(driver)
        rows, status = session.crawl_youtube(f'https://youtu.be/{VIDEO_A}', limit=0)
        assert status == OK and [row['评论ID'] for row in rows] == ['cid1', 'cid2']

    def test_a_link_that_names_no_video_is_dead_rather_than_empty(self, session_maker):
        session = session_maker(FakeDriver({}))
        rows, status = session.crawl_youtube('https://www.youtube.com/@NASA', limit=0)
        assert rows == [] and status == 'dead'

    def test_a_page_that_never_became_a_watch_page_is_dead(self, session_maker):
        driver = FakeDriver({}, config={'key': '', 'context': None})
        session = session_maker(driver)
        rows, status = session.crawl_youtube(f'https://youtu.be/{VIDEO_A}', limit=0)
        assert rows == [] and status == 'dead'
