"""YouTube: an innertube client that runs *inside* the page it opened.

Measured on the live site (2026-09; scratchpad/youtube_map.json, yt_author.json),
and the measurements are what decided this design:

* The site is JSON-first. Every list the browser shows is produced by
  ``POST /youtubei/v1/<endpoint>`` with the page's own ``INNERTUBE_CONTEXT`` and
  ``INNERTUBE_API_KEY``, so the crawler opens one page and then asks for data
  instead of navigating for it: a keyword round is **0.68 s for 10 videos**, one
  video's facts **0.31 s**, one comment round **0.32 s for 20 comments**. The
  same search rendered in the DOM gave 5-10 cards in 3-4 s, so the JSON path is
  both faster and more complete — and unsigned, unlike douyin's search.
* The base defaults (eager load, images blocked) are right: nothing here reads a
  pixel. Headless answered exactly like a visible window — the same 10 videos and
  the same player facts in both modes — so YouTube carries no ``never_headless``
  flag and a run keeps the cheap browser.
* A channel's upload tab is reachable only by its ``UC…`` id: ``browse`` answers
  **400 for a @handle**, so the author mode visits the channel page once to read
  ``metadata.channelMetadataRenderer.externalId`` (measured 3.2 s) and pages by
  JSON afterwards (55 items per 0.6 s round).
* That browse answer carries **five** continuation tokens and only the trailing
  ``continuationItemRenderer`` pages the grid — using ``tokens[0]`` returned 0
  items in 109 KB. Hence :func:`page_token`, not "the first token in the tree".
* The search list speaks ``videoRenderer`` while a channel tab speaks
  ``lockupViewModel`` (the 2025+ view-model shape), so both readers exist and
  neither guesses about the other.

Comments live in ``crawlers/comments.py`` (``CommentSession.crawl_youtube``):
that engine is shared with the standalone Comment node, and a video's 评论数 is
read there rather than guessed here — the player answer does not carry it.
"""

import logging
import re
from urllib.parse import quote

from i18n import t

from .base import Crawler
from .engine import innertube
from .engine.counters import parse_count
from .engine.jsonpath import collect, get_in, runs_text

logger = logging.getLogger(__name__)

# The transport itself — reading the page's own API key, POSTing a round trip and
# telling a refusal from an empty list — is in ``engine/innertube.py``, shared
# with the comment engine, which asks the same endpoints the same way.


def clock(seconds: int) -> str:
    """4259 → ``1:10:59``. Only used when a card carried no duration badge."""
    seconds = int(seconds or 0)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f'{hours}:{minutes:02d}:{secs:02d}' if hours else f'{minutes}:{secs:02d}'


def duration_seconds(node) -> int:
    """Seconds from a duration badge, whichever half of it the page filled.

    The badge text is a clock face (``3:10:59``) and its accessibility label
    spells the units out (``3 hours, 10 minutes, 59 seconds``); some surfaces now
    carry only the label. Reading the label's first integer as a duration — or the
    clock face as a number — is how a 3-hour video ends up recorded as 3 seconds.
    """
    label = str(
        get_in(node, 'rendererContext.accessibilityContext.label')
        or get_in(node, 'accessibility.accessibilityData.label')
        or ''
    )
    numbers = [int(chunk) for chunk in re.findall(r'\d+', label)]
    if numbers:
        seconds = 0
        for value in numbers:
            seconds = seconds * 60 + value
        return seconds
    # Two spellings of the same clock: a search card's ``lengthText`` carries a
    # simpleText, a channel badge a plain ``text`` field.
    text = runs_text(node) or str((node or {}).get('text') or '')
    if ':' in text:
        seconds = 0
        for chunk in text.split(':'):
            if chunk.strip().isdigit():
                seconds = seconds * 60 + int(chunk)
        return seconds
    return parse_count(text)


def watch_url(video_id: str) -> str:
    return f'https://www.youtube.com/watch?v={video_id}' if video_id else ''


def video_id_of(url: str) -> str:
    """``watch?v=``, ``youtu.be``, ``/shorts``, ``/live``, ``/embed`` and a bare id.

    The share host is in here because it is what a phone's share sheet actually
    produces: a reader that only understood ``watch?v=`` would call the most
    common paste of all an unsupported link, and the user would watch a perfectly
    good comment node report 0 links.
    """
    text = str(url or '').strip()
    if not text:
        return ''
    match = re.search(r'[?&]v=([\w-]{6,20})', text)
    if match:
        return match.group(1)
    match = re.search(r'(?:youtu\.be/|/(?:shorts|live|embed)/)([\w-]{6,20})', text)
    if match:
        return match.group(1)
    return text if re.fullmatch(r'[\w-]{11}', text) else ''


