"""Workflow DAG parser and executor."""

import logging
from collections import defaultdict, deque

import cookie_preflight

import crawl_capabilities as capabilities
from config import Config
from i18n import t
from services.cookie_manager import CookieManager
from utils.helpers import as_bool, platform_for, split_urls

logger = logging.getLogger(__name__)


def is_effectively_enabled(node: dict, disabled_types: set) -> bool:
    """Whether *node* takes part in a run, or is treated as if it were not on the canvas.

    A node is disabled two ways: its own ``enabled`` switch is off, or its node *type* is
    switched off for the whole canvas. ``disabled_types`` is the type-level set. A missing
    ``enabled`` reads as the default (on) through ``as_bool`` — never a ``== True`` test,
    which would flip a real ``False`` JSON value the wrong way (see the rule this honours).
    """
    if not as_bool((node.get('params') or {}).get('enabled'), True):
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


#: Node types whose result is a table of rows.
#:
#: A name node is metadata and a visualize node answers a chart SPEC, so neither can hand
#: rows to anything downstream. That matters at exactly one place, and it is not obvious
#: there: the save node now MERGES its incoming tables, so a wire from a node that carries
#: no rows is one the canvas draws and the run ignores — the silent half of the picture
#: this rule exists to refuse.
TABLE_NODE_TYPES = frozenset({'source', 'upload', 'resume', 'comment', 'process', 'analysis', 'tokenize', 'output'})


