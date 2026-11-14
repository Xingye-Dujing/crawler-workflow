"""Source node: scrape a platform, one row at a time, with the platform lane held.

With a run context the crawler streams into the database instead of building a list in
memory: rows survive whatever kills the run, and items an earlier attempt already collected
are given back to it so it can stop scraping early rather than refilling them.

The lane splits per ACCOUNT (``gate._lane``): the measured wall is one SESSION searching
twice, so two logins of one platform are two lanes and may crawl at the same moment — which is
the whole reason accounts exist here. Holding it around the WHOLE node (rather than around each
request) keeps a retry inside the turn: a retry that released the queue first would collide
with the very workflow it had been waiting behind.
"""

import contextlib
import os
import time

import capabilities.registry as capabilities
from api.http import _safe_int
from core.refs import as_bool, comment_platforms, split_urls
from runtime import gate, paths, phases
from runtime.settings import get_setting
from runtime.state import _wf_local, add_log, ambient, execution_state, stop_requested

from crawlers import get_crawler, is_crawlable
from crawlers.backends.catbus import CatbusCrawler
from crawlers.core.crawler import UNDER_TARGET
from crawlers.core.faults import CrawlerStopped, PageNotArrivedError, SessionBlockedError
from i18n import t
from nodes.context import NodeCall
from nodes.executors.comment import execute_comment_node
from nodes.labels import node_label
from services import pool
from services.ingest import net as network_probe
from services.ingest.lifecycle import close_login_browser
from services.ingest.runtime import item_scope, name_parts, source_stream
from services.pool import selector as pool_selector
from services.runs.files import record_file
from services.runs.windows import note_window

NODE_TYPE = 'source'

#: The comment router's supported platforms, read as a sequence for the localized message.
_COMMENT_PLATFORMS = tuple(comment_platforms())


def is_collision(crawler, resume) -> bool:
    """Whether a refusal reads as "two of our own crawls met at the door".

    Three conditions, each removing a different false alarm: the platform really
    bounced us, nothing was collected (so there is no paid-for work to duplicate and
    no cursor to rewind), and the run still wants its rows (a Stop is not a pause —
    retrying after it would crawl on behind a run already declared over).
    """
    return bool(
        getattr(crawler, 'login_wall', False)
        and not crawler.collected()
        and not resume
        and execution_state['running']
        and float(get_setting('wall_retry_backoff')) > 0
    )


def _blocked_reason(crawler) -> str:
    """Which pool reason this session reported, or ``''``.

    One mapping for every raise point, so a wall met as an exception and the same wall met
    after the crawl returns are filed against the same subject.
    """
    if getattr(crawler, 'login_wall', False):
        return pool.health.LOGIN_WALL
    if getattr(crawler, 'risk_blocked', False):
        return pool.health.RISK
    return ''


def backoff_for_retry(crawler, platform: str) -> bool:
    """Say it once, wait out the back-off, and answer whether a retry is still wanted.

    The two flags the previous attempt set are cleared so the retry can report a wall
    of its own. The wait is slice-checked against 停止, not one long ``sleep``: this is
    the one place a stopped run could still be sitting when the user pressed Stop, and
    a sleep that ignores it both delays the run-record verdict by up to
    ``WALL_RETRY_BACKOFF`` and lets the caller open a second browser for a run already
    declared over. False means "the user stopped us — do not retry".
    """
    backoff = float(get_setting('wall_retry_backoff'))
    add_log(t('run.wallRetry', platform=platform, n=int(backoff)))
    cancel = execution_state.get('cancel_event')
    interrupted = False
    deadline = time.monotonic() + backoff
    while time.monotonic() < deadline:
        if not execution_state['running']:
            interrupted = True
            break
        if cancel is not None and cancel.wait(min(0.5, max(0.0, deadline - time.monotonic()))):
            interrupted = True
            break
    # The retry gets a clean slate whether or not the wait was cut short: the flags
    # describe the attempt that just failed.
    crawler.login_wall = False
    crawler.risk_blocked = False
    crawler.unreachable = False
    return not interrupted


