"""A small typed registry. One table per contribution kind; a duplicate is refused."""

import threading


class ExtensionRegistry:
    """The shared contribution tables. Built-ins and plugins register through the same call."""

    KINDS = ('providers', 'tools', 'context_sources', 'skills', 'artifact_renderers', 'ui_commands')

    def __init__(self):
        self._tables = {kind: {} for kind in self.KINDS}
        self._owners = {kind: {} for kind in self.KINDS}
        self._lock = threading.RLock()

    def register(self, kind: str, name: str, value, owner: str) -> None:
        if kind not in self._tables:
            raise ValueError(f'unknown contribution kind: {kind}')
        key = str(name or '').strip()
        if not key:
            raise ValueError('a contribution needs a name')
        with self._lock:
            if key in self._tables[kind]:
                raise ValueError(f'{kind} contribution {key!r} is already owned by {self._owners[kind][key]}')
            self._tables[kind][key] = value
            self._owners[kind][key] = owner

    def get(self, kind: str, name: str):
        return self._tables.get(kind, {}).get(name)

    def all(self, kind: str) -> dict:
        return dict(self._tables.get(kind, {}))

    def unregister_owner(self, owner: str) -> int:
        removed = 0
        with self._lock:
            for kind, table in self._tables.items():
                for key in [key for key, who in self._owners[kind].items() if who == owner]:
                    table.pop(key, None)
                    self._owners[kind].pop(key, None)
                    removed += 1
        return removed


HOST = ExtensionRegistry()
