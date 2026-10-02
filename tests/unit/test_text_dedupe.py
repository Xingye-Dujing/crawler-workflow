"""Tests for services/text_dedupe.py — identity and near-duplicate text rules.

Two properties carry the whole module. First, ``normalize_text`` reduces a
comment to the residue that identifies it, so every rule below is pinned with a
string a real crawl produced: the crawler's URL shapes, Weibo's reply/forward
chrome and its emoji codes. Second, the near-duplicate search must be banded,
not all-pairs — a hundred-thousand-row comment table is the stated input — and
banding is only sound while the pigeonhole argument holds, so that argument is
measured here rather than trusted.

The failure this pins is expensive: an identity that moves between runs
(salted ``hash``) or a group that misses a pair turns a paid comment farm into
"unique rows", and the user pays to analyse the same comment twice.
"""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from services.text_dedupe import (
    group_near_duplicates,
    hamming,
    normalize_text,
    normalized_key,
    simhash64,
)

pytestmark = pytest.mark.unit

# ``tests/`` is imported with the project root and ``backend/`` on sys.path
# (tests/conftest.py); a fresh interpreter starts with neither, so the
# subprocess check below has to hand backend/ over explicitly.
_BACKEND_DIR = Path(__file__).resolve().parents[2] / 'backend'


def _simhash_in_subprocess(hash_seed: str) -> int:
    """Compute the pinned fingerprint in a fresh interpreter.

    The seed only matters because it changes ``hash()``: the value must not
    move with it.
    """
    script = (
        'from services.text_dedupe import simhash64; '
        "print(hex(simhash64('\u4e09\u4e9a\u7684\u6d77\u975e\u5e38\u84dd\uff0c\u9002\u5408\u51ac\u5929\u5ea6\u5047\u6f5c\u6c34')))"
    )
    environment = {**os.environ, 'PYTHONPATH': str(_BACKEND_DIR), 'PYTHONHASHSEED': hash_seed}
    completed = subprocess.run(
        [sys.executable, '-c', script],
        capture_output=True,
        check=True,
        env=environment,
        text=True,
    )
    return int(completed.stdout.strip(), 16)


# One realistic comment, used where the point is the *combination* of rules.
REAL_COMMENT = 'http://t.cn/A6xYz 哈哈哈哈哈哈 @小明 回复@小红: 今天天气真好 #美食# [doge] 网页链接'

# The same sentence in the four spellings a farm buys: a tracking URL, a
# mention, an emoji code and padding whitespace. They must all hash alike.
SAME_COMMENT = [
    '三亚的海非常蓝，适合冬天度假潜水',
    '三亚的海非常蓝，适合冬天度假潜水 ',
    '  三亚的海非常蓝，适合冬天度假潜水\n',
    '三亚的海非常蓝，适合冬天度假潜水http://t.cn/A6xYz',
    '三亚的海非常蓝，适合冬天度假潜水[微笑]',
    '三亚的海非常蓝，适合冬天度假潜水 @好友',
    '三亚的海非常蓝，适合冬天度假潜水　',
]

# A comment the normalisation cannot reduce to nothing, so a caller can
# distinguish "this is noise" from "this is a comment".
SAME_COMMENT_ANCHOR = '三亚的海非常蓝，适合冬天度假潜水'

# A longer pair for the near-duplicate rules, where one edited character is a
# small enough share of the comment for SimHash to land inside max_distance.
# The short anchor above sits 5+ bits from its own one-word edits, which is
# exactly why near-duplicate detection is a separate pass and not the key.
NEAR_COMMENT = '三亚的海非常蓝，适合冬天度假潜水，十一月份去人不多，机票也便宜，酒店推荐亚龙湾，海鲜市场记得讲价'
EDITED_COMMENT = '三亚的海非常蓝，适合冬天度假潜水，十一月份去人不多，机票也便宜，酒店推荐亚龙湾，海鲜市场记得砍价'
UNRELATED_COMMENT = '海口的海南粉汤底非常鲜美，值得专程去吃，骑楼老街晚上很热闹，可以顺便逛逛，打车过去十几分钟'
OTHER_COMMENT = '今天股市大跌，心情很不好，观望了一整天还是没敢加仓'


