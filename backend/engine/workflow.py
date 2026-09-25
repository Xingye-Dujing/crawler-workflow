"""Workflow DAG parser and executor."""

import logging
from collections import defaultdict, deque

import crawl_capabilities as capabilities
from i18n import t
from utils.helpers import platform_for

logger = logging.getLogger(__name__)


def node_label(node: dict, nid: str) -> str:
    """Console-friendly reference to a node: a name first, the id as suffix.

    'node-7' means nothing once a canvas holds a dozen boxes. The name comes
    from the user's title; older saved workflows (and any JSON built without
    one) fall back to the node type's own label, so the console never speaks
    in bare ids. The id stays appended because names repeat — '#node-7' is
    what lets two nodes called 清洗 be told apart in the console.
    """
    node = node or {}
    title = str(node.get('title') or '').strip()
    if not title or title == nid:
        ntype = str(node.get('type') or '').strip()
        fallback = t(f'node.{ntype}') if ntype else ''
        # t() echoes the key when it is missing — an unknown type must not
        # print 'node. #nid'.
        title = '' if not fallback or fallback.startswith('node.') else fallback
    if title and title != nid:
        return f'{title} #{nid}'
    return nid


class WorkflowEngine:
    """Parses DAG from workflow definition and schedules execution."""

    def __init__(self, workflow: dict, executor=None):
        self.workflow = workflow
        self.executor = executor
        self.nodes = {n['id']: n for n in workflow.get('nodes', [])}
        self.connections = workflow.get('connections', [])
        self.settings = workflow.get('settings', {})
        self._adj = defaultdict(list)
        self._in_degree = defaultdict(int)
        self._build_graph()

    def _build_graph(self):
        # Both ends must be nodes this canvas actually holds. A connection naming a
        # node that is not there — a hand-edited file, a payload from another
        # version of the canvas — used to enter the in-degree table anyway, which
        # made the ordering place more ids than there are nodes and raise
        # 「工作流存在环，以下节点无法排序：」 with an *empty* node list: the user was
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
        """Wires that name a node the canvas does not contain."""
        return [c for c in self.connections if c.get('from') not in self.nodes or c.get('to') not in self.nodes]

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
        sub_nodes = [self.nodes[nid] for nid in component if nid in self.nodes]
        sub_conns = [c for c in self.connections if c['from'] in component and c['to'] in component]
        sub_workflow = {
            'nodes': sub_nodes,
            'connections': sub_conns,
            'settings': self.settings,
        }
        return WorkflowEngine(sub_workflow, self.executor)

    @staticmethod
    def _source_errors(node: dict, params: dict, platform, label: str) -> list[str]:
        """Refuse a data source whose declared mode cannot run — using the matrix.

        This used to be a hand-written copy of "which platform wants what", with
        ``if platform == 'wechat'`` here and the same branches again in the
        executor. Two descriptions of one rule is how a node passed validation
        and then crawled something else, so there is now exactly one place that
        knows: :mod:`crawlers.capabilities`.
        """
        if not platform:
            return [t('engine.source_no_platform', nid=label)]
        mode = capabilities.mode_of_node(node)
        if mode is None:
            return [t('engine.source_unknown_platform', nid=label, platform=platform)]
        wanted = capabilities.requested_mode_key(node)
        offered = capabilities.mode_keys_for(platform)
        if wanted and len(offered) > 1 and wanted not in offered:
            # More than one mode on this platform means the fallback would have run
            # a different kind of crawl than the node asked for. Named by what it
            # asked for, not by the field the substituted mode happens to require.
            return [t('engine.source_unknown_mode', nid=label, platform=platform)]
        errors = []
        for field in capabilities.required_missing(mode, params):
            errors.append(t('engine.source_missing', nid=label, field=t(field.name_key)))
        for field, value in capabilities.unoffered_selections(mode, params):
            errors.append(t('engine.source_bad_option', nid=label, field=t(field.name_key), value=value))
        for field in capabilities.link_fields(mode):
            urls = field.value_from(params)
            bad = sum(1 for u in urls if platform_for(u) != field.links_of)
            if bad:
                errors.append(t('engine.source_link_mismatch', nid=label, n=bad, platform=field.links_of))
        return errors

    def validate(self) -> list[str]:
        """Everything that would make a node produce nothing.

        Messages go through i18n (the engine is loaded by the app, which has the
        catalogues) so a validation failure reads in the console's language
        instead of as a stray English line. The cycle check below is no
        exception: it raises a ValueError whose text is catalogued too, because a
        malformed workflow is still something the user has to fix from the
        console's words.
        """
        errors = []
        if not self.nodes:
            # An empty canvas has no cycle, no missing parameter and no node to
            # report — and used to "complete": 「发现 0 条工作流」, 0/0 nodes,
            # outcome completed, toast 已完成. A run of nothing is not a success;
            # the browser's own gate says so, and the backend must too.
            return [t('engine.empty_canvas')]
        for conn in self.dangling_connections():
            # Named by the ids, because the node they point at is exactly the thing
            # the canvas no longer has — no title exists to resolve.
            errors.append(t('engine.dangling_connection', src=str(conn['from']), dst=str(conn['to'])))
        for nid, node in self.nodes.items():
            ntype = node.get('type')
            params = node.get('params', {})
            # Console references lead with the node's (possibly renamed) title
            # so "node-7" never has to be decoded against the canvas.
            label = node_label(node, nid)
            if ntype == 'source':
                platform = node.get('platform') or params.get('platform')
                errors.extend(self._source_errors(node, params, platform, label))
            if ntype == 'upload' and not params.get('dataset_id'):
                errors.append(t('engine.upload_no_file', nid=label))
            if ntype == 'comment' and not str(params.get('urls') or '').strip():
                errors.append(t('engine.comment_no_urls', nid=label))
            # The canvas writes ``operation`` on the node *and* in its params, and
            # every executor reads either. Validation has to accept the same pair,
            # or a hand-edited file that would run perfectly is refused as
            # misconfigured — the strictness has no counterpart in the runner.
            operation = node.get('operation') or params.get('operation')
            if ntype == 'process' and not operation:
                errors.append(t('engine.process_no_op', nid=label))
            if ntype == 'output' and not operation:
                errors.append(t('engine.output_no_op', nid=label))
            if ntype == 'analysis' and not (params.get('steps') or operation):
                errors.append(t('engine.analysis_no_op', nid=label))
            if ntype == 'tokenize' and not params.get('text_column'):
                errors.append(t('engine.tokenize_no_column', nid=label))
            if ntype == 'visualize':
                if not params.get('chart_type'):
                    errors.append(t('engine.visualize_no_chart', nid=label))
                if not params.get('x_field'):
                    errors.append(t('engine.visualize_no_x', nid=label))
            if ntype == 'name':
                # The name node is pure metadata: it carries no data, so it
                # must sit at the head (nothing feeds into it), wire into a
                # real node, and carry a non-empty label — that label is what
                # groups the run in the Execution History panel.
                if not str(params.get('workflow_name') or '').strip():
                    errors.append(t('engine.name_no_label', nid=label))
                if any(c.get('to') == nid for c in self.connections):
                    errors.append(t('engine.name_not_head', nid=label))
                if not any(c.get('from') == nid for c in self.connections):
                    errors.append(t('engine.name_no_downstream', nid=label))
        try:
            self.topological_sort()
        except ValueError as e:
            errors.append(str(e))
        return errors
