"""One heavy GPU job at a time, on every platform.

The laptop has one 8 GB card and 16 GB of RAM. Two training processes or a training run beside a
batch inference would either OOM or thrash, and the failure names nothing useful. A single lock file
owned by one process makes the rule enforceable from the CLI as well as from the app: acquire before
loading torch weights, release in ``finally``.

The lock stores the owner's pid and start time. A stale lock is NOT silently broken — someone may
still be training in another terminal; the refusal tells the caller exactly which file to inspect.
"""

import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import _env


class JobBusyError(RuntimeError):
    """Another job owns the GPU slot; the message names the lock file."""


def lock_path() -> Path:
    return _env.LOCKS_DIR / 'gpu.lock'


@contextmanager
def gpu_slot(label: str = ''):
    """Hold the single training/inference slot for the duration of the block."""
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        try:
            owner = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            owner = {}
        raise JobBusyError(
            f'{path}: a GPU job is already running (pid {owner.get("pid", "?")}, '
            f'{owner.get("label") or "unlabelled"}, started {owner.get("started", "?")}). '
            'Wait for it to finish; remove the lock only after confirming its process is gone.'
        ) from exc
    with os.fdopen(handle, 'w', encoding='utf-8') as stream:
        json.dump(
            {
                'pid': os.getpid(),
                'label': str(label),
                'started': datetime.now(UTC).isoformat(timespec='seconds'),
            },
            stream,
        )
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)
