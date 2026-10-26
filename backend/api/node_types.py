"""节点类型目录 Blueprint — one read-only endpoint that describes every node type.

The canvas needs three facts per type: does a pasted/restored canvas know it, what label and
group does the palette show, and which parameters does a new node start with. Serving them from
the server keeps ``nodes/catalog.py`` the single declaration; the frontend's own tables remain a
cold-page fallback that ``tests/unit/test_node_plugins.py`` pins against this payload.
"""

from flask import Blueprint, jsonify
from nodes.catalog import PLUGINS
from nodes.defaults import DYNAMIC_DEFAULTS, NODE_DEFAULTS

bp = Blueprint('node_types', __name__)


@bp.route('/api/node-types', methods=['GET'])
def node_types():
    types = []
    for plugin in PLUGINS.values():
        types.append(
            {
                'type': plugin.type,
                'labelKey': plugin.label_key,
                'category': plugin.category,
                'rows': plugin.rows,
                'quiet': plugin.quiet,
                'defaults': NODE_DEFAULTS.get(plugin.type),
                'defaultsFrom': DYNAMIC_DEFAULTS.get(plugin.type, ''),
            }
        )
    return jsonify({'ok': True, 'types': types})
