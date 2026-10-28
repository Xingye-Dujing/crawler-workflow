"""Durable storage for uploaded / pasted datasets — the files behind an
Upload node.

The problem this solves: a file used to live in a Python dict. Restart the
server, open the saved workflow tomorrow, and every Upload node pointed at
nothing — you re-uploaded before you could run anything, and a workflow that
was supposed to be repeatable was not.

``DatasetStore`` keeps the rows in SQLite (``data/datasets.db``):

- ``datasets``       one row per file: identity, columns, size, compressed
                     payload of every record.
- ``dataset_refs``   which Upload node of which workflow points at which
                     file — the mapping a saved workflow carries with it.

Two decisions do most of the work:

**Identity is the content.** ``dataset_id`` is the hash of the records, not a
random uuid. Uploading the same file twice stores one copy and hands back the
same id, so nothing accumulates; and a workflow whose *ref* row was lost still
rebinds itself the moment the same bytes arrive again.

**A ref is repairable.** Saving a workflow records node → file, loading one
checks it. A file that went missing is looked up again by name and row count
before the node is declared empty, and loading tells the UI exactly which
files came back and which one still needs re-uploading.
"""

import contextlib
import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
import zlib

import pandas as pd
from core.config import Config
from core.refs import sanitize_filename

from i18n import t

logger = logging.getLogger(__name__)

# Where a table of this upload came from. Only used for the listing UI, but it
# explains at a glance why a file exists.
SOURCE_UPLOAD = 'upload'
SOURCE_PASTE = 'paste'
SOURCE_ANALYSIS = 'analysis'
SOURCE_IMPORT = 'import'
SOURCE_MERGE = 'merge'
SOURCE_CUMULATIVE = 'cumulative'


def safe_records(df: pd.DataFrame) -> list:
    """Records with NaN/NaT folded to None.

    Raw NaN survives round-tripping through pandas fine but is not valid JSON,
    so SQLite gets something it can store and the browser can parse later.
    Needed twice: once to hash a dataset (so NaN and None compare equal) and
    once to store it.
    """
    return df.astype(object).where(pd.notna(df), None).to_dict('records')


def _canonical(records: list) -> str:
    return json.dumps(records, sort_keys=True, ensure_ascii=False, separators=(',', ':'), default=str)


def content_id(records: list) -> str:
    """Stable id for a set of records, or '' when there are none.

    An empty table has no identity to speak of — every empty CSV would hash
    alike and the UI would start confusing them — so it gets a fresh uuid and
    no dedupe instead.
    """
    if not records:
        return ''
    return hashlib.sha1(_canonical(records).encode('utf-8')).hexdigest()[:16]


