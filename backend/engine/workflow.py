"""Workflow DAG parser and executor."""

import logging
from collections import defaultdict, deque

from capabilities_kernel.registry import manifest_for_node
from core.refs import as_bool
from nodes.catalog import NODE_TYPES
from nodes.labels import node_label

from i18n import t
from services.validation.engine import ValidationContext, validation_problems

logger = logging.getLogger(__name__)


def node_params(node: dict) -> dict:
    """A node's params as a mapping — the ONE reader, for a file whose params are not an object.

    An AI-written or hand-edited workflow can carry ``"params": "去重，按评论内容"`` (a sentence,
    not an object). Every caller here assumed a dict, so the first ``.get`` raised
    ``AttributeError: 'str' object has no attribute 'get'`` inside
    ``/api/workflow/diagnostics`` and ``/api/runs/resumable`` — a 500 every few seconds, with
    nothing naming the file. Reading through this helper keeps the surface alive; the invalid
    shape is refused WHERE IT IS REPORTED (``validate_workflow``) rather than mid-computation.
    """
    params = node.get('params') if isinstance(node, dict) else None
    return params if isinstance(params, dict) else {}


def is_effectively_enabled(node: dict, disabled_types: set) -> bool:
    """Whether *node* takes part in a run, or is treated as if it were not on the canvas.

    A node is disabled two ways: its own ``enabled`` switch is off, or its node *type* is
    switched off for the whole canvas. ``disabled_types`` is the type-level set. A missing
    ``enabled`` reads as the default (on) through ``as_bool`` — never a ``== True`` test,
    which would flip a real ``False`` JSON value the wrong way (see the rule this honours).
    """
    if not as_bool(node_params(node).get('enabled'), True):
        return False
    return str(node.get('type') or '') not in (disabled_types or set())


def effective_workflow(workflow: dict) -> dict:
    """The graph a run actually sees: a node is present only if it is switched on (its own
    ``enabled`` and its type are both on) AND it still has a way in — at least one upstream that
    is itself present, or no upstream at all.

    This is the single answer to "a disabled node is as if it were not there". Removing a node
    takes its wires with it, so its downstream lose an input; a downstream node that has no other
    live input starves and is removed too, and that cascades. The point the user gave for the
    feature: disabling the head node of a workflow starves the whole chain, so 禁用工作流 is just
    禁用节点 applied to the first box — there is no separate workflow-switch to keep in sync. The
    exception is fan-in: a node fed by several upstreams (a join) survives as long as ANY one of
    them is live, because it still has a way to receive data. A wire whose far end is not a node
    on the canvas is not an upstream at all (that is a dangling wire, reported by ``validate``).

    It returns a fresh dict and never mutates *workflow*, so the caller can still compare against
    the full canvas — that is how the run record names the workflows that were skipped.
    """
    settings = workflow.get('settings') or {}
    disabled_types = set(settings.get('disabledTypes') or [])
    raw_connections = [c for c in (workflow.get('connections') or []) if isinstance(c, dict)]
    nodes = [n for n in (workflow.get('nodes') or []) if isinstance(n, dict)]
    ids = {str(n.get('id')) for n in nodes}

    # Every present node needs a live way in: an incoming wire whose source is itself present,
    # or no incoming wire at all. Removal is monotonic (a node only ever loses its 'present'
    # flag), so iterating to a fixed point converges — including over a cycle, which validate
    # rejects anyway but must not loop on here.
    upstream = defaultdict(set)
    for conn in raw_connections:
        source, target = str(conn.get('from')), str(conn.get('to'))
        if source in ids and target in ids:
            upstream[target].add(source)

    present = {str(n.get('id')): is_effectively_enabled(n, disabled_types) for n in nodes}
    changed = True
    while changed:
        changed = False
        for nid in ids:
            if not present[nid]:
                continue
            parents = upstream.get(nid)
            if parents and not any(present.get(p) for p in parents):
                present[nid] = False
                changed = True

    kept = [n for n in nodes if present[str(n.get('id'))]]
    kept_ids = {str(n.get('id')) for n in kept}
    connections = [c for c in raw_connections if str(c.get('from')) in kept_ids and str(c.get('to')) in kept_ids]
    return {'nodes': kept, 'connections': connections, 'settings': settings}


