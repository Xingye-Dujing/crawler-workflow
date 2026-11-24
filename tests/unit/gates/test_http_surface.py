"""Every route is declared under ``backend/api/`` (or the composition root's one page route).

On 2026-11-24 two blueprints lived beside their domain — ``sessions/routes.py`` (14 routes) and
``services/pool/routes.py`` (7) — and both imported ``api.auth``/``api.http`` back. That made
"where is the HTTP surface?" a search rather than a directory, and it made the service layer depend
on the HTTP layer. The domain modules answer questions; ``api/`` translates a request into one and a
result into JSON.

``app.py`` is allowed exactly one route, ``/``, which serves the page. A ``@x.get``/``@x.post``
decorator counts the same as ``@x.route``: Flask treats them as routes.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / 'backend'

ROUTE_METHODS = {'route', 'get', 'post', 'put', 'patch', 'delete'}

#: The page route lives on the app object, not in a Blueprint.
ALLOWED = {'app.py'}


def routes(root: Path) -> list[str]:
    """``path:line @decorator`` for every route decorator outside the allowed files."""
    found = []
    for path in root.rglob('*.py'):
        rel = path.relative_to(root).as_posix()
        if '__pycache__' in path.parts or rel in ALLOWED or rel.startswith('api/'):
            continue
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                    continue
                if decorator.func.attr in ROUTE_METHODS:
                    found.append(f'{rel}:{node.lineno} @{ast.unparse(decorator.func)}')
    return found


class TestHttpSurface:
    def test_routes_live_in_api(self):
        found = routes(BACKEND)
        assert found == [], (
            'a route outside api/ splits the HTTP surface; move the handler into api/ and keep the '
            'domain in its package: ' + '; '.join(found)
        )

    def test_only_the_page_route_is_outside(self):
        """The allowance is one file with one route — not a licence for more."""
        app = (BACKEND / 'app.py').read_text(encoding='utf-8')
        tree = ast.parse(app)
        count = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            for decorator in node.decorator_list
            if isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr in ROUTE_METHODS
        )
        assert count == 1, f'app.py declares {count} routes; it owns exactly one (the page)'

    def test_the_gate_can_fail(self, tmp_path):
        (tmp_path / 'sessions').mkdir()
        (tmp_path / 'sessions' / 'bad.py').write_text(
            'from flask import Blueprint\n'
            'bp = Blueprint("x", __name__)\n'
            '@bp.route("/x")\n'
            'def handler():\n'
            '    return ""\n',
            encoding='utf-8',
        )
        found = routes(tmp_path)
        assert found and 'sessions/bad.py' in found[0], found
