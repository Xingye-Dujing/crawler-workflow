"""The ``dedupe_similar`` step, one module of the analysis op registry (see ops/__init__.py)."""

import logging

import pandas as pd

from i18n import t
from services.analysis.kernels import UnknownOperationError

logger = logging.getLogger(__name__)


def dedupe_similar(df: pd.DataFrame, column: str, max_distance: int = 8) -> pd.DataFrame:
    """Drop near-duplicate rows — SimHash distance within ``max_distance`` bits.

    What ``drop_duplicates`` cannot see: a comment reposted with one word changed, or
    the same sentence padded to a different length. SimHash puts each comment's
    *meaning-bearing tokens* into 64 bits, so a small edit flips few bits and the row
    collapses into the group it belongs to.

    The first row of each group is kept, matching ``keep='first'`` above, and the
    search is sub-quadratic by banding (see :mod:`services.datasets.dedupe`) — an
    all-pairs scan over a hundred-thousand-row comment table is not a thing this can
    afford, so a distance the banded index cannot prove is refused by name rather than
    answered with a slow scan or a quietly incomplete group.

    The default is 8 rather than the tightest distance that could be justified, and it
    is measured rather than chosen: on hand-written Weibo comments a one-word rewrite
    sits 5–18 bits away while two unrelated comments sit 26–28, so 8 catches the
    clearly-identical rewrites and leaves the genuinely-different ones alone. Raising
    it towards 15 buys recall and spends precision — worth doing per table, with the
    row counts the run reports, rather than once for every table.
    """
    work = df.copy()
    if column not in work.columns:
        return work
    # Imported here, not at module scope: this module is what the app loads on a plain
    # crawl, and the dedupe helpers pull in jieba for tokenising.
    from services.datasets.dedupe import MAX_BANDED_DISTANCE, group_near_duplicates, normalize_text, simhash64

    distance = 8 if max_distance is None else int(max_distance)
    if not 0 <= distance <= MAX_BANDED_DISTANCE:
        raise UnknownOperationError(t('analysis.dedupe_distance', value=distance, max=MAX_BANDED_DISTANCE))
    candidates = []
    for idx, raw in work[column].items():
        if pd.isna(raw):
            continue
        text = str(raw)
        # A comment that is only artifacts has no fingerprint of its own: every such
        # row hashes to the same value, so including them would collapse unrelated
        # rows into one group. They are not duplicates of each other — they are empty.
        if not normalize_text(text):
            continue
        candidates.append((str(idx), simhash64(text)))
    dropped = []
    for group in group_near_duplicates(candidates, max_distance=distance):
        dropped.extend(int(member) for member in group[1:])
    if dropped:
        work = work.drop(index=dropped)
    logger.info(t('analysis.dedupe_similar', n=len(dropped), column=column, distance=distance))
    return work.reset_index(drop=True)
