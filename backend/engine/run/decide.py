"""Which record this attempt writes, and whether it splits — the decisions, without the I/O.

The run package used to hold these four as private helpers between 1984 lines of loop and store
calls, so the only way to test "a same-named component of another canvas must not adopt this row"
was to run a whole workflow. The rules are pure: they read dicts and sets and answer a bool or an
index. The caller keeps every side effect (the pop that consumes an adopted row, ``start_run``,
the lock).

Keeping the pop at the call site is deliberate: adopting CONSUMES the candidate, because one
canvas may legitimately carry two same-named components, and a match that stayed in the list handed
BOTH the same ``run_id`` — the second ``start_run`` reset the first's record to
``running/node_done=0`` and left the other same-named row an orphan nobody adopts.
"""

from __future__ import annotations


def record_has_component(candidate: dict | None, node_ids: set | None) -> bool:
    """Whether a stored row carries any node of this component (or says nothing about nodes)."""
    if not node_ids:
        return True
    stored = {str(node.get('node_id') or '') for node in (candidate or {}).get('nodes') or [] if isinstance(node, dict)}
    return not stored or bool(stored & node_ids)


def record_belongs(record: dict | None, node_ids: set | None, fingerprint: str = '') -> bool:
    """Whether *record* is THIS component's row, so its id may be kept by it.

    Two questions, both about not writing one workflow's work onto another's record: the row has to
    carry one of this component's nodes, and it must describe the same canvas (a same-named component
    of another fingerprint is a different row). An empty fingerprint on either side is "not
    recorded", not a mismatch — older rows and direct callers.
    """
    if not record:
        return False
    recorded = str(record.get('workflow_fingerprint') or '')
    if fingerprint and recorded and recorded != fingerprint:
        return False
    return record_has_component(record, node_ids)


def split_records(mode: str, wf_count: int, adopted: dict | None) -> bool:
    """Whether this attempt opens one record per workflow instead of one for the canvas.

    Serial is one row per workflow that starts — but a 继续 onto a record that covered the whole
    canvas (``wf_count > 1``, written by a 并行 attempt) has to keep that one row: its stored rows
    are filed under that id, and a per-component row refuses a node set it does not own, so every
    component but the first would re-crawl work the record already holds.
    """
    if mode != 'serial' or wf_count <= 1:
        return False
    return not (adopted is not None and int(adopted.get('wf_count') or 1) > 1)


def choose_record(
    name: str,
    resumable: list,
    resuming: bool,
    requested: str = '',
    fingerprint: str = '',
    node_ids: set | None = None,
) -> tuple[int | None, dict]:
    """The position and row this workflow should keep writing, if it is a 继续.

    Only the resume path adopts: the attempt after a 继续 must accumulate onto the rows that already
    exist, so it finds each workflow's own unfinished row of this canvas again instead of opening a
    fresh one per press. A plain Run is a new attempt and gets new rows — "one record per attempt" is
    what makes the panel's history mean anything.

    ``requested`` is the id the user pressed 继续 on. It is preferred over the newest name match:
    re-deriving the record from the name alone made a run on an OLD interrupted row adopt the newer
    (even completed) row of the same workflow, rewrite its history and leave the chosen row
    interrupted forever.

    The id may be older than the 50 rows the caller could list; the caller prepends the requested
    row's own record, so this function sees it. The fingerprint is the identity that survives a
    工作流命名 edit, because the label is not an input.

    Returns ``(None, {})`` when nothing is adopted. The caller pops the returned index: consuming
    the candidate is what keeps two same-named components from sharing one ``run_id``.
    """
    if not resuming:
        return None, {}
    wanted = str(requested or '')
    if wanted:
        for position, candidate in enumerate(resumable):
            same_component = str(candidate.get('workflow_name') or '') == name
            same_canvas = bool(fingerprint) and str(candidate.get('workflow_fingerprint') or '') == fingerprint
            if (
                str(candidate.get('run_id') or '') == wanted
                and (same_component or same_canvas)
                and record_has_component(candidate, node_ids)
            ):
                return position, dict(candidate)
    for position, candidate in enumerate(resumable):
        candidate_fp = str(candidate.get('workflow_fingerprint') or '')
        if fingerprint and candidate_fp and candidate_fp != fingerprint:
            # A same-named component of another fingerprint is a different record; adopting it
            # put the upload's node on the crawl's row.
            continue
        if not record_has_component(candidate, node_ids):
            continue
        if str(candidate.get('workflow_name') or '') == name:
            return position, dict(candidate)
    return None, {}
