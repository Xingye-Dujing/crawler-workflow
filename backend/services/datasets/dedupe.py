"""Text normalisation and near-duplicate detection for crawled social text.

Two comments that a human would call "the same" never compare equal as raw
strings: a paid comment farm defeats the exact sha1 of ``run_store.item_key``
by appending an emoji code, pasting a different tracking URL, or padding the
sentence with a forward chain. So identity here is computed over a *normalised*
form, and ``normalize_text`` is deliberately lossy — it exists for identity
only. Never render its output: it destroys the author's spacing, topics and
emoticons, which is exactly the material the analysis layer displays.

The second half of the module answers the harder question: two comments that
are *nearly* identical. SimHash compresses one comment into 64 bits so that
small edits flip few bits, and ``group_near_duplicates`` finds the pairs whose
bit difference is at most ``max_distance`` **without comparing every pair** —
cutting the hash into enough equal bands that a close pair must agree on one of
them makes the search sub-quadratic, which is the whole reason a
hundred-thousand-row comment table can be deduplicated at all. How wide that
banding can be stretched is ``MAX_BANDED_DISTANCE``, and the measured reason it
is 15 rather than 3 is written beside it.
"""

import hashlib
import re
import unicodedata
from collections import Counter

import jieba

# ─── Patterns ───

# Zero-width and BOM characters are invisible in the UI, so they are the
# cheapest edit a comment farm can make: two rows render identically and hash
# differently. U+200B..U+200D (ZWSP/ZWNJ/ZWJ), U+FEFF (BOM/ZWNBSP),
# U+2060 (word joiner), U+00AD (soft hyphen) and the bidi isolates.
_INVISIBLE_RE = re.compile('[\u200b-\u200d\u2060\ufeff\u00ad\u2066-\u2069]')

# Weibo renders every emoji as a bracket code. Latin codes ("[doge]") are
# recognisable by shape; Chinese ones ("[微笑]") are not distinguishable from
# real prose by shape, so they are matched against the emoticon names Weibo
# actually serves. This is an allow-list on purpose: a shape that stripped
# every bracketed Chinese word would delete "[免费]领券" — the comment itself.
# A code outside the list is left in place, which costs a duplicate match for
# an uncommon emoticon; a wildcard would cost the text.
_EMOJI_CODE_RE = re.compile(r'\[[A-Za-z0-9_]{1,16}\]|\[[\u4e00-\u9fff]{1,4}\]')
_EMOJI_NAMES = frozenset(
    [
        '微笑',
        '大笑',
        '偷笑',
        '挤眼',
        '酷',
        '汗',
        '泪',
        '哭',
        '哈哈',
        '嘻嘻',
        '可爱',
        '爱你',
        '花心',
        '亲亲',
        '允悲',
        '喵喵',
        '太开心',
        '思考',
        '嘘',
        '并不简单',
        '费解',
        '疑问',
        '汗颜',
        '害怕',
        '可怜',
        '失望',
        '怒',
        '抓狂',
        '晕',
        '衰',
        '骷髅',
        '敲打',
        '手心',
        '胜利',
        '握手',
        '抱拳',
        '勾引',
        '拳头',
        '差劲',
        '干杯',
        '礼物',
        '蛋糕',
        '蜡烛',
        '炸弹',
        '便便',
        '咖啡',
        '围脖',
        '赞',
        '鼓掌',
        '心',
        '伤心',
        '围观',
        '威武',
        '钟',
        '麦克风',
        '沙漏',
        '飞机',
        '汽车',
        '房子',
        '月亮',
        '太阳',
        '星星',
        '闪电',
        '下雨',
        '雪花',
        '熊猫',
        '兔子',
        '猪头',
        '公鸡',
        '狗',
        '猴子',
        '老虎',
        '牛',
        '猫',
        '章鱼',
        '螃蟹',
        '蜜蜂',
        '玫瑰',
        '凋谢',
        '向日葵',
        '树叶',
        '大米',
        '面包',
        '啤酒',
        '饮料',
        '茶',
        '苹果',
        '香蕉',
        '西瓜',
        '草莓',
        '樱桃',
        '葡萄',
        '桔子',
        '柠檬',
    ]
)