def crawl_with_collision_retry(
    crawler, handler, crawl_args: dict, resume: dict, platform: str, allow_retry: bool = True
):
    """One trip to the platform, plus the second attempt a collision deserves.

    A wall met before the first row is the shape two same-platform workflows make of
    each other — measured: weibo answers the second session of one account with a
    passport redirect inside the same second. Backing off once and trying again is the
    difference between a red node and a green one.

    A wall met *after* rows were collected is the other event entirely: a cookie dying
    mid-crawl. That one must not be retried here — it settles the node partial, fails
    the run and hands the user the 继续 banner, which is the path that keeps the rows
    already paid for. The wait happens **inside** the platform's turn (see
    ``gate.hold`` in :func:`run`), or a retry would queue up behind the very
    workflow it is waiting for.
    """
    if not allow_retry:
        # Pool mode: the wall was just measured against THIS login, and the next step is a
        # different pair, not the same session after a sleep. Retrying here is exactly the
        # spend the pool exists to avoid.
        return handler(**crawl_args, resume=resume)
    try:
        rows = handler(**crawl_args, resume=resume)
    except BaseException:
        if not is_collision(crawler, resume):
            raise
        if not backoff_for_retry(crawler, platform):
            raise
        return handler(**crawl_args, resume=resume)
    if not rows and is_collision(crawler, resume) and backoff_for_retry(crawler, platform):
        rows = handler(**crawl_args, resume=resume)
    return rows


#: Which sentence each diagnosis answers. ``'slow'`` is deliberately the fall-through:
#: it is the one verdict that admits nothing was found, and a message that named a cause
#: here would be a guess wearing the authority of a probe.
_NET_ADVICE_KEYS = {
    'region': 'net.region',
    'offline': 'net.offline',
    'blocked': 'net.blocked',
    'slow': 'net.slow',
}


def _net_advice(platform: str) -> str:
    """What this machine can say about its own network, in the run's language.

    Asked only after a page went unmatched for the whole patience budget, which is what
    makes the cost defensible: two control hosts and one 2 s throughput sample, on the
    path where the run has already lost minutes. The controls are why this is worth
    asking at all — without a host that *should* answer for comparison, "switch network"
    is a guess, and the user is entitled to know which of the two it is.
    """
    diagnosis = network_probe.diagnose(capabilities.region_of(platform), platform)
    key = _NET_ADVICE_KEYS.get(str(diagnosis.get('verdict')), 'net.slow')
    speed = diagnosis.get('speed_kbps')
    return t(key) + (t('net.speed', speed=speed) if speed else '')


def page_not_arrived(platform: str, exc: PageNotArrivedError) -> ValueError:
    """Turn one crawler's observation into a line that says what to do next.

    The crawler's own sentence is about a page ("no cards after N seconds at this
    address"); this adds the only fact that sentence cannot carry, which is whether the
    machine running it can reach anything at all. The node label and the “执行失败” frame
    come from the executor, so nothing is said twice.

    No advice is appended when the page already explained itself — a login wall, a captcha
    or the browser's own ``net::ERR_…`` token are each a named cause, and a network probe
    on top of one of them would be a second opinion about something already measured.
    """
    advice = ''
    if exc.verdict in ('', 'ok', 'breaker'):
        with contextlib.suppress(Exception):
            # A probe that cannot run must not become the reason a crawl cannot report.
            advice = _net_advice(platform)
    streak = t('run.pageStreak', n=exc.gave_up) if exc.gave_up > 1 else ''
    if not (advice or streak):
        return ValueError(str(exc))
    return ValueError(t('run.pagePending', page=str(exc), streak=streak, advice=advice))


def feed_parent_rows(upstream: list) -> list | None:
    """The first parent that actually carries a data table, or None.

    ``name → source`` is the labelling pattern this canvas has always had, and a
    name node produces no rows — so "has any wire in" cannot mean "has a feed".
    The feed is the first parent whose result is a non-empty list of dict rows,
    whatever its position in the connection order.
    """
    for _pid, rows in upstream or ():
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            return rows
    return None


def column_to_links(rows: list, column: str) -> tuple[list[str], int]:
    """A column read row by row into a link list: (links, skipped-empty-cells).

    Blank/missing cells are counted, not guessed at; a cell holding several links
    is split exactly like the pasted textarea would be (one coercion, ``split_urls``).
    First-occurrence dedupe is what keeps the resume cursor honest: the comment
    engine stores ``url_index`` BY POSITION, so the list a resumed run rebuilds
    from the same parent rows must be identical — and a duplicated link would
    otherwise pay for the same article twice inside one node.
    """
    links: list[str] = []
    seen: set[str] = set()
    skipped = 0
    for row in rows:
        cells = split_urls(row.get(column))
        if not cells:
            skipped += 1
            continue
        for u in cells:
            if u not in seen:
                seen.add(u)
                links.append(u)
    return links, skipped


