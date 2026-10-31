"""Where one scope's data lives. The single answer to "which file/database do we open?".

The app was written around one checkout-level ``data/`` tree, and every path was a ``Config``
class attribute read at import. Multi-account hosting needs the same shape *per account*, so this
module turns that tree into a value object:

* :func:`system` — the local owner's tree, read from ``Config`` **on every call**. It must not be
  cached: the test harness repoints ``Config.DATA_DIR``/``COOKIE_DIR`` through private fixtures,
  a second root is selected with ``CRAWLER_DATA_ROOT``, and a frozen copy would keep opening the
  user's real database after the switch.
* :func:`for_user` — ``<DATA_DIR>/users/<user_id>/…``, a pure string-join, never cached. The id is
  server-generated and shape-checked here, so a username can never become a path segment.
* :func:`active` — whoever :mod:`runtime.account_context` says this thread speaks for; ``None``
  means the local owner.

Machine-level state is deliberately NOT part of this object: trained models and
``model_registry.json``, the jieba dictionary, the editable lexicons and ``settings.json`` stay
global, because one process has one of each (a jieba dictionary can only be loaded once) and they
describe the machine, not a person.
"""

import os
import re
from dataclasses import dataclass

from core.config import Config

#: The shape :mod:`services.accounts` mints (``u_`` + 12 hex). Checked wherever an id enters a
#: filesystem path; an id read from a cookie or a database row is still untrusted input.
USER_ID_RE = re.compile(r'^u_[0-9a-f]{12}$')

_TRASH = '.trash'


@dataclass(frozen=True)
class DataPaths:
    """Every file and directory one scope owns."""

    data_dir: str
    cookie_dir: str
    export_dir: str
    workflow_dir: str
    checkpoint_dir: str
    profile_dir: str
    harvest_dir: str
    reusable_dir: str
    runs_db: str
    datasets_db: str
    history_db: str
    workflow_history_db: str
    biblio_db: str
    locks_json: str
    schedules_json: str

    def ensure(self) -> 'DataPaths':
        """Create the directories this scope needs. Idempotent, called when an account is created
        and again on first use (a user may have deleted the tree by hand)."""
        for directory in (
            self.data_dir,
            self.cookie_dir,
            self.export_dir,
            self.workflow_dir,
            self.checkpoint_dir,
            self.profile_dir,
            self.harvest_dir,
            self.reusable_dir,
        ):
            os.makedirs(directory, exist_ok=True)
        return self


def system() -> DataPaths:
    """The local owner's (pre-accounts) tree, read live from ``Config``."""
    data_dir = Config.DATA_DIR
    return DataPaths(
        data_dir=data_dir,
        cookie_dir=Config.COOKIE_DIR,
        export_dir=Config.EXPORT_DIR,
        workflow_dir=Config.WORKFLOW_DIR,
        checkpoint_dir=Config.LLM_CHECKPOINT_DIR,
        profile_dir=Config.BROWSER_PROFILE_DIR,
        harvest_dir=Config.HARVEST_DIR,
        reusable_dir=Config.REUSABLE_DIR,
        runs_db=Config.RUNS_DB,
        datasets_db=Config.DATASETS_DB,
        history_db=os.path.join(data_dir, 'history.db'),
        workflow_history_db=Config.WORKFLOW_HISTORY_DB,
        biblio_db=Config.BIBLIO_DB,
        locks_json=os.path.join(data_dir, 'locks.json'),
        schedules_json=os.path.join(data_dir, 'schedules.json'),
    )


def users_root() -> str:
    """Where all account trees live. Under ``DATA_DIR`` so ``CRAWLER_DATA_ROOT`` moves them too."""
    return os.path.join(Config.DATA_DIR, 'users')


def trash_root() -> str:
    """Deleted accounts are moved here, never deleted in place."""
    return os.path.join(users_root(), _TRASH)


def user_root(user_id: str) -> str:
    """One account's tree root, with the id validated (it is a path segment)."""
    text = str(user_id or '')
    if not USER_ID_RE.match(text):
        raise ValueError(f'Invalid account id: {user_id!r}')
    return os.path.join(users_root(), text)


def for_user(user_id: str) -> DataPaths:
    """An account's own tree. Names mirror :func:`system` so a caller switches scope by asking
    this module, not by rebuilding a path."""
    root = user_root(user_id)
    return DataPaths(
        data_dir=root,
        cookie_dir=os.path.join(root, 'cookies'),
        export_dir=os.path.join(root, 'exports'),
        workflow_dir=os.path.join(root, 'workflows'),
        checkpoint_dir=os.path.join(root, 'checkpoints'),
        profile_dir=os.path.join(root, 'chrome_profile'),
        harvest_dir=os.path.join(root, 'harvest'),
        reusable_dir=os.path.join(root, 'reusable_nodes'),
        runs_db=os.path.join(root, 'runs.db'),
        datasets_db=os.path.join(root, 'datasets.db'),
        history_db=os.path.join(root, 'history.db'),
        workflow_history_db=os.path.join(root, 'workflow_history.db'),
        biblio_db=os.path.join(root, 'biblio.db'),
        locks_json=os.path.join(root, 'locks.json'),
        schedules_json=os.path.join(root, 'schedules.json'),
    )


def active() -> DataPaths:
    """The paths of the scope this thread speaks for (local owner when no account is bound)."""
    from runtime import account_context

    account = account_context.current()
    return for_user(account.user_id) if account is not None else system()
