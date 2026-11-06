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
from services.analysis.kernels import _to_datetime
from services.datasets.dedupe import _band_count, _bands, hamming, normalize_text, simhash64

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


def _author_cell(value) -> str:
    """One 评论者 cell as a name; a missing author is EMPTY, never the string ``'nan'``.

    ``float('nan')`` is truthy, so ``str(value or '')`` kept it. Every deleted-account row then
    became one pseudo-author called nan: the ``not author`` guards never fired, duplicate
    comparisons were skipped BETWEEN all blank-author rows, and a burst was pooled from them.
    """
    if value is None:
        return ''
    try:
        if pd.isna(value):
            return ''
    except (TypeError, ValueError):
        pass
    return str(value).strip()


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
        authors = [_author_cell(a) for a in work[author_column].tolist()]
        # The project's own parser, not ``pd.to_datetime``: our crawlers write
        # ``2022年01月27日 00:59``, which pandas answers with NaT for the WHOLE column — every
        # ``times`` was then empty, so the burst signal was permanently 0 and bot_score silently
        # became "duplicate ratio alone", with the evidence column saying nothing had been found.
        times = _to_datetime(work[time_column])
        hashes = [simhash64(tx) if tx else None for tx in texts]

        dup_partner = [False] * len(work)
        # The pair scan is BANDED, not all-pairs: the same pigeonhole index the dedupe step
        # uses (4 equal bands prove 3 bits — a pair within ``DUP_BITS`` must share one whole
        # band, so only rows sharing a bucket are ever compared). The all-pairs form this
        # used to run is ~10⁸ hamming checks at 10k rows and ~10¹⁰ at 100k — minutes to
        # hours, with no candidate filtering. Any pair the banding never compares is farther
        # than ``DUP_BITS`` by construction, so the verdict is identical, not approximate.
        # The per-row ``cancel_event`` check stays: 停止 lands within one row's candidate
        # scan instead of the whole pass (a run holds the single-run queue while it lives).
        band_count = _band_count(DUP_BITS)
        row_bands = [_bands(value, band_count) if value is not None else None for value in hashes]
        buckets: dict[tuple[int, int], list[int]] = {}
        for index, bands_of_row in enumerate(row_bands):
            if bands_of_row is None:
                continue
            for position, band in enumerate(bands_of_row):
                buckets.setdefault((position, band), []).append(index)
        for i in range(len(work)):
            if cancel_event is not None and cancel_event.is_set():
                from crawlers.core.faults import CrawlerStopped

                raise CrawlerStopped(t('crawl.stopped'))
            if row_bands[i] is None or not authors[i]:
                continue
            seen: set[int] = set()
            for position, band in enumerate(row_bands[i]):
                for j in buckets.get((position, band), ()):
                    if j == i or j in seen:
                        continue
                    seen.add(j)
                    if hashes[j] is None or authors[i] == authors[j] or not authors[j]:
                        continue
                    if hamming(hashes[i], hashes[j]) <= DUP_BITS:
                        dup_partner[i] = True
                        break
                if dup_partner[i]:
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