def execute_source_node(
    node: dict,
    headless: bool,
    ctx: dict = None,
    upstream: list = None,
    account_override: str = None,
    proxy: dict = None,
    pool_mode: bool = False,
):
    """Scrape a platform, one row at a time.

    With a run context the crawler streams into the database instead of
    building a list in memory: rows survive whatever kills the run, and the
    items an earlier attempt already collected are given back to it so it can
    stop scraping early rather than refilling them (and so the duplicates are
    dropped rather than handed downstream twice).
    """
    params = node.get('params', {})
    nid = str(node.get('id') or '')
    platform = node.get('platform', params.get('platform', ''))
    if not is_crawlable(platform) and not capabilities.can_crawl_platform(platform, params):
        # Cookie capture and crawling are different capabilities: bilibili and
        # douyin were added to the Cookie panel first, so a saved session exists
        # for a platform nothing can crawl. Refusing here by name beats the
        # alternative — an empty table that looks like an empty search.
        # A CatBus-only platform (快手/TikTok/京东/淘宝/闲鱼) has no Selenium crawler class but
        # is still crawlable through the second engine; the engine gate answers for it below.
        raise ValueError(t('run.notCrawlable', label=node_label(node, str(node.get('id') or '')), platform=platform))
    mode = capabilities.mode_of_node(node)
    # The mode is the whole decision that used to be a chain of platform tests:
    # 评论采集 routes to the shared comment engine, every other mode calls the
    # crawler method the matrix names with the arguments the matrix declares.
    # An unknown mode key reads as the platform's first mode (what the panel
    # shows), so a stale canvas cannot ask for a crawl nothing describes.
    if mode is None:
        raise ValueError(
            t('engine.source_unknown_platform', nid=node_label(node, str(node.get('id') or '')), platform=platform)
        )
    # A link-list mode fed from an upstream column: the column's values become the
    # field's list here, once, so the comment engine and wechat's article reader
    # crawl exactly the rows the user wired in without either knowing feeding exists.
    # The matrix decides feedability (Field.fed_by) — this executor holds no second
    # opinion about which modes take a feed, and validation already refused the
    # mismatched shapes (wired-without-column, column-without-wire, non-fed mode
    # with a table). Column wins over the pasted list: merging would make the
    # positional url_index cursor unrebuildable on resume, and an article present in
    # both lists would be paid for twice. Operating on copies never writes back —
    # the node's stored params are the user's textarea, not this run's input set.
    feed = capabilities.feed_of(mode)
    parent_rows = feed_parent_rows(upstream)
    if feed and parent_rows is not None:
        fed_field, col_key = feed[0]
        column = str(params.get(col_key) or '').strip()
        if column:
            if column not in {str(c) for c in parent_rows[0]}:
                # Fail BY NAME at the row source, like validate_step does for a
                # process column: an empty table here would read as "the feed found
                # nothing", not as "the user's column name is wrong".
                raise ValueError(
                    t('source.feed_column_missing', nid=node_label(node, str(node.get('id') or '')), col=column)
                )
            fed, skipped = column_to_links(parent_rows, column)
            if skipped:
                add_log(t('source.feed_skipped', n=skipped))
            if not fed:
                raise ValueError(t('comment.no_urls', platforms=_COMMENT_PLATFORMS))
            params = dict(params)
            params[fed_field.key] = fed
            node = dict(node, params=params)
    if mode.handler == 'comments':
        # Same engine as the standalone Comment node — which stays valid for the
        # canvases that used to own it.
        return execute_comment_node(dict(node, type='comment'), headless=headless, ctx=ctx)
    crawl_args = capabilities.crawl_kwargs(mode, params)
    # The account is the executor's own field (like recrawl it stays out of crawl_args):
    # it chooses WHICH session and WHICH browser device the crawl runs as — two accounts
    # of one platform are two devices, so two nodes can crawl in real parallel instead
    # of queueing behind one rate limit. Blank is the historical default account.
    account = str(account_override if account_override is not None else params.get('account') or '').strip()
    # A mode without a row budget (WeChat's article list) promised no number, so
    # nothing can be missing from it: the cookie-wall check below reads zero as
    # "this crawl ended where it was meant to" instead of inventing a target.
    target_count = crawl_args.get('target_count') or 0

    # No source node forces a visible window any more. Douyin and X used to (a headless browser
    # got a captcha/403), but a headless Chrome now reports a desktop fingerprint instead
    # (base.py, #148) — measured serving real rows on both, and on zhihu's author page — so the
    # run's own 无头/窗口 choice is honoured as asked. The comment engine makes the same choice
    # verbatim now too: a headless Chrome even opens a scroll-only panel (see the comment plugin).

    watermark_scope = ''
    watermark_found = None
    if as_bool(params.get('watermark')):
        if mode is None or platform != 'bilibili' or mode.handler != 'author':
            raise ValueError(t('run.watermarkUnsupported', platform=platform, mode=getattr(mode, 'key', '')))
        if as_bool(params.get('recrawl')):
            raise ValueError(t('engine.watermarkRecrawl', nid=node_label(node, nid)))
        fingerprint = str(((ctx or {}).get('fingerprints') or {}).get(nid) or '')
        if not fingerprint or not (ctx or {}).get('store'):
            raise ValueError(t('run.watermarkNoScope'))
        watermark_scope = 'wm:' + fingerprint
        watermark_found = ctx['store'].get_watermark(watermark_scope)

    if capabilities.is_catbus(params):
        # Chosen here rather than inside ``get_crawler``, whose arguments are all about a device —
        # a profile directory, a cookie file, a headless window — and none of which means anything
        # to a backend that runs as a child process with its own account files. An unsupported
        # 平台 × 模式 is refused by that backend, with the manifest's own reason.
        crawler = CatbusCrawler(platform=platform, params=params, account=account, abort=stop_requested)
    else:
        build = {
            'headless': headless,
            'cookie_dir': paths.active().cookie_dir,
            'use_profile': (ctx or {}).get('use_profile'),
            # `stop_requested`, not "no run is in flight": this predicate is what makes the
            # crawl end at its next row, and an idle server (a test calling the executor
            # directly) is not a user who pressed 停止.
            'abort': stop_requested,
            'account': account,
        }
        # Omitted entirely when there is no exit, so a test double's older signature still
        # works: an argument nobody uses is not worth breaking an interface over.
        if proxy:
            build['proxy'] = proxy
        crawler = get_crawler(platform, **build)
    # Registered and guarded from here on: everything between buying a browser
    # and using it can still fail — a read-only or missing export directory, a
    # locked runs.db, a cursor that will not parse — and a Chrome that Stop does
    # not know about is a process left on the user's machine forever.
    execution_state['active_crawlers'].add(crawler)

    def _proved_rows() -> int:
        """How many rows this node has on disk right now.

        The question a pool asks before switching login is "did THIS attempt pay for
        anything?", and the durable row count is the only answer that survives an exception
        raised from deep inside a platform walk. A node with no run context has no ledger, so
        it reports zero — it also has nothing to resume, which is what makes rotation there
        harmless.
        """
        if ctx is None:
            return 0
        with contextlib.suppress(Exception):
            return int(ctx['store'].row_count(ctx['run_id'], nid))
        return 0

    stored_before = _proved_rows()
    resume = {}
    seed_count = 0
    if watermark_scope:
        if watermark_found and watermark_found.get('last_key'):
            crawler.set_watermark(watermark_found['last_key'])
            add_log(t('run.watermarkLoaded', boundary=watermark_found['last_key']))
        else:
            add_log(t('run.watermarkFirst'))

    def _merge_parts(partial_rows) -> None:
        """Close the 分批输出 writer and announce the merged file — exactly once.

        Named here rather than inlined below because the crawl can also END BY
        RAISING, and a crawl that refuses to carry on when it hits the wall owed the
        user the same two facts a crawl that returns under-target gives: the file its
        parts merged into, and the cookie diagnosis. Neither line existed for
        zhihu — the platform most likely to bounce us — because both sat after the
        call that raised.
        """
        if writer is None:
            return
        if ctx is None and partial_rows:
            # One-shot path without a run context: nothing flowed through the
            # tee'd sink, so hand the rows to the writer directly.
            writer.add(partial_rows)
        info = writer.finish()
        record_file(ctx, nid, info['path'], 'merged')
        add_log(
            t(
                'run.progress_file',
                file=os.path.basename(str(info['path'])),
                rows=info['rows'],
                parts=info['parts'],
            )
        )

    try:
        # ── progressive part files (分批输出) ──
        # With part_size>0 every kept row also lands in a numbered part file while
        # the crawl is still running, and the parts merge into one file at the end
        # — the results are openable before the node finishes.
        part_size = _safe_int(params.get('part_size'), 0, minimum=0)
        keep_parts = as_bool(params.get('keep_parts'))
        pfmt = 'json' if str(params.get('format') or 'csv') == 'json' else 'csv'
        # A crawl “按时间” writes a table for a stated stretch of the calendar, and on
        # disk that fact used to exist nowhere but the node's own form: the file for
        # January and the file for March were both “微博-src-node-2.csv”, so the second
        # one silently replaced the first and nobody could tell afterwards which month
        # they were reading. The window goes into the name of the parts AND of the file
        # they merge into, because those two are the same stem.
        note_window(getattr(_wf_local, 'idx', None), params.get('start_time'), params.get('end_time'))
        parts = name_parts(params, (ctx or {}).get('export_stamp') or '')
        writer = None
        if part_size > 0:
            from services.ingest.parts import PartWriter, safe_stem

            stem = safe_stem(f'{ambient().get("workflow_name") or platform}-src-{nid}{parts}')
            # Record each shard as it lands (so an interrupted run's parts are still attributed
            # to the record) — but only when “保留分片” is on: with keep_parts off the writer
            # deletes them the moment the merge succeeds, so there is nothing for 智能清除 to find.
            writer = PartWriter(
                paths.active().export_dir,
                stem,
                pfmt,
                part_size,
                keep_parts,
                on_write=(lambda path, kind: record_file(ctx, nid, path, kind)) if keep_parts else None,
            )
        if ctx is not None:
            scope = item_scope(ctx, node)
            if as_bool(params.get('recrawl')) and not ctx.get('resume'):
                # 重新采集 (node setting): release this node's 'already collected'
                # ledger so the same items are collected again — the incremental
                # default would skip every one of them. Never on a resumed run:
                # there the ledger is precisely its dedupe machinery.
                add_log(t('run.recrawl', n=ctx['store'].forget_items(scope)))
            row_sink, cursor_sink = source_stream(ctx, nid, scope, node_label(node, nid))
            if writer is not None:
                base_sink = row_sink

                def tee_sink(item, _base=base_sink, _w=writer):
                    kept = _base(item)
                    if kept:
                        _w.add([item])
                    return kept

                row_sink = tee_sink

            crawler.set_sink(row_sink)
            crawler.set_cursor_sink(cursor_sink)
            if ctx.get('resume'):
                resume = ctx['store'].get_cursor(ctx['run_id'], nid) or {}
            # Rows saved by an earlier attempt, handed back so `collected()` starts
            # honest: targeting 200 with 180 already saved asks the page for 20.
            saved = ctx['store'].load_rows(ctx['run_id'], nid)
            if saved:
                seed_count = len(saved)
                crawler.seed(saved)
                add_log(t('run.resume_crawl', nid=node_label(node, nid), have=len(saved)))
                if writer is not None and not writer.has_parts:
                    # Rows paid for before batching was switched on (or before any
                    # part survived): the merged file should hold the whole table,
                    # not only what comes after the switch.
                    writer.add(saved)
        # The matrix decided what this crawl is called with; `resume` is the one
        # argument that is not the user's — it is where this run stopped, handed
        # over from the store.
        allow_retry = not (pool_mode and bool(get_setting('pool_skip_wall_backoff')))
        _crawl_started = time.monotonic()
        rows = []
        try:
            rows = crawl_with_collision_retry(
                crawler, getattr(crawler, mode.handler), crawl_args, resume, platform, allow_retry=allow_retry
            )
        finally:
            # The search/list phase in the Console's phase log: a slow account spends most
            # of its time here, and “the window sat on the feed” needs this number beside it.
            phases.record(
                'crawl',
                time.monotonic() - _crawl_started,
                label=platform,
                platform=platform,
                mode=str(getattr(mode, 'handler', '')),
                rows=len(rows),
                wall=bool(getattr(crawler, 'login_wall', False)),
                risk=bool(getattr(crawler, 'risk_blocked', False)),
            )
        if stop_requested():
            # A walk that honours 停止 does not raise: it breaks at its next row and hands
            # back what it collected. So a crawl that finished by *returning* after the
            # button was pressed would settle DONE — the run record saying 运行完成 over a
            # half-collected table, and the 继续 banner never appearing, which is the one
            # outcome a stop must never produce. The rows stand; the node is reported as
            # what it was.
            raise CrawlerStopped(t('crawl.stopped'))
    except PageNotArrivedError as exc:
        # A wall/risk page that arrived as "the page never came" is still evidence about the
        # session. In pool mode with nothing paid for, it is the cleanest rotation point there
        # is: no rows, no cursor, nothing a second login would have to inherit.
        blocked = _blocked_reason(crawler)
        if blocked and pool_mode and _proved_rows() <= stored_before:
            with contextlib.suppress(Exception):
                _merge_parts(None)
            raise SessionBlockedError(str(exc), reason=blocked, platform=platform, account=account) from exc
        # The patience budget ran out with nothing on the page. What the crawler saw is
        # turned into a line that also says what this machine can reach, then the node
        # settles the way any refusal settles: the rows already streamed stay (which is
        # what makes it ``partial`` with a 继续 rather than an empty failure), and the
        # run is failed so the banner appears. Deliberately *not* routed through
        # ``cookie_expired``: an unreachable page says nothing about the session, and
        # sending the user to re-save a cookie they just saved is how this project has
        # burned a user's trust in its messages before.
        if getattr(crawler, 'login_wall', False):
            execution_state['cookie_expired'] = True
        elif getattr(crawler, 'risk_blocked', False):
            # A 验证码/风控 that mounted mid-wait is an *answer*, not a slow page: name it
            # as 风控 so the user backs off instead of retrying into the wall.
            with contextlib.suppress(Exception):
                _merge_parts(None)
            raise ValueError(t('run.riskControlled', platform=platform)) from exc
        with contextlib.suppress(Exception):
            _merge_parts(None)
        raise page_not_arrived(platform, exc) from exc
    except BaseException as exc:
        # The crawler gave up (a wall it refuses to walk into, a risk page, a dead
        # session). Publish what that answer means BEFORE the failure travels on:
        # the toast flag, and the merged partial file the row sink already filled.
        # Suppress the bookkeeping's own errors — they must not replace the real one.
        # A SessionBlockedError is different: it says "this attempt is over, the next login may
        # still work", so raising the global cookie toast here would be an alarm about a run
        # that has not failed yet.
        if not isinstance(exc, SessionBlockedError) and getattr(crawler, 'login_wall', False):
            execution_state['cookie_expired'] = True
        with contextlib.suppress(Exception):
            _merge_parts(None)
        raise
    finally:
        close_login_browser(crawler)  # bounded quit + PID-targeted reap, never a global taskkill
        execution_state['active_crawlers'].discard(crawler)
    if ctx is not None:
        skipped = (ctx.get('skipped_seen') or {}).get(nid)
        if skipped:
            # Incremental dedupe made visible: a re-run that already knows
            # every item would otherwise end as '0 results' with no reason.
            add_log(t('run.dedupe_skipped', n=skipped))
            if not rows:
                # …and when EVERY item was skipped, say what happens next —
                # downstream sees an empty table, which reads as a failure
                # unless the console named the two ways out.
                add_log(t('run.dedupe_all_skipped'))
    wall = bool(getattr(crawler, 'login_wall', False))
    _merge_parts(rows)
    if wall:
        if len(rows) < target_count:
            if pool_mode and _proved_rows() <= stored_before:
                # Nothing was paid for by this attempt, so a different login may take the
                # whole walk from the top with nothing to reconcile.
                raise SessionBlockedError(
                    t('run.cookieExpired', platform=platform),
                    reason=pool.health.LOGIN_WALL,
                    platform=platform,
                    account=account,
                )
            # A long crawl can outlive its cookie: the platform bounces the
            # browser to a login page mid-run. The rows collected before the
            # wall are safe in the store — surface the flag for the toast and
            # say so in the console.
            execution_state['cookie_expired'] = True
            # Under-target is not a finished crawl, so the node must not look
            # like one. Failing it keeps every stored row, marks the RUN failed
            # (the resume banner's trigger), and lets 继续 resume pick the crawl
            # up at the cursor the wall stopped on — refresh the cookie, click
            # continue, get the rest. Marking it done would hide the gap.
            #
            # The message is raised, not also logged here: the executor prints
            # every failure as '节点 X 执行失败：…', which names the node. Both
            # calls made the same sentence appear twice, once without the node.
            raise ValueError(t('run.cookieExpired', platform=platform))
        # Wall met exactly as the target was reached: the session died at the finish
        # line, so there is nothing missing — do not raise a false alarm.
        add_log(t('run.cookieExpiredOk', platform=platform))
    # A 风控 bounce that left the crawl short is named here — the sibling of U1, and the
    # opposite advice. A login wall says "re-save the cookie"; risk control says the session
    # may be perfectly fine and the ONLY safe move is to back off, so the node FAILS (keeps
    # every row, run marked failed so 继续 appears) with a line that forbids an immediate
    # re-run. Before U1, because a risk short must report 风控, never 采得不足. (A login wall
    # already raised in the block above, so reaching here short with ``wall`` set is impossible —
    # the two refusals are mutually exclusive by control flow, not by an added guard.)
    if target_count and len(rows) < target_count and getattr(crawler, 'risk_blocked', False):
        if pool_mode and _proved_rows() <= stored_before:
            raise SessionBlockedError(
                t('run.riskControlled', platform=platform),
                reason=pool.health.RISK,
                platform=platform,
                account=account,
            )
        raise ValueError(t('run.riskControlled', platform=platform))
    # U1: a non-wall, non-risk, non-stopped crawl that came back under its target WITHOUT a
    # site-attested end must not settle clean DONE — that is §6's silent-under-collect, which
    # until now only the test tier's ``classify_verdict`` convicted, never the run itself.
    # ``end_reason`` is ``None`` for a not-yet-migrated handler (stays today's behaviour, no
    # regression while platforms migrate one at a time); a ``LICENSED_ENDS`` word means the SITE
    # said this is all (settles clean); ``UNDER_TARGET`` — and ONLY that — is the convicted
    # short. A loop self-summary cannot reach here as a license: ``Crawler.note_end`` refuses it.
    # A risk bounce is settled by the branch just above (named 风控, back off), so this gate
    # skips when ``risk_blocked`` is set — the two refusals never collide.
    if (
        target_count
        and len(rows) < target_count
        and getattr(crawler, 'end_reason', None) == UNDER_TARGET
        and not getattr(crawler, 'risk_blocked', False)
    ):
        counts = getattr(crawler, 'walk_counts', {}) or {}
        # Attribute the gap only when the funnel is fully measured; a partial one is omitted
        # rather than printed with invented zeros or a raw unfilled {slot}.
        walk = (
            t('run.underTargetWalk', scanned=counts['scanned'], kept=counts['kept'], refused=counts['refused'])
            if {'scanned', 'kept', 'refused'} <= set(counts)
            else ''
        )
        raise ValueError(t('run.underTargetShort', platform=platform, have=len(rows), want=target_count, walk=walk))
    failures = int(getattr(crawler, 'sink_failures', 0) or 0)
    if failures:
        # The crawl itself survived (one poisoned row must not lose the rest), but the table
        # is short by exactly this many rows and the user has to hear it from the node, not
        # from a diff against the site tomorrow.
        add_log(t('run.sinkFailures', n=failures, have=len(rows)))
    if watermark_scope:
        candidate = str(getattr(crawler, '_watermark_candidate', '') or '')
        if candidate and not failures:
            # The column the boundary belongs to is the crawl's own answer: 哔哩哔哩's browser walk
            # keys on BV号, while the second backend keys on whichever column its manifest declares
            # as that cell's identity. Stored as data next to the value, so a boundary is never
            # compared against a column that holds something else.
            column = str(getattr(crawler, 'watermark_column', '') or '') or 'BV号'
            ctx['store'].save_watermark(watermark_scope, platform, column, candidate, ctx['run_id'])
            add_log(t('run.watermarkSaved', boundary=candidate, n=max(0, int(crawler.collected()) - seed_count)))
        elif candidate:
            # A boundary recorded from a run whose sink dropped rows would make the next
            # incremental run stop BEFORE the gap: the missing rows could never come back.
            # Keeping the previous boundary costs a re-scan and loses nothing.
            add_log(t('run.watermarkWithheld', n=failures))
        elif getattr(crawler, 'watermark', ''):
            add_log(t('run.watermarkNoNew', boundary=crawler.watermark))
    return rows