def _account_session_errors(platforms, params: dict, label: str) -> list[str]:
    """Refuse a node whose account holds no login — named, never guessed around.

    The 账号 field is not a choice from a fixed list, so :func:`
    capabilities.unoffered_selections` cannot judge it: it names a *session*, and the
    question is whether this machine can produce that session right now. Answered by
    :func:`cookie_preflight.has_session_to_test`, the same question the pre-run probe
    asks, because two definitions of "is a login here" is how a valid session gets
    called missing on one side and a dead one accepted on the other.

    A blank means the **default account** — an account with a real file of its own, not
    a wildcard. Falling back to "whichever login exists" would hand this node somebody
    else's session (and their rate limit, and their risk profile), while crawling on
    with no login at all returns a wall read as an empty table: the run looks done and
    collected nothing. Both are refused by name instead.

    ``platforms`` is every platform the node will visit, because a comment node crawls
    several feeds with the single account on its form.
    """
    account = str(params.get('account') or '').strip()
    manager = CookieManager(Config.COOKIE_DIR)
    out = []
    for platform in dict.fromkeys(str(p or '').strip() for p in platforms if str(p or '').strip()):
        if not cookie_preflight.has_session_to_test(platform, account=account):
            out.append(
                t(
                    'engine.source_no_cookie_account',
                    nid=label,
                    platform=platform,
                    account=manager.label_of(account),
                )
            )
    return out


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
        sub_nodes = [self.nodes[nid] for nid in component if nid in self.nodes]
        sub_conns = [c for c in self.connections if c['from'] in component and c['to'] in component]
        sub_workflow = {
            'nodes': sub_nodes,
            'connections': sub_conns,
            'settings': self.settings,
        }
        return WorkflowEngine(sub_workflow, self.executor)

    @staticmethod
    def _source_errors(node: dict, params: dict, platform, label: str, has_data_input: bool = False) -> list[str]:
        """Refuse a data source whose declared mode cannot run — using the matrix.

        This used to be a hand-written copy of "which platform wants what", with
        ``if platform == 'wechat'`` here and the same branches again in the
        executor. Two descriptions of one rule is how a node passed validation
        and then crawled something else, so there is now exactly one place that
        knows: :mod:`crawlers.capabilities`.

        ``has_data_input`` is the feed's other half: the matrix says WHICH forms
        can read an upstream column, the graph says whether a table actually
        arrives, and every mismatch between the two is refused by name — because
        "wired but unfed" would silently re-crawl the pasted list the user thinks
        they replaced, and "fed but unwired" would read a table that is not there.
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
        feed = capabilities.feed_of(mode)
        fed = capabilities.fed_keys(mode, has_data_input)
        if has_data_input and not feed:
            errors.append(t('engine.source_feed_no_mode', nid=label))
        elif has_data_input:
            for field, col in feed:
                if not str(params.get(col) or '').strip():
                    errors.append(t('engine.source_feed_no_column', nid=label, field=t(field.name_key)))
        elif feed and any(str(params.get(col) or '').strip() for _field, col in feed):
            errors.append(t('engine.source_feed_no_input', nid=label))
        for field in capabilities.required_missing(mode, params, fed_keys=fed):
            errors.append(t('engine.source_missing', nid=label, field=t(field.name_key)))
        for field, value in capabilities.unoffered_selections(mode, params):
            errors.append(t('engine.source_bad_option', nid=label, field=t(field.name_key), value=value))
        # A session crawl is refused here when the account its node names holds no login.
        # Anonymous modes (weibo's 热搜 board, a WeChat article body) declare
        # ``needs_session=False`` and are not asked — refusing them would be the same bug
        # that once stopped WeChat crawling entirely.
        if mode.needs_session:
            errors.extend(_account_session_errors([platform], params, label))
        for field in capabilities.link_fields(mode):
            if field.key in fed:
                # The fed column's content is the parent's — unknown at design time, so
                # ownership cannot be decided here. The comment engine filters and names
                # foreign links at execution time; that is the net, not this check.
                continue
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
            errors.append(t('engine.dangling_connection', src=str(conn['from']), dst=str(conn['to'])))
        for nid, node in self.nodes.items():
            ntype = node.get('type')
            params = node.get('params', {})
            # Console references lead with the node's (possibly renamed) title
            # so "node-7" never has to be decoded against the canvas.
            label = node_label(node, nid)
            if ntype == 'source':
                platform = node.get('platform') or params.get('platform')
                errors.extend(self._source_errors(node, params, platform, label, has_data_input=nid in data_inputs))
            if ntype == 'upload' and not params.get('dataset_id'):
                errors.append(t('engine.upload_no_file', nid=label))
            if ntype == 'comment' and not str(params.get('urls') or '').strip():
                errors.append(t('engine.comment_no_urls', nid=label))
            elif ntype == 'comment':
                # A comment crawl is always a logged-in one (its rate limit is per ACCOUNT,
                # which is the reason accounts exist), and one node walks several feeds with
                # the single account on its form — so every platform those links name has to
                # be able to answer for it. Unknown until the links are read, so this is the
                # node's own text only: nothing is inferred about an upstream table.
                links = split_urls(str(params.get('urls') or ''))
                errors.extend(_account_session_errors([platform_for(u) for u in links], params, label))
            # The canvas writes ``operation`` on the node *and* in its params, and
            # every executor reads either. Validation has to accept the same pair,
            # or a hand-edited file that would run perfectly is refused as
            # misconfigured — the strictness has no counterpart in the runner.
            operation = node.get('operation') or params.get('operation')
            if ntype == 'process' and not operation:
                errors.append(t('engine.process_no_op', nid=label))
            if ntype == 'output' and not operation:
                errors.append(t('engine.output_no_op', nid=label))
            if ntype == 'output':
                # A save node is the canvas's merge point: several incoming tables become
                # one file, and the merged table is what flows onwards. Both halves of
                # "there is nothing to save here" were passing validation silently — a
                # save node with no wire at all, and one fed only by a name node or a
                # chart — and then wrote an empty file over a green node.
                parents = [str(c.get('from')) for c in self.connections if str(c.get('to')) == str(nid)]
                if not parents:
                    errors.append(t('engine.output_no_upstream', nid=label))
                elif not any((self.nodes.get(pid) or {}).get('type') in TABLE_NODE_TYPES for pid in parents):
                    errors.append(t('engine.output_no_table', nid=label))
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