def row_from_video_renderer(item: dict) -> dict:
    """One search card. Every figure here is the list's own rounding."""
    if not isinstance(item, dict):
        return {}
    video_id = str(item.get('videoId') or '')
    thumbnails = get_in(item, 'thumbnail.thumbnails') or []
    return {
        '标题': runs_text(item.get('title')),
        '正文': runs_text(get_in(item, 'detailedMetadataSnippets.0.snippetText')),
        '作者': runs_text(item.get('ownerText') or item.get('longBylineText')),
        '视频ID': video_id,
        '链接': watch_url(video_id),
        '播放数': parse_count(runs_text(item.get('viewCountText')) or runs_text(item.get('shortViewCountText'))),
        '点赞数': 0,
        '发布时间': runs_text(item.get('publishedTimeText')),
        '时长': runs_text(item.get('lengthText')),
        '时长秒': duration_seconds(item.get('lengthText')),
        '频道ID': str(get_in(item, 'ownerText.runs.0.navigationEndpoint.browseEndpoint.browseId') or ''),
        '图片链接': str((thumbnails[-1] if thumbnails else {}).get('contentUrl') or ''),
    }


def row_from_lockup(item: dict) -> dict:
    """One ``lockupViewModel`` — the 2025+ card a channel tab is made of.

    Its metadata rows are prose ("1.2M views", "2 days ago") with no guaranteed
    order, so each is classified by what it looks like: index 0 is not always the
    view count, and writing "2 days ago" into 播放数 is exactly the kind of
    plausible wrong number this reader exists to prevent.
    """
    if not isinstance(item, dict):
        return {}
    video_id = str(item.get('contentId') or '')
    meta = get_in(item, 'metadata.lockupMetadataViewModel') or {}
    parts: list[str] = []
    for group in collect(meta.get('metadata'), 'metadataParts'):
        for part in group or []:
            text = runs_text(part.get('text') if isinstance(part, dict) else part)
            if text:
                parts.append(text)
    views = next((text for text in parts if 'view' in text.lower() or '次观看' in text), '')
    published = next((text for text in parts if 'ago' in text.lower() or text.endswith('前')), '')
    badge = (
        get_in(
            item,
            'contentImage.thumbnailViewModel.overlays.0.thumbnailBottomOverlayViewModel.badges.0.thumbnailBadgeViewModel',
        )
        or {}
    )
    sources = get_in(item, 'contentImage.thumbnailViewModel.image.sources') or []
    return {
        '标题': runs_text(meta.get('title')),
        '正文': '',
        '作者': '',
        '视频ID': video_id,
        '链接': watch_url(video_id),
        '播放数': parse_count(views),
        '点赞数': 0,
        '发布时间': published,
        '时长': runs_text(badge.get('text')),
        '时长秒': duration_seconds(badge),
        '频道ID': '',
        '图片链接': str((sources[0] if sources else {}).get('url') or ''),
    }


def page_token(payload: dict) -> str:
    """The token that pages this list — see :func:`engine.innertube.grid_token`.

    Kept as a name here because the readers below are the ones that have to
    explain it: a search round and a channel tab mark their pager the same way,
    and anything else in the answer (a menu, a chip bar, the related-video rail)
    is a token that answers *something* — which is worse than one that answers
    nothing, because the crawl keeps walking and the table stops growing.
    """
    return innertube.grid_token(payload)


def search_items(payload: dict) -> list[dict]:
    """One keyword round's rows."""
    rows = [row_from_video_renderer(item) for item in collect(payload, 'videoRenderer')]
    return [row for row in rows if row.get('视频ID')]


def channel_items(payload: dict) -> list[dict]:
    """A channel tab's rows, in whatever shape the page happens to use.

    ``lockupViewModel`` is what the live site answers today; the other two names
    are read as a fallback because the same tab has carried all three across
    rollouts, and an empty answer would otherwise be reported as "this creator
    has no videos" — a claim about the channel, not about the parser.
    """
    lockups = [
        row for row in (row_from_lockup(item) for item in collect(payload, 'lockupViewModel')) if row.get('视频ID')
    ]
    if lockups:
        return lockups
    rows = [row_from_video_renderer(item) for item in collect(payload, 'videoRenderer')]
    rows += [row_from_video_renderer(item) for item in collect(payload, 'gridVideoRenderer')]
    return [row for row in rows if row.get('视频ID')]


