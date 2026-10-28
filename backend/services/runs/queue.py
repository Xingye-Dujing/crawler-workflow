"""The run queue: requests waiting for the one run slot, plus the mirror that survives a restart.

One run at a time is a property of this product, not an accident: the console, the crawl
browsers, the checkpoint store and the resume cursor all assume a single writer. What was missing
is somewhere to put the next request while one is busy — it used to be refused outright, and the
user had to press Run again at the right moment.

The in-memory list (``state._RUN_QUEUE``) is the runtime source of truth — ordering, the drain
and the liveness check all read it — and ``runs.db`` holds only a recovery mirror of it, so a
mirror failure must never break the request that triggered it. A restart therefore drops nothing
the user was told about: ``load_pending_queue()`` re-fills an EMPTY queue at boot.

Starting a queued request is deliberately **injected**: :func:`drain_queue` takes the app's
``_begin_run`` as a callback, because a queue module that imported the application would both
invert the layering and freeze a circular import in place. Everything the hand-off has to know
about the *queue* — who is next, what the mirror says, who goes back to the front — stays here.
"""

import logging
import threading
import time
import uuid
from collections.abc import Callable

from state import _RUN_QUEUE, QueueEntry, add_log
from stores import get_run_store

from i18n import t
from services.runs.payload import workflow_shape_error

logger = logging.getLogger(__name__)

#: Queued requests live in memory only (see ``state._RUN_QUEUE``). A restart drops them, which is
#: the honest behaviour for a list of intentions nobody is here to confirm.
QUEUE_MAX = 8

queue_lock = threading.Lock()


def enqueue_run(data: dict, lang_header: str) -> dict:
    """Park a request until the running one finishes.

    The payload is checked here, at the moment the user pressed the button, and
    not at drain time: a request that cannot become a run must be refused to the
    browser that sent it, where someone can fix it. Discovered minutes later, in
    another thread, it would only be a missing run.
    """
    shape_error = workflow_shape_error(data)
    if shape_error:
        return {'status': 400, 'body': {'ok': False, 'error': shape_error}}
    workflow = data.get('workflow') or {}
    name = str(data.get('workflow_name') or workflow.get('name') or '').strip()
    with queue_lock:
        if len(_RUN_QUEUE) >= QUEUE_MAX:
            return {'status': 409, 'body': {'ok': False, 'error': t('api.queueFull', n=QUEUE_MAX)}}
        entry: QueueEntry = {
            'id': uuid.uuid4().hex[:12],
            'workflow_name': name,
            'nodes': len(workflow.get('nodes') or []),
            'data': data,
            'lang': lang_header or '',
            'queued_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        }
        _RUN_QUEUE.append(entry)
        position = len(_RUN_QUEUE)
    # ``wf.unnamed`` renders 「未命名工作流{i}」 with the WORKFLOW's index on the canvas;
    # this is a queue POSITION, and feeding one into the other printed 「已排队（第 2
    # 位）：未命名工作流2」 where the 2 happened to be the depth of the queue.
    add_log(t('run.queued', name=name or t('run.queuedUnnamed'), at=position))
    mirror_queue()
    return {
        'status': 200,
        'body': {
            'ok': True,
            'queued': True,
            'queue_id': entry['id'],
            'position': position,
            'message': t('api.queued', at=position),
        },
    }


def queue_snapshot() -> list:
    """The waiting requests, oldest first — without their payloads."""
    with queue_lock:
        return [{key: entry[key] for key in ('id', 'workflow_name', 'nodes', 'queued_at')} for entry in _RUN_QUEUE]


def cancel_queued(queue_id: str) -> bool:
    """Drop one waiting request by its queue id. True when it is gone."""
    with queue_lock:
        for position, entry in enumerate(_RUN_QUEUE):
            if entry['id'] == queue_id:
                del _RUN_QUEUE[position]
                break
        else:
            return False
    mirror_queue()
    return True


def clear_queue() -> int:
    with queue_lock:
        count = len(_RUN_QUEUE)
        del _RUN_QUEUE[:]
    mirror_queue()
    return count


def mirror_queue() -> None:
    """Write the current in-memory queue to ``runs.db`` so a restart does not lose it.

    The snapshot AND the write are one critical section. Read-then-write outside the lock let
    two concurrent mirrors land in either order: the older, shorter snapshot could arrive last
    and leave the disk mirror one entry short, so a request the user was told 「已排队（第 2
    位）」 silently vanished on the next restart — the exact thing this mirror exists to prevent.
    """
    try:
        with queue_lock:
            get_run_store().save_queue(list(_RUN_QUEUE))
    except Exception:
        logger.exception(t('run.queueMirrorFailed'))


def load_pending_queue() -> int:
    """Re-populate ``_RUN_QUEUE`` from the mirror after a restart (called at boot).

    Only fills an empty queue: a process that already has live in-memory entries (a test
    harness, or a re-entrant boot) must not have them clobbered by an older disk snapshot.
    Returns how many requests came back."""
    with queue_lock:
        if _RUN_QUEUE:
            return 0
        try:
            restored_requests = get_run_store().load_queue()
        except Exception:
            logger.exception(t('run.queueLoadFailed'))
            return 0
        _RUN_QUEUE.extend(restored_requests)
    return len(restored_requests)


def put_back(entry: QueueEntry) -> None:
    """Hand a request back to the front: someone else took the slot in between.

    A request the user already pressed Run for is never dropped because of a race — it waits
    for the next drain instead, which is what 「继续等待」 means in the console line.
    """
    with queue_lock:
        _RUN_QUEUE.insert(0, entry)
        add_log(t('run.queue_waited', name=entry['workflow_name'] or entry['id']))
    mirror_queue()


def drain_queue(start_run: Callable[[dict, str], dict]) -> None:
    """Start the oldest waiting request with ``start_run``, at the end of a run.

    ``start_run`` is injected because it is :func:`app._begin_run`: the queue may not import the
    application (that is a cycle, and the layering forbids it), while starting a run is exactly
    what a drain must be able to do. Everything about the *queue* stays here — who is next, the
    mirror, who goes back to the front, and the loop past a request that can never start.

    Called from the finishing thread *after* it released the slot and cleared its own handle:
    the claim also checks thread liveness, so a thread still alive while it unwinds would make
    this queue the next request behind itself — and nothing would ever start it again.
    """
    while True:
        entry: QueueEntry | None = None
        with queue_lock:
            if _RUN_QUEUE:
                entry = _RUN_QUEUE.pop(0)
        # The pop removed an entry from the queue; mirror BEFORE branching so a run that
        # starts (and is never put back) leaves the disk mirror without it too.
        mirror_queue()
        if entry is None:
            return
        name = entry['workflow_name'] or entry['id']
        try:
            answer = start_run(entry['data'], entry['lang'])
        except Exception as e:  # a broken request must not strand the ones behind it
            logger.exception(t('run.queueStartFailed'))
            add_log(t('run.queue_broken', name=name, err=e))
            continue
        body = answer.get('body') or {}
        if answer.get('drop'):
            # Refused at the moment of starting in a way a retry can never fix — the
            # record a 继续 pointed at has been purged while it waited. Without this
            # the entry would be pushed back and refused again after every run.
            add_log(t('run.queue_broken', name=name, err=body.get('error', '')))
            continue
        if answer.get('status') == 200 and body.get('ok') and not body.get('queued'):
            add_log(t('run.queue_started', name=name, rid=body.get('run_id', '')))
            return
        # Someone else took the slot in between (a manual Run press): put the
        # request back at the front rather than drop what the user already asked for.
        put_back(entry)
        return
