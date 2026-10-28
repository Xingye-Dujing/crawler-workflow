"""The ``topic_by_stage`` step, one module of the analysis op registry (see ops/__init__.py)."""

import logging

import pandas as pd

from i18n import t
from services.analysis.contracts import STAGE_NUMERALS
from services.analysis.kernels import UnknownOperationError
from services.analysis.topic_kernels import (
    _embed_vectors,
    _embedding_assignment,
    _EmbeddingTopicModel,
    _keep_text,
    _resolve_topic_method,
    _split_tokens,
    _stage_key,
    _stage_order,
    _stage_topic_counts,
    _tokenized,
)

logger = logging.getLogger(__name__)


def topic_by_stage(
    df: pd.DataFrame,
    column: str,
    stage_col: str = '阶段',
    order_col: str = '',
    topics=None,
    topn: int = 10,
    max_features: int = 2000,
    word_source: str = 'tfidf',
    sample_n: int = 5,
    method: str = 'lda',
    embedding_model: str = '',
) -> pd.DataFrame:
    """LDA fitted **inside each 舆情阶段** — the table the study publishes.

    One model over the whole corpus cannot produce it. A pooled LDA spends its topics on
    whichever phase supplied most of the text (爆发期 and 二次爆发期 are 7624 and 8029 of the
    paper's 19326 rows), so 发酵期's 349 rows either get no topic of their own or share one
    with a phase three weeks later — and 「谣言、暴力、刘某、发布、捞、细节、谩骂」 would stop
    being a description of the first week. So the corpus is split by the 阶段 column
    :meth:`bin_time` wrote, modelled stage by stage, and numbered Ⅰ-1 … Ⅴ-4 by lifecycle
    position, which is exactly how 表 1 reads.

    The output is WIDE — one row per (stage, topic) — because that is the artifact: the
    feature words go into one cell joined by 、, the same cell the paper prints. The long
    (topic, keyword, weight) shape stays available from :meth:`topic_model`.

    ``word_source='tfidf'`` follows the paper's stated method: LDA assigns each post to a
    topic, and the words are then the corpus TF-IDF of THAT bucket, so the list is what is
    distinctive about the posts rather than what the model's weight matrix happens to top.
    ``'lda'`` reads the weight matrix directly and is kept because the two lists differ
    (see :data:`WORD_SOURCES`).

    An assignment can leave a topic with no posts at all — a property of the fit, not of the
    user's choice — and then there is no bucket to score. The row is filled from that topic's
    own word distribution, ``doc_n`` reports 0, and one warning names it: the stage's other
    topics are real output, and dropping the table over an empty bucket (or printing an empty
    特征词 cell) would each lose information the model actually has.

    Sample posts are the ``sample_n`` rows with the highest posterior probability for the
    topic — not a random draw. A random one would hand :meth:`topic_label` different
    evidence on every run, and a summary that changes between two identical runs is not a
    finding.
    """
    from sklearn.decomposition import LatentDirichletAllocation
    from sklearn.feature_extraction.text import CountVectorizer

    from analyzers.keyword import KeywordExtractor

    if column not in df.columns or stage_col not in df.columns:
        return df
    method = _resolve_topic_method(method)
    stages = _stage_order(df, stage_col, order_col)
    per_stage = _stage_topic_counts(topics, stages)
    # Read once, positionally: ``Series.map`` on a categorical maps its CATEGORIES, not its
    # values, so the comparison would silently match nothing and every phase would come
    # back "has no rows".
    stage_keys = pd.Series([_stage_key(value) for value in df[stage_col].tolist()], index=df.index)
    blank = int((stage_keys == '').sum())
    if blank:
        logger.warning(t('analysis.stage_blank', col=stage_col, n=blank))

    rows = []
    for stage_index, stage in enumerate(stages):
        stage_rows = df[stage_keys == stage]
        # The rows the model actually reads: a blank text is not a document, and counting
        # it would let the guard below pass on a stage that is really empty.
        usable = stage_rows[stage_rows[column].notna() & (stage_rows[column].astype(str).str.strip() != '')]
        wanted = per_stage[stage_index]
        if not len(usable):
            raise UnknownOperationError(t('analysis.topic_stage_empty', stage=stage, col=stage_col))
        if len(usable) < wanted:
            # Refusing rather than dropping to "3 topics for 2 texts": the stage would then
            # report fewer numbered topics than the user asked for, and the numbering is the
            # thing the paper's table is read by.
            raise UnknownOperationError(t('analysis.topic_stage_rows', stage=stage, rows=len(usable), topics=wanted))
        texts = [str(value) for value in usable[column].tolist()]
        tokenized = _tokenized(texts)
        vectorizer = CountVectorizer(
            tokenizer=_split_tokens,
            preprocessor=_keep_text,
            token_pattern=None,
            max_features=max(10, int(max_features)),
        )
        try:
            matrix = vectorizer.fit_transform(tokenized)
        except ValueError as e:
            raise UnknownOperationError(t('analysis.topic_stage_features', stage=stage, err=e)) from e
        vocabulary = vectorizer.get_feature_names_out()
        if str(method) == 'embedding':
            # Embed this stage's texts and KMeans them, returning the same ``(doc_topic,
            # components_)`` shape the LDA branch yields so the bucketing, the numbering and the
            # empty-topic fallback below run unchanged for either method.
            vectors, _name = _embed_vectors(texts, embedding_model)
            doc_topic, components = _embedding_assignment(vectors, matrix, wanted)
            model = _EmbeddingTopicModel(components)
            perplexity = float('nan')
        else:
            model = LatentDirichletAllocation(n_components=wanted, random_state=42, learning_method='batch')
            doc_topic = model.fit_transform(matrix)
            perplexity = round(float(model.perplexity(matrix)), 2)
        # One pass assigns every document to its strongest topic. Doing the argmax inside the
        # topic loop would walk the whole stage again per topic, which on a 19,326-post
        # corpus is the difference between seconds and minutes for no extra information.
        buckets: dict = {}
        for position, owner in enumerate(int(row) for row in doc_topic.argmax(axis=1)):
            buckets.setdefault(owner, []).append(position)
        # The stage's POSITION, not its name: 表 1 says TopicⅠ-1 belongs to 发酵期 because
        # 发酵期 came first, and the numeral has to survive a rename of the phase labels.
        numeral = STAGE_NUMERALS[stage_index] if stage_index < len(STAGE_NUMERALS) else str(stage_index + 1)
        logger.info(t('analysis.topic_stage_done', stage=stage, n=wanted, rows=len(usable), perplexity=perplexity))
        for topic_index in range(wanted):
            label = f'Topic{numeral}-{topic_index + 1}'
            members = buckets.get(topic_index, [])
            doc_n = len(members)
            if word_source == 'tfidf':
                bucket = usable.iloc[members]
                scored = KeywordExtractor().tfidf_corpus(bucket, text_column=column, topk=int(topn), merge=True)
                words = [
                    (str(word), float(weight)) for word, weight in zip(scored['keyword'], scored['weight'], strict=True)
                ]
                if not words:
                    # An argmax can leave a topic with NO documents, and then there is no
                    # bucket to score TF-IDF over. That is a property of the fit, not a
                    # mistake by the user, and killing a stage's other three topics for it
                    # would be worse than saying so: the model does hold a word distribution
                    # for the unused topic, so the row is filled from that and ``doc_n`` = 0
                    # is what tells the reader no post was assigned to it.
                    component = model.components_[topic_index]
                    best = component.argsort()[::-1][: max(1, int(topn))]
                    words = [(str(vocabulary[position]), float(component[position])) for position in best]
                    logger.warning(t('analysis.topic_stage_unused', stage=stage, topic=label))
            else:
                component = model.components_[topic_index]
                best = component.argsort()[::-1][: max(1, int(topn))]
                words = [(str(vocabulary[position]), float(component[position])) for position in best]
            if not words:
                raise UnknownOperationError(t('analysis.topic_stage_words', stage=stage, topic=label))
            # This topic's mass per document, read out of the matrix BEFORE the sort: a key
            # function naming the loop's ``doc_topic``/``topic_index`` captures those CELLS, so
            # the next stage's fit would re-rank this row's samples (and 样例文本 is what a
            # reader sees of it). ``reverse=True`` keeps the old negated-ascending tie order —
            # the sort is stable either way.
            topic_mass = [float(value) for value in doc_topic[:, topic_index]]
            ranked = sorted(range(len(texts)), key=topic_mass.__getitem__, reverse=True)
            samples = ' ／ '.join(texts[position][:80] for position in ranked[: max(0, int(sample_n))])
            rows.append(
                {
                    'stage': stage,
                    'stage_order': stage_index + 1,
                    'topic': label,
                    'feature_words': '、'.join(word for word, _ in words),
                    'weights': ' '.join(f'{word}:{weight:.6f}' for word, weight in words),
                    'doc_n': doc_n,
                    'perplexity': perplexity,
                    'sample_texts': samples,
                }
            )
            logger.info(
                t(
                    'analysis.topic_stage_topic_words',
                    topic=label,
                    stage=stage,
                    words=' '.join(word for word, _ in words),
                )
            )
    if not rows:
        # Unreachable while ``stages`` is non-empty (the guard above raises on an empty
        # stage), but a table with no topic rows must not settle the node DONE.
        raise UnknownOperationError(t('analysis.topic_stage_rows', stage='、'.join(stages), rows=0, topics=1))
    return pd.DataFrame(rows)
