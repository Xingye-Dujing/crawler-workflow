"""Adopt a stored node output from an earlier run as this node's rows.

This is the node you drop in when the original source is no longer co-operating — logged out,
blocked, expensive — but its rows are already paid for and sitting in runs.db. It replaces nothing
upstream: whatever it produces flows onward exactly as the original node's output would have.

The store arrives through ``ctx`` (the run passes its own ledger), so this executor reads no store
singleton directly — it is pure against ``ctx``.
"""

from api.http import _safe_int
from state import add_log

from i18n import t
from nodes.context import NodeCall
from services.runs.store import RUN_RUNNING

NODE_TYPE = 'resume'


def execute_resume_node(node: dict, ctx: dict):
    store = ctx['store']
    params = node.get('params') or {}
    run_id = str(params.get('resume_run_id') or '').strip()
    node_id = str(params.get('resume_node_id') or '').strip()
    limit = _safe_int(params.get('resume_limit'), 0, minimum=0)

    if not run_id:
        # Nothing picked yet: fall back to the newest unfinished run of THIS workflow's shape.
        # Without the fingerprint filter a 'node-2' from an unrelated workflow — the id repeats in
        # every canvas — would be adopted wholesale; and the run currently writing must not feed
        # itself.
        candidates = [
            r
            for r in store.list_resumable(str(ctx.get('wf_fp') or '') or None, limit=5)
            if r.get('run_id') != ctx.get('run_id') and r.get('status') != RUN_RUNNING
        ]
        if not candidates:
            add_log(t('resume.no_run'))
            return []
        run_id = str(candidates[0].get('run_id') or '')

    def _adopted_label(nid: str) -> str:
        """The node being adopted, named the way the console names everything.

        ``node_label`` cannot help here: that node lives in another run's record, not on this canvas.
        But a bare ``node-2`` is just as unreadable, and the row it is about to hand over carries the
        title its own run stored — so the same 「标题 #id」 form is available, and a run of a dozen
        nodes can be told apart.
        """
        if not nid:
            return t('resume.unpicked')
        state = store.node_statuses(run_id).get(nid) or {}
        title = str(state.get('title') or '').strip()
        return f'{title} #{nid}' if title and title != nid else nid

    rows = store.load_rows(run_id, node_id) if node_id else []
    if not rows:
        # No node picked (or the pick holds nothing): take the fullest one.
        statuses = store.node_statuses(run_id)
        best = max(statuses.values(), key=lambda n: int(n.get('row_count') or 0), default=None)
        if best and int(best.get('row_count') or 0) > 0:
            node_id = str(best.get('node_id') or '')
            rows = store.load_rows(run_id, node_id)
    if not rows:
        add_log(t('resume.empty', rid=run_id, nid=_adopted_label(node_id)))
        return []
    if limit and len(rows) > limit:
        rows = rows[:limit]
    add_log(t('resume.loaded', rid=run_id, nid=_adopted_label(node_id), n=len(rows)))
    return rows


def run(node: dict, call: NodeCall) -> list:
    return execute_resume_node(node, call.ctx or {'store': _default_store(), 'run_id': ''})


def _default_store():
    # The direct-call path (no run context) needs a store; import here so the module stays importable
    # without the app's store singletons. ``app._run_resume`` used to inline this fallback.
    from stores import get_run_store

    return get_run_store()
