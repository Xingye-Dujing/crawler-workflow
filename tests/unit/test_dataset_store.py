"""Tests for persisted uploads (services/dataset_store.py).

The store's two load-bearing ideas get the most attention:

- *identity is the content*: re-supplying identical rows returns the same id and
  stores nothing, while any single-cell change produces a different id;
- *a ref is repairable*: workflow→node→file pointers survive saves, and a file
  whose id was lost is findable again by name (and row count), which is what
  lets a workflow opened tomorrow still find its inputs.
"""
import pytest

from config import Config
from services.dataset_store import (
    SOURCE_ANALYSIS,
    SOURCE_PASTE,
    SOURCE_UPLOAD,
    DatasetStore,
    content_id,
    safe_records,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def store(tmp_path):
    s = DatasetStore(str(tmp_path / 'datasets.db'))
    yield s
    s._conn.close()


def _df(n=3, col='值'):
    import pandas as pd

    return pd.DataFrame({col: [f'文{i}' for i in range(n)], '数量': list(range(n))})


# ─── content identity ───────────────────────────────────────────────────


class TestContentId:
    def test_same_records_same_id(self):
        records = safe_records(_df())
        assert content_id(records) == content_id([dict(r) for r in records])

    def test_single_cell_change_changes_id(self):
        import pandas as pd

        a = safe_records(pd.DataFrame({'v': ['x']}))
        b = safe_records(pd.DataFrame({'v': ['y']}))
        assert content_id(a) != content_id(b)

    def test_empty_table_has_no_content_id(self):
        # Every empty CSV sharing one hash would confuse the UI, so '' opts out.
        assert content_id([]) == ''

    def test_nan_and_none_hash_alike(self):
        import numpy as np
        import pandas as pd

        with_nan = pd.DataFrame({'v': [None, 'a', np.nan]})
        with_none = pd.DataFrame({'v': [None, 'a', None]})
        assert content_id(safe_records(with_nan)) == content_id(safe_records(with_none))

    def test_safe_records_folds_na_types(self):
        import pandas as pd

        df = pd.DataFrame({'v': [pd.NaT, 1.5]})
        assert safe_records(df)[0]['v'] is None


# ─── put / get ──────────────────────────────────────────────────────────


class TestPutGet:
    def test_put_stores_and_returns_meta(self, store):
        meta = store.put(_df(), name='销量.csv')
        assert meta['stored'] is True
        assert meta['row_count'] == 3
        assert meta['name'] == '销量.csv'
        assert meta['source'] == SOURCE_UPLOAD
        assert meta['columns'] == ['值', '数量']

    def test_reupload_same_content_is_idempotent_and_keeps_first_name(self, store):
        first = store.put(_df(), name='原名.csv')
        again = store.put(_df(), name='新名.csv')
        assert again['dataset_id'] == first['dataset_id']
        assert again['stored'] is False
        # Renaming under a saved workflow would break find_replacement, so the
        # name of record is the one workflows already learned.
        assert again['name'] == '原名.csv'

    def test_empty_frame_keeps_its_column_shape(self, store):
        import pandas as pd

        df = pd.DataFrame(columns=['a', 'b'])
        meta = store.put(df)
        back = store.get(meta['dataset_id'])
        assert list(back.columns) == ['a', 'b']
        assert len(back) == 0

    def test_two_empty_uploads_do_not_collide(self, store):
        import pandas as pd

        a = store.put(pd.DataFrame(columns=['x']))
        b = store.put(pd.DataFrame(columns=['x']))
        assert a['dataset_id'] != b['dataset_id']  # '' content id ⇒ fresh random ids

    def test_explicit_dataset_id_is_honoured(self, store):
        meta = store.put(_df(), dataset_id='pinned')
        assert meta['dataset_id'] == 'pinned'
        assert store.exists('pinned')

    def test_none_dataframe_rejected(self, store):
        with pytest.raises(ValueError):
            store.put(None)

    def test_row_cap_rejected_loudly(self, store, monkeypatch):
        monkeypatch.setattr(Config, 'DATASET_MAX_ROWS', 2)
        with pytest.raises(ValueError):
            store.put(_df(n=3))

    def test_get_missing_or_blank_returns_none(self, store):
        assert store.get('nope') is None
        assert store.get('') is None

    def test_get_treats_corrupt_blob_as_missing(self, store):
        meta = store.put(_df())
        store._execute('UPDATE datasets SET payload = ? WHERE dataset_id = ?', (b'not-zlib', meta['dataset_id']))
        assert store.get(meta['dataset_id']) is None

    def test_round_trip_preserves_values(self, store, sample_rows):
        import pandas as pd

        meta = store.put(pd.DataFrame(sample_rows))
        back = store.get(meta['dataset_id'])
        # Empty strings survive as-is — safe_records only folds NaN/NaT.
        assert back.to_dict('records') == sample_rows


# ─── listing, replacement, references ───────────────────────────────────


class TestRefsAndListing:
    def test_list_orders_by_last_use_and_embeds_workflows(self, store):
        a = store.put(_df(n=2), name='a.csv')
        b = store.put(_df(n=3), name='b.csv')
        store.bind('wf', {'node-1': b['dataset_id']})
        listing = store.list_datasets()
        assert [d['dataset_id'] for d in listing] == [b['dataset_id'], a['dataset_id']]
        assert listing[0]['workflows'] == ['wf']
        assert listing[1]['workflows'] == []

    def test_find_replacement_matches_name_then_row_count(self, store):
        target = store.put(_df(n=3), name='数据.csv')
        assert store.find_replacement('数据.csv') == target['dataset_id']
        assert store.find_replacement('数据.csv', row_count=99) is None
        assert store.find_replacement('') is None

    def test_find_replacement_prefers_most_recently_used(self, store):
        import pandas as pd

        stale = store.put(_df(n=2), name='同名.csv')
        # Different content stored under the same name: two ids, one name —
        # the recovery lookup must pick the file the user touched last.
        newer = store.put(pd.DataFrame({'值': ['新内容'], '数量': [1]}), name='同名.csv')
        store._execute(
            'UPDATE datasets SET last_used_at = ? WHERE dataset_id = ?',
            ('2000-01-01T00:00:00', stale['dataset_id']),
        )
        assert store.find_replacement('同名.csv') == newer['dataset_id']
        store._execute(
            'UPDATE datasets SET last_used_at = ? WHERE dataset_id = ?',
            ('2030-01-01T00:00:00', stale['dataset_id']),
        )
        assert store.find_replacement('同名.csv') == stale['dataset_id']

    def test_bind_accepts_every_caller_shape(self, store):
        store.bind(
            'wf',
            {
                'n-str': 'ds1',
                'n-dict': {'dataset_id': 'ds2', 'dataset_name': 'f.csv', 'row_count': 7},
                'n-tuple': ('ds3', 'g.csv', 3),
            },
        )
        refs = store.refs_for('wf')
        assert {k: v['dataset_id'] for k, v in refs.items()} == {'n-str': 'ds1', 'n-dict': 'ds2', 'n-tuple': 'ds3'}
        assert refs['n-dict']['name'] == 'f.csv' and refs['n-dict']['row_count'] == 7
        assert refs['n-str']['name'] == '' and refs['n-str']['row_count'] == 0

    def test_bind_replaces_wholesale_so_deleted_nodes_release_refs(self, store):
        keep = store.put(_df(n=2), name='keep.csv')
        drop = store.put(_df(n=3), name='drop.csv')
        store.bind('wf', {'node-1': keep['dataset_id'], 'node-2': drop['dataset_id']})
        store.bind('wf', {'node-1': keep['dataset_id']})
        refs = store.refs_for('wf')
        assert list(refs) == ['node-1']
        # keep_days=-1 forces the cutoff into the future: deterministic purge of
        # orphans regardless of same-second timestamps.
        assert store.purge_unreferenced(keep_days=-1) == 1
        assert store.exists(drop['dataset_id']) is False
        assert store.exists(keep['dataset_id']) is True

    def test_bind_needs_a_workflow_name(self, store):
        assert store.bind('', {'node-1': 'ds'}) == 0

    def test_datasets_of_flags_missing_files(self, store):
        meta = store.put(_df(), name='ok.csv')
        store.bind('wf', {'node-1': meta['dataset_id']})
        items = store.datasets_of('wf')
        assert items[0]['missing'] is False
        assert items[0]['node_id'] == 'node-1'
        # Simulate the file going away while the workflow still points at it:
        # delete() cascades refs, so the datasets row must go directly.
        store._execute('DELETE FROM datasets WHERE dataset_id = ?', (meta['dataset_id'],))
        items = store.datasets_of('wf')
        assert items[0]['missing'] is True

    def test_unbind_and_delete_release_everything(self, store):
        meta = store.put(_df())
        store.bind('wf', {'node-1': meta['dataset_id']})
        assert store.unbind('wf') == 1
        assert store.refs_for('wf') == {}
        store.bind('wf2', {'node-1': meta['dataset_id']})
        assert store.delete(meta['dataset_id']) is True
        assert store.refs_for('wf2') == {}
        assert store.delete(meta['dataset_id']) is False

    def test_clear_drops_all_tables(self, store):
        meta = store.put(_df())
        store.bind('wf', {'node-1': meta['dataset_id']})
        assert store.clear() == 1
        assert store.list_datasets() == []
        assert store.refs_for('wf') == {}


# ─── housekeeping ───────────────────────────────────────────────────────


class TestPurge:
    def test_purge_removes_old_orphans_only(self, store):
        orphan = store.put(_df(n=2), name='孤儿.csv')
        referenced = store.put(_df(n=3), name='在用.csv')
        store.bind('wf', {'node-1': referenced['dataset_id']})
        recent = store.put(_df(n=4), name='刚传.csv')
        stamp = '2000-01-01T00:00:00'
        store._execute(
            'UPDATE datasets SET last_used_at = ? WHERE dataset_id IN (?, ?)',
            (stamp, orphan['dataset_id'], referenced['dataset_id']),
        )
        removed = store.purge_unreferenced(keep_days=30)
        assert removed == 1
        assert store.exists(orphan['dataset_id']) is False
        assert store.exists(referenced['dataset_id']) is True  # still bound ⇒ never orphans
        assert store.exists(recent['dataset_id']) is True  # fresh ⇒ inside window

    def test_purge_uses_created_at_when_never_used(self, store):
        # A dataset stored long ago (created_at old, last_used_at also old).
        meta = store.put(_df(n=2), name='旧.csv')
        store._execute(
            'UPDATE datasets SET last_used_at = NULL, created_at = ? WHERE dataset_id = ?',
            ('2000-01-01T00:00:00', meta['dataset_id']),
        )
        assert store.purge_unreferenced(keep_days=1) == 1

    def test_stats_totals_match_content(self, store):
        store.put(_df(n=3), source=SOURCE_PASTE)
        store.put(_df(n=2), source=SOURCE_ANALYSIS)
        stats = store.stats()
        assert stats['datasets'] == 2
        assert stats['rows'] == 5
        assert stats['bytes'] > 0
        assert stats['refs'] == 0
