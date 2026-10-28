"""How a run, a node and a crawled item are named in the ledger.

Identity is deliberately split in two: ``workflow_fingerprint`` answers "is this the same
workflow?" so the UI can offer to continue after a parameter tweak, while
``node_fingerprint`` answers "is this node's stored output still valid?". A row's
``item_key`` is its site identity, never its content, so a re-format of the same post is
not a second item.
"""

import contextlib
import hashlib
import json
import math

import pandas as pd
from sessions.cookies import CookieManager

# Run lifecycle. `running` only ever exists while a process is alive: on startup
# every leftover `running` row is promoted to `interrupted`, which is exactly
# the case "the server died mid-run" that resume exists for.
RUN_RUNNING = 'running'
#: The user pressed 停止 and the record has been flipped off 运行中, but the worker has
#: not written its verdict yet. Its own status rather than an early `interrupted`,
#: because a stopped-but-unsettled run must be neither deletable (its rows are still
#: being written) nor offered to 继续 (its cursor is not final). The gap is real:
#: closing a browser from another thread does not interrupt the command the worker is
#: inside, which used to leave the record reading 运行中 for up to 40 s.
RUN_STOPPING = 'stopping'
RUN_INTERRUPTED = 'interrupted'
RUN_COMPLETED = 'completed'
RUN_FAILED = 'failed'
RUN_ABANDONED = 'abandoned'

#: Statuses that still owe somebody a verdict: never purge them as if they were over.
UNRESOLVED_RUN_STATUS = (RUN_RUNNING, RUN_STOPPING, RUN_INTERRUPTED)

# Node lifecycle. `partial` is the one that carries real work forward: the node
# died, but the rows it already produced are kept and handed downstream.
NODE_PENDING = 'pending'
NODE_RUNNING = 'running'
NODE_DONE = 'done'
NODE_PARTIAL = 'partial'
NODE_FAILED = 'failed'
NODE_SKIPPED = 'skipped'
NODE_RESTORED = 'restored'

# What 「可续跑」 means to a query. `stopping` is deliberately absent: that run is
# still unwinding, and offering it invites 重新开始 to discard the rows a live thread
# is writing. The panel sees it anyway — it lists everything.
RESUMABLE_RUN_STATUS = (RUN_INTERRUPTED, RUN_FAILED, RUN_RUNNING)

# Column names the crawlers in this project actually emit, best identity first.
_URL_FIELDS = ('链接', '笔记链接', '文章链接', '链接地址', '原文链接', '网址', 'URL', 'url', 'link')
_TITLE_FIELDS = ('标题', 'title')
_AUTHOR_FIELDS = ('作者', '发布者', '公众号', '博主', 'author')
_BODY_FIELDS = ('正文', '内容', '摘要', 'body', 'content')
# A comment's own site id, which every comment crawler in this repo emits (and which the YouTube
# comment walk already uses as the IN-RUN identity — see the ``identity=`` in
# ``crawlers/platforms/youtube/comments.py``).
_COMMENT_ID_FIELDS = ('评论ID',)
# Carried alongside it so a mixed batch cannot collapse a 知乎 numeric id onto a 微博 one:
# the two sites draw their ids from separate spaces and neither knows the other's.
_COMMENT_PLATFORM_FIELDS = ('平台',)


def _dumps(value) -> str:
    # sort_keys=True is a correctness property, not cosmetics: this output
    # feeds node fingerprints, and dict key order coming from a different
    # client (or a re-save) must not read as a changed node definition.
    return json.dumps(_clean(value), ensure_ascii=False, sort_keys=True)


