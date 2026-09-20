"""Workflow DAG parser and executor."""

import logging
from collections import defaultdict, deque

from i18n import t

logger = logging.getLogger(__name__)


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
        for conn in self.connections:
            f, t = conn['from'], conn['to']
            self._adj[f].append(t)
            self._in_degree[t] += 1
            if f not in self._in_degree:
                self._in_degree[f] = 0

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
            raise ValueError('Workflow contains a cycle!')
        return order

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
                raise ValueError('Workflow contains a cycle!')
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
            f, t = conn['from'], conn['to']
            undirected[f].add(t)
            undirected[t].add(f)

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
        """

        def _key(comp):
            nums = [int(nid.split('-')[-1]) for nid in comp]
            return min(nums)

        return sorted(components, key=_key)

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

    def validate(self) -> list[str]:
        """Everything that would make a node produce nothing.

        Messages go through i18n (the engine is loaded by the app, which has the
        catalogues) so a validation failure reads in the console's language
        instead of as a stray English line. The one exception is the cycle
        check below: that is a ValueError from the topological sort, i.e. a
        malformed workflow rather than a configuration mistake.
        """
        errors = []
        for nid, node in self.nodes.items():
            ntype = node.get('type')
            params = node.get('params', {})
            if ntype == 'source':
                platform = node.get('platform') or params.get('platform')
                if not platform:
                    errors.append(t('engine.source_no_platform', nid=nid))
                elif platform == 'wechat':
                    # WeChat scrapes article URLs; a keyword would do nothing.
                    if not str(params.get('urls') or '').strip():
                        errors.append(t('engine.source_no_urls', nid=nid))
                elif not str(params.get('keyword') or '').strip():
                    errors.append(t('engine.source_no_keyword', nid=nid))
            if ntype == 'upload' and not params.get('dataset_id'):
                errors.append(t('engine.upload_no_file', nid=nid))
            if ntype == 'process' and not node.get('operation'):
                errors.append(t('engine.process_no_op', nid=nid))
            if ntype == 'output' and not node.get('operation'):
                errors.append(t('engine.output_no_op', nid=nid))
            if ntype == 'analysis' and not (params.get('steps') or params.get('operation')):
                errors.append(t('engine.analysis_no_op', nid=nid))
            if ntype == 'tokenize' and not params.get('text_column'):
                errors.append(t('engine.tokenize_no_column', nid=nid))
            if ntype == 'visualize':
                if not params.get('chart_type'):
                    errors.append(t('engine.visualize_no_chart', nid=nid))
                if not params.get('x_field'):
                    errors.append(t('engine.visualize_no_x', nid=nid))
            if ntype == 'name':
                # The name node is pure metadata: it carries no data, so it
                # must sit at the head (nothing feeds into it), wire into a
                # real node, and carry a non-empty label — that label is what
                # groups the run in the Execution History panel.
                if not str(params.get('workflow_name') or '').strip():
                    errors.append(t('engine.name_no_label', nid=nid))
                if any(c.get('to') == nid for c in self.connections):
                    errors.append(t('engine.name_not_head', nid=nid))
                if not any(c.get('from') == nid for c in self.connections):
                    errors.append(t('engine.name_no_downstream', nid=nid))
        try:
            self.topological_sort()
        except ValueError as e:
            errors.append(str(e))
        return errors
