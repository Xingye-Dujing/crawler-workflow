"""Source-reading tools: ``code_search`` and ``code_read``, which never touch user data.

Both answer ``ai.codeCloudRefused`` on a host with no source tree, both stay inside the source root
(a ``..`` segment or an absolute path is refused), and both are bounded — 20 hits, 400 lines. They
exist for a citation or a patch proposal, not to browse the repository.
"""

from pathlib import Path

from ai.errors import AIError
from ai.tools.shared import _int_arg
from ai.types import ToolSpec


def tool_code_search(args: dict, _ctx: dict) -> dict:
    """A bounded read-only source search; local/desktop snapshot only, never cloud."""
    from ai import environment

    root_text = environment.code_root()
    if not root_text:
        raise AIError('ai.codeCloudRefused', kind='capability')
    query = str(args.get('query') or '').strip()
    if not query:
        raise AIError('ai.toolRefused', kind='bad_request', tool='code_search', reason='query is missing')

    root = Path(root_text)
    search_root = root / 'backend' if (root / 'backend').is_dir() else root
    hits = []
    for path in list(search_root.rglob('*.py'))[:2000] + list((search_root / 'static' / 'js').rglob('*.js'))[:2000]:
        if 'node_modules' in path.parts or 'vendor' in path.parts or '__pycache__' in path.parts:
            continue
        try:
            text = path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        if query not in text:
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            if query in line:
                hits.append(
                    {
                        'path': str(path.relative_to(search_root)).replace('\\', '/'),
                        'line': line_number,
                        'text': line.strip()[:240],
                    }
                )
                if len(hits) >= 20:
                    return {'hits': hits, 'truncated': True}
    return {'hits': hits, 'truncated': False}


def tool_code_read(args: dict, _ctx: dict) -> dict:
    """One source file (bounded), for a citation or a patch proposal."""
    from ai import environment

    root_text = environment.code_root()
    if not root_text:
        raise AIError('ai.codeCloudRefused', kind='capability')

    root = Path(root_text)
    relative = str(args.get('path') or '').strip().replace('\\', '/')
    if not relative or '..' in relative.split('/') or relative.startswith('/'):
        raise AIError(
            'ai.toolRefused', kind='bad_request', tool='code_read', reason='path must stay inside the source tree'
        )
    base = root / 'backend' if (root / 'backend').is_dir() else root
    target = (base / relative).resolve()
    if not str(target).startswith(str(base.resolve())) or not target.is_file():
        raise AIError('ai.toolRefused', kind='not_found', tool='code_read', reason=f'no source file {relative}')
    limit = _int_arg(args.get('lines'), 200, 1, 400)
    lines = target.read_text(encoding='utf-8', errors='replace').splitlines()
    return {
        'path': str(target.relative_to(base)).replace('\\', '/'),
        'lines': len(lines),
        'start': 1,
        'content': '\n'.join(lines[:limit]),
        'truncated': len(lines) > limit,
    }


TOOLS = (
    ToolSpec(
        'code_search',
        'Search this checkout’s Python and JavaScript source. Local/desktop snapshot only.',
        {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']},
        permission='read:code',
        handler=tool_code_search,
    ),
    ToolSpec(
        'code_read',
        'Read one source file (bounded) for a citation or a patch proposal.',
        {
            'type': 'object',
            'properties': {'path': {'type': 'string'}, 'lines': {'type': 'integer'}},
            'required': ['path'],
        },
        permission='read:code',
        handler=tool_code_read,
    ),
)
