"""The ``cooccur`` step, one module of the analysis op registry (see ops/__init__.py)."""

import logging

import pandas as pd

from i18n import t
from services.analysis.kernels import UnknownOperationError
from services.analysis.topic_kernels import COOCCUR_WORD_CAP, _whole

logger = logging.getLogger(__name__)


def cooccur(df: pd.DataFrame, column: str, topn: int = 30, min_count: int = 2, window: int = 0) -> pd.DataFrame:
    """Which words travel together — the co-occurrence edges of 论文's knowledge graph.

    One row per word pair, with the number of posts that contain both (or both within
    ``window`` tokens of each other, when a window is asked for). The paper's other figure
    is a 知识图谱 built from exactly this: two words are related in the graph because readers
    put them in the same sentence, not because a topic model grouped them.

    The candidate words are the corpus TF-IDF list :class:`KeywordExtractor` already ranks
    by how distinctive a term is in THIS table, and the token rule (two characters or more,
    jieba's cut) is the same call — a second tokenizer here would produce a graph whose
    words are not the words the keyword node reports for the same corpus.

    ``topn`` is capped at :data:`COOCCUR_WORD_CAP` and a larger request is refused rather
    than clamped: the graph is complete over its candidates, so quietly keeping 120 of the
    500 words asked for decides WHICH EDGES EXIST, and that is a data choice.
    """
    from itertools import combinations

    from analyzers.keyword import KeywordExtractor

    wanted = _whole(topn, 'cooccur', 'topn')
    if wanted < 2:
        raise UnknownOperationError(t('analysis.cooccur_topn', value=topn, cap=COOCCUR_WORD_CAP))
    if wanted > COOCCUR_WORD_CAP:
        raise UnknownOperationError(t('analysis.cooccur_topn', value=wanted, cap=COOCCUR_WORD_CAP))
    floor = _whole(min_count, 'cooccur', 'min_count')
    if floor < 1:
        raise UnknownOperationError(t('analysis.cooccur_count', value=min_count))
    span = max(0, _whole(window, 'cooccur', 'window'))

    scored = KeywordExtractor().tfidf_corpus(df, text_column=column, topk=wanted, merge=True)
    candidates = {str(word) for word in scored['keyword'].tolist()} if 'keyword' in scored.columns else set()
    if len(candidates) < 2:
        raise UnknownOperationError(t('analysis.cooccur_words', found=len(candidates), topn=wanted))

    counts: dict = {}
    documents = 0
    for text in df[column].dropna().tolist():
        tokens = KeywordExtractor.tokenize(str(text), None)
        sequence = [token for token in tokens if token in candidates]
        if len(sequence) < 2:
            continue
        documents += 1
        size = len(sequence) if span <= 0 else min(span, len(sequence))
        starts = range(1) if size >= len(sequence) else range(len(sequence) - size + 1)
        for start in starts:
            present = sorted(set(sequence[start : start + size]))
            for pair in combinations(present, 2):
                counts[pair] = counts.get(pair, 0) + 1
    edges = [
        {'source': left, 'target': right, 'value': count} for (left, right), count in counts.items() if count >= floor
    ]
    if not edges:
        raise UnknownOperationError(
            t(
                'analysis.cooccur_empty',
                floor=floor,
                top=max(counts.values()) if counts else 0,
                pairs=len(counts),
            )
        )
    # Strongest link first, and one fixed order for ties: the graph's edge width is read
    # from these rows, and a list that reorders itself between runs is a different figure.
    edges.sort(key=lambda edge: (-edge['value'], edge['source'], edge['target']))
    logger.info(
        t(
            'analysis.cooccur_done',
            words=len(candidates),
            docs=documents,
            pairs=len(counts),
            edges=len(edges),
            floor=floor,
        )
    )
    return pd.DataFrame(edges)


# ── The sentiment curve ─────────────────────────────────────
