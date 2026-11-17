"""The child processes this server started, so the panel can list and stop them.

A command the assistant runs, a Python script, the CatBus adapter: each is a real process on the
user's machine. Without a registry the only view of them is "that request is still open" — close the
tab and nothing is left to look at, while the child keeps running. Registration is by pid plus the
account that asked for it; the list prunes an entry whose process has already exited, so what the
panel shows is what is running, never a log of what once ran. Stopping goes through
``core.procs.reap_process``: one cross-platform answer for the child AND its tree.
"""

from __future__ import annotations

import threading
import time

from core import procs

from runtime import account_context

#: Live children, keyed by a short id the panel can name in a request.
_ROWS: dict[str, dict] = {}
_LOCK = threading.Lock()
_SEQ = 0
#: How long a stopped child is given to leave on its own before the tree is killed.
GRACE = 1.5


def register(kind: str, command: str, proc, owner: str = '') -> str:
    """Track ``proc`` under the calling account. Returns the id the panel will use."""
    global _SEQ
    with _LOCK:
        _SEQ += 1
        ident = f'p{_SEQ}'
        _ROWS[ident] = {
            'id': ident,
            'kind': str(kind or 'process'),
            'command': str(command or '')[:300],
            'pid': int(getattr(proc, 'pid', 0) or 0),
            'owner': str(owner if owner else account_context.scope_key()),
            'started': time.time(),
            'proc': proc,
        }
    return ident


def unregister(ident: str) -> None:
    with _LOCK:
        _ROWS.pop(str(ident or ''), None)


def _alive(row: dict) -> bool:
    proc = row.get('proc')
    poll = getattr(proc, 'poll', None)
    return bool(poll is None or poll() is None)


def rows(owner: str | None = None) -> list[dict]:
    """Running children, oldest first. ``owner`` limits the answer to one account's own."""
    now = time.time()
    out = []
    with _LOCK:
        for ident, row in list(_ROWS.items()):
            if not _alive(row):
                _ROWS.pop(ident, None)
                continue
            if owner is not None and row['owner'] != owner:
                continue
            out.append(
                {
                    'id': ident,
                    'kind': row['kind'],
                    'command': row['command'],
                    'pid': row['pid'],
                    'seconds': int(now - row['started']),
                }
            )
    return out


def stop(ident: str, owner: str | None = None) -> tuple[str, str]:
    """Stop one child and its tree: ``('stopped' | 'gone' | 'refused', machine_reason)``.

    Never silent: a refusal names why (the child belongs to another account) and a failure carries
    the operating system's own sentence back to the panel.
    """
    with _LOCK:
        row = _ROWS.get(str(ident or ''))
        if row is None:
            return 'gone', 'not running'
        if owner is not None and row['owner'] != owner:
            return 'refused', 'not yours'
        _ROWS.pop(str(ident), None)
    proc = row.get('proc')
    pid = int(row.get('pid') or 0)
    if not _alive(row):
        # It exited on its own between the panel's poll and this click: nothing to stop.
        return 'gone', ''
    terminate = getattr(proc, 'terminate', None)
    if terminate is not None:
        try:
            terminate()
            proc.wait(timeout=GRACE)
        except Exception:  # a child that ignored SIGTERM, or already gone: the tree kill decides
            pass
    if pid:
        stopped, reason = procs.reap_process(pid)
        if stopped:
            return 'stopped', ''
        # A child that exited on its own is not a failure: the reap says "no such process".
        return ('gone', '') if not _alive(row) else ('gone', reason)
    return 'stopped', ''


def reset_for_tests() -> None:
    with _LOCK:
        _ROWS.clear()
