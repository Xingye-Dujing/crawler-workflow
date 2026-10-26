"""How the console names a node: a user title first, the id as a suffix.

``node_label`` lives outside ``engine.workflow`` so every node executor can reach it without
importing the DAG parser — which pulls in the crawler capability layer and pandas — while
``engine.workflow`` keeps its own import of the same function for validation messages.
"""

from i18n import t


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
