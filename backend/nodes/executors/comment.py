"""Comment node: article links (or 红果 titles) in, comment rows out, batch by batch.

Built on the same durable legs as the source crawler — the row ledger (already-collected
comments are skipped, never re-fetched), the row store (resume restores position), and
PartWriter (every settled batch hits disk as a readable file while the run is still going).
The cursor records only the leading inputs the node PROVED complete: a walled or short walk
pins it, so 继续 re-walks from the first hole instead of laundering it.

The run's 无头/窗口 choice is honoured verbatim for every link platform: a headless Chrome
carries a desktop fingerprint, and even scroll-only panels were measured serving the same
rows headless, so no comment panel forces a window.
"""

import contextlib

import capabilities.registry as capabilities
import pandas as pd
from api.http import _safe_int
from core.config import Config
from core.refs import as_bool, comment_platforms, platform_for, split_urls
from state import add_log, execution_state, stop_requested

from crawlers import crawler_class, get_crawler
from crawlers.backends.catbus import CatbusCrawler
from crawlers.core.crawler import UNDER_TARGET
from crawlers.core.faults import CrawlerStopped
from i18n import t
from nodes.context import NodeCall
from nodes.labels import node_label
from services import catbus_bridge
from services.crawl_runtime import item_scope, name_parts, source_stream
from services.crawler_lifecycle import close_login_browser
from services.run_files import record_file

NODE_TYPE = 'comment'

#: The comment router's supported platforms, as raw keys. They go into a ``{platforms}`` slot
#: that localizes *and joins* them, so they must arrive as a sequence — a value pre-joined with
#: '/' reached the console verbatim because the localizer only splits on ',', '、'.
_COMMENT_PLATFORMS = tuple(comment_platforms())


def filter_comments_by_time(rows: list, params: dict, label: str) -> list:
    """Drop comments whose 评论时间 falls outside an optional [start, end] range.

    This is a TABLE-side filter of comments already crawled, deliberately separate from a
    crawl node's start_time/end_time (which decides how far back to CRAWL). The keys are
    comment_start/comment_end so the two meanings never share a name. A range chooses which
    data is kept, so a half range, an unparseable date or an inverted window is refused BY
    NAME rather than guessed (the same discipline the crawl window uses), and a comment whose
    time cell is blank or unrecognised is dropped and counted — never assigned a year, never
    kept as though it matched. Comparison is by calendar day (normalised), inclusive at both
    ends, matching bin_time.
    """
    start = str(params.get('comment_start') or '').strip()
    end = str(params.get('comment_end') or '').strip()
    if not start and not end:
        return rows
    if not start or not end:
        raise ValueError(t('comment.need_both', nid=label))
    lo = pd.to_datetime(start, errors='coerce')
    hi = pd.to_datetime(end, errors='coerce')
    if pd.isna(lo) or pd.isna(hi):
        raise ValueError(t('comment.bad_date', nid=label))
    if hi < lo:
        raise ValueError(t('comment.bad_range', nid=label))
    if not rows:
        return rows
    from services.data_analysis import _to_datetime

    times = _to_datetime(pd.Series([r.get('评论时间') for r in rows], dtype='object'))
    lo_day, hi_day = lo.normalize(), hi.normalize()
    out, unparsed = [], 0
    for row, valid, day in zip(rows, times.notna(), times.dt.normalize(), strict=True):
        if not valid:
            unparsed += 1  # a blank/unparseable 评论时间 is not a date; it cannot be shown to match
            continue
        if lo_day <= day <= hi_day:
            out.append(row)
    add_log(
        t(
            'comment.time_filtered',
            nid=label,
            start=start,
            end=end,
            kept=len(out),
            dropped=len(rows) - len(out),
        )
    )
    return out


