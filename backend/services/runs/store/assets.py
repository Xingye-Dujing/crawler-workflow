"""Content identity of what a node produced, and the lineage its children reuse on.

A node's fingerprint says *what the node IS* (its type and params), which is the right key for
"this node was not edited". It is the wrong key for "this node's input did not change": re-running a
parent over a changed keyword produces a different table under the SAME fingerprint, and a resume then
restored the child's rows that were computed from the old one — a table the user could see was stale
while the record called the run done.

``node_assets`` is the missing half: one row per node per run carrying the sha256 of what it produced
(:mod:`core.asset` is the contract) and the sha256 of its parents' assets. Two rules keep it honest:

* a node with no rows has no content, so it has no row here (the same reason ``node_schema`` skips an
  empty table) — and "no evidence" never refuses a reuse, it only fails to confirm one;
* an attempt writes one row per node, replacing the previous attempt's, because the address is
  ``(run_id, node_id)`` and the row must describe the content that is stored NOW.
"""

import hashlib
import json


class AssetsMixin:
    def put_asset(self, record: dict) -> None:
        """Record what one node produced. ``record`` is the store's flat shape (see the columns).

        ``record`` accepts either the asset's own ``id`` (``DataAsset.to_dict``) or an explicit
        ``asset_id``: the table column is named ``asset_id`` so a row reader never confuses it with
        the run's id.
        """
        self._execute(
            'INSERT OR REPLACE INTO node_assets '
            '(run_id, node_id, asset_id, schema_version, kind, owner, origin, sha256, size, uri, '
            ' parents_json, input_sha, meta_json, created_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (
                record['run_id'],
                record['node_id'],
                record.get('asset_id') or record['id'],
                int(record.get('schema_version') or 1),
                record['kind'],
                record['owner'],
                record['origin'],
                record['sha256'],
                int(record['size']),
                record['uri'],
                json.dumps(list(record.get('parents') or ()), ensure_ascii=False),
                str(record.get('input_sha') or ''),
                json.dumps(record.get('meta') or {}, ensure_ascii=False),
                record.get('created_at') or self.now(),
            ),
        )

    def asset_for(self, run_id: str, node_id: str) -> dict | None:
        """The asset row one node wrote in one run, or None when it produced nothing."""
        rows = self._query(
            'SELECT * FROM node_assets WHERE run_id = ? AND node_id = ?',
            (run_id, node_id),
        )
        return dict(rows[0]) if rows else None

    def input_sha_for(self, run_id: str, node_ids: list) -> str:
        """The digest of ``node_ids``' assets in this run, or '' when none of them has one.

        Sorted, so the answer does not depend on the order the canvas happens to list connections
        in; ts includes the asset id as well as its hash, so a rewired canvas is a different input
        even when both parents produced identical content.
        """
        pairs = []
        for node_id in node_ids:
            asset = self.asset_for(run_id, str(node_id))
            if asset:
                pairs.append(f'{node_id}:{asset["sha256"]}')
        if not pairs:
            return ''
        return hashlib.sha256('\n'.join(sorted(pairs)).encode('utf-8')).hexdigest()

    def drop_assets(self, run_id: str, node_ids: list | None = None) -> int:
        """Forget the assets of one run (or of some of its nodes). Called wherever rows go away."""
        if node_ids is None:
            cur = self._execute('DELETE FROM node_assets WHERE run_id = ?', (run_id,))
            return cur.rowcount
        removed = 0
        with self._lock:
            for node_id in node_ids:
                removed += self._conn.execute(
                    'DELETE FROM node_assets WHERE run_id = ? AND node_id = ?', (run_id, str(node_id))
                ).rowcount
            self._conn.commit()
        return removed
