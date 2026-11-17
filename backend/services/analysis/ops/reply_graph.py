"""The ``reply_graph`` step, one module of the analysis op registry (see ops/__init__.py)."""

import logging

import pandas as pd

from i18n import t
from services.analysis.kernels import UnknownOperationError

logger = logging.getLogger(__name__)


def reply_graph(
    df: pd.DataFrame,
    author_col: str = '评论者',
    floor_col: str = '楼层',
    parent_floor_col: str = '父楼层',
    article_col: str = '文章URL',
) -> pd.DataFrame:
    """Who replies to whom, as an edge table the 网络图 chart draws.

    A comment row carries its own position (楼层) and, for a nested reply, the floor of the
    comment it answers (父楼层). Joining a reply's 父楼层 back to the top-level row that holds
    that 楼层 recovers the parent's author, so the pair (parent author → replying author) is a
    directed edge and its count is the weight — exactly the ``x``/``y``/value a force graph
    reads. Self-replies and replies whose parent is absent from the table are dropped.

    **Floors are numbered per ARTICLE, not per table.** Every comment adapter writes 文章URL
    and numbers 楼层 inside its own thread (weibo's ``floor_number`` comes from the site,
    douyin counts across one video's panel), so a comment node with three links holds three
    #1 comments. Resolving 父楼层 against one global floor map attached article B's reply to
    an unrelated author in article A — a complete-looking graph that is simply wrong. The
    join key is therefore (article, floor); ``article_col`` names that column and a table
    without it (one article, or a hand-made CSV) keeps the single-bucket reading and says so.

    It RAISES rather than returning an empty table when no reply link resolves: a zero-edge
    graph would settle the node DONE and hand the chart nothing measured, which is the same
    silent-success this project refuses everywhere else.
    """
    for name in (author_col, floor_col, parent_floor_col):
        if name not in df.columns:
            raise UnknownOperationError(t('analysis.step_col_missing', op='reply_graph', col=name))
    per_article = bool(article_col) and article_col in df.columns
    if not per_article:
        logger.warning(t('analysis.reply_graph_no_article', op='reply_graph', col=article_col or '-', floor=floor_col))
    floor_to_author = {}
    records = df.to_dict('records')
    for row in records:
        floor = str(row.get(floor_col, '') or '').strip()
        author = str(row.get(author_col, '') or '').strip()
        parent = str(row.get(parent_floor_col, '') or '').strip()
        if author and floor and not parent:
            article = str(row.get(article_col, '') or '') if per_article else ''
            floor_to_author.setdefault((article, floor), author)
    edges: dict = {}
    for row in records:
        author = str(row.get(author_col, '') or '').strip()
        parent = str(row.get(parent_floor_col, '') or '').strip()
        if not (author and parent):
            continue
        article = str(row.get(article_col, '') or '') if per_article else ''
        src = floor_to_author.get((article, parent))
        if src and src != author:
            edges[(src, author)] = edges.get((src, author), 0) + 1
    if not edges:
        raise UnknownOperationError(t('analysis.reply_graph_no_edges'))
    rows = [{'src_author': s, 'dst_author': d, 'weight': w} for (s, d), w in edges.items()]
    rows.sort(key=lambda r: r['weight'], reverse=True)
    nodes = {n for r in rows for n in (r['src_author'], r['dst_author'])}
    logger.info(t('analysis.reply_graph_done', edges=len(rows), nodes=len(nodes)))
    return pd.DataFrame(rows)