class TestInvisibleAndWidth:
    """Invisible characters and full/half-width folding run first."""

    def test_zero_width_and_bom_padding_is_removed(self):
        # A zero-width space renders as nothing, so two rows *look* identical
        # while hashing differently — the cheapest farm edit there is.
        assert normalize_text('今天天气真好\u200b\ufeff') == normalize_text('今天天气真好')

    def test_the_bom_does_not_survive_as_a_character(self):
        assert '\ufeff' not in normalize_text('\ufeff今天天气真好')

    def test_full_width_ascii_folds_to_half_width(self):
        assert normalize_text('ＡＢＣ１２３') == 'ABC123'

    def test_full_width_punctuation_folds_to_half_width(self):
        # The fold has to reach punctuation too, or a full-width comma and an
        # ASCII comma are two different comments.
        assert normalize_text('今天天气真好，推荐') == '今天天气真好,推荐'


class TestCrawlerArtefacts:
    """URLs, link anchor text, collapsed bodies and video suffixes."""

    @pytest.mark.parametrize(
        'artefact',
        [
            'http://t.cn/A6xYz',
            'https://weibo.com/1234567/abcdef',
            'O网页链接',
            '网页链接',
            '展开c',
            '收起c',
            'L微博视频',
        ],
    )
    def test_each_emitted_artefact_is_removed(self, artefact):
        text = f'今天天气真好 {artefact}'
        assert normalize_text(text) == '今天天气真好'

    def test_a_collapsed_body_tail_with_digits_is_removed(self):
        assert normalize_text('原帖正文 展开62') == '原帖正文'

    def test_the_link_anchor_prefix_does_not_survive_as_a_letter(self):
        # "O网页链接" is the ASCII O plus the anchor text; removing only the
        # CJK half would leave a one-character comment behind.
        assert normalize_text('O网页链接 L微博视频 展开62') == ''

    def test_prose_that_merely_starts_with_the_same_words_survives(self):
        # Over-stripping is as expensive as under-stripping: it deletes the
        # comment. "展开说说" is a sentence, not the collapsed-body marker.
        assert normalize_text('请展开说说你的想法') == '请展开说说你的想法'


class TestMentionsAndReplies:
    """@ mentions, reply prefixes and forward chains."""

    def test_a_mid_sentence_mention_goes_but_the_sentence_stays(self):
        assert normalize_text('@小明 我觉得不错') == '我觉得不错'

    def test_the_reply_prefix_goes(self):
        assert normalize_text('回复@小红: 今天天气真好') == '今天天气真好'

    def test_the_reply_marker_does_not_outlive_the_name_it_introduced(self):
        # The ":" is part of the reply token; left behind it becomes a
        # one-character identity shared by every reply.
        assert normalize_text('回复@小红:今天天气真好') == '今天天气真好'

    def test_a_bare_forward_chain_keeps_the_original_segment(self):
        # Weibo puts the commenter's own words FIRST and the quoted words
        # after "//@who:", so the trailing segment is the comment.
        assert normalize_text('//@a:说得对//@b:确实如此') == '确实如此'

    def test_a_two_link_chain_is_reduced_to_the_last_segment(self):
        assert normalize_text('//@a:说得对 //@b: 确实如此') == '确实如此'

    def test_the_commenters_own_words_before_a_chain_are_kept(self):
        # Cutting on every marker would delete the sentence under test: here
        # "同感" is what the user wrote and the rest is someone else's.
        assert normalize_text('同感//@a:说得对//@b:确实如此') == '同感'

    def test_a_reply_prefix_before_a_chain_is_chrome_not_a_comment(self):
        assert normalize_text('回复@a: //@b:这个观点很对') == '这个观点很对'


class TestTopicsAndEmojiCodes:
    """Topic markers keep their words; emoji codes and laughing runs collapse."""

    def test_topic_hashes_go_but_the_words_stay(self):
        assert normalize_text('今天天气真好#美食#') == '今天天气真好美食'

    def test_an_emoji_coded_comment_is_recognisable_after_stripping(self):
        assert normalize_text('今天天气真好 [doge]') == normalize_text('今天天气真好')

    def test_an_emoji_only_comment_normalises_to_nothing(self):
        assert normalize_text('[doge]') == ''
        assert normalize_text('[微笑][微笑][微笑]') == ''

    def test_a_bracketed_chinese_word_is_not_an_emoji_code(self):
        # "[免费]" is prose, not a code; stripping it would delete content.
        assert normalize_text('[免费]领券') == '[免费]领券'

    def test_a_long_laugh_is_the_same_laugh(self):
        assert normalize_text('哈哈哈哈哈哈') == normalize_text('哈哈')

    def test_whitespace_runs_collapse_to_one_space(self):
        assert normalize_text('今天  天气\t真好') == '今天 天气 真好'


