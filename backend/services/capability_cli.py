"""The capability tree from a terminal: list, show, validate.

The same three questions the MCP server answers, for a person or a script: what capabilities exist,
what does one of them need, and is this workflow document legal. Every answer comes from the same
functions the app uses (``ai.knowledge`` and ``engine.workflow``), so a terminal can never print a
capability the running product does not have.

``tools/capability_cli.py`` is the entry point (it puts ``backend/`` on ``sys.path``).
"""

from __future__ import annotations

import argparse
import json
import sys

from capabilities_kernel.manifest import KINDS


def listed(kind: str = '', query: str = '') -> list[dict]:
    """The L1 catalogue rows for one kind (or all), in the catalogue's own order.

    ``MAX_LIMIT`` rather than the short default page: a listing surface that silently truncated would
    make a capability look undeclared (the surface gate compares exact sets).
    """
    from ai import knowledge

    return knowledge.catalog(kind=str(kind or ''), query=str(query or ''), limit=knowledge.MAX_LIMIT)['skills']


def _print_listing(rows: list[dict]) -> None:
    for row in rows:
        short = str(row.get('summary') or '').split('。')[0].strip()
        print(f'{row["id"]:<32} {short}')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='capability-cli', description='采析绘 capability tree')
    sub = parser.add_subparsers(dest='command', required=True)

    list_parser = sub.add_parser('list', help='list capabilities')
    list_parser.add_argument('--kind', default='', choices=('', *KINDS))
    list_parser.add_argument('--query', default='')

    show_parser = sub.add_parser('show', help='read one capability skill')
    show_parser.add_argument('id', help='e.g. node.tokenize, operator.topic_model, chart.bar, platform.weibo')

    validate_parser = sub.add_parser('validate', help='validate a workflow document')
    validate_parser.add_argument('path', help='a .json workflow file')

    args = parser.parse_args(argv)
    if args.command == 'list':
        rows = listed(args.kind, args.query)
        if not rows:
            print(f'no capability matches kind={args.kind or "*"} query={args.query or "*"}', file=sys.stderr)
            return 1
        _print_listing(rows)
        return 0
    if args.command == 'show':
        from ai import knowledge

        try:
            skill = knowledge.load(args.id)
        except Exception as exc:  # the refusal names the id the caller sent
            print(f'{type(exc).__name__}: {exc}', file=sys.stderr)
            return 2
        print(skill['markdown'])
        return 0
    from engine.workflow import WorkflowEngine

    try:
        with open(args.path, encoding='utf-8') as handle:
            document = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(f'cannot read {args.path}: {exc}', file=sys.stderr)
        return 2
    problems = WorkflowEngine(document).validate_detailed()
    print(json.dumps({'ok': not problems, 'problems': problems}, ensure_ascii=False, indent=2))
    return 0 if not problems else 1
