"""Dataset-level union: same columns, one provenance column, no silent outer join."""

import pandas as pd
import pytest
from core.config import Config

from services.dataset_merge import SOURCE_COLUMN, merge_datasets
from services.dataset_store import SOURCE_MERGE, DatasetStore


@pytest.fixture()
def store(tmp_path):
    instance = DatasetStore(str(tmp_path / 'datasets.db'))
    yield instance
    instance.close()


def _put(store, name, rows, columns=('标题', '正文')):
    frame = pd.DataFrame(rows, columns=list(columns))
    return store.put(frame, name=name, source='upload')


class TestMergeDatasets:
    def test_same_columns_become_one_table_with_a_source_column(self, store):
        a = _put(store, 'A.csv', [{'标题': 'a', '正文': 'x'}])
        b = _put(store, 'B.csv', [{'标题': 'b', '正文': 'y'}, {'标题': 'c', '正文': 'z'}])
        result = merge_datasets(store, [a['dataset_id'], b['dataset_id']], '合并结果')
        assert result['rows'] == 3
        assert result['columns'][0] == SOURCE_COLUMN
        assert result['dataset']['source'] == SOURCE_MERGE
        merged = store.get(result['dataset']['dataset_id'])
        assert list(merged[SOURCE_COLUMN]) == ['A.csv', 'B.csv', 'B.csv']
        assert list(merged['标题']) == ['a', 'b', 'c']
        assert [row['rows'] for row in result['sources']] == [1, 2]

    def test_a_different_column_set_is_refused_with_the_names(self, store):
        a = _put(store, 'A.csv', [{'标题': 'a', '正文': 'x'}])
        b = _put(store, 'B.csv', [{'标题': 'b', '额外': 1}], columns=('标题', '额外'))
        with pytest.raises(ValueError) as exc:
            merge_datasets(store, [a['dataset_id'], b['dataset_id']], '合并结果')
        message = str(exc.value)
        assert 'B.csv' in message and '额外' in message and '正文' in message

    def test_a_missing_source_and_a_blank_name_are_named(self, store):
        a = _put(store, 'A.csv', [{'标题': 'a', '正文': 'x'}])
        with pytest.raises(ValueError) as exc:
            merge_datasets(store, [a['dataset_id'], 'gone'], 'x')
        assert 'gone' in str(exc.value)
        with pytest.raises(ValueError):
            merge_datasets(store, [a['dataset_id']], 'x')
        with pytest.raises(ValueError):
            merge_datasets(store, [a['dataset_id'], a['dataset_id']], 'x')
        b = _put(store, 'B.csv', [{'标题': 'b', '正文': 'y'}])
        with pytest.raises(ValueError) as exc:
            merge_datasets(store, [a['dataset_id'], b['dataset_id']], '  ')
        assert str(exc.value)

    def test_an_existing_source_column_is_not_overwritten(self, store):
        a = _put(
            store,
            'A.csv',
            [{'标题': 'a', '正文': 'x', SOURCE_COLUMN: '手动来源'}],
            columns=('标题', '正文', SOURCE_COLUMN),
        )
        b = _put(
            store,
            'B.csv',
            [{'标题': 'b', '正文': 'y', SOURCE_COLUMN: '另一个'}],
            columns=('标题', '正文', SOURCE_COLUMN),
        )
        result = merge_datasets(store, [a['dataset_id'], b['dataset_id']], '保留来源')
        merged = store.get(result['dataset']['dataset_id'])
        assert list(merged[SOURCE_COLUMN]) == ['手动来源', '另一个']

    def test_the_total_row_cap_is_named(self, store, monkeypatch):
        a = _put(store, 'A.csv', [{'标题': 'a', '正文': 'x'}])
        b = _put(store, 'B.csv', [{'标题': 'b', '正文': 'y'}])
        monkeypatch.setattr(Config, 'DATASET_MAX_ROWS', 1)
        with pytest.raises(ValueError) as exc:
            merge_datasets(store, [a['dataset_id'], b['dataset_id']], '太大')
        assert '2' in str(exc.value)
