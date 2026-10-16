"""水军 / bot likelihood — a recall device for coordinated posting, NOT a classifier.

Astroturfing is a real object of this study's governance concern: the same message pushed by many
accounts, or one account posting in a burst. Neither is visible from a single row, so this op reads
the WHOLE table and annotates every row with a per-AUTHOR signal.

It is deliberately modelled like :mod:`analyzers.aggression`, which this project already treats as a
recall device rather than a verdict:

* it can only see what is IN the table — near-duplicate text across different 评论者, and an
  abnormally short posting window for one author. A coordinated actor that varies its wording and
  its timing is, by construction, missed; that miss is unmeasurable and this module never claims a
  false-negative rate;
* every required column (text, author, time) is refused BY NAME if absent — a missing author column
  is not "no author", it is a mistake that would silently score every row as one author;
* the score is a 0..1 likelihood of "posted in a coordinated way", and the level is a hint, not a
  ban-list. The console prints exactly one line naming the limit so a reader of the run cannot take
  the column for ground truth.

Reuses the same SimHash the dedupe step uses, so "near-identical" means the same thing (a few bits
apart) in both places, not a second private definition of it.
"""

import logging

import pandas as pd

from i18n import t
from services.text_dedupe import hamming, normalize_text, simhash64

logger = logging.getLogger(__name__)

#: How many SimHash bits apart two texts may be to count as the SAME message (matches the dedupe
#: near-duplicate band), and the burst window in minutes an author must fit more than
#: ``BURST_MIN_POSTS`` posts into to be flagged. Both are coarse on purpose: this ranks suspicion,
#: it does not adjudicate it.
DUP_BITS = 3
BURST_WINDOW_MIN = 10
BURST_MIN_POSTS = 5
#: Author-level sub-scores are combined, then cut into levels. ``likely`` is high on purpose: a
#: label that reads like a verdict should only appear when BOTH signals are strong.
SUSPECT_AT = 0.34
LIKELY_AT = 0.67


class BotLikelihoodAnalyzer:
    """Per-author coordinated-posting signal written onto every row."""

    def analyze_dataframe(
        self,
        df: pd.DataFrame,
        text_column: str = '正文',
        author_column: str = '评论者',
        time_column: str = '评论时间',
        cancel_event=None,
    ) -> pd.DataFrame:
        if text_column not in df.columns:
            raise ValueError(t('analysis.bot_col_missing', col=text_column))
        if author_column not in df.columns:
            raise ValueError(t('analysis.bot_col_missing', col=author_column))
        if time_column not in df.columns:
            raise ValueError(t('analysis.bot_col_missing', col=time_column))

        work = df.copy()
        # Row order is preserved so the score lands back on the row it came from; the frame is
        # never reordered (a shuffled output would break the merge-order/SimHash invariants).
        texts = [normalize_text(str(v)) for v in work[text_column].tolist()]
        authors = [str(a or '').strip() for a in work[author_column].tolist()]
        times = pd.to_datetime(work[time_column], errors='coerce')
        hashes = [simhash64(tx) if tx else None for tx in texts]

        dup_partner = [False] * len(work)
        # The pair scan is O(n²). Without a per-row check on ``cancel_event``, 停止
        # pressed during a bot node would not land until the WHOLE scan finished —
        # minutes on a large table, during which the run holds the single-run queue
        # (AGENTS.md: "one run at a time; a busy server queues"). Checking once per
        # outer row bounds the wait to a single row's inner scan.
        for i in range(len(work)):
            if cancel_event is not None and cancel_event.is_set():
                from crawlers.base import CrawlerStopped

                raise CrawlerStopped(t('crawl.stopped'))
            if hashes[i] is None:
                continue
            for j in range(len(work)):
                if i == j or hashes[j] is None or authors[i] == authors[j] or not authors[i] or not authors[j]:
                    continue
                if hamming(hashes[i], hashes[j]) <= DUP_BITS:
                    dup_partner[i] = True
                    break

        author_stats: dict = {}
        for idx, author in enumerate(authors):
            if not author:
                continue
            st = author_stats.setdefault(author, {'n': 0, 'dup': 0, 'times': []})
            st['n'] += 1
            if dup_partner[idx]:
                st['dup'] += 1
            stamp = times.iloc[idx]
            if pd.notna(stamp):
                st['times'].append(stamp)

        # A burst is relative to the corpus: the median author's busiest 10-minute window. An author
        # whose own peak is far above that, and posts enough to have a peak at all, is the signal.
        peaks = []
        for st in author_stats.values():
            if st['n'] >= BURST_MIN_POSTS and len(st['times']) >= BURST_MIN_POSTS:
                peaks.append(_peak_window(st['times']))
        median_peak = (sorted(peaks)[len(peaks) // 2] if peaks else 0) or 0

        scores = []
        levels = []
        evidence = []
        for author in authors:
            st = author_stats.get(author)
            if not st or st['n'] == 0:
                scores.append(0.0)
                levels.append('none')
                evidence.append('')
                continue
            dup_ratio = st['dup'] / st['n']
            peak = _peak_window(st['times']) if st['n'] >= BURST_MIN_POSTS else 0
            burst = 0.0
            if median_peak > 0 and peak > median_peak:
                burst = min(1.0, (peak - median_peak) / (2 * median_peak))
            score = round(0.6 * dup_ratio + 0.4 * burst, 4)
            level = 'likely' if score >= LIKELY_AT else ('suspect' if score >= SUSPECT_AT else 'none')
            notes = []
            if dup_ratio > 0:
                notes.append(t('analysis.bot_evidence_dup', ratio=round(dup_ratio, 2)))
            if burst > 0:
                notes.append(t('analysis.bot_evidence_burst', peak=peak, median=median_peak))
            scores.append(score)
            levels.append(level)
            evidence.append('；'.join(notes))

        work['bot_score'] = scores
        work['bot_level'] = levels
        work['bot_evidence'] = evidence
        flagged = sum(1 for lv in levels if lv != 'none')
        logger.info(t('analysis.bot_done', rows=len(work), flagged=flagged, authors=len(author_stats)))
        logger.warning(t('analysis.bot_limit'))
        return work


def _peak_window(stamps: list) -> int:
    """The most posts an author made inside any single ``BURST_WINDOW_MIN``-minute window."""
    minutes = sorted(int(ts.timestamp() // 60) for ts in stamps)
    best = 0
    left = 0
    for right in range(len(minutes)):
        while minutes[right] - minutes[left] > BURST_WINDOW_MIN:
            left += 1
        best = max(best, right - left + 1)
    return best