class DatasetStore:
    """SQLite-backed table storage for files dropped into a workflow."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or Config.DATASETS_DB
        os.makedirs(os.path.dirname(self.db_path) or '.', exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # If WAL cannot be enabled (some network shares reject it) the store
        # still works — just with the default journal.
        with contextlib.suppress(sqlite3.DatabaseError):
            # WAL lets the UI list datasets while a run reads one.
            self._conn.execute('PRAGMA journal_mode=WAL')
        self._conn.execute('PRAGMA synchronous=NORMAL')
        self._ensure_tables()

    # ── schema ──────────────────────────────────────────────────

    def _ensure_tables(self):
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    dataset_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'upload',
                    columns TEXT NOT NULL DEFAULT '[]',
                    row_count INTEGER NOT NULL DEFAULT 0,
                    byte_size INTEGER NOT NULL DEFAULT 0,
                    payload BLOB NOT NULL,
                    created_at TEXT,
                    last_used_at TEXT
                );
                CREATE TABLE IF NOT EXISTS dataset_refs (
                    workflow_name TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    dataset_id TEXT NOT NULL,
                    file_name TEXT,
                    row_count INTEGER,
                    updated_at TEXT,
                    PRIMARY KEY (workflow_name, node_id)
                );
                CREATE TABLE IF NOT EXISTS dataset_lineages (
                    lineage_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    current_dataset_id TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS dataset_lineage_versions (
                    lineage_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    dataset_id TEXT NOT NULL,
                    run_id TEXT NOT NULL DEFAULT '',
                    node_id TEXT NOT NULL DEFAULT '',
                    added_rows INTEGER NOT NULL DEFAULT 0,
                    total_rows INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT,
                    PRIMARY KEY (lineage_id, version)
                );
                CREATE INDEX IF NOT EXISTS idx_lineage_current ON dataset_lineages(current_dataset_id);
                CREATE INDEX IF NOT EXISTS idx_lineage_version_dataset ON dataset_lineage_versions(dataset_id);
                CREATE INDEX IF NOT EXISTS idx_datasets_used ON datasets(last_used_at);
                CREATE INDEX IF NOT EXISTS idx_refs_dataset ON dataset_refs(dataset_id);
                """
            )
            self._conn.commit()

    @staticmethod
    def now() -> str:
        return time.strftime('%Y-%m-%dT%H:%M:%S')

    def _execute(self, sql: str, params=()):
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def _query(self, sql: str, params=()):
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def close(self) -> None:
        """Release the connection, or do nothing if it is already gone.

        Closing has to take the same lock every query takes: the housekeeping sweep runs on a run
        worker's thread and the UI reads datasets on the request thread, so a bare
        ``store._conn.close()`` can finalise the SQLite handle while another thread is inside
        ``execute`` on it — which does not raise, it faults the process (measured as an
        ``access violation`` part-way through a full suite run).
        """
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # ── data ────────────────────────────────────────────────────

    def _encode(self, records: list) -> bytes:
        return zlib.compress(_canonical(records).encode('utf-8'), 6)

    @staticmethod
    def _decode(blob: bytes) -> list:
        return json.loads(zlib.decompress(blob).decode('utf-8'))

    def put(self, df: pd.DataFrame, name: str = 'dataset', source: str = SOURCE_UPLOAD, dataset_id: str = '') -> dict:
        """Store a table and return its metadata.

        Idempotent by content: handing over the same rows twice returns the
        existing id and reports ``stored=False`` rather than keeping a second
        copy, which is what stops a habit of re-uploading from filling the disk.
        """
        if df is None:
            raise ValueError('dataset must be a DataFrame')
        if len(df) > Config.DATASET_MAX_ROWS:
            raise ValueError(
                t('ds.too_many_rows', n=len(df), limit=Config.DATASET_MAX_ROWS),
            )
        records = safe_records(df)
        columns = [str(c) for c in df.columns]
        wanted_id = dataset_id or content_id(records) or _random_id()
        payload = self._encode(records)
        stamp = self.now()

        existing = self.meta(wanted_id)
        # Identical rows re-uploaded under another file name keep the name they
        # were first stored with: that is the name saved workflows know this
        # file by, and renaming it underneath them would break the recovery in
        # `find_replacement` the one time it is needed.
        keep_name = str((existing or {}).get('name') or name or 'dataset')
        with self._lock:
            self._conn.execute(
                'INSERT INTO datasets'
                ' (dataset_id, name, source, columns, row_count, byte_size, payload, created_at, last_used_at)'
                ' VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)'
                ' ON CONFLICT(dataset_id) DO UPDATE SET'
                ' source = excluded.source, columns = excluded.columns,'
                ' row_count = excluded.row_count, byte_size = excluded.byte_size,'
                ' payload = excluded.payload, last_used_at = excluded.last_used_at',
                (
                    wanted_id,
                    keep_name,
                    source,
                    json.dumps(columns, ensure_ascii=False),
                    len(records),
                    len(payload),
                    payload,
                    (existing or {}).get('created_at') or stamp,
                    stamp,
                ),
            )
            self._conn.commit()
        meta = self.meta(wanted_id) or {}
        meta['stored'] = existing is None
        logger.info(t('store.dataset_saved', name=name, rows=len(records), did=wanted_id))
        return meta

    def get(self, dataset_id: str) -> pd.DataFrame | None:
        """Read a stored table back, columns included — or None if it is gone."""
        if not dataset_id:
            return None
        row = self._query(
            'SELECT payload, columns FROM datasets WHERE dataset_id = ?',
            (str(dataset_id),),
        )
        if not row:
            return None
        with contextlib.suppress(sqlite3.DatabaseError):
            # A last-used stamp is housekeeping; losing the touch must not lose
            # the file, so it rides its own transaction.
            self._execute('UPDATE datasets SET last_used_at = ? WHERE dataset_id = ?', (self.now(), str(dataset_id)))
        try:
            records = self._decode(row[0]['payload'])
        except (zlib.error, ValueError):
            logger.warning(t('ds.corrupt', did=dataset_id))
            return None
        columns = json.loads(row[0]['columns'] or '[]')
        # The explicit column list restores the shape of a zero-row file, whose
        # records alone carry no column names at all.
        return pd.DataFrame(records, columns=columns) if columns else pd.DataFrame(records)

    def meta(self, dataset_id: str) -> dict | None:
        if not dataset_id:
            return None
        rows = self._query(
            'SELECT dataset_id, name, source, columns, row_count, byte_size, created_at, last_used_at'
            ' FROM datasets WHERE dataset_id = ?',
            (str(dataset_id),),
        )
        if not rows:
            return None
        row = rows[0]
        return {
            'dataset_id': row['dataset_id'],
            'name': row['name'],
            'source': row['source'],
            'columns': json.loads(row['columns'] or '[]'),
            'row_count': int(row['row_count'] or 0),
            'byte_size': int(row['byte_size'] or 0),
            'created_at': row['created_at'],
            'last_used_at': row['last_used_at'],
        }

    def exists(self, dataset_id: str) -> bool:
        return bool(dataset_id) and self.meta(dataset_id) is not None

    def list_datasets(self, limit: int = 200) -> list:
        rows = self._query(
            'SELECT dataset_id, name, source, columns, row_count, byte_size, created_at, last_used_at'
            ' FROM datasets ORDER BY last_used_at DESC LIMIT ?',
            (int(limit),),
        )
        refs = self._ref_counts()
        out = []
        lineage_rows = self._query('SELECT current_dataset_id, name, version FROM dataset_lineages')
        lineages = {
            str(row['current_dataset_id']): {'name': str(row['name']), 'version': int(row['version'])}
            for row in lineage_rows
        }
        for row in rows:
            item = {
                'dataset_id': row['dataset_id'],
                'name': row['name'],
                'source': row['source'],
                'columns': json.loads(row['columns'] or '[]'),
                'row_count': int(row['row_count'] or 0),
                'byte_size': int(row['byte_size'] or 0),
                'created_at': row['created_at'],
                'last_used_at': row['last_used_at'],
            }
            item['workflows'] = refs.get(row['dataset_id'], [])
            item['lineage'] = lineages.get(str(row['dataset_id']))
            out.append(item)
        return out

    def _ref_counts(self) -> dict:
        out = {}
        for row in self._query('SELECT dataset_id, workflow_name FROM dataset_refs'):
            out.setdefault(row['dataset_id'], []).append(row['workflow_name'])
        return out

    def referenced_by(self, dataset_id: str) -> list:
        """Which saved workflows point at this file. The delete endpoint refuses
        on a non-empty answer, so the check has to be a public question rather
        than a caller reaching into ``_ref_counts``."""
        rows = self._query('SELECT DISTINCT workflow_name FROM dataset_refs WHERE dataset_id = ?', (str(dataset_id),))
        return sorted({str(row['workflow_name']) for row in rows if row['workflow_name']})

    def find_replacement(self, name: str, row_count: int = None) -> str | None:
        """A file that matches this one by name (and row count, when known).

        Used when a workflow points at rows that vanished: the same file
        re-uploaded under a new id is almost certainly what it meant. Newest
        first, because the most recent upload is the likeliest candidate.
        """
        if not name:
            return None
        sql = 'SELECT dataset_id FROM datasets WHERE name = ?'
        params = [str(name)]
        if row_count is not None:
            sql += ' AND row_count = ?'
            params.append(int(row_count))
        sql += ' ORDER BY last_used_at DESC LIMIT 1'
        rows = self._query(sql, tuple(params))
        return str(rows[0]['dataset_id']) if rows else None

    # ── cumulative lineages ─────────────────────────────────────
    #
    # A lineage is a named, append-only table: every version points at an
    # ordinary immutable dataset row, and `current_dataset_id` names the newest.
    # Content identity is untouched — the version history is the lineage's
    # bookkeeping, not a mutation of a dataset.

    def _lineage_header(self, row: sqlite3.Row) -> dict:
        meta = self.meta(row['current_dataset_id']) or {}
        return {
            'lineage_id': str(row['lineage_id']),
            'name': str(row['name']),
            'current_dataset_id': str(row['current_dataset_id']),
            'version': int(row['version']),
            'created_at': str(row['created_at'] or ''),
            'updated_at': str(row['updated_at'] or ''),
            'rows': int(meta.get('row_count') or 0),
            'columns': list(meta.get('columns') or []),
            'source': str(meta.get('source') or ''),
        }

    def lineage(self, name: str) -> dict | None:
        rows = self._query('SELECT * FROM dataset_lineages WHERE name = ?', (str(name or ''),))
        return self._lineage_header(rows[0]) if rows else None

    def list_lineages(self) -> list:
        rows = self._query('SELECT * FROM dataset_lineages ORDER BY name')
        return [self._lineage_header(row) for row in rows]

    def lineage_history(self, name: str) -> list:
        found = self.lineage(name)
        if found is None:
            return []
        rows = self._query(
            'SELECT * FROM dataset_lineage_versions WHERE lineage_id = ? ORDER BY version DESC',
            (found['lineage_id'],),
        )
        return [
            {
                'version': int(row['version']),
                'dataset_id': str(row['dataset_id']),
                'run_id': str(row['run_id'] or ''),
                'node_id': str(row['node_id'] or ''),
                'added_rows': int(row['added_rows'] or 0),
                'total_rows': int(row['total_rows'] or 0),
                'created_at': str(row['created_at'] or ''),
            }
            for row in rows
        ]

    def dataset_lineage(self, dataset_id: str) -> dict | None:
        """The lineage whose current version is *dataset_id* (for delete/purge guards)."""
        rows = self._query(
            'SELECT lineage_id FROM dataset_lineage_versions WHERE dataset_id = ? LIMIT 1',
            (str(dataset_id or ''),),
        )
        if not rows:
            return None
        found = self._query('SELECT * FROM dataset_lineages WHERE lineage_id = ?', (rows[0]['lineage_id'],))
        return self._lineage_header(found[0]) if found else None

    @staticmethod
    def _lineage_key(record: dict, columns: list) -> str:
        return json.dumps([record.get(column) for column in columns], ensure_ascii=False, sort_keys=True, default=str)

    def create_lineage(self, name: str, dataset_id: str, version: int = 1) -> dict:
        """Attach an existing dataset as the first version of a lineage (bundle import)."""
        clean = str(name or '').strip()
        if not clean:
            raise ValueError(t('ds.lineage_name_required'))
        meta = self.meta(dataset_id)
        if meta is None:
            raise ValueError(t('ds.lineage_missing_dataset', id=dataset_id))
        with self._lock:
            existing = self._query('SELECT * FROM dataset_lineages WHERE name = ?', (clean,))
            if existing:
                return self._lineage_header(existing[0])
            lineage_id = f'ln-{uuid.uuid4().hex[:12]}'
            stamp = self.now()
            self._conn.execute(
                'INSERT INTO dataset_lineages'
                ' (lineage_id, name, current_dataset_id, version, created_at, updated_at)'
                ' VALUES (?, ?, ?, ?, ?, ?)',
                (lineage_id, clean, str(dataset_id), max(1, int(version or 1)), stamp, stamp),
            )
            self._conn.execute(
                'INSERT INTO dataset_lineage_versions'
                ' (lineage_id, version, dataset_id, run_id, node_id, added_rows, total_rows, created_at)'
                ' VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (
                    lineage_id,
                    max(1, int(version or 1)),
                    str(dataset_id),
                    '',
                    '',
                    int(meta.get('row_count') or 0),
                    int(meta.get('row_count') or 0),
                    stamp,
                ),
            )
            self._conn.commit()
        return self.lineage(clean)

    def append_lineage(
        self,
        name: str,
        df: pd.DataFrame,
        identity: str = 'row',
        key_columns: list = None,
        run_id: str = '',
        node_id: str = '',
    ) -> dict:
        """Append rows that are new by the chosen identity, and return the full table.

        ``identity='row'`` treats a byte-identical row (all current columns) as a
        duplicate; ``identity='columns'`` uses the named key columns and refuses a
        missing one. The existing schema wins: new columns are a named refusal,
        not an outer join. A no-new-rows call returns the current version and does
        not create a version row.
        """
        clean = str(name or '').strip()
        if not clean:
            raise ValueError(t('ds.lineage_name_required'))
        identity = str(identity or 'row').strip().lower()
        if identity not in ('row', 'columns'):
            raise ValueError(t('ds.lineage_identity', value=identity))
        columns = [str(column) for column in (key_columns or []) if str(column).strip()]
        with self._lock:
            found = self._query('SELECT * FROM dataset_lineages WHERE name = ?', (clean,))
            if not found:
                lineage_id = f'ln-{uuid.uuid4().hex[:12]}'
                current = pd.DataFrame(columns=[str(column) for column in df.columns])
                version = 0
                current_id = ''
            else:
                lineage = self._lineage_header(found[0])
                lineage_id = lineage['lineage_id']
                version = lineage['version']
                current_id = lineage['current_dataset_id']
                current = self.get(current_id)
                if current is None:
                    raise ValueError(t('ds.lineage_current_missing', name=clean, id=current_id))

            new_columns = [str(column) for column in df.columns]
            if len(current.columns) and set(new_columns) != set(current.columns):
                extra = [column for column in new_columns if column not in current.columns]
                missing = [column for column in current.columns if column not in new_columns]
                raise ValueError(
                    t(
                        'ds.lineage_columns',
                        name=clean,
                        extra=', '.join(extra) or '-',
                        missing=', '.join(missing) or '-',
                    )
                )
            if not len(current.columns):
                current = current.reindex(columns=new_columns)
            incoming = df.reindex(columns=list(current.columns))
            if identity == 'columns':
                if not columns:
                    raise ValueError(t('ds.lineage_keys_required'))
                missing = [column for column in columns if column not in current.columns]
                if missing:
                    raise ValueError(t('ds.lineage_key_missing', cols=', '.join(missing)))
                key_cols = columns
            else:
                key_cols = list(current.columns)

            existing_keys = {self._lineage_key(row, key_cols) for row in current.to_dict('records')}
            added = []
            seen = set()
            for row in incoming.to_dict('records'):
                key = self._lineage_key(row, key_cols)
                if key in existing_keys or key in seen:
                    continue
                seen.add(key)
                added.append(row)
            if len(current) + len(added) > Config.DATASET_MAX_ROWS:
                raise ValueError(
                    t('ds.lineage_too_large', name=clean, n=len(current) + len(added), max=Config.DATASET_MAX_ROWS)
                )
            if not added:
                meta = self.meta(current_id) or {}
                return {
                    'lineage': {
                        'lineage_id': lineage_id,
                        'name': clean,
                        'current_dataset_id': current_id,
                        'version': version,
                        'rows': len(current),
                    },
                    'dataset': meta,
                    'frame': current,
                    'rows': len(current),
                    'added': 0,
                    'changed': False,
                }

            merged = pd.concat([current, pd.DataFrame(added, columns=list(current.columns))], ignore_index=True)
            meta = self.put(merged, name=clean, source=SOURCE_CUMULATIVE)
            new_version = version + 1
            now = self.now()
            if not found:
                self._conn.execute(
                    'INSERT INTO dataset_lineages'
                    ' (lineage_id, name, current_dataset_id, version, created_at, updated_at)'
                    ' VALUES (?, ?, ?, ?, ?, ?)',
                    (lineage_id, clean, meta['dataset_id'], new_version, now, now),
                )
            else:
                self._conn.execute(
                    'UPDATE dataset_lineages SET current_dataset_id = ?, version = ?, updated_at = ?'
                    ' WHERE lineage_id = ?',
                    (meta['dataset_id'], new_version, now, lineage_id),
                )
            self._conn.execute(
                'INSERT INTO dataset_lineage_versions'
                ' (lineage_id, version, dataset_id, run_id, node_id, added_rows, total_rows, created_at)'
                ' VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (
                    lineage_id,
                    new_version,
                    meta['dataset_id'],
                    str(run_id or ''),
                    str(node_id or ''),
                    len(added),
                    len(merged),
                    now,
                ),
            )
            self._conn.commit()
        return {
            'lineage': {
                'lineage_id': lineage_id,
                'name': clean,
                'current_dataset_id': meta['dataset_id'],
                'version': new_version,
                'rows': len(merged),
            },
            'dataset': meta,
            'frame': merged,
            'rows': len(merged),
            'added': len(added),
            'changed': True,
        }

    def reset_lineage(self, name: str) -> bool:
        """Forget a lineage's history (datasets remain until their own cleanup)."""
        clean = str(name or '').strip()
        if not clean:
            return False
        with self._lock:
            rows = self._query('SELECT lineage_id FROM dataset_lineages WHERE name = ?', (clean,))
            if not rows:
                return False
            lineage_id = rows[0]['lineage_id']
            self._conn.execute('DELETE FROM dataset_lineage_versions WHERE lineage_id = ?', (lineage_id,))
            self._conn.execute('DELETE FROM dataset_lineages WHERE lineage_id = ?', (lineage_id,))
            self._conn.commit()
        return True

    def delete(self, dataset_id: str) -> bool:
        """Drop one file and every pointer to it."""
        cur = self._execute('DELETE FROM datasets WHERE dataset_id = ?', (str(dataset_id),))
        self._execute('DELETE FROM dataset_refs WHERE dataset_id = ?', (str(dataset_id),))
        return bool(cur.rowcount)

    def rename(self, dataset_id: str, name: str) -> str | None:
        """Label a stored file. Returns the stored name, or None when refused.

        The name is the only thing a user can recognise in the dataset list — the
        id is a content hash — and the Upload node titles itself with it, so a
        file that cannot be renamed is a file that can only be recognised by
        counting rows. It is a label, not an identity: two files may carry the
        same one, and `find_replacement` resolves that by newest-use, which is
        how it already behaves for a re-upload.
        """
        clean = sanitize_filename(str(name or '').strip())
        if not clean or not self.exists(dataset_id):
            return None
        self._execute('UPDATE datasets SET name = ? WHERE dataset_id = ?', (clean, str(dataset_id)))
        return clean

    def clear(self) -> int:
        with self._lock:
            cur = self._conn.execute('DELETE FROM datasets')
            self._conn.execute('DELETE FROM dataset_refs')
            self._conn.execute('DELETE FROM dataset_lineage_versions')
            self._conn.execute('DELETE FROM dataset_lineages')
            self._conn.commit()
        return cur.rowcount

    # ── workflow ↔ file mapping ─────────────────────────────────

    def bind(self, workflow_name: str, refs: dict) -> int:
        """Record node → file for one saved workflow. Returns how many pointers.

        Replacing wholesale rather than merging is deliberate: the refs describe
        the workflow *as it was just written*, so an Upload node the user
        deleted since the last save must not keep a pointer alive.
        """
        workflow_name = str(workflow_name or '')
        if not workflow_name:
            return 0
        stamp = self.now()
        rows = [
            (workflow_name, str(node_id), str(dataset_id), str(meta or ''), rows_n, stamp)
            for node_id, dataset_id, meta, rows_n in _normalise_refs(refs)
        ]
        with self._lock:
            self._conn.execute('DELETE FROM dataset_refs WHERE workflow_name = ?', (workflow_name,))
            if rows:
                self._conn.executemany(
                    'INSERT INTO dataset_refs'
                    ' (workflow_name, node_id, dataset_id, file_name, row_count, updated_at)'
                    ' VALUES (?, ?, ?, ?, ?, ?)',
                    rows,
                )
            self._conn.commit()
        return len(rows)

    def refs_for(self, workflow_name: str) -> dict:
        rows = self._query(
            'SELECT node_id, dataset_id, file_name, row_count FROM dataset_refs WHERE workflow_name = ?',
            (str(workflow_name),),
        )
        return {
            row['node_id']: {
                'dataset_id': row['dataset_id'],
                'name': row['file_name'],
                'row_count': int(row['row_count'] or 0),
            }
            for row in rows
        }

    def unbind(self, workflow_name: str) -> int:
        cur = self._execute('DELETE FROM dataset_refs WHERE workflow_name = ?', (str(workflow_name),))
        return cur.rowcount

    def move_workflow(self, old: str, new: str) -> int:
        """Re-point every dataset reference from *old* to *new* (a rename).

        Without this, a renamed workflow reopens with empty Upload nodes (the
        restore asks by the new name and finds nothing) while the OLD name keeps a
        phantom reference that makes its bound files refuse deletion forever — the
        same referenced-by rule the 删除 guard reads. The target's stale refs go
        first so a rename onto a name that once existed cannot inherit them.
        """
        old, new = str(old), str(new)
        with self._lock:
            self._conn.execute('DELETE FROM dataset_refs WHERE workflow_name = ?', (new,))
            cur = self._conn.execute('UPDATE dataset_refs SET workflow_name = ? WHERE workflow_name = ?', (new, old))
            self._conn.commit()
            return cur.rowcount

    def datasets_of(self, workflow_name: str) -> list:
        """Full metadata for every file a saved workflow depends on."""
        refs = self.refs_for(workflow_name)
        out = []
        for node_id, ref in refs.items():
            meta = self.meta(ref['dataset_id'])
            item = dict(meta) if meta else {'dataset_id': ref['dataset_id'], 'missing': True}
            item['node_id'] = node_id
            item['ref_name'] = ref['name']
            item['missing'] = meta is None
            out.append(item)
        return out

    def purge_unreferenced(self, keep_days: int = None) -> int:
        """Delete files no workflow points at and nobody has used recently.

        Keeps everything still referenced: a file a saved workflow depends on
        is what makes that workflow runnable, so only orphans — the leftovers
        of unsaved experiments — are ever removed.
        """
        keep_days = Config.DATASET_KEEP_DAYS if keep_days is None else keep_days
        cutoff = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(time.time() - keep_days * 86400))
        rows = self._query(
            'SELECT dataset_id FROM datasets WHERE dataset_id NOT IN (SELECT dataset_id FROM dataset_refs)'
            ' AND dataset_id NOT IN (SELECT dataset_id FROM dataset_lineage_versions)'
            ' AND COALESCE(last_used_at, created_at) < ?',
            (cutoff,),
        )
        ids = [row['dataset_id'] for row in rows]
        for dataset_id in ids:
            self._execute('DELETE FROM datasets WHERE dataset_id = ?', (dataset_id,))
        if ids:
            logger.info(t('ds.purged', n=len(ids), days=keep_days))
        return len(ids)

    def stats(self) -> dict:
        row = self._query(
            'SELECT COUNT(*) AS n, COALESCE(SUM(byte_size), 0) AS bytes, COALESCE(SUM(row_count), 0) AS rows'
            ' FROM datasets',
        )[0]
        refs = self._query('SELECT COUNT(*) AS n FROM dataset_refs')[0]
        return {
            'datasets': int(row['n']),
            'rows': int(row['rows']),
            'bytes': int(row['bytes']),
            'refs': int(refs['n']),
        }


def _normalise_refs(refs) -> list:
    """Turn ``{node_id: dataset_id}`` (or richer per-node dicts) into rows.

    Tolerating several shapes matters because the caller may only have the
    node's params — which already carry name and row count — and retyping them
    at every call site is how detail gets lost.
    """
    out = []
    for node_id, value in (refs or {}).items():
        if isinstance(value, dict):
            dataset_id = str(value.get('dataset_id') or '')
            name = value.get('dataset_name') or value.get('name') or ''
            row_count = int(value.get('row_count') or 0)
        elif isinstance(value, (list, tuple)):
            dataset_id = str(value[0] or '')
            name = value[1] if len(value) > 1 else ''
            row_count = int(value[2] or 0) if len(value) > 2 else 0
        else:
            dataset_id, name, row_count = str(value or ''), '', 0
        if dataset_id:
            out.append((node_id, dataset_id, name, row_count))
    return out


def _random_id() -> str:
    return hashlib.sha1(os.urandom(16)).hexdigest()[:16]
