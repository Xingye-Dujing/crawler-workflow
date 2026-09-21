"""PartWriter tests — the batch/merge contract for progressive output.

The visible promise of batching is: part files exist WHILE the run works,
the merged final file equals the union of everything streamed, keep/delete is
the user's choice, and a crash mid-run leaves the completed parts readable
(the resume ledger then only re-collects what is missing).
"""

import json
import os

import pandas as pd
import pytest

from services.part_writer import PartWriter, SnapshotWriter, safe_stem

pytestmark = pytest.mark.unit


def _rows(n, start=0):
    return [{'评论者': f'u{i}', '评论内容': f'文本{i}', '文章URL': 'https://x/1'} for i in range(start, start + n)]


class TestNoBatching:
    def test_finish_writes_single_final_file(self, tmp_path):
        w = PartWriter(str(tmp_path), 'plain', 'csv', batch_size=0)
        w.add(_rows(7))
        info = w.finish()
        assert info['parts'] == 0 and info['rows'] == 7
        frame = pd.read_csv(info['path'])
        assert len(frame) == 7
        assert sorted(os.listdir(tmp_path)) == ['plain.csv']

    def test_empty_run_still_produces_a_file(self, tmp_path):
        info = PartWriter(str(tmp_path), 'none', 'csv').finish()
        assert info['rows'] == 0
        assert os.path.exists(info['path'])


class TestBatching:
    def _two_batches(self, tmp_path, keep=True, fmt='csv'):
        w = PartWriter(str(tmp_path), 'wf', fmt, batch_size=5, keep_parts=keep)
        w.add(_rows(12))
        parts = sorted(f for f in os.listdir(tmp_path) if '.part' in f)
        assert len(parts) == 2  # mid-run: 10 flushed, 2 still buffered
        info = w.finish()
        return w, parts, info

    def test_parts_visible_mid_run_and_merged_at_end(self, tmp_path):
        _, parts, info = self._two_batches(tmp_path)
        assert info['parts'] == 2 and info['removed_parts'] == 0 and info['rows'] == 12
        frame = pd.read_csv(info['path'])
        assert len(frame) == 12 and list(frame.columns) == ['评论者', '评论内容', '文章URL']

    def test_keep_parts_false_removes_them(self, tmp_path):
        w = PartWriter(str(tmp_path), 'wf', 'csv', batch_size=5, keep_parts=False)
        w.add(_rows(12))
        info = w.finish()
        assert info['removed_parts'] == 2
        assert not [f for f in os.listdir(tmp_path) if '.part' in f]
        assert os.path.exists(info['path'])

    def test_json_round_trip(self, tmp_path):
        w = PartWriter(str(tmp_path), 'wf', 'json', batch_size=4)
        w.add(_rows(10))
        info = w.finish()
        with open(info['path'], encoding='utf-8') as fh:
            data = json.load(fh)
        assert len(data) == 10 and data[0]['评论者'] == 'u0'

    def test_tail_is_merged_not_parted(self, tmp_path):
        w = PartWriter(str(tmp_path), 'tail', 'csv', batch_size=100)  # never fills a batch
        w.add(_rows(3))
        info = w.finish()
        assert info['rows'] == 3 and info['parts'] == 0  # the tail rides straight into the final file


class TestCrashSemantics:
    def test_parts_written_before_a_crash_are_readable(self, tmp_path):
        w = PartWriter(str(tmp_path), 'crash', 'csv', batch_size=5)
        w.add(_rows(10))  # two parts flushed; simulate death here (no finish)
        parts = sorted(os.listdir(tmp_path))
        assert parts == ['crash.part001.csv', 'crash.part002.csv']
        frames = [pd.read_csv(os.path.join(tmp_path, p)) for p in parts]
        assert sum(len(f) for f in frames) == 10  # the partial result is real data

    def test_resume_merges_old_parts_with_new(self, tmp_path):
        # A resumed run's new writer adopts the parts the crashed one left.
        w1 = PartWriter(str(tmp_path), 'r', 'csv', batch_size=5)
        w1.add(_rows(5))  # part001 flushed pre-crash
        w2 = PartWriter(str(tmp_path), 'r', 'csv', batch_size=5)
        assert w2._parts and w2._part_no == 1  # adoption is automatic
        w2.add(_rows(5, start=5))
        info = w2.finish()
        assert info['rows'] == 10


class TestStem:
    def test_safe_stem(self):
        assert safe_stem('my/wf:*?').strip() != ''
        assert '/' not in safe_stem('a/b')
        assert safe_stem('..') == 'export'
        assert safe_stem('中文名.csv') == '中文名'


class TestHasParts:
    def test_fresh_writer_has_no_parts(self, tmp_path):
        assert PartWriter(str(tmp_path), 'h', 'csv', batch_size=2).has_parts is False

    def test_flushed_and_adopted_writers_report_parts(self, tmp_path):
        w1 = PartWriter(str(tmp_path), 'h', 'csv', batch_size=2)
        w1.add(_rows(2))
        assert w1.has_parts is True
        assert PartWriter(str(tmp_path), 'h', 'csv', batch_size=2).has_parts is True


class TestSnapshotWriter:
    """The LLM live view: one file, rewritten whole, always complete."""

    def test_first_write_creates_the_live_file(self, tmp_path):
        w = SnapshotWriter(str(tmp_path), 'snap')
        assert w.write(_rows(2)).endswith('snap.live.csv')
        frame = pd.read_csv(w.path, encoding='utf-8-sig')
        assert len(frame) == 2

    def test_rewrite_keeps_only_the_latest_table(self, tmp_path):
        w = SnapshotWriter(str(tmp_path), 'snap')
        w.write(_rows(3))
        w.write(_rows(10))
        assert len(pd.read_csv(w.path, encoding='utf-8-sig')) == 10
        # No half-written leftovers: the tmp file is renamed away, not littered.
        assert sorted(os.listdir(tmp_path)) == ['snap.live.csv']

    def test_columns_accumulate_across_writes(self, tmp_path):
        w = SnapshotWriter(str(tmp_path), 'snap')
        w.write([{'正文': 'a'}])
        w.write([{'正文': 'a', '情感': 'pos'}])
        assert list(pd.read_csv(w.path, encoding='utf-8-sig').columns) == ['正文', '情感']

    def test_json_format(self, tmp_path):
        w = SnapshotWriter(str(tmp_path), 'snap', 'json')
        w.write(_rows(2))
        with open(w.path, encoding='utf-8') as fh:
            assert len(json.load(fh)) == 2

    def test_directory_is_created_on_demand(self, tmp_path):
        w = SnapshotWriter(str(tmp_path / 'deep' / 'dir'), 'snap')
        w.write(_rows(1))
        assert w.path.endswith(os.path.join('deep', 'dir', 'snap.live.csv'))
