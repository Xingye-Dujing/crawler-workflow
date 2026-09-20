import logging

import jieba
import pandas as pd
from sklearn.cluster import DBSCAN, KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score

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
            logger.error('Column "%s" not found', text_column)
            return df

        mask = df[text_column].notna() & (df[text_column].astype(str).str.strip() != '')
        valid = df[mask].copy()
        if len(valid) < 2:
            logger.warning('Not enough valid rows for clustering (need >= 2)')
            valid['cluster'] = 0
            return valid

        texts = valid[text_column].astype(str).tolist()
        tokenized = [self._tokenize(t) for t in texts]

        vectorizer = TfidfVectorizer(
            tokenizer=lambda t: t.split(),
            preprocessor=lambda t: t,
            token_pattern=None,
            max_features=max_features,
        )

        x_mat = vectorizer.fit_transform(tokenized)

        if method in ('kmeans', 'kmeans++'):
            n = min(n_clusters, len(valid))
            model = KMeans(n_clusters=n, random_state=42, n_init='auto')
            labels = model.fit_predict(x_mat)
            score = silhouette_score(x_mat, labels) if len(set(labels)) > 1 else 0.0
            valid['cluster'] = labels
            valid['silhouette'] = round(score, 4)

        elif method == 'dbscan':
            model = DBSCAN(eps=eps, min_samples=min_samples, metric='cosine')
            labels = model.fit_predict(x_mat.toarray())
            n_clusters_found = len(set(labels)) - (1 if -1 in labels else 0)
            n_noise = list(labels).count(-1)
            score = silhouette_score(x_mat, labels) if len(set(labels)) > 1 else 0.0
            valid['cluster'] = labels
            valid['silhouette'] = round(score, 4)
            valid['is_noise'] = (labels == -1).astype(int)
            logger.info('DBSCAN found %s clusters + %s noise points', n_clusters_found, n_noise)

        else:
            raise ValueError(f'Unknown clustering method: {method}')

        logger.info(
            'Clustering completed: %s rows into %s clusters (silhouette=%.3f)', len(valid), len(set(labels)), score
        )
        return valid
