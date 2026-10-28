"""Reading what a run is going to be — its shape, its cost and its shape on the graph.

Four questions are answered here, each of them once, and none of them needs the Flask app, the
run ledger or a browser: which of the two run shapes the canvas asked for, which transport it
will speak, whether anything on this canvas will call a language model, and which nodes a rerun
of one node invalidates.

They left ``app.py`` because a scheduled fire, a rerun of a single node and the API's execute
door all ask the same questions, and a Blueprint or a scheduler module may not import the app to
ask them. Behaviour is unchanged; the equivalence was measured against the app-internal versions
over the cases ``tests/api/test_nodes_execution.py`` already names.
"""

from analyzers.llm_client import LLMClient
from engine.workflow import effective_workflow
from i18n import t
from services.analysis.pipeline import UnknownOperationError
from services.analysis.process import PROCESS_ENUMS

#: The two run shapes the canvas settings can name. Kept next to the reader that refuses
#: anything else, so a second spelling of this list cannot drift away from the first.
RUN_MODES = ('parallel', 'serial')

#: The AI transports this app can actually speak. Kept next to the reader that refuses anything
#: else so a second spelling cannot drift — the single source is ``LLMClient.PROVIDERS``.
LLM_PROVIDERS = LLMClient.PROVIDERS


def run_mode(settings: dict) -> str:
    """The run's shape, READ — and an unrecognised name is refused, never guessed.

    ``mode == 'serial'`` was the old test, so every other token ran PARALLEL while the browser
    asked the same question the safe way round (`workflow.js`: ``mode !== 'parallel'`` means
    serial). A draft whose settings said anything else therefore started two same-platform
    crawls at once while the panel believed it was running one, and the 「本次不用 Profile」
    question — which is what keeps two crawls off one browser profile — never fired. That is
    the measured login-wall collision, decided by a string comparison nobody validated.
    """
    raw = (settings or {}).get('mode')
    value = str(raw or '').strip().lower()
    if not value:
        return RUN_MODES[0]
    if value not in RUN_MODES:
        raise UnknownOperationError(
            t('api.runSettingOption', setting='mode', value=str(raw), allowed=', '.join(RUN_MODES))
        )
    return value


def llm_provider(llm_cfg: dict) -> str:
    """The transport name, READ — an unrecognised one is refused BY NAME, never folded.

    The request's ``provider`` reaches ``LLMClient``, which used to write
    ``provider if provider in (...) else 'ollama'``: a hand-typed or stale-tab
    ``"OpenRouter"`` (wrong case) became a silent local-daemon call looking for a tag that does
    not exist, the whole node failed, yet the durable run record still claimed the transport was
    OpenRouter — a record naming a transport that never ran. ``transport.py`` already refuses
    this shape for the cloud host; a local host must refuse it too rather than guess.
    """
    raw = (llm_cfg or {}).get('provider')
    value = str(raw or '').strip().lower()
    if not value:
        return LLM_PROVIDERS[0]
    if value not in LLM_PROVIDERS:
        raise UnknownOperationError(
            t('api.runSettingOption', setting='provider', value=str(raw), allowed=', '.join(LLM_PROVIDERS))
        )
    return value


def op_needs_llm(op: str, params: dict) -> bool:
    """Whether this node's own choice will call a language model.

    Read through the declared default the panel shows (``PROCESS_ENUMS``), because a blank
    field means "not stated", not "not the model": an ``emotion`` node left empty IS an LLM
    run, while an empty ``sentiment`` node is SnowNLP and costs nothing. The test this
    replaces was ``mode != 'ml'``, which charged a row-by-row model pass to every node whose
    mode said something else — and a cloud host then refused the whole run for a missing API
    key that no node in it had asked for.

    ``clean`` used to be listed here as an operation that always calls a model. It has a
    mode of its own now, and its regex mode washes a Weibo comment without asking anyone —
    so the answer comes from that same table instead of from a hard-coded membership, and
    the two can no longer disagree.
    """
    spec = PROCESS_ENUMS.get(op) or {}
    if 'mode' not in spec:
        return False
    # Only the declared DEFAULT is read here; the option list beside it is the panel's
    # business (and an unlisted spelling is refused by name when the node runs).
    default, _ = spec['mode']
    raw = str(params.get('mode') or '').strip()
    value = raw if raw else default
    # Only the mode that NAMES the model needs one. An unrecognised mode is not treated as
    # a model call either: it is refused BY NAME when the node runs, and answering "a key
    # is required" here would send the user to configure credentials for a definition
    # whose actual problem is a spelling.
    return value == 'llm'


def workflow_needs_llm(workflow: dict) -> bool:
    """True when any process node in the payload will actually call a model.

    Cleaner always does; the three classifiers and entity recognition only when the node
    picked the model. A crawl-and-save workflow must not be blocked by a missing API key or
    an unpicked Ollama tag — the frontend makes the same distinction (``nodeNeedsLlm``)
    before it opens the console, and both read one table of which mode means which model.

    Read off the EFFECTIVE graph, not the drawn one. A switched-off node is not on the canvas
    (the engine's own rule, which validate/naming/fingerprint/execution all obey), and this is
    a COST question: walking the raw nodes refused 「请选择模型」 for a run that would call no
    model at all, and refused a scheduled canvas — forever, at save time and again at every
    fire — over a node the user had deliberately turned off.
    """
    for node in effective_workflow(workflow).get('nodes') or []:
        if not isinstance(node, dict) or node.get('type') != 'process':
            continue
        params = node.get('params') or {}
        op = str(params.get('operation') or node.get('operation') or '')
        if op_needs_llm(op, params):
            return True
    return False


def component_name(sub_engine) -> str:
    """This connected component's own workflow name, from its name node.

    The canvas may hold several workflows in one run, each headed by its own
    name node — recording them all under the *first* name on the canvas
    swallowed every other workflow's label (they all filed as the first
    one's name, or as "untitled" when the label sat in another component).
    """
    for node in sub_engine.nodes.values():
        if node.get('type') != 'name':
            continue
        label = str((node.get('params') or {}).get('workflow_name') or '').strip()
        if label:
            return label
    return ''


def downstream_closure(effective: dict, node_id: str) -> list:
    """``node_id`` plus every node reachable by following wires forward.

    A rerun of one node invalidates that node AND everything downstream of it, because a
    child's input IS its parent's output — keeping a child's stale rows would let it feed
    on a result that no longer exists. Walked over the effective (already-disabled-dropped)
    graph so a disabled node is never resurrected by a rerun of its neighbour."""
    adjacency: dict = {}
    for conn in effective.get('connections') or []:
        adjacency.setdefault(conn.get('from'), []).append(conn.get('to'))
    seen = {node_id}
    stack = [node_id]
    while stack:
        current = stack.pop()
        for child in adjacency.get(current, []):
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return list(seen)
