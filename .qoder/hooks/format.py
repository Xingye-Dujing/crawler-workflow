"""PostToolUse hook: run ruff format + autofix on a Python file just written/edited.

Reads the hook JSON payload on stdin (jq is not guaranteed on this platform) and
exits 0 unconditionally so a lint failure never blocks the agent's tool call.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUFF = ROOT / '.venv' / 'Scripts' / 'ruff.exe'


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (ValueError, OSError):
        return
    tool_input = data.get('tool_input') or {}
    tool_response = data.get('tool_response') or {}
    path = tool_response.get('filePath') or tool_input.get('file_path') or ''
    if not str(path).lower().endswith('.py'):
        return
    if not Path(path).is_file() or not RUFF.is_file():
        return
    for args in (['format', str(path)], ['check', '--fix', str(path)]):
        subprocess.run([str(RUFF), *args], check=False, capture_output=True, text=True)


if __name__ == '__main__':
    main()