#: The node-type set comes from the node catalogue (``nodes/catalog.py``): one declaration per type,
#: with its row shape and console quietness. The executor registry (``nodes/registry.py``) is pinned
#: against the same catalogue by a contract test, so a type cannot be half-registered. The plugin
#: architecture was designed by the 2026-10 refactor (its process ledger has since been removed; the
#: tree it describes is what ``nodes/catalog.py`` declares today).
#
# ``TABLE_NODE_TYPES``/``PDF_SOURCE_NODE_TYPES`` are no longer imported here: the checks that needed
# them moved into the capabilities' own validators in P2 (accumulate, compile, output).


class WorkflowEngine:
    """Parses DAG from workflow definition and schedules execution."""

    def __init__(self, workflow: dict, executor=None):
        self.workflow = workflow
        self.executor = executor
        # The whole canvas — disabled nodes and their wires included — is kept so the run
        # record can name which workflows were switched off. Every decision the engine
        # MAKES (validation, topological order, components, the structure fingerprint) is
        # taken on the effective graph below, where a disabled node simply is not there.
        self.all_nodes = {n['id']: n for n in workflow.get('nodes', [])}
        self.all_connections = workflow.get('connections', [])
        effective = effective_workflow(workflow)
        self.settings = effective['settings']
        self.disabled_types = set(self.settings.get('disabledTypes') or [])
        self.nodes = {n['id']: n for n in effective['nodes']}
        self.connections = effective['connections']
        self._adj = defaultdict(list)
        self._in_degree = defaultdict(int)
        self._build_graph()

    def effective_workflow_dict(self) -> dict:
        """The effective graph as a plain workflow dict, for structure fingerprinting."""
        return {'nodes': list(self.nodes.values()), 'connections': self.connections, 'settings': self.settings}

    def _build_graph(self):
        # Both ends must be nodes this canvas actually holds. A connection naming a
        # node that is not there — a hand-edited file, a payload from another
        # version of the canvas — used to enter the in-degree table anyway, which
        # made the ordering place more ids than there are nodes and raise
        # “工作流存在环，以下节点无法排序：” with an *empty* node list: the user was
        # told to hunt a loop that did not exist, in a sentence whose own slot was
        # blank. The honest report is the missing endpoint, and ``validate`` says it.
        for conn in self.connections:
            f, t_ = conn['from'], conn['to']
            if f not in self.nodes or t_ not in self.nodes:
                continue
            self._adj[f].append(t_)
            self._in_degree[t_] += 1
            if f not in self._in_degree:
                self._in_degree[f] = 0

    def dangling_connections(self) -> list[dict]:
        """Wires that name a node the canvas does not contain at all.

        Computed against the FULL canvas, not the effective graph: a wire into a
        *disabled* node is not broken (that node is on the canvas, just switched off —
        it is dropped as-if-deleted, silently), but a wire into a node that is not on
        the canvas is a hand-edited or stale file the user must be told about. Scanning
        the effective graph instead would hide that bug behind the disable filter.
        """
        return [
            c for c in self.all_connections if c.get('from') not in self.all_nodes or c.get('to') not in self.all_nodes
        ]

    def topological_sort(self) -> list[str]:
        in_deg = defaultdict(int, self._in_degree)
        for nid in self.nodes:
            if nid not in in_deg:
                in_deg[nid] = 0
        queue = deque([n for n, d in in_deg.items() if d == 0])
        order = []
        while queue:
            node = queue.popleft()
            order.append(node)
            for nb in self._adj[node]:
                in_deg[nb] -= 1
                if in_deg[nb] == 0:
                    queue.append(nb)
        if len(order) != len(self.nodes):
            raise ValueError(self._cycle_error(set(self.nodes) - set(order)))
        return order

    def _cycle_error(self, stuck) -> str:
        """Name the nodes the ordering could not place, in the console's own form.

        A bare English 'Workflow contains a cycle!' said nothing about *which*
        two nodes were wired back into each other, and the loop is drawn right in
        front of the user — the one message in this file that must point at it.
        """
        labels = ', '.join(node_label(self.nodes[nid], str(nid)) for nid in sorted(stuck))
        return t('engine.cycle', nodes=labels)

    def group_by_level(self) -> list[list[str]]:
        """Group nodes by BFS level for parallel execution."""
        in_deg = defaultdict(int, self._in_degree)
        for nid in self.nodes:
            if nid not in in_deg:
                in_deg[nid] = 0
        levels = []
        remaining = set(self.nodes.keys())
        while remaining:
            current = [n for n in remaining if in_deg[n] == 0]
            if not current:
                raise ValueError(self._cycle_error(remaining))
            levels.append(current)
            for n in current:
                for nb in self._adj[n]:
                    in_deg[nb] -= 1
                remaining.remove(n)
        return levels

    def find_workflows(self) -> list[set[str]]:
        """Find all connected components (workflows) in the DAG.

        Uses undirected BFS so that disconnected sub-graphs are
        detected independently.
        """
        # Build undirected adjacency
        undirected = defaultdict(set)

        for conn in self.connections:
            source, target = conn['from'], conn['to']
            # Same rule as the graph above: a wire to a node that is not on the
            # canvas joins nothing, and letting it in would invent a component
            # consisting of an id the executor cannot run.
            if source not in self.nodes or target not in self.nodes:
                continue
            undirected[source].add(target)
            undirected[target].add(source)

        visited = set()
        components = []
        for nid in self.nodes:
            if nid in visited:
                continue
            comp = set()
            queue = [nid]
            while queue:
                cur = queue.pop(0)
                if cur in visited:
                    continue
                visited.add(cur)
                comp.add(cur)
                for nb in undirected[cur]:
                    if nb not in visited:
                        queue.append(nb)
            components.append(comp)
        return components

    @staticmethod
    def sort_workflows(components: list[set[str]]) -> list[set[str]]:
        """Sort connected components by their minimum creation index
        (the numeric suffix of node IDs like 'node-1', 'node-2').

        This determines which workflow runs first in serial mode.

        A canvas always mints ``node-N`` ids, but a workflow opened from a file
        someone edited by hand can name its nodes anything — and reading the
        suffix with ``int()`` used to raise on 'n1', which took the whole run
        down with an unhandled ValueError before a single node executed. An id
        without a numeric suffix now sorts last, tie-broken by its own text, so
        the order stays deterministic without assuming how nodes are named.
        """

        def _index(nid: str) -> tuple:
            tail = str(nid).rsplit('-', 1)[-1]
            return (0, int(tail), '') if tail.isdigit() else (1, 0, str(nid))

        return sorted(components, key=lambda comp: min(_index(nid) for nid in comp))

    def extract_subworkflow(self, component: set[str]) -> 'WorkflowEngine':
        """Create a new WorkflowEngine containing only the nodes and
        internal connections belonging to *component*."""
        # Walk ``self.nodes`` (insertion order, i.e. the canvas's own node order) and keep the
        # ones in this component — never iterate the ``component`` SET. A set's iteration order
        # depends on string hashing (PYTHONHASHSEED), so a component holding two ``name`` nodes
        # could emit them in either order, ``_component_name`` would pick a different label as
        # the FIRST name node, and a serial run's per-workflow ``workflow_name`` would rename
        # itself between two attempts of the same canvas. ``继续`` and the row lookup key on that
        # name, so a renamed component orphaned rows the crawl had already paid for.
        component_ids = set(component)
        sub_nodes = [node for nid, node in self.nodes.items() if nid in component_ids]
        sub_conns = [c for c in self.connections if c['from'] in component_ids and c['to'] in component_ids]
        sub_workflow = {
            'nodes': sub_nodes,
            'connections': sub_conns,
            'settings': self.settings,
        }
        return WorkflowEngine(sub_workflow, self.executor)

    def validate(self, samples: dict | None = None, columns: dict | None = None) -> list[str]:
        """The console-facing view of validation: the run gate's messages, in entry order.

        Only ``error`` entries block a run; a ``warning`` is advice for the canvas and must not
        refuse a run that would otherwise start (a missing column the executor names at run time is
        the existing case). The parity tests read this; the edit-time badges read
        ``validate_detailed`` to know WHICH node each message is about. Kept as a one-line
        projection so there is exactly one rule body."""
        return [
            entry['message']
            for entry in self.validate_detailed(samples=samples, columns=columns)
            if entry['severity'] == 'error'
        ]

    def validate_detailed(self, samples: dict | None = None, columns: dict | None = None) -> list[dict]:
        """Every problem the canvas should show, as one entry per problem (errors and warnings).

        ``id`` is the node the problem belongs to (``None`` for a canvas-wide one —
        an empty canvas, a dangling wire, a cycle), so the frontend can put a badge on
        the right box; ``code`` is the ``engine.*`` key (or ``engine.source`` for the
        matrix-driven source rules, whose message already names the field); ``message``
        is the localised text. ``severity``/``param``/``fix`` travel with it so a panel can
        point at the box and apply a mechanical fix without re-deriving either. ``validate``
        is the run gate: it keeps the error entries only.

        ``samples`` is ``{node_id: rows}`` — up to 200 upstream rows from a stored run of the same
        node fingerprint. It is OPTIONAL and the caller owns it (``services.validation.samples``):
        the engine itself never opens a database, so a unit test or an AI draft stays pure. A node
        absent from the mapping is not preflighted — no sample, no verdict.

        ``columns`` is ``{node_id: [column names] | None}`` — the shape of each node's output table
        (a settled run's recorded schema, else the producer's declared contract;
        ``services.validation.contracts``). It is optional for the same reason, and an unknown
        upstream (``None``) makes the consumer's read check silent rather than a guess.
        """
        entries: list[dict] = []

        def add(nid, code, message, *, severity='error', param='', fix=None):
            entry = {'id': nid, 'code': code, 'message': message, 'severity': severity, 'param': param, 'fix': fix}
            entries.append(entry)

        if not self.nodes:
            # An empty canvas has no cycle, no missing parameter and no node to
            # report — and used to "complete": “发现 0 条工作流”, 0/0 nodes,
            # outcome completed, toast 已完成. A run of nothing is not a success;
            # the browser's own gate says so, and the backend must too.
            add(None, 'engine.empty_canvas', t('engine.empty_canvas'))
            return entries
        # Which nodes a DATA table can reach: an incoming wire from anything other
        # than a name node. ``name → source`` is the labelling pattern this canvas
        # has always had, and a name node produces no rows — treating "any wire" as
        # "a feed" would refuse every labelled workflow.
        data_inputs = set()
        for conn in self.connections:
            src = self.nodes.get(conn.get('from'))
            if src is not None and src.get('type') != 'name' and conn.get('to') in self.nodes:
                data_inputs.add(conn.get('to'))
        for conn in self.dangling_connections():
            # Named by the ids, because the node they point at is exactly the thing
            # the canvas no longer has — no title exists to resolve.
            add(
                None,
                'engine.dangling_connection',
                t('engine.dangling_connection', src=str(conn['from']), dst=str(conn['to'])),
            )
        for nid, node in self.nodes.items():
            ntype = node.get('type')
            # Console references lead with the node's (possibly renamed) title
            # so "node-7" never has to be decoded against the canvas.
            label = node_label(node, nid)
            if ntype not in NODE_TYPES:
                # No executor knows this type: refuse it by name here, before the run is paid for,
                # rather than falling through to an empty result the record would stamp 完成.
                add(nid, 'engine.unknown_node_type', t('engine.unknown_node_type', nid=label, type=str(ntype)))
                continue
            # A migrated node declares its pre-run refusals in its manifest; this loop is the one
            # evaluator, so the console, the canvas badge and the AI tools cannot disagree about
            # what a node needs. Warnings stay in this list for the canvas badge; ``validate``
            # filters them out so only an error can refuse a run.
            manifest = manifest_for_node(ntype)
            if manifest is not None:
                context = ValidationContext(
                    node_id=str(nid),
                    label=label,
                    nodes=self.nodes,
                    connections=self.connections,
                    data_inputs=frozenset(data_inputs),
                )
                for problem in validation_problems(
                    manifest,
                    node,
                    context,
                    sample=(samples or {}).get(str(nid)),
                    columns=columns,
                ):
                    add(
                        nid,
                        problem['code'],
                        t(problem['message_key'], nid=label, **problem['context']),
                        severity=problem['severity'],
                        param=problem.get('param') or '',
                        fix=problem.get('fix'),
                    )
        try:
            self.topological_sort()
        except ValueError as e:
            add(None, 'engine.cycle', str(e))
        return entries