class TestNoise:
    """A comment made only of chrome must not become a text identity."""

    @pytest.mark.parametrize(
        'noise',
        [
            'http://t.cn/A6xYz',
            'O网页链接',
            '网页链接 展开c',
            '[doge]',
            '@小明',
            '回复@小明:',
            '//@a:',
            # Written with chr() because a "\u200b" escape inside a parametrize
            # list reaches the test as six literal characters, which would make
            # this cell pass for the wrong reason.
            chr(0x200B) + chr(0xFEFF) + '  \n',
            '',
        ],
    )
    def test_pure_noise_normalises_to_an_empty_string(self, noise):
        # Empty is the one value callers can test for; a leftover ":" or "回复"
        # would silently group every noisy row together as duplicates.
        assert normalize_text(noise) == ''

    def test_none_is_not_text(self):
        assert normalize_text(None) == ''

    def test_normalisation_is_idempotent(self):
        # Callers may store the normalised form; running the rules over their
        # own output must not change the identity.
        for text in [REAL_COMMENT, '同感//@a:说得对', '哈哈哈哈哈哈', '[doge]', SAME_COMMENT_ANCHOR]:
            once = normalize_text(text)
            assert normalize_text(once) == once


class TestNormalizedKey:
    """The "exact duplicate after normalisation" key."""

    def test_url_mentions_emoji_and_whitespace_do_not_change_the_key(self):
        keys = {normalized_key(text) for text in SAME_COMMENT}
        assert len(keys) == 1
        assert keys != {''}

    def test_two_genuinely_different_comments_do_not_collide(self):
        assert normalized_key(SAME_COMMENT_ANCHOR) != normalized_key('糟糕的体验，服务很差劲不推荐')

    def test_a_raw_sha1_of_the_text_would_not_have_matched(self):
        # The rule this module replaces: item_key's exact sha1 over the raw
        # field sees one emoji and calls the comment new.
        raw = hashlib.sha1('三亚的海非常蓝，适合冬天度假潜水[微笑]'.encode()).hexdigest()
        assert raw != normalized_key('三亚的海非常蓝，适合冬天度假潜水')

    def test_the_key_is_sha1_of_the_normalised_text(self):
        assert (
            normalized_key(SAME_COMMENT_ANCHOR)
            == hashlib.sha1(normalize_text(SAME_COMMENT_ANCHOR).encode('utf-8')).hexdigest()
        )


