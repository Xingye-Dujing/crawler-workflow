import logging

import numpy as np
import pandas as pd

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
            numeric_cols = [c for c in columns if c in numeric_cols]

        if len(numeric_cols) < 2:
            logger.warning('Need at least 2 numeric columns for correlation analysis')
            return pd.DataFrame(columns=['col1', 'col2', 'method', 'correlation', 'abs_correlation'])

        corr_matrix = df[numeric_cols].corr(method=method)

        pairs = []
        for i, c1 in enumerate(numeric_cols):
            for c2 in numeric_cols[i + 1 :]:
                val = corr_matrix.loc[c1, c2]
                if pd.isna(val):
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

        result = pd.DataFrame(pairs)
        if not result.empty:
            result = result.sort_values('abs_correlation', ascending=False).reset_index(drop=True)

        logger.info('Correlation analysis (%s): %s pairs found (min_abs=%.2f)', method, len(result), min_abs)
        return result