# The crawlers emit URLs in four shapes, listed here in the order they must be
# removed: a real href, the literal anchor text Weibo serves to scripts
# (O网页链接 / 网页链接), the truncated "展开<digits>" tail that marks a
# collapsed body, and the video-link suffix. Each is matched with its own
# trailing boundary so prose that merely starts with the same word survives.
_URL_RE = re.compile(r'https?://\S+|www\.\S+')
_LINK_TEXT_RE = re.compile(r'[Oo]?网页链接')
_EXPAND_RE = re.compile(r'(?:展开|收起)[0-9A-Za-z]{1,3}')
# The bare marker (no suffix) is only removed where a sentence cannot follow
# it, so prose like "请展开说说" survives.
_EXPAND_TAIL_RE = re.compile(r'(?:展开|收起)(?=$|\s)')
_VIDEO_RE = re.compile(r'L?微博视频[0-9A-Za-z]*')

# "@somebody" may appear anywhere. A colon right after the name is the reply
# marker and belongs to the same token, so it is consumed with it — otherwise
# the leftover ":" outlives the name it introduced and two spellings of the
# same reply stop matching. The name itself ends at punctuation or whitespace.
_MENTION_NAME = r'[^\s@:：,，。！？!?、；;/]{1,30}'
_MENTION_RE = re.compile(rf'@{_MENTION_NAME}[:：]?')
_REPLY_PREFIX_RE = re.compile(rf'^\s*(?:回复)?\s*@{_MENTION_NAME}\s*[:：]\s*')

# A forward chain is "//@who:原文", and Weibo puts the REPOSTER'S OWN comment in
# FRONT of the marker — so the head is the text being deduplicated ("同感//@a:说得对"
# is the commenter's "同感") and everything from the first marker on is other
# people's words. The tail is kept only when the head carries nothing but a reply
# prefix, because then the head is UI chrome rather than a comment. The marker
# itself allows a trailing space before the name, since the page renders
# "//@某人: 内容" with one.
_FORWARD_CHAIN_RE = re.compile(rf'//\s*[^\s@:：]*\s*@{_MENTION_NAME}\s*[:：]\s*')

# A topic marker wraps words the user *did* write, so only the hashes go; the
# words stay in the identity.
_TOPIC_RE = re.compile(r'#[^#]{0,40}#')

# A comment farm changes the length of a laugh, never its meaning. Runs longer
# than two collapse to two, in every script ("哈哈哈哈哈哈" == "哈哈").
_CHAR_RUN_RE = re.compile(r'(.)\1{2,}')
_WHITESPACE_RE = re.compile(r'\s+')


# ─── Helpers ───


def _is_reply_prefix_only(text: str) -> bool:
    """True when ``text`` is nothing but a "回复@who:" prefix.

    The forward-chain guard needs to tell "the commenter wrote 同感 and then
    quoted someone" from "the UI labelled this a reply"; both start with text,
    and only the second one may be discarded.
    """
    match = _REPLY_PREFIX_RE.match(text)
    return bool(match) and not text[match.end() :].strip()


def _strip_emoji_codes(value: str) -> str:
    """Drop the bracket codes Weibo uses for emoticons.

    The substitution runs through a callback so the allow-list lookup happens
    only for the codes the cheap shape match already found — the common comment
    has none, and this runs once per row over the whole table.
    """

    def replace(match: re.Match) -> str:
        code = match.group()[1:-1]
        # Latin codes are emoticon codes by shape alone; only the Chinese ones
        # need the allow-list, because "[免费]" is a word.
        keep = not code.isascii() and code not in _EMOJI_NAMES
        return match.group() if keep else ' '

    return _EMOJI_CODE_RE.sub(replace, value)


# ─── Banding ───

