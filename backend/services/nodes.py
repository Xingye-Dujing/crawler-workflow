"""Workflow node executors — the A-4 sequence that moves ``_execute_*_node`` out of ``app.py``.

``app.py`` is the HTTP layer plus, historically, the whole node-execution subsystem. This module
takes the executors one at a time so ``app.py`` stops growing every time an analyzer or chart type
is added. Each executor is imported back into ``app.py`` **under its original ``_execute_*_node``
name** (``from services.nodes import execute_name_node as _execute_name_node``), so ``_execute_node``'s
dispatch table and any test that pokes the app-module symbol are unaffected — the function just
lives here now. Executors depend only on their arguments (node/current_input/upstream/run_ctx/ctx)
plus the shared services/engine modules; anything still reaching a raw ``app``-module global is a
reason to keep that executor in ``app.py`` until the seam is ready, not to import it half-moved.

First slice: ``execute_name_node`` — the metadata node, the most self-contained executor (pure:
takes the node dict, returns no rows), so it proves the pattern with zero behaviour change.
"""


def execute_name_node(node: dict) -> list:
    """The name node is metadata, not data: its label was already lifted into
    ``workflow_name`` before the run started (so the history panel can group by
    it). It produces no rows — downstream source/upload nodes read nothing
    from their inputs, which is exactly why the node must connect to one."""
    return []
