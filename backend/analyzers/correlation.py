import logging

import numpy as np
import pandas as pd

from i18n import t

logger = logging.getLogger(__name__)


class CorrelationAnalyzer:
    """Compute pairwise correlations among numeric columns.

    Supports three methods:
      - ``pearson``: linear correlation (default).
      - ``spearman``: rank-based (monotonic, robust to outliers).
      - ``kendall``: Kendall's tau (ordinal, small-sample robust).

    Returns a tidy (long-format) DataFrame of column-pair correlations.
    """

    @staticmethod
    def analyze_dataframe(
        df: pd.DataFrame,
        columns: list = None,
        method: str = 'pearson',
        min_abs: float = 0.0,
    ) -> pd.DataFrame:
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        if columns:
            wanted = [str(c) for c in columns]
            unusable = [c for c in wanted if c not in numeric_cols]
            numeric_cols = [c for c in wanted if c in numeric_cols]
            if not numeric_cols:
                # Nothing the user pointed at holds numbers: an empty table would
                # read as "these columns are unrelated" when the real answer is
                # "text cannot be correlated".
                raise ValueError(t('corr.no_usable_columns', columns=', '.join(unusable)))
            if unusable:
                logger.warning(t('corr.ignored_columns', columns=', '.join(unusable)))

        if len(numeric_cols) < 2:
            # Refused, not answered with an empty table: zero rows downstream reads as "these
            # columns are unrelated", which is a finding, while the truth is "there was nothing
            # to correlate". Same rule the unusable-column branch above already raises.
            raise ValueError(t('corr.need_cols_more', columns='、'.join(numeric_cols) or '—'))

        corr_matrix = df[numeric_cols].corr(method=method)

        pairs = []
        undefined = []
        for i, c1 in enumerate(numeric_cols):
            for c2 in numeric_cols[i + 1 :]:
                val = corr_matrix.loc[c1, c2]
                if pd.isna(val):
                    # A constant column has no correlation — the number does not exist rather
                    # than being zero. Naming the pair is what tells the user where it went.
                    undefined.append(f'{c1}/{c2}')
                    continue
                if abs(val) >= min_abs:
                    pairs.append(
                        {
                            'col1': c1,
                            'col2': c2,
                            'method': method,
                            'correlation': round(val, 4),
                            'abs_correlation': round(abs(val), 4),
                        }
                    )

        if not pairs and undefined:
            # Every surviving pair was constant/undefined: the correlation does not exist, so an
            # empty table would settle the node DONE over a "finding" nobody measured.
            raise ValueError(t('corr.no_defined_pairs', pairs='、'.join(undefined)))

        # Keep the same columns whether or not any pair survived: downstream
        # nodes read them by name.
        result = pd.DataFrame(pairs, columns=['col1', 'col2', 'method', 'correlation', 'abs_correlation'])
        if not result.empty:
            result = result.sort_values('abs_correlation', ascending=False).reset_index(drop=True)

        if undefined:
            logger.warning(t('corr.undefined_pairs', pairs='、'.join(undefined)))
        logger.info(t('corr.done', method=method, n=len(result), min_abs=min_abs))
        return result