class TestSimHash:
    """Deterministic 64-bit fingerprints over jieba tokens."""

    def test_repeated_calls_in_one_process_agree(self):
        assert simhash64(REAL_COMMENT) == simhash64(REAL_COMMENT)

    def test_the_value_is_pinned_to_a_constant(self):
        # The load-bearing promise is *reproducibility across processes*, and
        # builtin hash() is salted per process, so this constant — computed
        # once and pasted here — is what a salted hash would break. It changes
        # only if the normalisation or the jieba dictionary does.
        assert simhash64('三亚的海非常蓝，适合冬天度假潜水') == 0x558CACB249552106

    def test_two_processes_with_different_hash_seeds_agree(self):
        # PYTHONHASHSEED perturbs ``hash()`` and nothing else, so a simhash
        # that leaned on it would print a different constant here while the
        # in-process test above stayed green. This is the only honest way to
        # observe the salt.
        assert _simhash_in_subprocess('0') == _simhash_in_subprocess('12345') == 0x558CACB249552106

    def test_a_private_sha1_token_hash_is_what_produces_the_bits(self):
        # Guards the other direction: someone "fixing" the fingerprint by
        # swapping in a faster non-cryptographic hash. Two tokens that agree
        # today must keep agreeing tomorrow.
        from services.text_dedupe import _token_hash

        assert _token_hash('三亚') == int.from_bytes(hashlib.sha1('三亚'.encode()).digest()[:8], 'big')
        assert _token_hash('aa') != _token_hash('ab')

    def test_identical_normalised_text_hashes_identically(self):
        for text in SAME_COMMENT:
            assert simhash64(text) == simhash64(SAME_COMMENT_ANCHOR)

    def test_an_edit_turns_only_a_few_bits(self):
        base = simhash64(NEAR_COMMENT)
        # One character changed costs 3 bits — the pinned measurement, so a
        # normalisation regression that re-tokenises the text shows up here.
        assert hamming(base, simhash64(EDITED_COMMENT)) == 3
        assert hamming(base, simhash64(UNRELATED_COMMENT)) > 15
        assert hamming(base, simhash64(OTHER_COMMENT)) > 15

    def test_a_short_comment_is_more_sensitive_than_a_long_one(self):
        # The reason near-duplicates need their own pass: on a short comment a
        # one-word edit already exceeds the banded limit, while the key rule
        # (normalize_text + sha1) cannot see the edit at all.
        short = simhash64(SAME_COMMENT_ANCHOR)
        assert hamming(short, simhash64(SAME_COMMENT_ANCHOR + '，推荐')) > 3
        assert normalized_key(SAME_COMMENT_ANCHOR) != normalized_key(SAME_COMMENT_ANCHOR + '，推荐')

    def test_a_noise_only_comment_has_no_fingerprint(self):
        # Documented consequence of hashing nothing: every noise row shares 0,
        # so this is a value callers must not treat as "the same comment".
        assert simhash64('[doge]') == 0


class TestHamming:
    def test_distance_is_the_popcount_of_the_xor(self):
        assert hamming(0b1011, 0b0001) == 2
        assert hamming(0, 0) == 0
        assert hamming(0, 0xFFFFFFFFFFFFFFFF) == 64

    def test_it_is_symmetric(self):
        assert hamming(0xDEADBEEF, 0x12345678) == hamming(0x12345678, 0xDEADBEEF)


class TestGroupNearDuplicates:
    """Banded grouping: each id in exactly one group, never a singleton."""

    def test_two_near_identical_comments_are_grouped(self):
        base = simhash64(NEAR_COMMENT)
        near = simhash64(EDITED_COMMENT)
        assert hamming(base, near) <= 3
        assert group_near_duplicates([('row-1', base), ('row-2', near)]) == [['row-1', 'row-2']]

    def test_a_longer_laugh_does_not_make_a_new_comment(self):
        base = simhash64(NEAR_COMMENT)
        near = simhash64(NEAR_COMMENT + '哈哈')
        assert group_near_duplicates([('row-1', base), ('row-2', near)]) == [['row-1', 'row-2']]

    def test_unrelated_comments_are_not_grouped(self):
        left = simhash64(NEAR_COMMENT)
        right = simhash64(UNRELATED_COMMENT)
        assert group_near_duplicates([('row-1', left), ('row-2', right)]) == []

    def test_an_id_appears_in_exactly_one_group(self):
        base = simhash64(SAME_COMMENT_ANCHOR)
        items = [
            ('a', base),
            ('b', base),
            ('c', base ^ 0b111),
            ('d', simhash64(OTHER_COMMENT)),
        ]
        groups = group_near_duplicates(items)
        flattened = [item_id for group in groups for item_id in group]
        assert sorted(flattened) == ['a', 'b', 'c']
        assert len(flattened) == len(set(flattened))

    def test_singletons_are_not_reported_as_duplicates(self):
        # One row is the absence of a duplicate, not a group of one; a caller
        # that received it would delete every row it ever passed in.
        assert group_near_duplicates([('only', simhash64(SAME_COMMENT_ANCHOR))]) == []

    def test_an_over_large_distance_is_refused_by_name(self):
        # Silently scanning all pairs instead would be a different complexity
        # class than the caller budgeted for; silently returning *wrong* groups
        # would be worse, so the parameter is named in the refusal. The bound is
        # read from the module rather than pasted: it is a property of how many
        # bands the search can afford, and it moved once already (4 → 16 bands,
        # because a 3-bit search found nothing on real Weibo comments).
        from services.text_dedupe import MAX_BANDED_DISTANCE

        with pytest.raises(ValueError, match='max_distance'):
            group_near_duplicates([('a', 0), ('b', 1)], max_distance=MAX_BANDED_DISTANCE + 1)

    def test_the_widest_provable_distance_is_still_served(self):
        from services.text_dedupe import MAX_BANDED_DISTANCE

        # A pair three bits apart is found at every distance that claims to cover it,
        # including the widest one — the band count follows the request.
        left, right = 0, (1 << 0) | (1 << 16) | (1 << 32)
        assert group_near_duplicates([('a', left), ('b', right)], max_distance=MAX_BANDED_DISTANCE) == [['a', 'b']]

    def test_a_negative_distance_is_refused_by_name(self):
        with pytest.raises(ValueError, match='max_distance'):
            group_near_duplicates([('a', 0)], max_distance=-1)

    def test_empty_input_has_no_groups(self):
        assert group_near_duplicates([]) == []


