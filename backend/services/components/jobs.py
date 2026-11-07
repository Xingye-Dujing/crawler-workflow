"""Background installation jobs for the browser panel.

A download is minutes long, so the HTTP request starts it and returns an id; the panel polls. Jobs
are in-memory on purpose: an installation interrupted by closing the app is resumed by the
installer's own retry, and a durable queue would be a second source of truth for a folder that
already records what is installed.

One job per component at a time; starting the same component twice returns the running job instead
of downloading it twice.
"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Any

from services.components.catalog import Catalog, CatalogError
from services.components.fetch import DownloadError
from services.components.install import InstallError, install_component
from services.components.manifest import ManifestError

_JOBS: dict[str, dict[str, Any]] = {}
_CANCEL: dict[str, threading.Event] = {}
_LOCK = threading.Lock()


def _snapshot(job: dict[str, Any]) -> dict[str, Any]:
    return {
        'id': job['id'],
        'component': job['component'],
        'state': job['state'],
        'done': job['done'],
        'total': job['total'],
        'error': job['error'],
        'path': job['path'],
        'cancellable': job['state'] == 'running',
    }


def start(catalog: Catalog, component_id: str, root: str | Path, *, system: str | None = None) -> dict[str, Any]:
    """Start installing one component; return the job snapshot (new or already running)."""
    with _LOCK:
        for job in _JOBS.values():
            if job['component'] == component_id and job['state'] == 'running':
                return _snapshot(job)
        job_id = uuid.uuid4().hex[:12]
        stop = threading.Event()
        job = {
            'id': job_id,
            'component': component_id,
            'state': 'running',
            'done': 0,
            'total': 0,
            'error': '',
            'path': '',
        }
        _JOBS[job_id] = job
        _CANCEL[job_id] = stop

    def progress(done: int, total: int) -> None:
        with _LOCK:
            job['done'] = done
            job['total'] = total

    def work() -> None:
        try:
            path = install_component(
                catalog,
                component_id,
                root,
                system=system,
                progress=progress,
                cancel=stop.is_set,
            )
        except (InstallError, DownloadError, CatalogError, ManifestError, OSError) as exc:
            with _LOCK:
                job['state'] = 'cancelled' if stop.is_set() else 'failed'
                job['error'] = str(exc)
        else:
            with _LOCK:
                job['state'] = 'done'
                job['path'] = str(path)

    threading.Thread(target=work, name=f'component-{component_id}', daemon=True).start()
    started = get(job_id)
    if started is None:
        raise RuntimeError('the component job disappeared before it could be reported')
    return started


def get(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return _snapshot(job) if job else None


def cancel(job_id: str) -> bool:
    with _LOCK:
        event = _CANCEL.get(job_id)
        if event is None:
            return False
        event.set()
        return True


def reset() -> None:
    """Drop every finished job; tests call this so one run cannot inherit another's history."""
    with _LOCK:
        for job_id in [key for key, job in _JOBS.items() if job['state'] != 'running']:
            _JOBS.pop(job_id, None)
            _CANCEL.pop(job_id, None)
