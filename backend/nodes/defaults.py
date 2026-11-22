"""The parameters a freshly created node starts with, per node type.

`GET /api/node-types` seeds a new node from this table, and
``tests/unit/analysis/test_node_plugins`` pins it against the catalogue. Every type declares its
seeds in its manifest's ``params`` section, so this module is the projection, not a second table.
``source`` has no entry on purpose — its defaults depend on the crawl matrix the browser has just
fetched (platform, engine, mode), so the canvas derives them from that matrix instead of freezing
one shape here; ``DYNAMIC_DEFAULTS`` tells the client which type that is.
"""

from capabilities_kernel import registry as capabilities

NODE_DEFAULTS: dict[str, dict] = capabilities.node_defaults()

#: Types whose defaults are derived where the facts live, not frozen here. The API says so in
#: ``defaultsFrom`` so the client knows to ask its own source of truth.
DYNAMIC_DEFAULTS = {'source': 'capabilities'}
