"""Per-item "lock" for the list panels: 导出产物 / 运行记录 / 历史记录 / 工作流文件.

The panels all offer a bulk 清空 and a per-row delete. A lock makes one entry survive
both until the user unlocks it — "don't sweep away the one export I still need". The
state is one small JSON file under the data root, keyed by panel and entry, because a
lock is a UI intent, not a property of the artefact (an export file or a run row has no
notion of being locked; the user's decision lives here and can be thrown away safely).

The path is computed from ``Config.DATA_DIR`` at every call rather than bound at import,
so the test isolation (which redirects ``Config.DATA_DIR`` before ``app`` is imported)
lands locks in the throwaway root automatically — no per-module path override needed.
"""

import json
import os
import threading

from config import Config

_lock = threading.Lock()

#: The panels that honour a lock. Kept as a closed set so a typo'd panel cannot create
#: an orphan bucket the UI never reads back.
PANELS = ('exports', 'runs', 'history', 'workflows')


def _path() -> str:
    return os.path.join(Config.DATA_DIR, 'locks.json')


def _load() -> dict:
    try:
        with open(_path(), encoding='utf-8') as f:
            stored = json.load(f)
    except (OSError, ValueError):
        return {p: [] for p in PANELS}
    if not isinstance(stored, dict):
        return {p: [] for p in PANELS}
    return {p: [str(k) for k in (stored.get(p) or []) if isinstance(k, (str, int))] for p in PANELS}


def _save(values: dict) -> None:
    tmp = _path() + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(values, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _path())


def all_locks() -> dict:
    with _lock:
        return {p: sorted(set(_load()[p])) for p in PANELS}


def is_locked(panel: str, key: str) -> bool:
    """False for an unknown panel — a panel nobody declared has no locks to honour."""
    if panel not in PANELS:
        return False
    with _lock:
        return str(key) in _load()[panel]


def set_locked(panel: str, key: str, locked: bool) -> list:
    """Mark *key* locked/unlocked in *panel* and return the panel's full lock list.

    Raises KeyError on an unknown panel so the endpoint refuses rather than silently
    filing a lock nobody will ever read back.
    """
    if panel not in PANELS:
        raise KeyError(panel)
    key = str(key)
    with _lock:
        values = _load()
        current = set(values[panel])
        if locked:
            current.add(key)
        else:
            current.discard(key)
        values[panel] = sorted(current)
        _save(values)
        return values[panel]


def drop(panel: str, key: str) -> None:
    """Forget a lock for an entry that no longer exists (a run was cleared out from
    under its lock), so the file does not accumulate keys for dead ids."""
    if panel not in PANELS:
        return
    key = str(key)
    with _lock:
        values = _load()
        if key in values[panel]:
            values[panel] = [k for k in values[panel] if k != key]
            _save(values)
