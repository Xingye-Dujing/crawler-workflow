"""zhihu comments: the per-panel row builder (author, time, body).

The panel read lives in :mod:`crawlers.comments` (one in-page script per panel); this file turns
what that script measured into rows, in the columns the export shows.

Two columns are here because a measurement said what the panel does and does not hold
(``backend/test_zhihu_comment_dom.py``, two real panels, 22 items):

* **评论时间** is on the page — relative for recent comments (「14 小时前」), absolute for old ones
  (「2019-08-15」) — so it is read. It used to be written as ``''`` without looking, and the relative
  half then sat in the column as the site's own words: a time series over it loses exactly the
  comments a live event is about, so both shapes go through ``engine.times.absolute`` here.
* **点赞数** is not reachable as a button, an ``aria-label`` or a bare number anywhere in an item's
  own subtree, so it is published as ``''``. It used to be a hard ``0``, which is a number the user
  reads as "nobody liked this" about a column this crawler never asked the site for.
"""

from .engine import times


def parse_zhihu_comments(url: str, items) -> list:
    """One panel's readings (``{text, author, href, time, parent}``) into rows.

    ``author`` is empty only when the comment's OWN subtree holds no ``/people/`` link at all.
    The reader refuses to climb higher than that on purpose: an ancestor wide enough to be
    another comment's header would name the wrong person, and a wrong name is worse than none.

    ``parent`` is the index (in the same read) of the comment this one replies to, or -1. Measured:
    nested replies do not exist in the DOM until 「展开其中 N 条回复」 is clicked, and on one answer
    the items whose author sat outside their own subtree were exactly those — so the column both
    keeps a thread readable and tells a future reader whether a blank author means 「anonymous」 or
    「a reply, whose header lives one wrapper deeper」.
    """
    rows = []
    index = 0
    for one in items:
        text = str(one.get('text') or '').strip()
        if not text:
            continue
        index += 1
        parent = one.get('parent')
        rows.append(
            {
                '平台': 'zhihu',
                '文章URL': url,
                '评论者': str(one.get('author') or ''),
                '评论者主页': str(one.get('href') or ''),
                '评论内容': text,
                # Zhihu prints a relative wording for recent comments; converted at the row
                # boundary so every platform's 评论时间 is one format.
                '评论时间': times.absolute(one.get('time')),
                '点赞数': '',
                '楼层': index,
                '父楼层': (int(parent) + 1) if isinstance(parent, int) and parent >= 0 else '',
            }
        )
    return rows
