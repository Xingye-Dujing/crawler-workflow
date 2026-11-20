"""An account-level path is resolved through ``runtime.paths``, never read off a ``Config`` constant.

AGENTS pins the rule — "never cache a path in a module constant or a store default, so a bare
``WorkflowManager()`` resolves the caller's folder too". The four stores that used to default their
database to ``Config.RUNS_DB``/``DATASETS_DB``/``BIBLIO_DB``/``WORKFLOW_HISTORY_DB`` are exactly that
shape: the scoped registry passes explicit paths today, so nothing read the wrong tree, while the
default promised that any bare construction — inside another account's request, or in code added
next month — belongs to the SYSTEM owner. A default is a claim the next caller gets to make, so the
claim is checked here instead.

The check parses Python instead of grepping for the literal ``Config.``: an import alias
(``from core.config import Config as C``) or ``getattr(Config, 'RUNS_DB')`` reads the very same
constant and must not slip through; strings and comments must not be accused of reading it.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

BACKEND = Path(__file__).resolve().parents[3] / 'backend'

#: The fields that belong to whichever account is asking. The system-level exceptions (``accounts.db``,
#: ``settings.json``, ``lexicon.db``, ``models/``, the jieba user dict, ``logs/``) are deliberately NOT
#: in this list: those one reader is a machine fact and stays on ``Config`` by design.
ACCOUNT_LEVEL = (
    'RUNS_DB',
    'DATASETS_DB',
    'BIBLIO_DB',
    'WORKFLOW_HISTORY_DB',
    'COOKIE_DIR',
    'EXPORT_DIR',
    'WORKFLOW_DIR',
    'HARVEST_DIR',
    'REUSABLE_DIR',
    'LLM_CHECKPOINT_DIR',
    'BROWSER_PROFILE_DIR',
)

#: The one module allowed to read them — it owns the shape of ``data/`` and ``data/users/<id>/``.
OWNER = Path('runtime') / 'paths.py'


def _config_names(tree: ast.AST) -> set[str]:
    """Every local name that can hold the Config class, including import aliases."""
    names = {'Config'}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not (node.module or '').endswith('config'):
            continue
        for alias in node.names:
            if alias.name == 'Config':
                names.add(alias.asname or alias.name)
    return names


def _offenders(text: str) -> list[str]:
    """The account-level constant reads in *text*, with prose and comments ignored by the AST."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    names = _config_names(tree)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in ACCOUNT_LEVEL:
            if isinstance(node.value, ast.Name) and node.value.id in names:
                found.append(f'Config.{node.attr}')
            continue
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != 'getattr':
            continue
        if len(node.args) < 2 or not isinstance(node.args[0], ast.Name) or node.args[0].id not in names:
            continue
        wanted = node.args[1].value if isinstance(node.args[1], ast.Constant) else None
        if wanted in ACCOUNT_LEVEL:
            found.append(f"getattr(Config, '{wanted}')")
    return found


class TestAnAccountPathIsNeverCached:
    def test_only_the_path_module_reads_an_account_level_constant(self):
        offenders = []
        for path in sorted(BACKEND.rglob('*.py')):
            relative = path.relative_to(BACKEND)
            if path.name.startswith('test_') or '__pycache__' in path.parts or relative == OWNER:
                continue
            for found in _offenders(path.read_text(encoding='utf-8', errors='replace')):
                offenders.append(f'{relative}:{found}')
        assert offenders == [], 'an account path resolved from a system constant:\n' + '\n'.join(offenders)

    def test_the_gate_notices_aliases_indirection_and_ignores_prose(self):
        """A scan that matches nothing reports a green rule nobody wrote."""
        sample = (
            'class RunStore:\n'
            '    """Config.RUNS_DB is named in prose here."""\n'
            '    def __init__(self, db_path=None):\n'
            '        self.db_path = db_path or Config.RUNS_DB\n'
        )
        assert _offenders(sample) == ['Config.RUNS_DB']
        assert _offenders('from core.config import Config as C\nx = C.RUNS_DB\n') == ['Config.RUNS_DB']
        assert _offenders("x = getattr(Config, 'RUNS_DB')\n") == ["getattr(Config, 'RUNS_DB')"]
        assert _offenders('        # used to read Config.RUNS_DB\n') == []
        assert _offenders('x = Config.ACCOUNTS_DB\n') == []

    def test_the_scoped_stores_answer_the_callers_tree(self):
        """The rule has one observable consequence: a bare construction follows WHO IS ASKING.

        Proved against ``run_history`` (the seam that takes no explicit path) rather than by reading
        the default, because the default is the thing a later edit can only get wrong silently."""
        from runtime import account_context, paths

        from services.runs.history import ExecutionHistoryService

        outside = ExecutionHistoryService().db_path
        assert outside == paths.system().history_db, outside
        with account_context.use(account_context.Account('u_deadbeefcafe', 'alice')):
            inside = ExecutionHistoryService().db_path
        assert inside == paths.for_user('u_deadbeefcafe').history_db, inside
