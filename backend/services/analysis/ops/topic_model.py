"""The ``topic_model`` step, one module of the analysis op registry (see ops/__init__.py)."""

import logging

import pandas as pd

from i18n import t
from services.analysis.kernels import UnknownOperationError
from services.analysis.topic_kernels import (
    _embedding_topic_rows,
    _keep_text,
    _resolve_topic_method,
    _split_tokens,
    _tokenized,
)

logger = logging.getLogger(__name__)


def topic_model(
    df: pd.DataFrame,
    column: str,
    n_topics: int = 5,
    topn: int = 10,
    max_features: int = 2000,
    method: str = 'lda',
    embedding_model: str = '',
) -> pd.DataFrame:
    """LDA (default) or embedding-cluster topic discovery over one text column.

    ``method='embedding'`` (opt-in) embeds each text with a sentence model and KMeans-clusters
    them; both methods emit the SAME ``{topic, rank, keyword, weight}`` table so the keyword
    chart and the 概括 step read either unchanged. LDA stays the default and the entire existing
    pipeline; the embedding path refuses by name when its optional encoder is not installed.

    ``sklearn``'s ``LatentDirichletAllocation``, not Gensim's: scikit-learn is already
    a dependency of this project and gensim is not, and a topic model that needs a
    second numerical stack installed to read a table is not worth the extra words it
    would type. Both fit the same generative model; the numbers they report are not
    identical, so a replication should say which one produced its table.

    The output is ONE ROW PER (topic, keyword) rather than one row per topic with its
    words joined: it is the shape the keyword node already answers with, it keeps every
    weight addressable, and a chart can group it by ``topic`` directly. Reading it as
    the paper's table is a job for the console line, which prints each topic's words in
    order.

    The perplexity is logged because "设定主题个数" is a real decision and the paper
    does not say how it was made: run the node at several ``n_topics`` and read the
    number, which falls as the model fits better and stops meaning anything once it
    starts memorising rows.
    """
    from sklearn.decomposition import LatentDirichletAllocation
    from sklearn.feature_extraction.text import CountVectorizer

    if column not in df.columns:
        return df
    topics = int(n_topics)
    if topics < 2:
        raise UnknownOperationError(t('analysis.topic_count', value=topics))
    texts = [str(value) for value in df[column].dropna().tolist() if str(value).strip()]
    if len(texts) < topics:
        raise UnknownOperationError(t('analysis.topic_rows', rows=len(texts), topics=topics))
    # Tokens with no letter or digit in them are dropped before the model sees them, the
    # same rule the word-cloud tokenizer applies: jieba hands back the punctuation it
    # split on, and a topic model whose vocabulary is "。" and "！" has topics that are
    # punctuation. A corpus that is nothing BUT punctuation then has no vocabulary at
    # all, which is refused below rather than answered with an empty table.
    tokenized = _tokenized(texts)
    method = _resolve_topic_method(method)
    if method == 'embedding':
        return _embedding_topic_rows(texts, tokenized, topics, max(1, int(topn)), embedding_model)
    vectorizer = CountVectorizer(
        tokenizer=_split_tokens,
        preprocessor=_keep_text,
        token_pattern=None,
        max_features=max(10, int(max_features)),
    )
    try:
        matrix = vectorizer.fit_transform(tokenized)
    except ValueError as e:
        raise UnknownOperationError(t('analysis.topic_features', err=e)) from e
    model = LatentDirichletAllocation(n_components=topics, random_state=42, learning_method='batch')
    model.fit(matrix)
    vocabulary = vectorizer.get_feature_names_out()
    rows = []
    lines = []
    for index, component in enumerate(model.components_):
        best = component.argsort()[::-1][: max(1, int(topn))]
        words = [str(vocabulary[position]) for position in best]
        lines.append(f'Topic-{index + 1}: {" ".join(words)}')
        for rank, position in enumerate(best):
            rows.append(
                {
                    'topic': f'Topic-{index + 1}',
                    'rank': rank + 1,
                    'keyword': str(vocabulary[position]),
                    'weight': round(float(component[position]), 6),
                }
            )
    logger.info(
        t(
            'analysis.topic_done',
            n=topics,
            rows=len(texts),
            perplexity=round(float(model.perplexity(matrix)), 2),
        )
    )
    for line in lines:
        # One line per topic, so the console reads like the paper's table without an
        # export round trip — the whole point of running the node.
        logger.info(line)
    return pd.DataFrame(rows, columns=['topic', 'rank', 'keyword', 'weight'])