def _clean(value):
    """JSON-safe copy: NaN/Inf become null instead of the invalid literals
    ``json.dumps`` would otherwise emit, which no strict reader accepts."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_clean(v) for v in value]
    with contextlib.suppress(TypeError, ValueError):
        if pd.isna(value):
            return None
    return str(value)


def _sha1(*parts) -> str:
    joined = '\x1e'.join('' if part is None else str(part) for part in parts)
    return hashlib.sha1(joined.encode('utf-8')).hexdigest()


def first_text(item: dict, fields) -> str:
    for field in fields:
        value = str(item.get(field) or '').strip()
        if value:
            return value
    return ''


def item_key(item) -> str:
    """Fingerprint of one crawled item — "have I already got this?".

    A **comment** is identified by its own site id, and must be: its row also carries
    楼层 (and 父楼层), which a fresh harness numbers from 1 again, so the whole-row hash
    below would read the same comment as a NEW item on every resume and re-store the
    whole set with invented floors. The site id is the only field that survives a replay.

    Otherwise a link is the best identity when the crawler captured one. Otherwise title
    + author + the head of the body: enough to recognise the same post after a
    re-crawl, while ignoring the parts that change between visits (like/comment
    counts, "展开全文" artefacts, whitespace).
    """
    if not isinstance(item, dict):
        return _sha1('raw', item)
    cid = first_text(item, _COMMENT_ID_FIELDS)
    if cid:
        return _sha1('comment', first_text(item, _COMMENT_PLATFORM_FIELDS), cid)
    link = first_text(item, _URL_FIELDS)
    if link:
        return _sha1('url', link)
    parts = [
        first_text(item, _TITLE_FIELDS),
        first_text(item, _AUTHOR_FIELDS),
        first_text(item, _BODY_FIELDS)[:200],
    ]
    if any(parts):
        return _sha1('text', *parts)
    return _sha1('json', _dumps(item))


# The labels an Upload node carries about its file, and the label a 工作流命名 node
# carries about its workflow. They are left out of a fingerprint because they
# *describe* the input rather than choose it: ``dataset_name`` follows from
# ``dataset_id``, and a workflow's name is what the run record is filed under, not
# something the crawl reads. Re-saving a workflow with a tidied name must not
# invalidate a single stored row — and it used to: a node's fingerprint feeds its
# children, so renaming one label cascaded over the whole component AND moved the
# dedupe ledger's scope (``'item:' + node_fingerprint``), which made 继续 after a
# cosmetic rename re-crawl and re-pay every item it had already collected.
# The ids themselves stay in the fingerprint: they identify real input, so pointing
# a node at a different file or a different run must invalidate everything
# downstream of it.
#
# ``recrawl`` (重新采集) joined this set for the same reason it joined the last one, and a
# measurement said so: the checkbox is an instruction about the ledger, not a choice of data —
# the keyword, the URLs and the target decide what is collected, and the box only says "do not
# trust what you already have". While it was in the fingerprint, ticking it MOVED the ledger's
# scope instead of releasing it: the comment-node test recorded ``released 0 dedupe records``
# while collecting 4 rows, so the re-collection happened by accident on an empty new scope and
# the claims the user had asked to forget stayed behind forever — which is the silent
# under-collection retention exists to prevent.
#
# ``enabled`` (the node's on/off switch) belongs here for the same class of reason: it is an
# instruction about whether a node runs, not a choice of what data it reads. Toggling a node off
# and back on must not invalidate its stored rows or move the dedupe ledger. Whether a node is
# *present at all* in the structure fingerprint is decided one level up — :func:`effective_workflow`
# removes disabled nodes from the graph before the fingerprint is taken — so this only keeps the
# surviving nodes' own data fingerprint free of the switch.
#
# The output-shape switches joined for the SAME class of reason, and one measurement made the
# cost concrete: a 700-row crawl interrupted, the user ticks 「保留分片」 (or flips 格式 csv→json)
# in the panel and presses 继续 — and because these keys were in the fingerprint, the node's
# paid-for rows were DELETED and its cursor NULLed, so the walk re-opened every link and spent
# the account again for a table that already existed. None of them chooses DATA (the keyword, the
# URLs, the target do); they choose how a file is spelled on disk. And an export is re-rendered
# from the durable ``node_rows`` on demand, so leaving them out of the fingerprint strands no
# stale-format artifact — the next export from the kept rows honours the new switch.
_VOLATILE_PARAMS = frozenset(
    {
        'dataset_name',
        'row_count',
        'workflow_name',
        'recrawl',
        'watermark',
        'enabled',
        'layout_order',
        # output-shape only: never a choice of what is collected
        'part_size',
        'keep_parts',
        'per_article_file',
        'format',
        'live_export',
        'part_timestamp',
        'filename_timestamp',
        'filename_time_range',
        'emit_latex',
        'emit_latex_table',
        # Cross-run monitoring: none of these changes a single row the node produces — they say
        # where its capture is filed, which capture to compare with, and what to call it. Keyed in,
        # renaming a capture would recompute a paid-for graph; keyed out, the graph is reused and
        # the monitoring still files whatever run actually executed the node.
        'watch_project',
        'watch_baseline',
        'watch_label',
    }
)


def stable_params(params) -> dict:
    """The parameters that choose DATA, for hashing.

    Volatile entries (labels, switches) drop out entirely. A BLANK 账号 is also
    dropped: blank IS the default account — the very session this node crawled as
    before multi-account existed — so a panel stamping ``''`` onto an old canvas
    must not re-key rows already paid for. A NAMED account stays in the hash: it
    selects a different session and device, and per the design that makes it a
    different crawl — its cursor and dedupe scope must not claim the old one's.

    A BLANK model is dropped for the same reason: blank IS 跟随全局 (the run's
    global model), so reopening a node panel and picking 「跟随全局」 must not
    re-key the node's paid LLM rows. A NAMED model stays in the hash: it selects
    a different model, and per the design that makes it a different answer — its
    cached answers and children's dedupe scope must not claim the old model's.
    """
    out = {k: v for k, v in (params or {}).items() if str(k) not in _VOLATILE_PARAMS}
    # Folded through CookieManager, not compared to '': a node panel that stamps the default
    # login by NAME (which is what the candidate list and a new node's preselection hand out)
    # and one that leaves it BLANK are one session, so they must produce one fingerprint. Keyed
    # apart, 继续 cannot find the paid rows of its own run and re-crawls — which spends the
    # account again for a table that already exists.
    if CookieManager.is_default(out.get('account') or ''):
        out.pop('account', None)
    if str(out.get('model') or '').strip() == '':
        out.pop('model', None)
    # The same fold, one rung further: ``selenium`` IS the crawl every existing canvas already
    # describes, spelled either by name or by the absence of the key. Kept in the hash unchanged,
    # adding the switch would move every saved node's fingerprint, 继续 would not find its own paid
    # rows, and the whole database would re-crawl to discover it.
    if str(out.get('backend') or '').strip().lower() in ('', 'selenium'):
        out.pop('backend', None)
    return out


def node_fingerprint(node: dict, upstream: tuple = ()) -> str:
    """What makes a node's stored output reusable.

    Type, operation, parameters, and the fingerprints of its parents — so
    changing a chart type invalidates just that node, while changing a
    crawler's keyword invalidates it and everything wired after it. Input
    metadata (`_VOLATILE_PARAMS`) is left out.
    """
    return _sha1(
        node.get('type', ''),
        node.get('operation', ''),
        _dumps(stable_params(node.get('params'))),
        '|'.join(sorted(upstream)),
    )


def workflow_fingerprint(workflow: dict) -> str:
    """Identity of the workflow *structure*: node ids, node types and the
    wiring — deliberately not the parameters. That is what the resume banner
    matches on, so tweaking a setting still finds the interrupted run."""
    nodes = workflow.get('nodes') or []
    conns = workflow.get('connections') or []
    return _sha1(
        _dumps(sorted((str(n.get('id')), str(n.get('type'))) for n in nodes if isinstance(n, dict))),
        _dumps(sorted((str(c.get('from')), str(c.get('to'))) for c in conns if isinstance(c, dict))),
    )


def fingerprints_for_workflow(workflow: dict) -> dict:
    """{node_id: node_fingerprint} for a whole workflow definition.

    Parents are resolved first (topological order via Kahn's algorithm) so a
    node's fingerprint can include its ancestors'. A cycle — which the engine
    rejects anyway — just stops the walk and leaves the rest without parent
    fingerprints rather than looping forever.
    """
    nodes = {str(n.get('id')): n for n in (workflow.get('nodes') or []) if isinstance(n, dict)}
    parents = {}
    children = {nid: [] for nid in nodes}
    for conn in workflow.get('connections') or []:
        if not isinstance(conn, dict):
            continue
        src, dst = str(conn.get('from')), str(conn.get('to'))
        if src in nodes and dst in nodes:
            parents.setdefault(dst, []).append(src)
            children.setdefault(src, []).append(dst)

    out = {}
    queue = [nid for nid in nodes if not parents.get(nid)]
    while queue:
        nid = queue.pop(0)
        upstream = tuple(out.get(p, '') for p in parents.get(nid, []))
        out[nid] = node_fingerprint(nodes[nid], upstream)
        for child in children.get(nid, []):
            if all(p in out or p not in nodes for p in parents.get(child, [])):
                queue.append(child)
    return out
