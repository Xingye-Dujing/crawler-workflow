"""douyin comments: the rendered-block field splitter and the tuple adapter.

The panel's line order is fixed but not dense, so the fields are recognised by
*shape* rather than by index — that is also what keeps a truncated preview from
becoming comment text.
"""

import re

# ``1周前·江苏`` / ``刚刚`` / ``2026-08-04`` — douyin puts the relative time and
# the IP 地区 in one line, and it is the only line of the block that is neither a
# name, the text itself, nor a number.
_DOUYIN_WHEN_RE = re.compile(r'^(?:刚刚|\d+\s*(?:分钟|小时|天|周|月|年)前|\d{4}-\d{1,2}-\d{1,2})(?:·.+)?$')
_DOUYIN_SUBS_RE = re.compile(r'展开\s*(\d+)\s*条回复')


def douyin_comment_fields(text: str) -> tuple:
    """One rendered comment block → (author, content, when, region, likes, subs).

    The panel's line order is fixed but not dense: an author whose name is empty
    collapses a line, so the fields are recognised by *shape* (a date-shaped line,
    a bare number, a 展开N条回复 label) rather than by index. That is also what
    keeps a truncated preview (``展开更多`` inserts a literal ``...`` line) from
    becoming comment text.

    The time line is the anchor, not just another field. The text used to be
    ``lines[1]`` unconditionally, which filed ``1天前·北京`` as the comment when the
    author line had absorbed it — a row whose 评论内容 is a timestamp is a lie in the
    column the user reads — and it dropped every line after the first on a comment
    that wraps, so a two-line comment lost its second line (「不漏采」 is the whole
    point of this table). Lines between the author and the anchor are therefore the
    text, joined; a number standing there is part of what someone wrote, not the
    like count, which only ever sits below the anchor.
    """
    lines = [line.strip() for line in str(text or '').split('\n') if line.strip() and line.strip() != '...']
    author = lines[0] if lines else ''
    when, region, likes, subs = '', '', 0, 0
    anchor = next((i for i, one in enumerate(lines[1:], 1) if _DOUYIN_WHEN_RE.match(one)), None)
    head = lines[1:anchor] if anchor is not None else lines[1:2]
    content = '\n'.join(head)
    tail_start = (anchor + 1) if anchor is not None else 2
    for line in lines[tail_start:]:
        match = _DOUYIN_SUBS_RE.search(line)
        if match and not subs:
            subs = int(match.group(1))
            continue
        if line.isdigit() and not likes:
            likes = int(line)
    if anchor is not None:
        when, _, region = lines[anchor].partition('·')
        when, region = when.strip(), region.strip()
    return author, content, when, region, likes, subs


def parse_douyin_threads(threads: dict, url: str) -> tuple:
    """Ordered parent→reply rows and the UNCOLLECTED reply count, numbered across the whole panel.

    ``threads`` is ``{parent_key: {author, content, when, region, likes, subs, replies: {key: {...}}}}``
    in first-seen order (``dict`` preserves it). 楼层 is a single continuous floor over parents and
    their replies (so a reply's 父楼层 can point back at its parent's number), exactly like zhihu's.

    A parent's **子回复数** is the number of reply rows we actually landed (the user's "实际子行数"),
    falling back to the site's declared 「展开N条回复」 when the thread could not be opened. ``nested`` is
    the sum of ``declared − captured`` over every parent — the replies the denominator counts but this
    walk never reached — so the ``comment.dyShort`` gap stays honest whether or not the threads opened,
    and reply rows (now real rows) are never double-counted against it.
    """
    rows = []
    nested = 0
    floor = 0
    for slot in threads.values():
        floor += 1
        parent_floor = floor
        captured = len(slot['replies'])
        nested += max(slot['subs'] - captured, 0)
        rows.append(
            {
                '平台': 'douyin',
                '文章URL': url,
                '评论者': slot['author'],
                '评论者主页': '',
                '评论内容': slot['content'],
                '评论时间': slot['when'],
                '评论地区': slot['region'],
                '点赞数': slot['likes'],
                '子回复数': captured if captured else slot['subs'],
                '楼层': parent_floor,
                '父楼层': '',
            }
        )
        for reply in slot['replies'].values():
            floor += 1
            rows.append(
                {
                    '平台': 'douyin',
                    '文章URL': url,
                    '评论者': reply['author'],
                    '评论者主页': '',
                    '评论内容': reply['content'],
                    '评论时间': reply['when'],
                    '评论地区': reply['region'],
                    '点赞数': reply['likes'],
                    '子回复数': 0,
                    '楼层': floor,
                    '父楼层': parent_floor,
                }
            )
    return rows, nested