def execute_comment_node(node: dict, headless: bool = True, ctx: dict = None):
    """Comment crawler: article links in, comment rows out, batch by batch.

    Built on the same durable legs as the source crawler — the row ledger
    (already-collected comments are skipped, never re-fetched), the row store
    (resume restores position), and PartWriter (every settled batch hits disk
    as a readable file while the run is still going; a resumed writer adopts
    the parts the crashed run left behind, so kept-elsewhere rows are exactly
    the rows already in those files). The window is the run's own 无头/窗口 choice,
    honoured verbatim for every link platform: a headless Chrome carries a desktop
    fingerprint (#148) and even scroll-only panels were measured serving the same
    rows headless (zhihu comments 5/5, 2026-09-26), so no comment panel forces a
    window or rewrites the record.
    """
    from crawlers.commenting.protocol import BLOCKED, DEAD, OK
    from crawlers.commenting.session import CommentSession
    from services.part_writer import PartWriter, safe_stem

    params = node.get('params') or {}
    # A Data Source in comments mode carries the platform the user selected;
    # links from another site must not silently crawl a platform nobody chose.
    # The standalone Comment node has no platform param, so it stays mixed-input.
    # Read the same two places the source executor reads (a hand-written or fed file can
    # hold it at either), because the answer decides which input lines are name-feeding.
    want = str(params.get('platform') or node.get('platform') or '').strip().lower()
    # Which saved login (and device) walks these comments; blank is the historical
    # default account. The comment wall is a per-ACCOUNT rate limit — the reason
    # multi-account exists — so this must reach every get_crawler call below.
    account = str(params.get('account') or '').strip()
    # Does this platform's own comment form take plain names as well as links? Asked of the
    # matrix, because the router below sorts its input by DOMAIN and would otherwise drop a
    # 红果 剧名 as an unsupported link — 红果 crawls inside the client, where a title is
    # exactly what the client's own boards answer to.
    accepts_names = capabilities.names_also_accepted(capabilities.mode_for(want, 'comments')) if want else False
    all_urls = split_urls(params.get('urls'))
    urls, dropped, mismatched = [], [], []
    for u in all_urls:
        plat = platform_for(u)
        if not plat and accepts_names and not capabilities.is_url_cell(u):
            urls.append(u)
        elif not plat:
            dropped.append(u)
        elif want and plat != want:
            mismatched.append(u)
        else:
            urls.append(u)
    if dropped:
        add_log(t('comment.unsupported', n=len(dropped), platforms=_COMMENT_PLATFORMS))
        if not want:
            # Which mode takes plain names is a per-platform fact, so a mixed-input comment
            # node cannot route a 剧名 at all. Said as the reason it was refused, not filed
            # under a count of 「unsupported links」 the user then hunts through real links.
            named = [u for u in dropped if not capabilities.is_url_cell(u)]
            if named:
                add_log(t('comment.unsupportedNames', n=len(named)))
    if mismatched:
        add_log(t('comment.platformMismatch', n=len(mismatched), platform=want))
    if not urls:
        if mismatched:
            raise ValueError(t('comment.allMismatched', platform=want))
        raise ValueError(t('comment.no_urls', platforms=_COMMENT_PLATFORMS))

    limit = _safe_int(params.get('comment_limit'), 0, minimum=0)  # 0 = every comment
    part_size = _safe_int(params.get('part_size'), 0, minimum=0)  # 0 = single final file only
    per_article = as_bool(params.get('per_article_file'))
    keep_parts = as_bool(params.get('keep_parts'), True)
    fmt = 'json' if str(params.get('format') or 'csv') == 'json' else 'csv'
    nid = str(node.get('id') or '')
    # The same two filename components a crawl node writes: a comment table collected for
    # a stated stretch carries the same ambiguity, and a second pass over the same links
    # the same overwrite. A comments mode declares no window today, so only the record
    # stamp ever lands here.
    parts = name_parts(params, (ctx or {}).get('export_stamp') or '')
    stem_base = safe_stem(f'{execution_state.get("workflow_name") or "comments"}-{nid}{parts}')

    row_sink = cursor_sink = None
    resumed_index = 0
    if ctx is not None:
        if as_bool(params.get('recrawl')) and not ctx.get('resume'):
            # 重新采集 means the same thing here as in a source crawl: the ledger that
            # says "this comment is already stored" is released, so the comments are
            # fetched again. Never on a resumed run — there that ledger *is* the resume
            # machinery, and clearing it would re-buy every comment already paid for.
            add_log(t('run.recrawl', n=ctx['store'].forget_items(item_scope(ctx, node))))
        row_sink, cursor_sink = source_stream(ctx, nid, item_scope(ctx, node), node_label(node, nid))
        if ctx.get('resume'):
            from crawlers.core.crawler import as_index

            resumed_index = as_index((ctx['store'].get_cursor(ctx['run_id'], nid) or {}).get('url_index'))

    writers = {}
    rows_out = []
    if ctx is not None and ctx.get('resume'):
        # A re-run of this node pays for the missing articles only — but the
        # table it hands downstream must be the WHOLE comment set, so the rows
        # an earlier attempt stored come back into the result list up front.
        # (The ledger refuses them as duplicates, so nothing double-stores.)
        rows_out = list(ctx['store'].load_rows(ctx['run_id'], nid))
    counts = {OK: 0, BLOCKED: 0, DEAD: 0}
    # Inputs the node did NOT prove complete, in order. This is what decides whether the
    # cursor may advance (see the write below), and it is the reason the tail refusals can
    # promise 「继续」: a cursor written *before* the walk rested at ``len(urls)-1`` after a
    # full pass, so resuming a node that skipped four dramas re-walked the LAST drama only,
    # a fresh harness reported no skips at all, and the node settled DONE over the hole.
    unproven: list[int] = []
    # Which platforms actually answered with a login page, in the order they did.
    blocked_by: list[str] = []
    # Blocked platforms whose owning crawler named 风控 (back off) rather than a dead cookie
    # (re-save); kept per-platform because the two refusals carry opposite advice and a mixed
    # batch must not mislabel the cookie-only ones. ``login_seen`` marks that SOME blocked
    # platform named a login wall — that always defers to the actionable cookie verdict.
    risk_by: list[str] = []
    login_seen = False
    sessions = {}

    def _writer_for(idx: int) -> PartWriter:
        stem = f'{stem_base}-{idx:02d}' if per_article else stem_base
        if stem not in writers:
            # Same ledger contract as a source crawl: shards are recorded as they land, and only
            # when 「保留分片」 is on (with it off the merge deletes them, so there is nothing to clear).
            writers[stem] = PartWriter(
                Config.EXPORT_DIR,
                stem,
                fmt,
                part_size,
                keep_parts,
                on_write=(lambda path, kind: record_file(ctx, nid, path, kind)) if keep_parts else None,
            )
        return writers[stem]

    def _publish_parts() -> list:
        """Finish every writer into its merged file and record it in the run→files ledger.

        Called once on the success path (a real merge error then fails the node like any other),
        and best-effort on the exception path — so a comment crawl that dies mid-walk still ships
        the shards it produced instead of leaving them orphaned (「保留分片」 off means they were
        never individually recorded, so 智能清除-by-record cannot find them). The source crawl
        closes this exact hole in every one of its handlers."""
        finished = [writer.finish() for writer in writers.values()]
        for _info in finished:
            record_file(ctx, nid, _info['path'], 'merged')
        return finished

    try:
        for idx, url in enumerate(urls, 1):
            if not execution_state['running']:
                break
            if idx <= resumed_index:
                continue
            # The adapter's platform, chosen the same way the input list was: by DOMAIN, or —
            # for a mode whose matrix declares it takes NAMES (红果) — by the platform this
            # node already names. Never a guess: an unknown kind still lands on the named
            # ``comment.noAdapter`` below, which is the whole reason the router exists.
            kind = platform_for(url) or (want if accepts_names else '')
            if kind not in sessions:
                if capabilities.is_catbus(params):
                    # The second backend plays BOTH cached roles, exactly as 红果's harness does: the
                    # session whose ``crawl_<kind>`` returns ``(rows, status)`` per link, and the
                    # owner whose ``skipped_targets`` / ``end_reason`` the settlement reads by
                    # attribute. Asked before the browser branch, so a CatBus node never builds a
                    # Chrome, never plants a cookie and never takes a profile lock.
                    _state, why = catbus_bridge.mode_state(kind, 'comments')
                    if not catbus_bridge.supports(kind, 'comments'):
                        raise ValueError(t('catbus.refused', platform=kind, mode='comments', detail=why))
                    catbus_session = CatbusCrawler(
                        platform=kind,
                        params=params,
                        account=account,
                        abort=stop_requested,
                        log=lambda m: add_log(f'{t("comment.prefix")} {m}'),
                    )
                    sessions[kind] = (catbus_session, catbus_session)
                    execution_state['active_crawlers'].add(catbus_session)
                else:
                    harness_factory = getattr(crawler_class(kind), 'browserless_comment_harness', None)
                    if harness_factory is not None:
                        # A platform whose comment crawl drives an external desktop app instead
                        # of a browser (红果短剧; the measurement that forced this shape is in
                        # docs/crawler_notes.md): the harness plays BOTH cached roles, owns its
                        # own processes, and dies in this node's ``finally`` and on 停止 through
                        # the same reaper — its ``driver`` is None, which the reaper already
                        # reads as "no pid to kill", and its own close() aims the kills.
                        harness = harness_factory(
                            params=params,
                            log=lambda m: add_log(f'{t("comment.prefix")} {m}'),
                            abort=stop_requested,
                        )
                        sessions[kind] = (harness, harness)
                        execution_state['active_crawlers'].add(harness)
                    else:
                        # The run's 无头/窗口 choice is honoured verbatim (#148). A headless Chrome now
                        # carries a desktop fingerprint, and a *scrolled* comment panel was measured
                        # serving the same rows in both shapes (zhihu comments 5/5 headless, real profile,
                        # 2026-09-26), so the old rule that forced a window onto scroll-only panels inside a
                        # headless run is gone: no comment panel overrides what the user asked for.
                        crawler = get_crawler(
                            kind,
                            headless=headless,
                            cookie_dir=Config.COOKIE_DIR,
                            use_profile=(ctx or {}).get('use_profile'),
                            abort=stop_requested,
                            # The node's chosen login walks its comments too: the comment rate
                            # limit is an ACCOUNT limit, which is the whole reason multi-account
                            # exists. Blank = the historical default session.
                            account=account,
                        )
                        # Registered for the same reason the source node registers its own:
                        # a browser 停止 does not know about is a window the user watches keep
                        # working — and this loop only asks "may I stop?" between URLs, so one
                        # article's page walk could run the whole node out after the Stop.
                        sessions[kind] = (
                            crawler,
                            # The comment engine reports per-URL facts; prefix them so a
                            # line in the shared console says which node it came from.
                            CommentSession(
                                crawler.driver,
                                log=lambda m: add_log(f'{t("comment.prefix")} {m}'),
                                abort=stop_requested,
                                # The live attribute, not just its value: see CommentSession.driver.
                                owner=crawler,
                            ),
                        )
                        # Last, so a refusal while building the session cannot leave a
                        # registered browser that nothing here would ever close.
                        execution_state['active_crawlers'].add(crawler)
            _crawler, session = sessions[kind]
            # One dispatch, one surface: every walker — the browser session, the CatBus backend, the
            # 红果 harness — answers ``walk(platform, url, limit)``, and each refuses a platform it has
            # no adapter for BY NAME. The engine used to build the method name out of the routing key
            # (``getattr(session, f'crawl_{kind}')``) and check for ``None`` here, which pushed the
            # "does this backend speak this site?" question into an attribute lookup and made the
            # CatBus class synthesise methods to stay reachable. Adding a platform to
            # ``core.refs._COMMENT_DOMAINS`` without writing its walk is still a refusal, just one
            # the walker states itself.
            skipped_before = len(getattr(_crawler, 'skipped_targets', ()) or ())
            rows, status = session.walk(kind, url, limit)
            counts[status] = counts.get(status, 0) + 1
            if (
                status != OK
                or len(getattr(_crawler, 'skipped_targets', ()) or ()) > skipped_before
                or getattr(_crawler, 'end_reason', None) == UNDER_TARGET
            ):
                # Not proven: a dead or walled link, one the harness names as skipped, or one
                # whose own walk came home short of what the site counted.
                unproven.append(idx)
            elif cursor_sink is not None and not unproven:
                # Recorded AFTER the walk, and only while the run of completed inputs is
                # UNBROKEN — so ``url_index`` means "the leading inputs this node PROVED", the
                # one thing 继续 has to trust. A hole at 2 must pin the cursor at 1 even when
                # 3..10 all come back clean: advancing over the hole is exactly the laundering
                # this rewrite exists to stop. The replay then re-walks from 2, and the ledger
                # refuses the rows it already paid for (``item_key`` now keys a comment by its
                # own site id), so the replay costs the player its time and never costs a
                # duplicate row.
                cursor_sink({'url_index': idx, 'url_total': len(urls)})
            if status == BLOCKED:
                # Named by what actually walled. The message used to fall back to a
                # hand-written list of four platforms, so a YouTube or X comment run
                # bounced by its own site was reported as 知乎/微博/小红书/哔哩哔哩
                # 的登录态失效 — naming four platforms the user never crawled and
                # leaving the one they did unnamed.
                blocked_by.append(kind)
                # 风控 and a dead cookie are OPPOSITE advice (back off vs re-save), and only the
                # owning crawler can tell them apart: it latches ``risk_blocked`` on a captcha and
                # ``login_wall`` on a login redirect. A platform that names neither keeps today's
                # bare-cookie verdict, so this changes nothing for them. Tracked PER platform (not
                # one boolean) so a mixed batch can only report 风控 when EVERY blocked platform
                # named it — otherwise the actionable cookie path wins.
                if getattr(_crawler, 'risk_blocked', False) and not getattr(_crawler, 'login_wall', False):
                    risk_by.append(kind)
                if getattr(_crawler, 'login_wall', False):
                    login_seen = True
            writer = _writer_for(idx)
            fresh = []
            for row in rows:
                if row_sink is not None:
                    if row_sink(row):  # ledger said new: store it AND publish it
                        fresh.append(row)
                else:
                    fresh.append(row)
            writer.add(fresh)
            rows_out.extend(fresh)
            add_log(t('comment.article', url=url, n=len(fresh), status=t(f'comment.status.{status}')))
    except BaseException:
        # Whatever the walk raised (a refused adapter, a harness that failed to start, a locked
        # runs.db in the sink, a full export dir), publish the part files first — but suppressed,
        # so a merge bookkeeping error can never REPLACE the real one that fails this node.
        with contextlib.suppress(Exception):
            _publish_parts()
        raise
    finally:
        for crawler, _session in sessions.values():
            # Out of the registry first: if 停止 reaches it on its own thread while
            # this one is still unwinding, the two must not both be reaping it.
            execution_state['active_crawlers'].discard(crawler)
            close_login_browser(crawler)

    files = _publish_parts()
    if stop_requested():
        # The article loop above stops taking URLs once the run is not wanted, and then it
        # *returns* — so without this check a comment node cut short by 停止 settled DONE
        # over a partial table and the run never offered 继续. Everything it did collect is
        # finished into its part files first; what is dropped is the ``comment.done``
        # summary, because the executor's own 被停止 line is the one true sentence here.
        raise CrawlerStopped(t('crawl.stopped'))
    blocked_seen = bool(counts.get(BLOCKED))
    # 风控-only when EVERY blocked platform named 风控 and none named a login wall: then the
    # back-off verdict owns the node and no cookie flag is raised. Any cookie wall, or any blocked
    # platform that named neither refusal, defers to the actionable cookie path unchanged.
    risk_only = blocked_seen and not login_seen and set(blocked_by) <= set(risk_by)
    if blocked_seen and not risk_only:
        # A blocked article whose session did NOT name 风控 is the cookie-death case: raise the
        # toast flag so the user refreshes and resumes. 风控-only is the exception — its session
        # may be fine and re-saving a working cookie is the lie this repo refuses, so the flag
        # stays down and the verdict (below) is the back-off one. Every platform that returns a
        # bare BLOCKED without latching risk keeps the original "any block → cookie" behaviour.
        execution_state['cookie_expired'] = True
    add_log(
        t(
            'comment.done',
            urls=len(urls),
            ok=counts.get(OK, 0),
            blocked=counts.get(BLOCKED, 0),
            dead=counts.get(DEAD, 0),
            rows=len(rows_out),
            files=len(files),
        )
    )
    # The source-crawl path names a ledger-skip (``run.dedupe_skipped`` / ``..._all_skipped``) so a re-run
    # that stored nothing is not read as an empty table; the comment node dedupes through the VERY SAME
    # ``row_sink``, which tallies each refused item into ``ctx['skipped_seen'][nid]``. Reading that one tally
    # (never re-deriving it) keeps a single definition with the source path, and it already excludes what this
    # run genuinely stored. Measured live 2026-09-29: a repeat of one video's comments filed nothing, printed
    # 「共 0 条评论」 and named nothing — indistinguishable from a thread that has no comments. Skipped on a
    # resume (there the ledger IS the resume machinery and the result is prefilled); a wall is left to raise
    # its own single line, so a run that both skipped and was blocked is not silenced.
    skipped = (ctx.get('skipped_seen') or {}).get(nid) if ctx is not None else None
    if skipped and not ctx.get('resume'):
        add_log(t('run.dedupe_skipped', n=skipped))
        if not rows_out:
            add_log(t('run.dedupe_all_skipped'))
    if blocked_seen:
        # Failed (not done) → the run lands in the resume banner and 继续
        # retries exactly the articles the wall refused.
        # A sequence, not a '/'.join(): the {platform} slot localizes+joins only
        # list values and comma-joined strings, so a slash string printed raw keys.
        named = list(dict.fromkeys(blocked_by))
        target_word = named or want or t('run.cookieAnyPlatform')
        if risk_only:
            # 风控 the whole batch: name it and tell them to back off, NOT to re-save a
            # cookie — that is the source crawler's rule, applied to the comment node too.
            raise ValueError(t('run.riskControlled', platform=target_word))
        raise ValueError(t('run.cookieExpired', platform=target_word))
    # U1 for the comment engine, asked the SAME attribute way as the source path: a
    # session that walked short without the site attesting an end must not settle
    # DONE. Browser adapters never set ``end_reason`` (it stays absent → None), so
    # this gate is dormant for every platform but the ones that declare a harness.
    for kind, (owner, _session) in sessions.items():
        missing = list(getattr(owner, 'skipped_targets', ()) or ())
        if missing:
            # Read BY ATTRIBUTE, exactly like the gate below: a browser adapter never grows
            # this list, so the check stays dormant for every platform but the ones that
            # declare a harness. A feed of ten dramas that opened six is not a finished
            # crawl, and 「新增 749 条（正常）」 was the sentence the run ended with.
            raise ValueError(t('run.commentsSkipped', platform=kind, n=len(missing), names='、'.join(missing)))
    for kind, (owner, _session) in sessions.items():
        if getattr(owner, 'end_reason', None) != UNDER_TARGET:
            continue
        want_total = getattr(owner, 'target_total', 0) or 0
        # The harness names its own missing count, because ROWS are not a fair denominator:
        # a comment crawl's table carries reply rows that no episode's printed ``total``
        # includes, so "we kept at least as many rows as the site counted" can be true while
        # an episode came home short. Asked by attribute — a browser adapter reports none,
        # and for those the row-count comparison is the whole rule.
        short_by = int(getattr(owner, 'shortfall', 0) or 0)
        if not want_total and not short_by:
            continue
        if not short_by and len(rows_out) >= want_total:
            continue
        # The denominator the console must print: with a named gap it is the rows in hand
        # PLUS that gap, never the site's own total alone — a crawl holding 520 rows over an
        # episode 500 short would otherwise read 「采到 520/1 条就停了」, convicting itself with
        # arithmetic nobody can audit.
        want = len(rows_out) + short_by if short_by else want_total
        counts = getattr(owner, 'walk_counts', {}) or {}
        walk = (
            t('run.underTargetWalk', scanned=counts['scanned'], kept=counts['kept'], refused=counts['refused'])
            if {'scanned', 'kept', 'refused'} <= set(counts)
            else ''
        )
        raise ValueError(t('run.underTargetShort', platform=kind, have=len(rows_out), want=want, walk=walk))
    rows_out = filter_comments_by_time(rows_out, params, node_label(node, str(nid)))
    return rows_out


def run(node: dict, call: NodeCall):
    return execute_comment_node(node, headless=call.headless, ctx=call.ctx)
