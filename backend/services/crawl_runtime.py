"""The plumbing a crawl node shares with everything downstream of it.

One row sink (every scraped item is committed as it arrives, so a kill at row 900 of 1000
still owns those 900), one item-key namespace (the node fingerprint, so a second attempt or
another workflow asking the same question never re-buys an item), and one filename
assembly (window + record stamp, read from the record rather than the clock).
"""

from core.refs import as_bool, window_tag


def item_scope(ctx: dict, node: dict) -> str:
    """Namespace for "have I crawled this already?".

    The node fingerprint, not the run id: an item collected once under this
    keyword must not be collected again by the next attempt, or by another
    workflow that asks the same question. That is what keeps a resumed crawl
    from handing back duplicates.
    """
    return 'item:' + str((ctx.get('fingerprints') or {}).get(node.get('id') or '', ''))


def source_stream(ctx: dict, nid: str, scope: str, label: str = ''):
    """Row sink + cursor sink for one source node.

    Every scraped item goes straight into the database as it is scraped, so a
    kill at item 900 of 1000 still owns those 900 rows; the position goes with
    it so the next attempt can continue instead of starting over.

    *label* is the node's user-facing name, handed down to the store's row-cap
    warning: whoever reads the console named that box, and ``node-7`` is not
    what they called it.

    This sink is deliberately **one write per row**. Buffering N rows per
    transaction would be the obvious optimisation and would cost the feature its
    purpose: with WAL + ``synchronous=NORMAL`` a commit is tens of microseconds,
    while a Selenium page costs seconds, so batching buys nothing measurable and
    throws away up to a batch of rows whenever the run is killed.
    """
    store = ctx['store']
    run_id = ctx['run_id']
    # Per-node tally of items the incremental ledger refused ("already
    # collected under this node fingerprint") — surfaced in the console and in
    # /api/workflow/status so an all-seen re-run is loud, not silent.
    tally = ctx.setdefault('skipped_seen', {})

    def row_sink(item):
        # A sink answers "was this new?" — the crawler drops duplicates itself,
        # which is how a resumed crawl re-reading the same page stays honest.
        kept, dropped = store.append_rows(run_id, nid, [item], dedupe_scope=scope, label=label)
        # kept=0,dropped>0 is a genuine ledger dedupe ("already collected"); kept=0,dropped=0 is
        # the STORAGE CAP (the row was never tried against the ledger, the store hit its limit and
        # already logged run.row_limit once). Tallied only the first: the console/advice says 开启
        # 「重新采集」 to release the claim, but a capped row has no claim to release — that advice
        # re-crawls into the same cap. And return True on a cap, so the pager does not read "the
        # site carried nothing new" from a local disk limit and print it as the site's own funnel.
        if not kept and dropped:
            tally[nid] = tally.get(nid, 0) + 1
        return bool(kept) or not dropped

    def cursor_sink(position):
        store.save_cursor(run_id, nid, position)

    return row_sink, cursor_sink


def name_parts(params: dict, stamp: str = '') -> str:
    """The filename components a crawl appends to its own name, in order.

    Two facts that used to live only in the node's form: which stretch of the calendar
    the crawl was asked to walk, and (on request) which record is writing these files.
    Empty answers stay empty rather than becoming a stray separator, and the stamp is
    handed in rather than read from the clock — see ``_record_export_stamp`` for the
    prefix a moving stamp would break.
    """
    window = window_tag(params.get('start_time'), params.get('end_time'))
    run = (stamp or '') if as_bool(params.get('part_timestamp')) else ''
    return window + run
