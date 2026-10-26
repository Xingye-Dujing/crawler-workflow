"""The name node: metadata only, no rows.

Its label was already lifted into ``workflow_name`` before the run started (so the history panel can
group by it). It produces no rows — downstream source/upload nodes read nothing from their inputs,
which is exactly why the node must connect to one.
"""

from nodes.context import NodeCall

NODE_TYPE = 'name'


def execute_name_node(_node: dict) -> list:
    """``_node`` is read by nothing here: every executor is called with it, and this one has no
    parameter to honour. The empty list is the answer, not a failure."""
    return []


def run(node: dict, _call: NodeCall) -> list:
    return execute_name_node(node)