# 64 bits split into a power-of-two number of EQUAL bands. Pigeonhole: two
# hashes that differ in at most ``bands - 1`` bits cannot differ in every band,
# so they must agree on at least one — which is what makes a bucket lookup
# sufficient instead of an all-pairs scan.
#
# The band count therefore follows the distance the CALLER asked for: 4 bands
# prove 3 bits, 8 prove 7, 16 prove 15. More bands than strictly needed only
# adds candidate pairs, never misses one, so the count is the smallest power of
# two that covers the request. Fixing it at 4 (as this was) is not a property
# of the data but an accident of the arithmetic — and it made the feature almost
# useless on the corpus it was written for: measured on hand-written Weibo
# comments, a one-word rewrite sits 6–18 bits away, so a 3-bit search finds
# essentially nothing that the normalised-exact key did not already find.
_BIT_WIDTH = 64

# Where the buckets stop being a filter. Unrelated comments measured 26–28 bits
# apart, so 15 is already deep into "these two may be different" territory; past
# it almost every short comment shares a bucket with its neighbours and the
# "fast" path degenerates into the quadratic scan it exists to avoid. Refused by
# name rather than served slowly.
MAX_BANDED_DISTANCE = 15


def _band_count(max_distance: int) -> int:
    """The smallest power-of-two band count that can prove ``max_distance`` bits."""
    bands = 1
    while bands <= max_distance:
        bands <<= 1
    return bands


# ─── Normalisation ───


def normalize_text(text: str) -> str:
    """Reduce a comment to the residue that identifies it — identity only.

    Every step here answers a specific farm trick: invisible padding, an
    emoji code, a fresh tracking URL, an added mention, a pasted forward
    chain, a longer laugh. The output is NOT display text; it is what
    ``normalized_key`` hashes and what ``simhash64`` tokenises, so it must
    stay cheap (module-level regexes, one pass each) because the analysis
    layer calls it once per row over tables of hundreds of thousands.
    """
    if not text:
        return ''
    value = _INVISIBLE_RE.sub('', str(text))
    # Full-width ASCII and CJK punctuation differ from their half-width forms
    # only by code point, so folding them first lets every later rule be
    # written once (a farm's "，" and "," must not produce two identities).
    value = unicodedata.normalize('NFKC', value)
    # Order matters. The collapsed-body tail and the video/link anchor text are
    # removed before the generic URL rule, because a leftover 展开62 would
    # otherwise be tokenised as prose and the "O网页链接" anchor's ASCII "O"
    # would survive as a one-character identity of its own.
    value = _EXPAND_RE.sub(' ', value)
    value = _EXPAND_TAIL_RE.sub(' ', value)
    value = _VIDEO_RE.sub(' ', value)
    value = _LINK_TEXT_RE.sub(' ', value)
    value = _URL_RE.sub(' ', value)
    value = _strip_emoji_codes(value)
    value = _TOPIC_RE.sub(lambda match: match.group().strip('#'), value)
    # The chain is cut first: everything after the last marker is the comment
    # the user actually wrote, and cutting before the reply/mention rules means
    # they only ever see the surviving segment's own prefix. The text in front
    # of the marker is kept when it carries anything — "同感//@a:说得对" is the
    # commenter's "同感" — but a bare reply prefix is UI chrome, not a comment,
    # so it is dropped and the quoted original survives instead.
    chain_matches = list(_FORWARD_CHAIN_RE.finditer(value))
    if chain_matches:
        head = value[: chain_matches[0].start()]
        # The head is the reposter's own words; the tail is only reached when the head is
        # nothing but a reply prefix, because then the head is UI chrome rather than text.
        keeps_head = bool(head.strip()) and not _is_reply_prefix_only(head)
        value = head if keeps_head else value[chain_matches[-1].end() :]
    value = _REPLY_PREFIX_RE.sub('', value)
    value = _MENTION_RE.sub(' ', value)
    value = _CHAR_RUN_RE.sub(r'\1\1', value)
    value = _WHITESPACE_RE.sub(' ', value)
    return value.strip()


def normalized_key(text: str) -> str:
    """sha1 of the normalised text — the "same comment" key.

    Separate from ``normalize_text`` so callers that only compare two rows do
    not carry a 40-character string per row, and so the key stays stable if
    the normalisation gains a rule (a stored key is a contract).
    """
    return hashlib.sha1(normalize_text(text).encode('utf-8')).hexdigest()


# ─── SimHash ───


