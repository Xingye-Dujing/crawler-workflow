"""One framework workspace per account, in its own directory — never the legacy ``ai.db``.

The old AI store keeps ``paths.active().ai_db``; the framework writes a different database file, so
the two paths can run side by side until parity. The manager caches one ``AgentWorkspace`` per
account (the store's path is resolved per call by the host), and closing it joins live runner
threads before the SQLite handle goes away.
"""

from __future__ import annotations

import threading
from pathlib import Path

from agent_workspace import AgentWorkspace
from runtime import paths

from ai_host.adapter import CaiXiHuiHost


class WorkspaceManager:
    def __init__(self, root: str | Path | None = None):
        self._root = Path(root) if root else None
        self._lock = threading.RLock()
        self._spaces: dict[str, AgentWorkspace] = {}

    def directory(self, account: str) -> Path:
        account = account or 'default'
        if self._root is not None:
            return self._root / account
        return Path(paths.user_root(account)) / 'ai_workspace'

    def workspace(self, account: str = 'default') -> AgentWorkspace:
        account = account or 'default'
        with self._lock:
            workspace = self._spaces.get(account)
            if workspace is None:
                workspace = AgentWorkspace(CaiXiHuiHost(data_dir=self.directory(account), lang='zh'))
                self._spaces[account] = workspace
            return workspace

    def close(self) -> None:
        with self._lock:
            spaces = list(self._spaces.values())
            self._spaces.clear()
        for workspace in spaces:
            workspace.close()
