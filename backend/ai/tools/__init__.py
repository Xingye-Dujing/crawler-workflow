"""The verbs the agent may call, one module per domain.

Most tools only read: a dataset, a run, the capability matrix or the docs, and return a bounded
JSON/text result. Writes to application state are **artifacts**: a proposal the user applies
through the app's normal route. That boundary is why an AI mistake cannot delete a run or rewrite
a canvas.

Two groups are the deliberate exception, both off by default and both refused on a cloud host:
``read:code`` (the repository source) needs ``ai_allow_code_context``, and ``read:python`` /
``write:python`` / ``exec:python`` (the account's script workspace) need ``ai_allow_python``.
The permission is checked at execution time in the domain module, not only where the turn's schema
list is built — a replayed history can name a tool the current turn does not offer.

This package is the aggregation, exactly like ``nodes/catalog.py``: each domain module ends with a
``TOOLS`` tuple of its own ``ToolSpec``s, and ``TOOLS`` below is the one dict every reader uses.

``ask_user_question``, ``update_plan`` and ``present_artifact`` are control tools: the runtime
intercepts them and never looks for a handler here.

| module | answers |
|---|---|
| ``catalog`` | what this build can do (coverage, capability skills, CatBus, charts, operators) |
| ``datasets`` | bounded dataset reads and the one quantitative query surface |
| ``runs`` | one run, its console, an edited result, and the failed-subtree rerun |
| ``workflows`` | saved-workflow management and the export shelf |
| ``models`` | which local model this machine can run, and two bounded uses |
| ``code`` | the read-only source tools (local/desktop only) |
| ``policy`` | the three name tables: universal / approval / always-approval |
"""

from ai.tools import catalog, code, datasets, models, runs, workflows
from ai.tools.policy import ALWAYS_APPROVAL_TOOLS, APPROVAL_TOOLS, UNIVERSAL_TOOLS
from ai.tools.runs import RERUN_REFUSAL_KEYS, rerun_refusal_message

__all__ = [
    'ALWAYS_APPROVAL_TOOLS',
    'APPROVAL_TOOLS',
    'RERUN_REFUSAL_KEYS',
    'TOOLS',
    'UNIVERSAL_TOOLS',
    'rerun_refusal_message',
]

_DOMAINS = (catalog, code, datasets, models, runs, workflows)


def __getattr__(name: str):
    """The historical ``ai.tools.tool_dataset_peek`` address, resolved on the OWNING module.

    A CALL keeps working, because the function is the same object wherever it is reached from. A
    PATCH must name the owner (``ai.tools.datasets._dataset_frame``): that is the namespace the
    function reads its globals from, and patching the package would leave it unchanged — the trap
    this split was careful to avoid in its own tests.
    """
    for module in _DOMAINS:
        if hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


#: Every tool this build offers, keyed by name. The dict is built from per-domain tuples, so "which
#: spec belongs to which question" is answered by the file, and adding a tool is one entry there.
TOOLS = {
    spec.name: spec
    for spec in (
        *catalog.TOOLS,
        *datasets.TOOLS,
        *runs.TOOLS,
        *models.TOOLS,
        *code.TOOLS,
        *workflows.TOOLS,
    )
}
