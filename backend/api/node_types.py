"""节点类型目录 Blueprint — one read-only endpoint that describes every node type.

The canvas needs three facts per type: does a pasted/restored canvas know it, what label and
group does the palette show, and which parameters does a new node start with. Serving them from
the server keeps ``nodes/catalog.py`` the single declaration; the frontend's own tables remain a
cold-page fallback that ``tests/unit/analysis/test_node_plugins.py`` pins against this payload.
"""

from flask import Blueprint, jsonify
from nodes.catalog import PLUGINS
from nodes.defaults import DYNAMIC_DEFAULTS, NODE_DEFAULTS
from runtime.settings import get_setting

bp = Blueprint('node_types', __name__)


def _defaults_for(node_type: str) -> dict | None:
    """The static defaults, with the user's global choices merged over the sizes.

    ``nodes/defaults.py`` stays the shape of a new node; the values a user can tune
    globally (comment limits, part sizes, live export) are read here so a fresh node,
    the panel and the executor cannot seed three different numbers.
    """
    base = NODE_DEFAULTS.get(node_type)
    if base is None:
        return None
    out = dict(base)
    if node_type == 'comment':
        out.update(
            {
                'comment_limit': int(get_setting('default_comment_limit')),
                'part_size': int(get_setting('default_comment_part_size')),
                'per_article_file': bool(get_setting('default_per_article_file')),
                'keep_parts': bool(get_setting('default_keep_parts')),
            }
        )
    elif node_type == 'process' and 'live_export' in out:
        out['live_export'] = bool(get_setting('default_live_export'))
    return out


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
                'defaults': _defaults_for(plugin.type),
                'defaultsFrom': DYNAMIC_DEFAULTS.get(plugin.type, ''),
            }
        )
    return jsonify({'ok': True, 'types': types})
