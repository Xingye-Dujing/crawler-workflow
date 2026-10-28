"""The ``topic_flow`` step, one module of the analysis op registry (see ops/__init__.py)."""

import logging

import pandas as pd

from i18n import t
from services.analysis.kernels import UnknownOperationError
from services.analysis.topic_kernels import _jsd, _stage_key, _stage_order, _word_cells, _word_weights

logger = logging.getLogger(__name__)


def topic_flow(
    df: pd.DataFrame,
    stage_col: str = 'stage',
    topic_col: str = 'topic',
    words_col: str = 'feature_words',
    weights_col: str = 'weights',
    order_col: str = '',
    min_similarity: float = 0.5,
    label_col: str = '',
) -> pd.DataFrame:
    """Which topic of one phase carried over into the next — the sankey's edges.

    ``label_col`` is optional and names the column whose text makes a topic readable (表 1's
    主题概括): the sankey's node names come straight out of ``source``/``target``, so without it
    图 15 is a diagram of row labels. The raw ids stay in ``source_topic``/``target_topic``.

    表 1 says what each phase was about; it does not say how one phase's subject BECAME the
    next one's. That is the paper's other structural claim (「外卖黑盒→外卖空包」 is one subject
    mutating, not two subjects), and the only way to read it from a per-phase model is to
    compare the topics of adjacent phases with each other.

    The comparison is the Jensen-Shannon divergence of the two word DISTRIBUTIONS, taken
    from the ``word:weight`` cell :meth:`topic_by_stage` writes, turned into a similarity by
    ``1 / (1 + d)``. The distributions rather than the word lists, because two topics can
    share 「外卖」 and mean different things by how hard they lean on it; where the lists are
    all that is left, :meth:`topic_timeline` is the step to use.

    Adjacent phases only, and deliberately so: comparing 发酵期 with 衰退期 would draw an
    edge across the whole lifecycle and make the flow figure unreadable in exactly the way
    the paper's own stage-by-stage narrative is not.

    A threshold nobody clears is an answer, not an empty table: the refusal names the best
    similarity that was measured, so lowering it is a decision the user can make with the
    number in front of them.
    """
    stages = _stage_order(df, stage_col, order_col, op='topic_flow')
    if len(stages) < 2:
        raise UnknownOperationError(t('analysis.flow_stages', stages=len(stages)))
    for name in (topic_col, words_col, weights_col):
        if name and name not in df.columns:
            raise UnknownOperationError(t('analysis.step_col_missing', op='topic_flow', col=name))
    try:
        threshold = float(min_similarity)
    except (TypeError, ValueError):
        raise UnknownOperationError(t('analysis.flow_similarity', value=min_similarity)) from None
    if not 0.0 < threshold <= 1.0:
        raise UnknownOperationError(t('analysis.flow_similarity', value=min_similarity))

    positions = {stage: index for index, stage in enumerate(stages)}
    keys = [_stage_key(value) for value in df[stage_col].tolist()]
    # Positional reads, for the reason given in ``topic_timeline``: a filtered table's row
    # labels are not its positions, and ``df.at`` would answer with the wrong row.
    weights_list = [_word_weights(value) for value in df[weights_col].tolist()]
    words_list = ['、'.join(_word_cells(value)) for value in df[words_col].tolist()] if words_col else [''] * len(keys)
    # A sankey names its nodes with whatever this column says, so `TopicⅠ-2` on the figure is
    # as informative as a row label in a spreadsheet. When the table carries the model's 主题概括
    # the two are joined — the number stays first so the figure is still auditable against 表 1.
    if label_col and label_col not in df.columns:
        raise UnknownOperationError(t('analysis.step_col_missing', op='topic_flow', col=label_col))
    summary_list = [str(value).strip() for value in df[label_col].tolist()] if label_col else [''] * len(keys)
    raw_topics = [str(value).strip() for value in df[topic_col].tolist()]
    topic_list = [
        f'{name}｜{summary[:14]}' if summary else name for name, summary in zip(raw_topics, summary_list, strict=True)
    ]
    buckets: list = [[] for _ in stages]
    skipped = 0
    for number, key in enumerate(keys):
        if key not in positions:
            skipped += 1
            continue
        weights = weights_list[number]
        if not weights:
            # No weights means no distribution. Filing the row as uniform-over-its-words
            # would compute a similarity from a list overlap while the message reported a
            # divergence, which is two different measurements wearing one name.
            raise UnknownOperationError(
                t('analysis.flow_weights', topic=topic_list[number] or f'#{number + 1}', stage=key, col=weights_col)
            )
        buckets[positions[key]].append(
            {
                'topic': topic_list[number],
                'id': raw_topics[number],
                'words': words_list[number],
                'weights': weights,
            }
        )
    if skipped:
        logger.warning(t('analysis.timeline_blank', col=stage_col, n=skipped))
    for stage, entries in zip(stages, buckets, strict=True):
        if not entries:
            raise UnknownOperationError(t('analysis.flow_stage_empty', stage=stage, col=stage_col))

    edges = []
    best_seen = 0.0
    for left_index in range(len(stages) - 1):
        for source in buckets[left_index]:
            for target in buckets[left_index + 1]:
                vocabulary = sorted(set(source['weights']) | set(target['weights']))
                divergence = _jsd(
                    [source['weights'].get(word, 0.0) for word in vocabulary],
                    [target['weights'].get(word, 0.0) for word in vocabulary],
                )
                similarity = 1.0 / (1.0 + divergence)
                best_seen = max(best_seen, similarity)
                if similarity < threshold:
                    continue
                edges.append(
                    {
                        'source': source['topic'],
                        'target': target['topic'],
                        'source_topic': source['id'],
                        'target_topic': target['id'],
                        'similarity': round(similarity, 6),
                        'divergence': round(divergence, 6),
                        'from_stage': stages[left_index],
                        'to_stage': stages[left_index + 1],
                        'source_words': source['words'],
                        'target_words': target['words'],
                    }
                )
    if not edges:
        raise UnknownOperationError(t('analysis.flow_no_edges', value=threshold, best=round(best_seen, 4)))
    # Thickest link first: the sankey draws what it is handed, and a flow table read top-down
    # should start with the carry-over that was strongest.
    edges.sort(key=lambda edge: (-edge['similarity'], edge['source'], edge['target']))
    logger.info(
        t(
            'analysis.flow_done',
            edges=len(edges),
            stages=len(stages),
            value=threshold,
            best=round(best_seen, 4),
        )
    )
    return pd.DataFrame(edges)