def apply_player(row: dict, payload: dict) -> dict:
    """Merge one ``player`` answer into a row: exact figures over rounded ones.

    评论数 is left alone on purpose — the player answer does not carry it
    (measured: ``microformat`` holds like/view/publish/date/category), so a 0 in
    that column would read as "no comments" rather than "not asked".
    """
    details = payload.get('videoDetails') or {}
    micro = get_in(payload, 'microformat.playerMicroformatRenderer') or {}
    row['标题'] = row.get('标题') or runs_text(details.get('title')) or runs_text(micro.get('title'))
    row['作者'] = runs_text(details.get('author')) or runs_text(micro.get('ownerChannelName')) or row.get('作者', '')
    row['频道ID'] = str(details.get('channelId') or micro.get('externalChannelId') or row.get('频道ID') or '')
    row['正文'] = (
        runs_text(details.get('shortDescription')) or runs_text(micro.get('description')) or row.get('正文', '')
    )
    row['播放数'] = parse_count(details.get('viewCount')) or row.get('播放数', 0)
    row['点赞数'] = parse_count(micro.get('likeCount') or details.get('likeCount')) or row.get('点赞数', 0)
    published = str(micro.get('publishDate') or micro.get('uploadDate') or '')
    if published:
        row['发布时间'] = published.replace('T', ' ')[:16]
    seconds = parse_count(details.get('lengthSeconds'))
    if seconds:
        row['时长秒'] = seconds
        row['时长'] = row.get('时长') or clock(seconds)
    row['分类'] = runs_text(micro.get('category'))
    row['是否直播'] = '1' if details.get('isLiveContent') else '0'
    if row.get('频道ID'):
        row['频道链接'] = f'https://www.youtube.com/channel/{row["频道ID"]}'
    return row


