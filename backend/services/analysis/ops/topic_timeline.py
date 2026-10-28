"""The ``topic_timeline`` step, one module of the analysis op registry (see ops/__init__.py)."""

import logging

import pandas as pd

from i18n import t
from services.analysis.kernels import UnknownOperationError
from services.analysis.topic_kernels import _stage_key, _stage_order, _word_cells

logger = logging.getLogger(__name__)


def topic_timeline(
    df: pd.DataFrame,
    stage_col: str = 'stage',
    words_col: str = 'feature_words',
    size_col: str = 'doc_n',
    topic_col: str = 'topic',
    order_col: str = '',
    min_overlap: float = 0.5,
) -> pd.DataFrame:
    """When each subject appeared, and which ones were 次生舆情.

    表 1 is one snapshot per phase. It cannot say that 「外卖空包」 only became a subject
    after the first week — that is a statement about rows in DIFFERENT phases, and the
    paper makes it: the 次生舆情 (the secondary flare-up of a case, off a subject the
    first week never had) is one of its findings.

    A phase-by-phase LDA gives every topic a label scoped to its own stage (TopicⅠ-1 is
    not the same object as TopicⅡ-1), so a subject is tracked by the WORDS it is about:
    two rows belong to one lifecycle when their word lists overlap by at least
    ``min_overlap`` (Jaccard over the two sets). That threshold is the user's call about
    how much similarity counts as the same subject, which is why it is a parameter and is
    printed with the result rather than buried in this function.

    Families are grown in lifecycle order against the union of the words the family has
    already shown, so a subject that drifts one word per phase stays ONE subject instead
    of being filed as five — and the price of that choice is that a subject which changes
    abruptly opens a second family. Both readings are defensible; neither is silent,
    because the threshold and the union rule are stated here and on the panel.

    ``is_secondary`` is the paper's own two-part shape: the subject did not first appear
    in the opening phase, AND its largest phase came after its first one. A subject that
    was born late and peaked immediately (one phase only) is a late topic, not a
    flare-up, and is reported ``False`` — the columns beside it (``first_stage``,
    ``peak_stage``, ``stages_present``) are what the reader needs to judge that
    themselves, which is why they are in the table rather than folded into one flag.
    """
    stages = _stage_order(df, stage_col, order_col, op='topic_timeline')
    if len(stages) < 2:
        raise UnknownOperationError(t('analysis.timeline_stages', stages=len(stages)))
    for name in (size_col, topic_col):
        if name and name not in df.columns:
            raise UnknownOperationError(t('analysis.step_col_missing', op='topic_timeline', col=name))
    try:
        threshold = float(min_overlap)
    except (TypeError, ValueError):
        raise UnknownOperationError(t('analysis.timeline_overlap', value=min_overlap)) from None
    if not 0.0 < threshold <= 1.0:
        raise UnknownOperationError(t('analysis.timeline_overlap', value=min_overlap))

    positions = {stage: index for index, stage in enumerate(stages)}
    # Read positionally and once per column: ``Series.map`` on a categorical maps its
    # CATEGORIES, ``df.at`` addresses by row LABEL (and a filtered table's labels are not
    # its positions), and this table usually arrives across a node boundary as plain
    # strings anyway (see the invariant in AGENTS.md).
    keys = [_stage_key(value) for value in df[stage_col].tolist()]
    unusable = sum(1 for key in keys if key not in positions)
    if unusable:
        logger.warning(t('analysis.timeline_blank', col=stage_col, n=unusable))
    ordered = sorted(
        (positions[key], number) for number, key in enumerate(keys) if key in positions
    )  # stage order first, and the table's own order inside one stage
    if not ordered:
        raise UnknownOperationError(t('analysis.timeline_stages', stages=0))
    present = {position for position, _ in ordered}
    if len(present) < 2:
        # The declared lifecycle can carry an empty category (a phase 按时间划分阶段 named and
        # no post fell into). A lifecycle is about the phases with rows in them: one of
        # those is not a before and an after, whatever the column's category list says.
        raise UnknownOperationError(t('analysis.timeline_stages', stages=len(present)))
    word_lists = [_word_cells(value) for value in df[words_col].tolist()]
    label_list = [str(value).strip() for value in df[topic_col].tolist()] if topic_col else [''] * len(keys)

    sizes = pd.to_numeric(df[size_col], errors='coerce') if size_col else pd.Series(dtype=float)
    usable_sizes = int(sizes.notna().sum()) if len(sizes) else 0
    if size_col and not usable_sizes:
        # Every cell of the size column is text the numbers cannot come out of. Peak is
        # then not "flat", it is UNMEASURED, and a table of peaks built on zeros would be
        # the paper's finding manufactured out of nothing.
        raise UnknownOperationError(t('analysis.timeline_size', col=size_col))
    if size_col and usable_sizes < len(sizes):
        logger.warning(t('analysis.timeline_partial', col=size_col, n=len(sizes) - usable_sizes))
    size_list = sizes.tolist() if size_col else [0.0] * len(keys)

    families: list = []
    for stage_position, number in ordered:
        words = word_lists[number]
        if not words:
            raise UnknownOperationError(
                t(
                    'analysis.timeline_words',
                    stage=stages[stage_position],
                    topic=label_list[number] or f'#{number + 1}',
                    col=words_col,
                )
            )
        raw_size = size_list[number]
        size = float(raw_size) if pd.notna(raw_size) else 0.0
        best, best_score = None, 0.0
        unique = set(words)
        for family in families:
            union = family['words'] | unique
            score = len(family['words'] & unique) / len(union) if union else 0.0
            if score > best_score:
                # Ties go to the family that opened first, because "same subject" is judged
                # against the debut that got there earliest, not against whichever the row
                # order happened to test first.
                best, best_score = family, score
        record = {'pos': stage_position, 'size': size, 'words': words, 'label': label_list[number]}
        if best is not None and best_score >= threshold:
            best['rows'].append(record)
            best['words'].update(words)
        else:
            families.append({'words': set(words), 'rows': [record]})

    rows = []
    for family in families:
        entries = sorted(family['rows'], key=lambda record: record['pos'])
        debut = entries[0]['pos']
        peak = max(entries, key=lambda record: (record['size'], -record['pos']))['pos']
        shown: list = []
        for record in entries:
            for word in record['words']:
                if word not in shown:
                    shown.append(word)
        rows.append(
            {
                'topic': entries[0]['label'] or f'Subject-{len(rows) + 1}',
                'topic_words': '、'.join(shown),
                'first_stage': stages[debut],
                'peak_stage': stages[peak],
                'last_stage': stages[entries[-1]['pos']],
                'stages_present': len({record['pos'] for record in entries}),
                'stage_path': ' → '.join(stages[record['pos']] for record in entries),
                'size_total': round(float(sum(record['size'] for record in entries)), 4),
                'peak_size': round(float(max(record['size'] for record in entries)), 4),
                'is_secondary': bool(debut > 0 and peak > debut),
            }
        )
    rows.sort(key=lambda row: (stages.index(row['first_stage']), row['topic']))
    multi = sum(1 for row in rows if row['stages_present'] > 1)
    secondary = sum(1 for row in rows if row['is_secondary'])
    logger.info(
        t(
            'analysis.timeline_done',
            topics=len(rows),
            multi=multi,
            secondary=secondary,
            value=threshold,
            stages=len(stages),
        )
    )
    for row in rows:
        if row['is_secondary']:
            logger.info(t('analysis.timeline_secondary', topic=row['topic'], path=row['stage_path']))
    return pd.DataFrame(rows)
