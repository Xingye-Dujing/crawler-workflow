"""An account-level path is resolved through ``runtime.paths``, never read off a ``Config`` constant.

AGENTS pins the rule — "never cache a path in a module constant or a store default, so a bare
``WorkflowManager()`` resolves the caller's folder too". The four stores that used to default their
database to ``Config.RUNS_DB``/``DATASETS_DB``/``BIBLIO_DB``/``WORKFLOW_HISTORY_DB`` are exactly that
shape: the scoped registry passes explicit paths today, so nothing read the wrong tree, while the
default promised that any bare construction — inside another account's request, or in code added
next month — belongs to the SYSTEM owner. A default is a claim the next caller gets to make, so the
claim is checked here instead.
"""

import re
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

_FIND = re.compile(r'Config\.(' + '|'.join(ACCOUNT_LEVEL) + r')\b')


def _strip_prose(text: str) -> str:
    """``text`` with comments and docstrings gone: prose ABOUT a constant is not a read of it.

    Counting the fences per line and toggling is the whole trick — a line holding two of them (a
    one-line docstring) leaves the state where it found it, which is what a docstring on one line
    means. A trailing hash-comment is a note about the code, so 「no global taskkill」 in one cannot
    read as a call to it."""
    kept = []
    inside = False
    for raw in text.splitlines():
        line = raw.strip()
        fences = line.count('"""') + line.count("'''")
        if fences % 2:
            inside = not inside
            continue
        if inside or line.startswith('#'):
            continue
        kept.append(line.split('#')[0])
    return '\n'.join(kept)


class TestAnAccountPathIsNeverCached:
    def test_only_the_path_module_reads_an_account_level_constant(self):
        offenders = []
        for path in sorted(BACKEND.rglob('*.py')):
            relative = path.relative_to(BACKEND)
            if path.name.startswith('test_') or '__pycache__' in path.parts or relative == OWNER:
                continue
            found = _FIND.search(_strip_prose(path.read_text(encoding='utf-8', errors='replace')))
            if found:
                offenders.append(f'{relative}:{found.group(0)}')
        assert offenders == [], 'an account path resolved from a system constant:\n' + '\n'.join(offenders)

    def test_the_gate_notices_a_store_that_caches_the_system_tree(self):
        """A scan that matches nothing reports a green rule nobody wrote."""
        sample = (
            'class RunStore:\n'
            '    """Config.RUNS_DB is named in prose here."""\n'
            '    def __init__(self, db_path=None):\n'
            '        self.db_path = db_path or Config.RUNS_DB\n'
        )
        stripped = _strip_prose(sample)
        assert 'Config.RUNS_DB' in stripped, 'the docstring prose survived the strip'
        assert _FIND.search(stripped)
        assert _FIND.search(_strip_prose('        # used to read Config.RUNS_DB\n')) is None

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
