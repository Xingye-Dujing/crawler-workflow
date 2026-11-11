"""The update job: what the updater is doing, written to disk so anyone can pick it up.

The job lives in ``<data>/updates/job.json`` and exists for three reasons, each of which was a
measured failure of the in-memory dictionary this replaces:

* **The window is not the program.** A download that runs in a daemon thread of the server dies
  with the window, and the user's consent to "update now" is lost with it. A worker process reads
  this file, so the job outlives every surface the user can close.
* **A restart must not silently throw the download away.** ``check()`` runs at every boot; the old
  sweep deleted ``data/updates`` unconditionally, which turned a finished, hash-checked package into
  a re-download every single launch.
* **A failure has to be readable after the process that saw it is gone.** The swap happens after
  this server has exited, so the only place its outcome can survive is the disk: ``state``,
  ``error_code``/``error_detail`` and the append-only ``update.log``.

Nothing here decides anything about the network, the package or the swap; it stores facts. Every
write is atomic (``core.atomic``) because the same file is read by the app, the worker and the
swapper at once.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from core import procs
from core.atomic import replace

#: The state machine. ``staged`` means "checked, unpacked, waiting for a restart"; ``applying`` is
#: stamped by the app right before it exits, and the new build turns it into ``applied`` on boot —
#: which is also how a swap that never finished is detected.
STATE_IDLE = 'idle'
STATE_DOWNLOADING = 'downloading'
STATE_STAGING = 'staging'
STATE_STAGED = 'staged'
STATE_APPLYING = 'applying'
STATE_APPLIED = 'applied'
STATE_FAILED = 'failed'
STATE_CANCELLED = 'cancelled'

#: States a live worker owns the staging folder in.
WORKER_STATES = (STATE_DOWNLOADING, STATE_STAGING)

#: States whose staging folder must survive a sweep: a worker is writing it, or the swap still
#: needs it. Everything else may be deleted (with its reason kept in the log).
KEEP_STATES = (*WORKER_STATES, STATE_STAGED, STATE_APPLYING)

JOB_NAME = 'job.json'
LOG_NAME = 'update.log'
LOCK_NAME = 'worker.lock'
MARKER_NAME = 'applying.marker'

#: Rotated, never grown forever: this file is appended to by three processes.
LOG_LIMIT = 256 * 1024

#: What a browser may see. ``staged`` is a server path and stays server-side; the panel only needs
#: to know whether a package IS staged.
PUBLIC_FIELDS = (
    'id',
    'version',
    'from_version',
    'state',
    'progress',
    'error_code',
    'error_detail',
    'attempts',
    'updated',
)

_LOCK = threading.RLock()


def _stamp() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds')


def data_dir(root=None) -> Path:
    """``<data>`` for the job files — the launcher's own root when it passes one.

    ``core.config`` is imported here rather than at module scope so the packaged launcher can read
    :func:`marker_file` before those settings are snapshotted (it resolves the data root itself).
    """
    if root is not None:
        return Path(root) / 'data'
    from core.config import Config

    return Path(Config.DATA_DIR)


def updates_root(root=None) -> Path:
    return data_dir(root) / 'updates'


def job_file(root=None) -> Path:
    return updates_root(root) / JOB_NAME


def log_file(root=None) -> Path:
    return updates_root(root) / LOG_NAME


def lock_file(root=None) -> Path:
    return updates_root(root) / LOCK_NAME


def marker_file(root=None) -> Path:
    """Present while a swapper is replacing files; the launcher waits for it to go."""
    return updates_root(root) / MARKER_NAME


# ─── The record ───────────────────────────────────────────────


def read(root=None) -> dict:
    """The job as stored, or ``{}``. A truncated file is "no job", never a crash."""
    try:
        payload = json.loads(job_file(root).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_raw(payload: dict, root=None) -> None:
    path = job_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f'{path.name}.{uuid.uuid4().hex}.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    replace(temporary, path)


def write(root=None, **fields) -> dict:
    """Merge ``fields`` into the job, stamp it, and store it atomically."""
    with _LOCK:
        current = read(root)
        current.update(fields)
        current['updated'] = _stamp()
        _write_raw(current, root)
        return current


def clear(root=None) -> None:
    """Forget the job (the log stays: it is the evidence of what happened)."""
    with _LOCK, contextlib.suppress(OSError):
        job_file(root).unlink()


def start(*, version: str, asset: dict, from_version: str, root=None) -> dict:
    """Open a brand-new job for one version, replacing whatever came before."""
    with _LOCK:
        clear(root)
        payload = {
            'schema': 1,
            'id': uuid.uuid4().hex,
            'version': str(version),
            'from_version': str(from_version or ''),
            'state': STATE_DOWNLOADING,
            'progress': 0,
            'error_code': '',
            'error_detail': '',
            'staged': '',
            'asset': dict(asset or {}),
            'owner_pid': os.getpid(),
            'worker_pid': 0,
            'swapper_pid': 0,
            'cancel': False,
            'attempts': 1,
            'created': _stamp(),
            'updated': _stamp(),
        }
        _write_raw(payload, root)
        return payload


def fail(code: str, detail: str = '', root=None, **fields) -> dict:
    """Record a named failure and its sentence. One line goes to the log with it."""
    job = write(
        root,
        state=STATE_FAILED,
        error_code=str(code or 'unknown')[:60],
        error_detail=str(detail or '')[:600],
        progress=0,
        **fields,
    )
    log(f'失败[{code}] {detail}', actor='app', root=root)
    return job


def public(job: dict | None = None, root=None) -> dict:
    """The browser's view: no filesystem paths, and an idle state instead of an empty answer."""
    job = dict(job or read(root))
    if not job:
        return {'state': STATE_IDLE, 'version': '', 'error_code': '', 'error_detail': '', 'progress': 0}
    payload = {key: job.get(key) for key in PUBLIC_FIELDS}
    payload['progress'] = int(job.get('progress') or 0)
    payload['attempts'] = int(job.get('attempts') or 0)
    payload['staged'] = bool(job.get('staged'))
    return payload


