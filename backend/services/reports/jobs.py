"""Background jobs for the slow document routes (HTML report, paper PDF, chart PDF).

A report conclusion asks a model, and a PDF runs ``xelatex``; both can take minutes. They used
to run on the Flask request thread, so one slow model held a worker open and 停止 could not
interrupt it. The POST now starts a job and answers at once; the panel polls ``/api/jobs/<id>``.

In-memory and bounded on purpose: a job is the answer to "this page asked for a file now", and
it dies with the process exactly like the page that asked. Everything that must survive is on
disk (the report/PDF in the export folder and its run-ledger row).

Three rules:

* **at most :data:`MAX_RUNNING` jobs** — an unbounded thread per click is the same resource
  problem on a different thread;
* **the owner is the caller at start** — another account polling the id gets 404, never a
  report about someone else's run;
* **the worker re-binds the account and the language** — a fresh thread inherits neither, and
  ``get_run_store()``/``t()`` resolve both at call time.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid

from runtime import account_context

from i18n import get_lang, set_lang, t

logger = logging.getLogger(__name__)

#: Two is the practical ceiling for this machine: a third simultaneous ``xelatex``/model call
#: only makes the first two slower.
MAX_RUNNING = 2
#: Finished jobs are kept for the page that is still polling; older ones are dropped.
KEEP_FINISHED = 20

_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()
_SLOTS = threading.BoundedSemaphore(MAX_RUNNING)
#: A cheap connection test must not occupy a report/PDF slot: a second account pressing
#: 生成报告 while another account is testing AI should not see "报告任务繁忙".
_LLM_SLOTS = threading.BoundedSemaphore(MAX_RUNNING)


def _snapshot(job: dict) -> dict:
    """The public view. The owner stays private: the id is not a capability to another account."""
    return {
        'id': job['id'],
        'kind': job['kind'],
        'state': job['state'],
        'result': job['result'],
        'error': job['error'],
        'created_at': job['created_at'],
        'status': job.get('status', 0),
        'cancellable': False,
    }


def _purge_locked() -> None:
    finished = sorted(
        (job for job in _JOBS.values() if job['state'] != 'running'),
        key=lambda job: job['created_at'],
    )
    for job in finished[:-KEEP_FINISHED] if len(finished) > KEEP_FINISHED else ():
        _JOBS.pop(job['id'], None)


def _finished(kind: str, status: int, result: dict, *, state: str = 'done', error: str = '') -> dict:
    return {
        'id': uuid.uuid4().hex[:12],
        'kind': kind,
        'state': state,
        'result': result,
        'error': error,
        'created_at': time.time(),
        'status': status,
    }


def _run_work(work) -> tuple[int, dict]:
    """Call the job body; a crash is one failed body, never a vanished job."""
    try:
        status, body = work()
    except Exception as exc:
        logger.exception(t('report.jobFailed', err=exc))
        return 500, {'ok': False, 'error': str(exc)}
    return int(status), body


def start(kind: str, work, *, lang: str | None = None) -> dict | None:
    """Run *work* on a daemon thread; ``None`` when every slot is busy.

    ``work`` answers ``(status, body)``. The body is the response the synchronous route used to
    return, so the poller and the old client read the same JSON.
    """
    owner = account_context.current()
    slots = _LLM_SLOTS if kind == 'llm_test' else _SLOTS
    if not slots.acquire(blocking=False):
        return None
    job = _finished(kind, 200, None, state='running')
    job['owner'] = account_context.scope_key()
    job['lang'] = lang or get_lang() or 'zh'
    with _LOCK:
        _JOBS[job['id']] = job
        _purge_locked()

    def run() -> None:
        token = account_context.bind(owner)
        set_lang(job['lang'])
        try:
            status, body = _run_work(work)
            with _LOCK:
                job['status'] = status
                job['result'] = body
                job['state'] = 'done'
        finally:
            account_context.unbind(token)
            slots.release()

    try:
        threading.Thread(target=run, name=f'document-{kind}', daemon=True).start()
    except BaseException:
        with _LOCK:
            _JOBS.pop(job['id'], None)
        slots.release()
        raise
    return _snapshot(job)


def run_now(kind: str, work, *, lang: str | None = None) -> dict:
    """The test seam: run the same body on the caller's thread and answer a finished job.

    The API tests that pin *what the report/PDF is* should not pay for a thread and a poll on
    every case; the route sees a finished job and returns the historical status/body unchanged.
    The async path itself is pinned by ``test_document_jobs.py`` on the real runner.
    """
    del lang  # the caller's thread already has the language set; kept for start()'s signature
    status, body = _run_work(work)
    job = _finished(kind, status, body)
    job['owner'] = account_context.scope_key()
    return _snapshot(job) | {'status': status}


def get(job_id: str) -> dict | None:
    """One job for its owner; another account gets the same answer as a missing id."""
    with _LOCK:
        job = _JOBS.get(str(job_id))
        if job is None or job.get('owner') != account_context.scope_key():
            return None
        return _snapshot(job)


def reset() -> None:
    """Drop every job (tests, and a clean shutdown)."""
    with _LOCK:
        _JOBS.clear()
