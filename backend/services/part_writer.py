"""Progressive part-file writer: results you can open before the run ends.

The complaint this answers: a 2000-row crawl or a long LLM pass hides all of
its work until the node finishes. With batching, every ``batch_size`` rows
are flushed to a numbered part file on disk (visible/inspectable right away),
and at completion the parts are merged into one final file. Parts can be kept
or deleted per the caller's ``keep_parts`` choice.

Crash behaviour is deliberate: parts already written are the partial results —
they survive a kill, and a re-run (whose ledger skips already-collected items)
writes only what is missing before merging everything.
"""

import contextlib
import csv
import json
import os

import pandas as pd


def dump_rows(rows, path: str, columns: list, fmt: str) -> None:
    """Write one table to one path in either supported format."""
    if fmt == 'csv':
        with open(path, 'w', newline='', encoding='utf-8-sig') as fh:
            writer = csv.DictWriter(fh, fieldnames=columns, extrasaction='ignore')
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, '') for k in columns})
    else:
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=1)


class PartWriter:
    def __init__(self, directory: str, stem: str, fmt: str = 'csv', batch_size: int = 0, keep_parts: bool = True):
        self.dir = directory
        self.stem = stem
        self.fmt = fmt if fmt in ('csv', 'json') else 'csv'
        self.ext = '.csv' if self.fmt == 'csv' else '.json'
        self.batch_size = max(0, int(batch_size or 0))
        self.keep_parts = bool(keep_parts)
        self._buffer: list = []
        self._columns: list = []
        os.makedirs(self.dir, exist_ok=True)
        # Adopt part files a previous (crashed) attempt already flushed:
        # resume continues the numbering and the final merge includes them —
        # that is what turns "parts survive a kill" into a real guarantee
        # instead of an orphaned pile of files.
        prefix = f'{stem}.part'
        self._parts = sorted(
            os.path.join(self.dir, f) for f in os.listdir(self.dir) if f.startswith(prefix) and f.endswith(self.ext)
        )
        self._part_no = len(self._parts)

    @property
    def batching(self) -> bool:
        return self.batch_size > 0

    @property
    def has_parts(self) -> bool:
        """Whether part files exist for this stem — freshly flushed or adopted
        from a crashed attempt. Callers seed legacy rows only when it is False,
        so re-adding rows an adopted part already holds never doubles them."""
        return bool(self._parts)

    # ─── ingest ─────────────────────────────────────────────────

    def add(self, rows) -> None:
        if not rows:
            return
        self._buffer.extend(rows)
        if self.batching:
            while len(self._buffer) >= self.batch_size:
                chunk, self._buffer = self._buffer[: self.batch_size], self._buffer[self.batch_size :]
                self._write_part(chunk)

    def _write_part(self, rows) -> None:
        if not rows:
            return
        self._part_no += 1
        ext = '.csv' if self.fmt == 'csv' else '.json'
        path = os.path.join(self.dir, f'{self.stem}.part{self._part_no:03d}{ext}')
        self._dump(rows, path)
        self._parts.append(path)

    def _dump(self, rows, path: str) -> None:
        for row in rows:
            for key in row:
                if key not in self._columns:
                    self._columns.append(key)
        dump_rows(rows, path, self._columns, self.fmt)

    # ─── finish ─────────────────────────────────────────────────

    def finish(self) -> dict:
        """Merge the flushed parts plus the still-buffered tail into the final
        file; return its info. The tail is deliberately NOT written as its own
        part first — a part on disk means 'a settled batch', and a crash here
        only ever loses rows the resume ledger will collect again anyway."""
        rows, _ = self._read_all_parts()
        rows.extend(self._buffer)
        self._buffer = []
        final = os.path.join(self.dir, f'{self.stem}{self.ext}')
        self._dump(rows, final)
        removed = 0
        if not self.keep_parts:
            for part in self._parts:
                with contextlib.suppress(OSError):
                    os.remove(part)
                    removed += 1
        return {'path': final, 'rows': len(rows), 'parts': len(self._parts), 'removed_parts': removed}

    def _read_all_parts(self):
        rows = []
        columns = list(self._columns)
        for part in self._parts:
            if self.fmt == 'csv':
                with contextlib.suppress(OSError):
                    frame = pd.read_csv(part, dtype=str, keep_default_na=False)
                    for col in frame.columns:
                        if col not in columns:
                            columns.append(col)
                    rows.extend(frame.to_dict('records'))
            else:
                with contextlib.suppress(OSError, ValueError):
                    with open(part, encoding='utf-8') as fh:
                        data = json.load(fh)
                    if isinstance(data, list):
                        for row in (r for r in data if isinstance(r, dict)):
                            for key in row:
                                if key not in columns:
                                    columns.append(key)
                            rows.append(row)
        return rows, columns


class SnapshotWriter:
    """A live view file that is rewritten whole, not a chunk meant to be merged.

    A long LLM pass settles rows batch by batch, but a batch of *enriched
    existing* rows is not the same animal as a batch of freshly scraped ones:
    the honest artifact is 'the table as it stands right now'. Every settled
    publish rewrites ``{stem}.live.{ext}`` atomically (tmp + os.replace), so a
    reader who opens the file mid-run sees the previous complete table, never
    a half-written one.
    """

    def __init__(self, directory: str, stem: str, fmt: str = 'csv'):
        os.makedirs(directory, exist_ok=True)
        self.fmt = fmt if fmt in ('csv', 'json') else 'csv'
        ext = '.csv' if self.fmt == 'csv' else '.json'
        self.path = os.path.join(directory, f'{stem}.live{ext}')
        self._columns: list = []

    def write(self, rows) -> str:
        for row in rows:
            for key in row:
                if key not in self._columns:
                    self._columns.append(key)
        tmp = f'{self.path}.tmp'
        dump_rows(rows, tmp, self._columns, self.fmt)
        os.replace(tmp, self.path)
        return self.path


def safe_stem(name: str) -> str:
    """Filesystem-safe stem for a workflow/node pair (delegates the charset
    rules to the same sanitizer every export path uses)."""
    from utils.helpers import sanitize_filename

    stem = sanitize_filename(name) or 'export'
    return os.path.splitext(stem)[0] or 'export'
