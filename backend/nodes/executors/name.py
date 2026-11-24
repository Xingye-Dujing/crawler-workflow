"""The name node: metadata only, no rows.

Its label was already lifted into ``workflow_name`` before the run started (so the history panel can
group by it). It produces no rows — downstream source/upload nodes read nothing from their inputs,
which is exactly why the node must connect to one.
"""

from nodes.context import NodeCall


def emit_columns(
    _node: dict,
    _merged: list[str] | None,
    _parents: list[list[str] | None] | None = None,
) -> list[str]:
    """The lineage view's answer: this node contributes no columns to anything downstream."""
    return []


def run(_node: dict, _call: NodeCall) -> list:
    """No parameter to honour and no rows to produce: the empty list is the answer, not a failure."""
    return []
