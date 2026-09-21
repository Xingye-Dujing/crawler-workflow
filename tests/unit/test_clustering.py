"""Tests for analyzers/clustering.py — TF-IDF text clustering.

A cluster column is joined back onto the crawl table by row position, so the
load-bearing contract is *row preservation*: an unusable row gets an empty
cluster instead of vanishing mid-pipeline. Beyond that, the guards are about
settings a user can type into the node (``n_clusters=0``, an unknown method,
punctuation-only text) not blowing up the run.
"""

import pandas as pd
import pytest

from analyzers.clustering import TextCluster

pytestmark = pytest.mark.unit

TEXTS = [
    '三亚的海非常蓝，适合冬天度假潜水',
    '海南粉的汤底非常鲜美，海口美食',
    '糟糕的体验，服务很差劲不推荐',
    '垃圾产品，难用死了太失望',
    '潜水看珊瑚，海水清澈见底',
    '小镇非常安静，适合散步发呆',
]


@pytest.fixture
def df():
    return pd.DataFrame({'正文': TEXTS, '点赞': list(range(len(TEXTS)))})


@pytest.fixture
def cluster():
    return TextCluster()


class TestKmeans:
    def test_the_frame_grows_a_cluster_and_a_score(self, cluster, df):
        result = cluster.analyze_dataframe(df, n_clusters=2)
        assert list(result.columns) == ['正文', '点赞', 'cluster', 'silhouette']
        assert len(result) == len(df)
        assert set(result['cluster']) <= {0, 1}
        assert -1.0 <= result['silhouette'].iloc[0] <= 1.0

    def test_identical_texts_cannot_be_split(self, cluster):
        frame = pd.DataFrame({'正文': ['三亚的海非常蓝适合度假'] * 3})
        result = cluster.analyze_dataframe(frame, n_clusters=2)
        assert set(result['cluster']) == {0}

    def test_the_cluster_count_never_exceeds_what_was_asked_for(self, cluster, df):
        result = cluster.analyze_dataframe(df, n_clusters=2)
        assert result['cluster'].nunique() <= 2

    def test_zero_clusters_is_coerced_into_one(self, cluster, df):
        result = cluster.analyze_dataframe(df, n_clusters=0)
        assert set(result['cluster']) == {0}

    def test_requesting_more_clusters_than_rows_is_capped(self, cluster, df):
        result = cluster.analyze_dataframe(df, n_clusters=99)
        assert result['cluster'].nunique() <= len(df)
        assert len(result) == len(df)

    def test_the_run_is_repeatable(self, cluster, df):
        first = cluster.analyze_dataframe(df, n_clusters=3)['cluster'].tolist()
        second = cluster.analyze_dataframe(df, n_clusters=3)['cluster'].tolist()
        assert first == second


class TestDegenerateInput:
    def test_a_single_valid_row_is_its_own_cluster_zero(self, cluster):
        frame = pd.DataFrame({'正文': ['只有一句可用的文本内容'], 'id': [1]})
        result = cluster.analyze_dataframe(frame)
        assert result['cluster'].tolist() == [0]
        assert 'silhouette' not in result.columns

    def test_blank_rows_keep_their_place_without_a_cluster(self, cluster):
        frame = pd.DataFrame({'正文': ['三亚海蓝适合度假', None, '   ', '海口的海南粉很鲜美', '潜水看珊瑚和海龟']})
        result = cluster.analyze_dataframe(frame)
        assert len(result) == 5
        assert pd.isna(result['cluster'].iloc[1]) and pd.isna(result['cluster'].iloc[2])
        assert pd.notna(result['cluster'].iloc[0])
        assert result['cluster'].iloc[[0, 3, 4]].nunique() <= 3

    def test_an_empty_frame_is_returned_as_is(self, cluster):
        result = cluster.analyze_dataframe(pd.DataFrame({'正文': pd.Series(dtype='str')}))
        assert list(result.columns) == ['正文', 'cluster']
        assert result.empty

    def test_a_label_for_every_row_cannot_be_scored(self, cluster):
        # Silhouette needs 2..n-1 distinct labels; a table where each row is its
        # own cluster must report 0.0 instead of killing the node.
        frame = pd.DataFrame({'正文': ['三亚的海非常蓝适合度假', '海口的海南粉很鲜美', '潜水看珊瑚海水清澈']})
        result = cluster.analyze_dataframe(frame, n_clusters=3)
        assert result['cluster'].nunique() == 3
        assert (result['silhouette'] == 0.0).all()

    def test_a_missing_text_column_returns_the_frame(self, cluster, df):
        assert cluster.analyze_dataframe(df, text_column='不存在') is df


class TestDbscan:
    def test_noise_is_marked_separately(self, cluster, df):
        result = cluster.analyze_dataframe(df, method='dbscan', eps=0.6, min_samples=2)
        assert {'cluster', 'silhouette', 'is_noise'} <= set(result.columns)
        assert set(result['is_noise']) <= {0, 1}
        assert (result['is_noise'] == (result['cluster'] == -1).astype(int)).all()

    def test_a_tight_radius_leaves_everything_as_noise(self, cluster, df):
        result = cluster.analyze_dataframe(df, method='dbscan', eps=0.001, min_samples=3)
        assert set(result['cluster']) == {-1}
        assert set(result['is_noise']) == {1}


class TestMethodDispatch:
    def test_kmeans_plus_plus_is_accepted(self, cluster, df):
        assert 'cluster' in cluster.analyze_dataframe(df, method='kmeans++', n_clusters=2).columns

    def test_an_unknown_method_is_a_config_error(self, cluster, df):
        with pytest.raises(ValueError, match='Unknown clustering method: hdbscan'):
            cluster.analyze_dataframe(df, method='hdbscan')

    def test_the_input_frame_is_not_mutated(self, cluster, df):
        before = df.copy()
        cluster.analyze_dataframe(df, n_clusters=2)
        pd.testing.assert_frame_equal(df, before)