def _token_hash(token: str) -> int:
    """64-bit hash of one token, reproducible in every process.

    Python's builtin ``hash()`` is salted per process (PYTHONHASHSEED), so a
    simhash built on it would differ between two runs over the same table —
    the near-duplicate groups would change run to run, which is a correctness
    bug, not a style choice. sha1's first 8 bytes are stable forever.
    """
    return int.from_bytes(hashlib.sha1(token.encode('utf-8')).digest()[:8], 'big')


def simhash64(text: str) -> int:
    """64-bit SimHash of the normalised text, over jieba tokens.

    Each token votes on every bit with a weight of its frequency; the sign of
    the total decides the bit. Near-identical comments therefore land a few
    bits apart, which is what ``group_near_duplicates`` searches. Empty text
    has no tokens and hashes to 0 — callers should not treat that as a real
    fingerprint (every noise-only comment shares it by construction).
    """
    normalized = normalize_text(text)
    if not normalized:
        return 0
    votes = [0] * 64
    # Frequency weighting rather than a set: a token repeated in the comment is
    # more of what the comment is about, and jieba re-emits ordinary words.
    for token, weight in Counter(jieba.lcut(normalized)).items():
        if not token.strip():
            continue
        token_hash = _token_hash(token)
        for bit in range(64):
            votes[bit] += weight if token_hash >> bit & 1 else -weight
    value = 0
    for bit in range(64):
        if votes[bit] > 0:
            value |= 1 << bit
    return value


def hamming(a: int, b: int) -> int:
    """Bit difference of two 64-bit fingerprints (popcount of the xor)."""
    return (a ^ b).bit_count()


# ─── Grouping ───


def _bands(value: int, count: int) -> tuple:
    """The ``count`` equal slices banding buckets on, lowest slice first."""
    width = _BIT_WIDTH // count
    return tuple((value >> (index * width)) & ((1 << width) - 1) for index in range(count))


def group_near_duplicates(items: list[tuple[str, int]], max_distance: int = 3) -> list[list[str]]:
    """Group ids whose simhashes are within ``max_distance`` bits.

    ``items`` is ``(id, simhash64)``. Grouping is by connected component, so a
    chain A-b-B-b-C reports A, B and C once rather than C(n,2) overlapping
    pairs — a duplicate cluster is one group to review, and the caller must
    see each id exactly once. Singletons are not results (an ungrouped id is
    the absence of a duplicate) so they are omitted.

    The search is sub-quadratic by banding, not by clever distance maths: the
    hash is cut into enough equal bands that any pair within ``max_distance``
    must agree on at least one whole band, so only ids sharing a bucket are ever
    compared. A caller asking for more than the banding can prove is refused
    *by name* rather than silently given an all-pairs scan (or quietly wrong
    groups).
    """
    if max_distance > MAX_BANDED_DISTANCE:
        raise ValueError(
            f'max_distance={max_distance} exceeds the banded search limit of {MAX_BANDED_DISTANCE}: '
            'a wider index stops filtering and the search becomes the all-pairs scan it exists to avoid'
        )
    if max_distance < 0:
        raise ValueError(f'max_distance={max_distance} is not a bit distance')

    band_count = _band_count(max_distance)
    ids = [str(item_id) for item_id, _ in items]
    fingerprints = [int(hash) for _, hash in items]

    parent = list(range(len(ids)))

    def find(index: int) -> int:
        # Path halving keeps the union-find flat without recursion (a comment
        # table can be deep enough to hit the recursion limit).
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    for band in range(band_count):
        buckets: dict[int, list[int]] = {}
        for index, value in enumerate(fingerprints):
            buckets.setdefault(_bands(value, band_count)[band], []).append(index)
        for bucket in buckets.values():
            for position, left in enumerate(bucket):
                for right in bucket[position + 1 :]:
                    if hamming(fingerprints[left], fingerprints[right]) <= max_distance:
                        union(left, right)

    grouped: dict[int, list[str]] = {}
    for index, item_id in enumerate(ids):
        grouped.setdefault(find(index), []).append(item_id)
    # Insertion order is the caller's order, so a group starts at the first
    # member the caller listed — the same table groups the same way twice.
    return [members for members in grouped.values() if len(members) > 1]
