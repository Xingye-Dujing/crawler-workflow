"""The ``topic_coherence`` step, one module of the analysis op registry (see ops/__init__.py)."""

import logging
import math

import pandas as pd

from i18n import t
from services.analysis.kernels import UnknownOperationError, _stable_seed
from services.analysis.topic_kernels import _fit_topic_model, _token_set, _whole

logger = logging.getLogger(__name__)


def topic_coherence(
    df: pd.DataFrame,
    column: str,
    min_topics: int = 2,
    max_topics: int = 8,
    topn: int = 10,
    max_features: int = 2000,
    max_documents: int = 2000,
) -> pd.DataFrame:
    """Score a SWEEP of topic counts, for the decision the paper never explains.

    「设定主题个数」 is a real choice and 表 1 gives no reason for 5/6/4/4/4. This step fits
    the same model :meth:`topic_model` fits, once per count, and prints two numbers per
    count: the log perplexity (how well the model predicts held-out word counts — it keeps
    falling as the model memorises rows) and a word-coherence score (whether a topic's top
    words actually appear together in the same posts, which perplexity does not check).

    The coherence score is **document-level NPMI over each topic's top ``topn`` words**,
    averaged over pairs and then over topics. That is a fraction of the coherence literature
    named C_v, not C_v: there is no sliding-window segmentation (each post is one window,
    which for short social posts is the same thing, but is not what the published algorithm
    does) and no reference-measure cosine step between topic pairs. It is reported here as
    ``coherence`` because it measures the same property; a replication of a published C_v
    number should not expect to agree with it.

    The pair count is what a zero-co-occurrence pair would silently become (an undefined
    log ratio), so such pairs are skipped and ``pairs_used`` says how many were not. A sweep
    with almost no usable pairs is a corpus whose topics do not share documents, and the
    perplexity alone is then the only number worth reading.
    """
    from itertools import combinations

    if column not in df.columns:
        raise UnknownOperationError(t('analysis.step_col_missing', op='topic_coherence', col=column))
    texts = [str(value) for value in df[column].dropna().tolist() if str(value).strip()]
    limit = _whole(max_documents, 'topic_coherence', 'max_documents')
    if limit > 0 and len(texts) > limit:
        # Deterministic on purpose: a sweep whose sample changes between runs changes its
        # numbers, and the user cannot tell the difference between a worse model and a
        # different dozen posts.
        texts = pd.Series(texts).sample(n=limit, random_state=_stable_seed(df)).sort_index().tolist()
        logger.info(t('analysis.coherence_sampled', used=limit, total=len(df[column].dropna())))
    low = _whole(min_topics, 'topic_coherence', 'min_topics')
    high = _whole(max_topics, 'topic_coherence', 'max_topics')
    if low < 2:
        raise UnknownOperationError(t('analysis.topic_count', value=low))
    if high < low:
        raise UnknownOperationError(t('analysis.coherence_range', low=low, high=high))
    if len(texts) < low:
        raise UnknownOperationError(t('analysis.topic_rows', rows=len(texts), topics=low))
    if high > len(texts):
        # Fitting five topics on three posts is not a model, and every count above the row
        # count would answer with the same degenerate fit. Saying so is the whole message.
        logger.info(t('analysis.coherence_capped', high=high, rows=len(texts)))
        high = len(texts)
    # One tokenisation per document, reused by every count: the vectoriser inside
    # ``_fit_topic_model`` re-cuts these texts (its contract is raw text, and sharing a
    # token list would make the two steps disagree the moment either changed its rule),
    # so this copy is for the co-occurrence counts only.
    documents = [_token_set(text) for text in texts]
    keep = max(1, _whole(topn, 'topic_coherence', 'topn'))
    rows = []
    for topics in range(low, high + 1):
        try:
            model, matrix, _doc_topic, vocabulary = _fit_topic_model(texts, topics, max_features)
        except ValueError as e:
            raise UnknownOperationError(t('analysis.topic_features', err=e)) from e
        perplexity = round(float(model.perplexity(matrix)), 2)
        tops = [
            [str(vocabulary[position]) for position in component.argsort()[::-1][:keep]]
            for component in model.components_
        ]
        candidates = set().union(*(set(words) for words in tops))
        singles = {word: sum(1 for document in documents if word in document) for word in candidates}
        joint: dict = {}
        for document in documents:
            present = sorted(document & candidates)
            for pair in combinations(present, 2):
                joint[pair] = joint.get(pair, 0) + 1
        total_documents = len(documents)
        scores = []
        used_pairs = 0
        skipped = 0
        for words in tops:
            values = []
            for pair in combinations(sorted(words), 2):
                count = joint.get(pair, 0)
                if not count or not singles[pair[0]] or not singles[pair[1]]:
                    skipped += 1
                    continue  # an undefined ratio is not a zero score
                used_pairs += 1
                p_ij = count / total_documents
                if p_ij >= 1.0:
                    # Both words are in every document, which is the one case where the
                    # denominator −log₂ p(i,j) is 0. Perfect co-occurrence is the maximum
                    # score by definition, so it is filed as 1.0 rather than as a division.
                    values.append(1.0)
                    continue
                numerator = (
                    math.log2(p_ij)
                    - math.log2(singles[pair[0]] / total_documents)
                    - math.log2(singles[pair[1]] / total_documents)
                )
                values.append(numerator / -math.log2(p_ij))
            if values:
                scores.append(sum(values) / len(values))
        coherence = round(sum(scores) / len(scores), 4) if scores else None
        rows.append(
            {
                'n_topics': topics,
                'coherence': coherence,
                'perplexity': perplexity,
                'documents': total_documents,
                'terms': len(vocabulary),
                'pairs_used': used_pairs,
                'pairs_skipped': skipped,
            }
        )
        logger.info(t('analysis.coherence_row', topics=topics, coherence=coherence, perplexity=perplexity))
    scored = [row for row in rows if row['coherence'] is not None]
    if not scored:
        raise UnknownOperationError(
            t('analysis.coherence_pairs', topn=keep, pairs=sum(row['pairs_skipped'] for row in rows))
        )
    best_coherence = max(scored, key=lambda row: row['coherence'])['n_topics']
    best_perplexity = min(rows, key=lambda row: row['perplexity'])['n_topics']
    logger.info(
        t(
            'analysis.coherence_best',
            coherence=best_coherence,
            perplexity=best_perplexity,
            low=low,
            high=high,
        )
    )
    return pd.DataFrame(rows)
