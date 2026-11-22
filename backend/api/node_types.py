"""节点类型目录 Blueprint — one read-only endpoint that describes every node type.

The canvas needs four facts per type: does a pasted/restored canvas know it, what label and group
does the palette show, which parameters does a new node start with, and which schema/form does its
settings panel render. Serving them from the server keeps the capability manifests the single
declaration; ``static/js/node-types-fallback.js`` is the generated cold-page copy of the same
payload (a page that has not finished the fetch still has a list), never a hand-written table.
"""

from capabilities_kernel import registry as capabilities
from flask import Blueprint, jsonify
from nodes.defaults import NODE_DEFAULTS
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
    for entry in capabilities.node_schema_entries():
        served = dict(entry)
        served['defaults'] = _defaults_for(entry['type'])
        types.append(served)
    return jsonify({'ok': True, 'types': types})
