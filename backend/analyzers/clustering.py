import logging

import jieba
import pandas as pd
from sklearn.cluster import DBSCAN, KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score

from i18n import t

logger = logging.getLogger(__name__)


class TextCluster:
    """Cluster text rows by semantic similarity using TF-IDF + sklearn.

    Two algorithms:
      - ``kmeans``: fixed-number K-Means (best for known category counts).
      - ``dbscan``: density-based (auto-detects cluster count, marks noise).
    """

    @staticmethod
    def _tokenize(text: str) -> str:
        return ' '.join(jieba.cut(str(text)))

    @staticmethod
    def _silhouette(x_mat, labels, n_rows: int) -> float:
        """Silhouette score, or 0.0 when it is not defined.

        sklearn needs between 2 and n-1 distinct labels, so a small table where
        KMeans gives (nearly) every row its own cluster used to raise
        "Number of labels is 3. Valid values are 2 to n_samples - 1" and kill
        the whole node.
        """
        if not 1 < len(set(labels)) < n_rows:
            return 0.0
        try:
            return float(silhouette_score(x_mat, labels))
        except ValueError:
            return 0.0

    def analyze_dataframe(
        self,
        df: pd.DataFrame,
        text_column: str = '正文',
        method: str = 'kmeans',
        n_clusters: int = 3,
        eps: float = 0.5,
        min_samples: int = 2,
        max_features: int = 3000,
    ) -> pd.DataFrame:
        if text_column not in df.columns:
            logger.error(t('analysis.col_missing', col=text_column))
            return df

        # Every input row keeps its place: rows without usable text get an empty
        # cluster rather than disappearing, so the row count never shrinks
        # silently in the middle of a pipeline.
        work = df.copy()
        work['cluster'] = pd.NA
        mask = work[text_column].notna() & (work[text_column].astype(str).str.strip() != '')
        valid = work[mask].copy()
        if len(valid) < 2:
            logger.warning(t('cluster.not_enough'))
            work.loc[mask, 'cluster'] = 0
            return work

        texts = valid[text_column].astype(str).tolist()
        tokenized = [self._tokenize(t) for t in texts]

        vectorizer = TfidfVectorizer(
            tokenizer=lambda t: t.split(),
            preprocessor=lambda t: t,
            token_pattern=None,
            max_features=max_features,
        )

        try:
            x_mat = vectorizer.fit_transform(tokenized)
        except ValueError as e:
            # "empty vocabulary" — every row is punctuation/symbols only.
            logger.warning(t('cluster.no_features', err=e))
            work.loc[mask, 'cluster'] = 0
            return work

        if method in ('kmeans', 'kmeans++'):
            # max(1, …): a configured 0 (or a negative) used to reach sklearn and
            # blow up the node.
            n = max(1, min(int(n_clusters), len(valid)))
            model = KMeans(n_clusters=n, random_state=42, n_init='auto')
            labels = model.fit_predict(x_mat)
            score = self._silhouette(x_mat, labels, len(valid))
            work.loc[valid.index, 'silhouette'] = round(score, 4)

        elif method == 'dbscan':
            model = DBSCAN(eps=eps, min_samples=min_samples, metric='cosine')
            labels = model.fit_predict(x_mat.toarray())
            n_clusters_found = len(set(labels)) - (1 if -1 in labels else 0)
            n_noise = list(labels).count(-1)
            score = self._silhouette(x_mat, labels, len(valid))
            work.loc[valid.index, 'silhouette'] = round(score, 4)
            work.loc[valid.index, 'is_noise'] = (labels == -1).astype(int)
            logger.info(t('cluster.dbscan', n=n_clusters_found, noise=n_noise))

        else:
            raise ValueError(f'Unknown clustering method: {method}')

        work.loc[valid.index, 'cluster'] = labels
        logger.info(t('cluster.done', rows=len(valid), clusters=len(set(labels)), score=score))
        return work
