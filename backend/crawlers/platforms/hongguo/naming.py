"""红果's name rules: which name answers which request, and which control is an expander.

Split out of :mod:`crawlers.platforms.hongguo.harvest` on purpose — these are string→verdict rules
with no driver, no UIA and no Windows in them, so the two table tests that pin them can be read and
run without a player window ever existing.

Every rule here is a measured one, and the comments say what was measured, because each of them
replaced a looser rule that let ANOTHER drama's comments into this table. A wrong-drama row is a
corrupted table, not a smaller one.
"""

import re

#: A card name may legitimately differ from the requested one by a season suffix the
#: other side does not print (「剧名」/「剧名 第二季」) — but never by containment in the
#: middle, which is what put another drama's comments into this table.
_MIN_TITLE_PREFIX = 4
_TITLE_NOISE = re.compile(r'[\s《》「」『』【】()（）·、,，.。!！?？:：\-—]+')
#: A comment's OWN action button is literally ``回复`` (or ``回复 3``); it opens the
#: composer and steals the keyboard focus the drawer scroll needs. Measured on a real
#: run 2026-10-19: the old needle '回复' clicked one of those, the wheel then paged
#: nothing, and a thread the site counted at 698 came home with 20 rows.
_BARE_REPLY_RE = re.compile(r'^回复\s*[\d.]*$')
#: The expand control says BOTH "replies" and "there are more of them to see".
_EXPAND_WORDS = ('展开', '查看', '更多')


def is_expand_control(name) -> bool:
    """Is this drawer control the 「展开 N 条回复」 link (and NOT a comment's 回复 button)?

    Pure, and pinned by a table test, because the rule cost a whole episode's comments:
    a name must speak of 回复 AND promise MORE of them. ``回复``/``回复 3`` refuse, and so
    does a section header like ``热门回复`` — nothing here opens a composer.
    """
    text = str(name or '').strip()
    if '回复' not in text:
        return False
    if _BARE_REPLY_RE.match(text):
        return False
    return any(word in text for word in _EXPAND_WORDS)


def norm_title(text) -> str:
    """A drama name compared the way the two pages spell it: no punctuation, no spacing."""
    return _TITLE_NOISE.sub('', str(text or '')).lower()


def same_drama(want_norm: str, name: str) -> bool:
    """Does this card name the drama the walk asked for?

    Equality after normalisation, or a start-with relation whose shorter side is long
    enough to be a name of its own. The loose containment this replaced matched a short
    card title inside a longer one, and 错剧 rows are a corrupted table rather than a
    smaller one — a missing drama is refused by name instead.

    This is the FALLBACK matcher only: :meth:`PlayerUI._play_for_title` asks for an exact
    card across the whole tree first, because this rule on its own still opens 斗罗大陆 for
    a request that named 斗罗大陆 第二季.
    """
    have = norm_title(name)
    if not want_norm or not have:
        return False
    if want_norm == have:
        return True
    shorter, longer = sorted((want_norm, have), key=len)
    return len(shorter) >= _MIN_TITLE_PREFIX and longer.startswith(shorter)


def screen_names(want_norm: str, have_norm: str) -> bool:
    """Does the on-screen header name the drama the walk asked for?

    A DIFFERENT rule from :func:`same_drama`, on purpose. That one matches a CARD to a request
    and must not let 斗罗大陆 answer 斗罗大陆 第二季, so it floors the prefix. This one is the
    screen gate, and it is read while the page is still repainting: a wrong 'drifted' throws
    away a whole drama the user paid to open, while a wrong 'keep going' is caught one layer
    down by the traffic gate (which refuses another book's pages by id). So the bias is to
    proceed, and the one relation the measurement supports — the header is the BASE name and the
    request may carry a season suffix, or the reverse (measured both ways) — is a prefix in
    EITHER direction, at ANY length. Only a name with no prefix relation at all is a drift.
    """
    if not want_norm or not have_norm:
        return False
    return want_norm == have_norm or want_norm.startswith(have_norm) or have_norm.startswith(want_norm)
