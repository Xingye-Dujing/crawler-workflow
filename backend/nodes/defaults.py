"""The parameters a freshly created node starts with, per node type.

`GET /api/node-types` seeds a new node from this table, and
``tests/unit/analysis/test_node_plugins`` pins it against the catalogue. Every type declares its
seeds in its manifest's ``params`` section, so this module is the projection, not a second table.
The source node declares no params on purpose — its fields depend on platform × engine × mode — so
its plugin answers ``defaults_from='capabilities'`` and the client asks the platform matrix.
"""

from capabilities_kernel import registry as capabilities

NODE_DEFAULTS: dict[str, dict] = capabilities.node_defaults()
