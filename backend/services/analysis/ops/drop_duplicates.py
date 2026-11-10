"""The ``drop_duplicates`` step, one module of the analysis op registry (see ops/__init__.py)."""

import pandas as pd

from i18n import t
from services.analysis.kernels import DEDUPE_MODES, UnknownOperationError


def drop_duplicates(df: pd.DataFrame, columns: list = None, keep: str = 'first', mode: str = 'exact') -> pd.DataFrame:
    """Drop repeated rows, by exact equality or by their normalised identity.

    ``exact`` is plain pandas equality. ``normalized`` compares the identity form
    from :mod:`services.datasets.dedupe`: a comment farm reposts the same sentence with a
    different tracking link, one more emoji code, or a re-pasted forward chain, and
    every one of those is a new string but the same comment. The original text is what
    survives — the key is a temporary column and never reaches the output.
    """
    wanted = [str(column) for column in (columns or [])]
    missing = [column for column in wanted if column not in df.columns]
    if missing:
        # An empty list means "every column" (the panel's 留空=全部). A non-empty list naming a
        # column the table does not hold is a typo, and the old intersection turned it into
        # "dedupe every column" — a different operation than the one asked for.
        raise UnknownOperationError(t('analysis.step_col_missing', op='drop_duplicates', col='、'.join(missing)))
    subset = wanted or None
    work = df.copy()
    if mode == 'exact':
        return work.drop_duplicates(subset=subset, keep=keep).reset_index(drop=True)
    if mode not in DEDUPE_MODES:
        raise UnknownOperationError(
            t(
                'analysis.bad_option',
                op='drop_duplicates',
                param='mode',
                value=mode,
                allowed=', '.join(DEDUPE_MODES),
            )
        )
    from services.datasets.dedupe import normalized_key

    cols = subset or [str(col) for col in work.columns]
    # Joined with a byte that cannot appear in a cell, so ('ab', 'c') and ('a', 'bc')
    # are not handed the same key — the bug a plain ''.join would produce.
    joined = work[cols[0]].fillna('').astype(str)
    for name in cols[1:]:
        joined = joined + '\x1e' + work[name].fillna('').astype(str)
    # ``normalized_key`` answers '' for a row that normalises to nothing (URL-only, emoticon-
    # only): that is "no identity", not one shared identity. A unique placeholder per position
    # keeps those rows apart instead of deleting all but the first as duplicates.
    work['__dedupe_key__'] = [key or f'__row_{position}__' for position, key in enumerate(joined.map(normalized_key))]
    out = work.drop_duplicates(subset=['__dedupe_key__'], keep=keep)
    return out.drop(columns=['__dedupe_key__']).reset_index(drop=True)
