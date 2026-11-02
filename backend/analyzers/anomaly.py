import logging

import numpy as np
import pandas as pd

from i18n import t

logger = logging.getLogger(__name__)

# IsolationForest is imported where it is used: this module is on the boot path through
# ``analyzers``, and ``sklearn.ensemble`` alone measured 5.4 s of process start.


class AnomalyDetector:
    """Detect anomalous rows in numeric columns using Isolation Forest.

    Works best on numeric columns — categorical / text columns are ignored.
    Returns the original DataFrame with ``anomaly_score`` and ``is_anomaly``
    columns added.

    When it cannot answer, it says so rather than answering: a row of
    ``anomaly_score=0.0, is_anomaly=0`` reads as "this table was checked and is
    clean", which is a conclusion this node did not earn. There is no visible
    difference in an exported file between "no anomalies" and "nothing could be
    scored", so the second case raises and the node settles FAILED.
    """

    #: Below this many rows Isolation Forest separates an outlier from noise by
    #: accident, so a flag would be a coin toss with a number on it.
    MIN_ROWS = 5

    @staticmethod
    def analyze_dataframe(
        df: pd.DataFrame,
        columns: list = None,
        contamination: float = 0.1,
        random_state: int = 42,
    ) -> pd.DataFrame:
        from sklearn.ensemble import IsolationForest

        work = df.copy()

        numeric_cols = work.select_dtypes(include=[np.number]).columns.tolist()
        if columns:
            wanted = [str(c) for c in columns]
            unusable = [c for c in wanted if c not in numeric_cols]
            numeric_cols = [c for c in wanted if c in numeric_cols]
            if not numeric_cols:
                # The user named columns to score and none of them hold numbers:
                # that is a wrong setting, not an empty result set.
                raise ValueError(t('anomaly.no_usable_columns', columns=', '.join(unusable)))
            if unusable:
                logger.warning(t('anomaly.ignored_columns', columns=', '.join(unusable)))

        if not numeric_cols:
            raise ValueError(t('anomaly.no_numeric'))

        if len(work) < AnomalyDetector.MIN_ROWS:
            raise ValueError(t('anomaly.too_few', n=len(work), min=AnomalyDetector.MIN_ROWS))

        # A missing cell is not a measured 0: filling with 0 made a row with an uncollected
        # like-count look like the extreme low of its column and get flagged as an outlier.
        # The column median is the neutral stand-in; a column with no value at all falls back
        # to 0, and both cases are named in the log.
        gaps = int(work[numeric_cols].isna().sum().sum())
        if gaps:
            empty = [str(name) for name in numeric_cols if work[name].isna().all()]
            x_mat = work[numeric_cols].fillna(work[numeric_cols].median()).fillna(0)
            logger.warning(
                t('anomaly.imputed', n=gaps, columns=', '.join(map(str, numeric_cols)), empty=', '.join(empty))
            )
        else:
            x_mat = work[numeric_cols]

        model = IsolationForest(
            contamination=contamination,
            random_state=random_state,
            n_estimators=100,
        )
        preds = model.fit_predict(x_mat)
        scores = model.score_samples(x_mat)

        work['anomaly_score'] = np.round(-scores, 4)
        work['is_anomaly'] = (preds == -1).astype(int)

        n_anomalies = int((preds == -1).sum())
        logger.info(t('anomaly.done', n=n_anomalies, total=len(work), c=contamination))
        return work
