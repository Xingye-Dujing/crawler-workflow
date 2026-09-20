"""Workflow DAG parser and executor."""

import logging
from collections import defaultdict, deque

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
        errors = []
        for nid, node in self.nodes.items():
            ntype = node.get('type')
            if ntype == 'source' and not node.get('platform'):
                errors.append(f'Node {nid}: source node missing platform')
            if ntype == 'process' and not node.get('operation'):
                errors.append(f'Node {nid}: process node missing operation')
            if ntype == 'output' and not node.get('operation'):
                errors.append(f'Node {nid}: output node missing operation')
            if ntype == 'analysis':
                params = node.get('params', {})
                steps = params.get('steps')
                if not steps and not params.get('operation'):
                    errors.append(f'Node {nid}: analysis node has no operation/steps configured')
            if ntype == 'tokenize':
                params = node.get('params', {})
                if not params.get('text_column'):
                    errors.append(f'Node {nid}: tokenize node missing text_column')
            if ntype == 'visualize':
                params = node.get('params', {})
                if not params.get('chart_type'):
                    errors.append(f'Node {nid}: visualize node missing chart_type')
                if params.get('data_source', 'input') == 'input' and not params.get('x_field'):
                    errors.append(f'Node {nid}: visualize node missing x_field')
        try:
            self.topological_sort()
        except ValueError as e:
            errors.append(str(e))
        return errors
