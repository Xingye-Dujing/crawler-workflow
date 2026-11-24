"""MCP server over stdio for the capability tree. Thin wrapper over ``services.mcp``.

Register it with an MCP client as ``python tools/mcp_server.py`` (from this repository). The tools are
``capabilities_list``, ``capabilities_show`` and ``workflow_validate``; everything they answer comes
from the same registry, skills and engine the app uses.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'backend') not in sys.path:
    sys.path.insert(0, str(ROOT / 'backend'))


def main() -> int:
    from services.mcp import serve

    serve(sys.stdin, sys.stdout)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