class TestBandingCorrectness:
    """The pigeonhole property the sub-quadratic fast path depends on."""

    def test_three_bits_in_three_different_bands_are_still_found(self):
        # One bit set per band in the SAME position of bands 0, 1 and 2 is what makes the
        # difference exactly three: moving a bit *within* a band would clear one bit and
        # set another, which is two differences and would silently turn this into a 6-bit
        # pair that the 3-bit search is not claiming to find. Band 3 is populated
        # identically in both hashes, so the agreeing band this test leans on is a real
        # bucket holding a real bit, not the empty bucket every hash agrees on.
        shared_band_3_bit = 1 << 48
        left = shared_band_3_bit
        right = shared_band_3_bit | (1 << 0) | (1 << 16) | (1 << 32)
        assert hamming(left, right) == 3
        # Bands 0, 1 and 2 each differ; band 3 is where the pair meets. One agreeing band
        # is exactly what the pigeonhole argument promises for a 3-bit difference across 4
        # bands, and the grouping is the proof that this pair was actually compared.
        assert [((left >> 16 * band) & 0xFFFF) == ((right >> 16 * band) & 0xFFFF) for band in range(4)] == [
            False,
            False,
            False,
            True,
        ]
        assert group_near_duplicates([('left', left), ('right', right)]) == [['left', 'right']]

    @pytest.mark.parametrize('max_distance', [0, 1, 2, 3])
    def test_the_banded_result_agrees_with_an_exhaustive_scan(self, max_distance):
        # The fast path is only allowed to be *faster*, never different.
        fingerprints = [
            simhash64(NEAR_COMMENT),
            simhash64(EDITED_COMMENT),
            simhash64(NEAR_COMMENT + '哈哈'),
            simhash64(UNRELATED_COMMENT),
            simhash64(OTHER_COMMENT),
            0,
            0b111,
            0b111000,
            # Hand-built hashes so the grid covers an exact 3-bit pair spread
            # across three bands, not only whatever jieba's text produced.
            (1 << 0) | (1 << 16) | (1 << 32),
            (1 << 15) | (1 << 31) | (1 << 32),
        ]
        items = [(f'row-{index}', value) for index, value in enumerate(fingerprints)]

        banded = {frozenset(group) for group in group_near_duplicates(items, max_distance=max_distance)}

        # The same connected components, computed the expensive way. Any pair
        # the banding missed shows up as a smaller component set here.
        parent = list(range(len(items)))

        def find(index):
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        for left in range(len(items)):
            for right in range(left + 1, len(items)):
                if hamming(items[left][1], items[right][1]) <= max_distance:
                    left_root, right_root = find(left), find(right)
                    if left_root != right_root:
                        parent[right_root] = left_root
        exhaustive = {}
        for index, (item_id, _) in enumerate(items):
            exhaustive.setdefault(find(index), set()).add(item_id)
        assert banded == {frozenset(group) for group in exhaustive.values() if len(group) > 1}

    def test_a_chain_of_near_duplicates_is_one_group(self):
        # A-B and B-C within distance is a cluster a reviewer sees once, not
        # two overlapping pairs.
        base = simhash64(NEAR_COMMENT)
        groups = group_near_duplicates(
            [('a', base), ('b', base ^ 0b1), ('c', base ^ 0b11), ('d', simhash64(OTHER_COMMENT))]
        )
        assert sorted(groups[0]) == ['a', 'b', 'c']
        assert len(groups) == 1
