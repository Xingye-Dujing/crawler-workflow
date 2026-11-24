"""What one node produced, as an asset row — and the line a child's reuse may not cross.

``core.asset.DataAsset`` is the contract; this module is the ONE place that fills it from a run, so
every node type gets the same identity without a single executor opting in. Two questions it answers
for :mod:`engine.run.node`:

* **record** — after a node settles with content, write the row: its sha256/size, the owners and
  origin, and the asset ids of its parents.
* **conflict** — may a stored child be reused? Only when the parents' content is the content it was
  computed from. The node fingerprint cannot answer that (it describes the node, not the table), so a
  resume after a re-crawled parent used to restore a child's rows from data that no longer existed.

Both answers are conservative in one direction on purpose: **no evidence never refuses a reuse**.
A run written before assets existed, a parent that produced nothing, a link to a node outside this
record — each of those leaves the lineage unknown, and the old structural rule still decides.
"""

import logging

from core.asset import DataAsset, artifact_digest, rows_digest
from runtime import account_context

from i18n import t

logger = logging.getLogger(__name__)


def _content(result) -> tuple[str, str, int] | None:
    """``(kind, sha256, size)`` for a node's product, or None when it produced nothing to name.

    A table is its rows; a chart/compile node's DICT is its product (a spec carrying LaTeX or a
    staged PDF), so it is hashed as one document rather than dropped — that is what lets
    ``visualize → compile`` carry a lineage too. Anything else (None, a scalar, an error dict) is
    not content.
    """
    if isinstance(result, list):
        if not result:
            return None
        sha, size = rows_digest(result)
        return 'table', sha, size
    if isinstance(result, dict) and result and not result.get('error'):
        sha, size = artifact_digest(result)
        return 'chart', sha, size
    return None


def _owner() -> str:
    """The account that produced the content; ``local`` is the login-free owner, not a blank."""
    account = account_context.current()
    return account.user_id if account is not None else 'local'


def record_asset(store, ctx: dict, node: dict, nid: str, result, upstream) -> dict | None:
    """Write this node's asset row and answer the record (None when there is nothing to name).

    Called from the settlement paths that leave the node's content as the thing downstream reads.
    A malformed record is logged and skipped rather than raised: the store write happens inside a
    run, and one unnameable asset must not turn a paid-for node into a failure.
    """
    content = _content(result)
    run_id = str((ctx or {}).get('run_id') or '')
    if content is None or not run_id:
        return None
    kind, sha, size = content
    parent_ids = []
    for pid, _res in upstream or ():
        parent = store.asset_for(run_id, str(pid))
        if parent:
            parent_ids.append(str(parent['asset_id']))
    asset = DataAsset(
        id=f'{run_id}:{nid}',
        kind=kind,
        owner=_owner(),
        origin=f'run:{run_id}:{nid}',
        sha256=sha,
        size=size,
        uri=f'run/{run_id}/{nid}',
        parents=tuple(parent_ids),
        meta={'rows': len(result) if isinstance(result, list) else 0, 'node_type': str(node.get('type') or '')},
        created_at=store.now(),
    )
    problems = asset.problems()
    if problems:
        logger.warning(t('run.assetSkipped', nid=nid, why='; '.join(problems)))
        return None
    record = asset.to_dict()
    record.update(
        run_id=run_id,
        node_id=nid,
        input_sha=store.input_sha_for(run_id, [str(pid) for pid, _res in upstream or ()]),
    )
    store.put_asset(record)
    return record


def lineage_conflict(store, run_id: str, nid: str, upstream) -> bool:
    """Whether a stored result for ``nid`` was computed from parents whose content has changed.

    Only a KNOWN mismatch counts: no stored asset, no recorded input digest, or no parent with an
    asset of its own each answer False, so an older run keeps the structural rule it was written
    under. A rewired canvas is a mismatch even when both parents produced identical rows, because
    the digest covers the node ids it was derived from.
    """
    stored = store.asset_for(run_id, nid)
    if not stored:
        return False
    was = str(stored.get('input_sha') or '')
    if not was:
        return False
    now = store.input_sha_for(run_id, [str(pid) for pid, _res in upstream or ()])
    return bool(now) and now != was
