import logging

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

logger = logging.getLogger(__name__)


class AnomalyDetector:
    """Detect anomalous rows in numeric columns using Isolation Forest.

    Works best on numeric columns — categorical / text columns are ignored.
    Returns the original DataFrame with ``anomaly_score`` and ``is_anomaly``
    columns added.
    """

    @staticmethod
    def analyze_dataframe(
        df: pd.DataFrame,
        columns: list = None,
        contamination: float = 0.1,
        random_state: int = 42,
    ) -> pd.DataFrame:
        work = df.copy()

        numeric_cols = work.select_dtypes(include=[np.number]).columns.tolist()
        if columns:
            numeric_cols = [c for c in columns if c in numeric_cols]

        if not numeric_cols:
            logger.warning('No numeric columns available for anomaly detection')
            work['anomaly_score'] = 0.0
            work['is_anomaly'] = 0
            return work

        x_mat = work[numeric_cols].fillna(0)

        if len(x_mat) < 5:
            logger.warning('Too few rows (%s) for reliable anomaly detection', len(x_mat))
            work['anomaly_score'] = 0.0
            work['is_anomaly'] = 0
            return work

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
        logger.info('Anomaly detection: %s/%s rows flagged (contamination=%.2f)', n_anomalies, len(work), contamination)
        return work