class YouTubeCrawler(Crawler):
    """Keyword search, one creator's uploads, and a single video's facts.

    ``.google.com`` is deliberately not one of its cookie hosts even though the
    sign-in passes through it: those cookies open Gmail and Drive, and a YouTube
    cookie file must not become a copy of the whole Google account. The session
    YouTube actually sends lives on ``.youtube.com``, which is what the Cookie
    panel stores after pulling the browser back to its own page. The crawl itself
    needs no session at all — every measured round worked logged out.
    """

    domain = 'www.youtube.com'
    login_url = 'https://www.youtube.com/'
    supports_crawl = True
    #: ``ytcfg`` is on every page and this one is the cheapest to reach; nothing
    #: is scraped from it — it exists to give the JSON calls an origin.
    crawl_entry = 'https://www.youtube.com/'

    POLITE_BASE = 0.12
    POLITE_SPREAD = 0.08

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._api_key = ''
        self._context = None
        #: Every innertube round's duration, so "this crawl was slow" can be
        #: told apart from "this crawl was short" in the log.
        self.rounds_ms: list[int] = []

    # ─── transport ────────────────────────────────────────────────────────

    def _boot(self, url: str | None = None) -> bool:
        """Open a page and read the API key and context it ships with.

        Both are per-page and they rotate, so they are taken from the document
        rather than written into code: a baked-in key is a crawl that dies the
        week YouTube changes it.
        """
        self.open(url or self.crawl_entry)
        found = innertube.ready(self.driver)
        if not found:
            logger.warning(t('crawl.yt.noContext', url=self._current_url()))
            return False
        self._api_key, self._context = found
        return True

    def _call(self, endpoint: str, extra: dict) -> dict:
        """One innertube round trip; ``{}`` when nothing usable came back."""
        if not self._context:
            return {}
        payload = innertube.call(self.driver, endpoint, self._api_key, self._context, extra)
        if not payload:
            logger.warning(t('crawl.yt.callFailed', endpoint=endpoint))
            return {}
        self.rounds_ms.append(int(payload.get('_ms') or 0))
        if innertube.refused(payload):
            # Risk control answers with HTML where JSON was promised, so the shape
            # of the refusal separates a blocked session from a list that really
            # is empty.
            self.login_wall = True
            logger.warning(t('crawl.yt.wall', url=self._current_url()))
            return {}
        if payload.get('_status') != 200:
            logger.warning(t('crawl.yt.badAnswer', endpoint=endpoint, status=payload.get('_status')))
            return {}
        return payload

    def _polite(self):
        # A JSON round is not a page view, so the courtesy pause is a tenth of
        # what a DOM walk pays — most of why this crawl is fast.
        self._polite_pause(self.POLITE_BASE, self.POLITE_SPREAD)

    # ─── modes ────────────────────────────────────────────────────────────

    def search(self, keyword: str, target_count: int = 50, with_facts: bool = True, **kwargs) -> list[dict]:
        """Keyword search, one JSON round per ~10 videos.

        ``with_facts`` adds the per-video ``player`` call (measured 0.31 s) that
        turns a rounded card into exact figures — 点赞数 exists nowhere else, and
        播放数/发布时间 stop being "1 year ago" when it is on.
        """
        resume = self.resume_of(kwargs)
        if self.collected() >= target_count:
            logger.info(t('crawl.yt.targetReached', n=target_count))
            return self.results()
        if not self._boot():
            raise RuntimeError(t('crawl.yt.noContext', url=self._current_url()))
        logger.info(t('crawl.yt.searchStart', kw=keyword, n=target_count))
        token = str(resume.get('token') or '')
        seen: set[str] = self._collected_ids()
        repeats = 0
        round_no = 0
        while self.collected() < target_count:
            round_no += 1
            payload = self._call('search', {'continuation': token} if token else {'query': keyword})
            if not payload:
                break
            rows = search_items(payload)
            if not rows:
                logger.info(t('crawl.yt.noPage', page=round_no))
                break
            fresh = [row for row in rows if row['视频ID'] not in seen]
            logger.info(t('crawl.yt.page', page=round_no, n=len(rows), fresh=len(fresh), done=self.collected()))
            nxt = page_token(payload)
            # The cursor records the token to ask for *next*, so a resumed run
            # continues instead of re-paying for the page it already stored; the
            # ids travelled with it are what keep a half-written page honest.
            self._harvest(fresh, seen, target_count, {'keyword': keyword, 'token': nxt}, with_facts)
            token = nxt
            if not token:
                logger.info(t('crawl.yt.drained'))
                break
            if not fresh:
                repeats += 1
                if repeats >= 2:
                    # The cursor replayed the same page twice: the list is
                    # exhausted or shuffled onto itself, and more rounds would
                    # only spend calls on rows the ledger already has.
                    logger.info(t('crawl.yt.replay', page=round_no))
                    break
            else:
                repeats = 0
            self._polite()
            if self.collected() >= target_count:
                break
        if not self.collected():
            self._explain_zero(keyword)
        logger.info(t('crawl.yt.finished', n=self.collected()))
        return self.results()

    def author(self, author: str, target_count: int = 50, with_facts: bool = True, **kwargs) -> list[dict]:
        """One creator's uploads, newest first.

        The channel's own 视频 tab is the list — Shorts and premieres that live in
        other tabs are not silently mixed in, because a row's 播放数 means
        different things on those surfaces.
        """
        resume = self.resume_of(kwargs)
        if self.collected() >= target_count:
            logger.info(t('crawl.yt.targetReached', n=target_count))
            return self.results()
        channel_url = self.channel_videos_url(author)
        if not channel_url:
            raise RuntimeError(t('crawl.yt.authorEmpty', author=author))
        if not self._boot(channel_url):
            raise RuntimeError(t('crawl.yt.noContext', url=self._current_url()))
        meta = get_in(self._initial_data(), 'metadata.channelMetadataRenderer') or {}
        channel_id = str(meta.get('externalId') or '')
        if not channel_id:
            raise RuntimeError(t('crawl.yt.authorNotFound', author=author))
        name = runs_text(meta.get('title'))
        logger.info(t('crawl.yt.authorStart', author=author, n=target_count))
        seen: set[str] = self._collected_ids()
        # The tab the browser just loaded IS the first page: its 30 items are in
        # the document (measured), so asking ``browse`` for the tab again would
        # fetch a 3.7 MB channel HOME — worse than slow, because the home shelf
        # mixes other channels' videos into a list the user asked to be one
        # channel's, and the rows then disagree about who their 频道ID is.
        token = str(resume.get('token') or '')
        if token:
            # A resumed run re-opens the cursor it stopped on. The first page is a
            # document rather than a token, so re-reading it would re-pay for rows
            # the ledger already holds.
            payload = self._call('browse', {'continuation': token})
            rows = channel_items(payload)
            if not rows:
                raise RuntimeError(t('crawl.yt.authorNoVideos', author=author))
            token = page_token(payload)
        else:
            document = self._initial_data()
            rows = channel_items(document)
            if not rows:
                raise RuntimeError(t('crawl.yt.authorNoVideos', author=author))
            token = page_token(document)
        round_no = 0
        while self.collected() < target_count:
            round_no += 1
            fresh = [row for row in rows if row['视频ID'] not in seen]
            logger.info(t('crawl.yt.page', page=round_no, n=len(rows), fresh=len(fresh), done=self.collected()))
            for row in fresh:
                row['作者'] = row.get('作者') or name
                row['频道ID'] = row.get('频道ID') or channel_id
            self._harvest(fresh, seen, target_count, {'author': author, 'token': token}, with_facts)
            if not token or self.collected() >= target_count:
                break
            payload = self._call('browse', {'continuation': token})
            rows = channel_items(payload)
            if not rows:
                break
            token = page_token(payload)
            self._polite()
        logger.info(t('crawl.yt.finished', n=self.collected()))
        return self.results()

    def get_detail(self, url: str) -> dict | None:
        """One video's facts by link.

        None for a link that names no video *and* for an answer that carries no
        video: ``player`` replies 200 with an empty object for a private, deleted
        or region-blocked video, and handing back a row of empty strings would put
        a plausible-looking blank line into the user's table.
        """
        video = video_id_of(url)
        if not video:
            return None
        if not self._context and not self._boot():
            return None
        payload = self._call('player', {'videoId': video})
        if not payload.get('videoDetails') and not payload.get('microformat'):
            return None
        return apply_player({'视频ID': video, '链接': watch_url(video)}, payload)

    # ─── helpers ──────────────────────────────────────────────────────────

    def _collected_ids(self) -> set:
        """The video ids this crawl already holds, read off its own rows.

        A resumed run is seeded with everything the node stored, so the rows *are*
        the set of ids to skip. The cursor used to carry a copy of it, which meant
        re-serialising the whole collected list on every emitted row — a 3,000-video
        crawl rewrote 3,000 ids 3,000 times to tell the database what the database
        already had. The pager **token** stays in the cursor: that is the one piece
        of position no row can speak for.
        """
        return {str(row.get('视频ID')) for row in self.results() if row.get('视频ID')}

    def _harvest(self, rows, seen, target_count, position, with_facts):
        """Emit fresh rows, paying the extra round per row only if asked."""
        for row in rows:
            if self.collected() >= target_count:
                return
            seen.add(row['视频ID'])
            if with_facts:
                payload = self._call('player', {'videoId': row['视频ID']})
                if payload:
                    apply_player(row, payload)
                self._polite()
            if self.emit(row):
                logger.info(t('crawl.yt.processed', i=self.collected(), title=str(row.get('标题', ''))[:40]))
            self.mark_position(**position, done=self.collected())

    def _explain_zero(self, keyword: str):
        """Say why nothing came back, when the reason is not 'no results'."""
        if self.login_wall:
            raise RuntimeError(t('crawl.yt.wall', url=self._current_url()))
        logger.info(t('crawl.yt.noResults', kw=keyword))

    @staticmethod
    def channel_videos_url(author: str) -> str:
        """Normalise what the user typed into that channel's 视频 page.

        A pasted link, an ``@handle``, a bare ``UC…`` id and a plain name all mean
        the same thing to a person; the name is quoted because handles carry
        dots, dashes and the occasional space.
        """
        text = str(author or '').strip()
        if not text:
            return ''
        if 'youtube.com/' in text.lower():
            base = text.split('?')[0].rstrip('/')
            for marker, prefix in (('/channel/', 'channel/'), ('/@', '@'), ('/user/', '@'), ('/c/', '@')):
                _head, _sep, tail = base.partition(marker)
                token = tail.split('/')[0].lstrip('@')
                if token:
                    return f'https://www.youtube.com/{prefix}{quote(token, safe="")}/videos'
            return ''
        if text.startswith('UC'):
            return f'https://www.youtube.com/channel/{text}/videos'
        if text.startswith('@'):
            return f'https://www.youtube.com/@{quote(text[1:], safe="")}/videos'
        # A bare name is not an address: two channels can be called "NASA", so
        # this is treated as a handle rather than guessed at by searching.
        return f'https://www.youtube.com/@{quote(text, safe="")}/videos'

    def _initial_data(self) -> dict:
        try:
            return self.driver.execute_script('return window.ytInitialData || {};') or {}
        except Exception:
            return {}