def run(node: dict, call: NodeCall):
    platform = node.get('platform') or (node.get('params') or {}).get('platform', '')
    account = str((node.get('params') or {}).get('account') or '').strip()
    # ``upstream`` reaches the source node itself: a link-list mode fed by an upstream column reads
    # the parent table here. Dropping it made the wire a lie — the canvas showed a feed and the
    # crawl ran the pasted list nobody asked for.
    # ``stop_requested()``, never ``not running``: its own docstring spells out why — a caller that
    # reaches this function without a claim in place has no run to be "not running", and inferring
    # “the user pressed 停止” from that abandoned the queue for every such call instead of holding
    # the lane.
    if not pool_selector.is_pool_value(account):
        with gate.hold(platform, log=add_log, abort=stop_requested, account=account):
            return execute_source_node(node, call.headless, ctx=call.ctx, upstream=call.upstream)
    if capabilities.is_catbus(node.get('params') or {}):
        # ``@pool`` claims a Selenium login and its exit; a CatBus walk runs as a child process
        # with its own account files and reads neither. Without this refusal the node claimed a
        # login (or told the user to save a cookie the run never opens), bound an exit and
        # wrote health rows, then ignored the name. The comment executor has the same guard.
        raise ValueError(t('pool.catbusUnsupported', platform=platform))
    # Pool mode. The gate is taken PER ATTEMPT with the account that attempt actually uses:
    # its lane is per login, so holding the sentinel's lane would serialize every pool crawl
    # of a platform into one queue and throw away the parallelism accounts exist for.
    mode = capabilities.mode_of_node(node)
    if mode is not None and mode.handler == 'comments':
        # The comment engine rotates per LINK and holds its own lane around each walk; a
        # node-level turn here would hold a second, fake lane for the whole batch.
        return execute_source_node(node, call.headless, ctx=call.ctx, upstream=call.upstream)
    tried: list[dict] = []
    run_id = str((call.ctx or {}).get('run_id') or '')
    node_id = str(node.get('id') or '')
    for attempt in range(pool.max_attempts()):
        candidate = pool.claim(platform, exclude_accounts=[item['account'] for item in tried])
        if candidate is None:
            break
        entry = {'account': candidate.account, 'reason': '', 'until_local': '', 'exit_id': candidate.exit_id}
        tried.append(entry)
        exit_note = f' ({candidate.label()})' if candidate.label() else ''
        add_log(
            t(
                'pool.attempt',
                platform=platform,
                n=attempt + 1,
                account=pool.account_word(candidate.account),
                exit=exit_note,
            )
        )
        try:
            with gate.hold(platform, log=add_log, abort=stop_requested, account=candidate.account):
                rows = execute_source_node(
                    node,
                    call.headless,
                    ctx=call.ctx,
                    upstream=call.upstream,
                    account_override=candidate.account,
                    proxy=candidate.proxy,
                    pool_mode=True,
                )
            # A finished attempt is a measurement too: it clears a strike counter that an old
            # wall left behind (so escalation cannot climb on stale evidence) and leaves the
            # row count next to the pair that produced it in the audit trail. ``assume_ok`` is
            # explicit: an attempt that RETURNED is a page this browser read, unlike a probe
            # that reported no facts at all.
            with contextlib.suppress(Exception):
                pool.observe(
                    platform,
                    candidate.account,
                    {},
                    exit_id=candidate.exit_id,
                    rows=len(rows) if isinstance(rows, list) else 0,
                    run_id=run_id,
                    node_id=node_id,
                    assume_ok=True,
                )
            return rows
        except SessionBlockedError as exc:
            verdict = pool.observe(
                platform,
                candidate.account,
                {
                    'login_wall': exc.reason == pool.health.LOGIN_WALL,
                    'risk_blocked': exc.reason == pool.health.RISK,
                },
                exit_id=candidate.exit_id,
                run_id=run_id,
                node_id=node_id,
            )
            entry['reason'] = verdict['reason']
            entry['until_local'] = verdict['until_local']
            add_log(
                t(
                    'pool.rotating',
                    platform=platform,
                    account=pool.account_word(candidate.account),
                    reason=pool.reason_word(verdict['reason']),
                    next=t('pool.nextAttempt'),
                )
            )
            continue
        finally:
            pool.release(candidate)
    if not tried:
        # Nothing was even attempted. The two reasons want two different actions, so they
        # are never folded into one sentence.
        snapshot = pool.snapshot(platform)
        key = 'engine.source_pool_empty' if not snapshot['total'] else 'engine.source_pool_cooling'
        raise ValueError(t(key, nid=node_label(node, node_id), platform=platform))
    raise ValueError(pool.exhaustion_message(platform, tried))