# ─── Liveness ────────────────────────────────────────────────


def worker_alive(job: dict | None = None, root=None) -> bool:
    """Whether the process that owns this job's download is still running."""
    job = dict(job or read(root))
    if job.get('state') not in WORKER_STATES:
        return False
    return procs.process_alive(int(job.get('worker_pid') or 0))


def _lock_owner(path: Path) -> int:
    try:
        return int(path.read_text(encoding='utf-8').strip() or 0)
    except (OSError, ValueError):
        return 0


def claim(pid: int, root=None) -> bool:
    """Become the one worker for this data root; ``False`` when another live one owns it.

    ``O_EXCL`` makes the create atomic. A lock whose owner is gone (a crash, a killed update) is
    reclaimed after a short grace period so an update is never blocked forever by a dead process.
    """
    path = lock_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    for _attempt in range(2):
        try:
            handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            owner = _lock_owner(path)
            try:
                age = time.time() - path.stat().st_mtime
            except OSError:
                age = 0.0
            if owner and procs.process_alive(owner):
                return False
            if age < 5:
                # A lock that was just created belongs to a worker that has not written its pid yet.
                return False
            try:
                path.unlink()
            except OSError:
                return False
            continue
        with os.fdopen(handle, 'w', encoding='utf-8') as writer:
            writer.write(str(int(pid)))
        return True
    return False


def release(pid: int | None = None, root=None) -> None:
    """Drop the lock, but only when it is ours (never a rival worker's)."""
    path = lock_file(root)
    if pid is not None and _lock_owner(path) not in (0, int(pid)):
        return
    with contextlib.suppress(OSError):
        path.unlink()


# ─── Log ─────────────────────────────────────────────────────


def log(line: str, actor: str = '', root=None) -> None:
    """Append one fact. Never raises: a full disk must not turn into a dead updater."""
    text = str(line or '').strip()
    if not text:
        return
    prefix = f'{_stamp()} [{actor}] ' if actor else f'{_stamp()} '
    path = log_file(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            _rotate(path)
            with open(path, 'a', encoding='utf-8') as handle:
                handle.write(prefix + text.replace('\n', ' ') + '\n')
    except OSError:
        pass


def _rotate(path: Path) -> None:
    try:
        if path.stat().st_size > LOG_LIMIT:
            replace(path, path.with_name(f'{path.name}.1'))
    except OSError:
        pass


def log_tail(lines: int = 80, root=None) -> str:
    """The last few log lines, for the panel's details view."""
    try:
        text = log_file(root).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''
    return '\n'.join(text.splitlines()[-max(1, int(lines)) :])


# ─── Retention ───────────────────────────────────────────────


def prune(keep: set[str] | None = None, root=None) -> None:
    """Delete staging folders that no job owns; ``keep`` names the ones that must survive.

    Called at every check. The old version of this deleted everything, which is why a finished
    download vanished on the next launch — the guard is the state machine, not a timer.
    """
    keep = {str(name) for name in (keep or set()) if str(name)}
    base = updates_root(root)
    if not base.is_dir():
        return
    for child in base.iterdir():
        if not child.is_dir():
            continue
        if child.name in keep:
            continue
        shutil.rmtree(child, ignore_errors=True)
