"""The run queue: requests waiting for the one run slot, plus the mirror that survives a restart.

One run at a time is a property of this product, not an accident: the console, the crawl
browsers, the checkpoint store and the resume cursor all assume a single writer. What was missing
is somewhere to put the next request while one is busy — it used to be refused outright, and the
user had to press Run again at the right moment.

The in-memory list (``state._RUN_QUEUE``) is the runtime source of truth — ordering, the drain
and the liveness check all read it — and ``runs.db`` holds only a recovery mirror of it, so a
mirror failure must never break the request that triggered it. A restart therefore drops nothing
the user was told about: ``load_pending_queue()`` re-fills an EMPTY queue at boot.

Starting a queued request is deliberately **injected**: :func:`drain_queue` takes
``engine.run.begin_run`` as a callback, because a queue module that imported the run start (or the
application) would both invert the layering and freeze a circular import in place. Everything the
hand-off has to know about the *queue* — who is next, what the mirror says, who goes back to the
front — stays here.
"""

import logging
import threading
import time
import uuid
from collections.abc import Callable

from runtime import account_context
from runtime.account_context import Account
from runtime.state import _RUN_QUEUE, QueueEntry, add_log
from runtime.stores import get_run_store

from i18n import t
from services.runs.payload import workflow_shape_error

logger = logging.getLogger(__name__)

#: Queued requests live in memory only (see ``state._RUN_QUEUE``). A restart drops them, which is
#: the honest behaviour for a list of intentions nobody is here to confirm.
QUEUE_MAX = 8

queue_lock = threading.Lock()
#: Serialises the read-snapshot/write-mirror pair, so two queue events cannot land their disk
#: snapshots out of order (the older, shorter one arriving last would drop the next entry).
_mirror_lock = threading.Lock()
#: Owners whose mirror has been written at least once; a queue that empties must also write an
#: empty mirror for its owner, or the restart would resurrect requests the user cancelled.
_MIRRORED_OWNERS: set = set()


def _owner_id() -> str:
    """The account this thread speaks for, spelled the way an entry stores it ('' = owner)."""
    account = account_context.current()
    return account.user_id if account is not None else ''


def _account_for(entry: QueueEntry):
    """The live account behind a queued entry, or ``None``.

    ``None`` for the local owner. A named entry whose account was deleted or disabled cannot be
    started (its tree may have moved); the drain drops it with a console line instead of writing a
    run into a directory nobody owns any more.
    """
    user_id = str(entry.get('user_id') or '')
    if not user_id:
        return None
    from services.accounts.service import get_account_service

    row = get_account_service().store.get_user(user_id)
    if row is None or row['status'] != 'active':
        return None
    return Account(row['user_id'], row['username'], row['role'])


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
            # The queue is shared by every account; this is what lets the drain start the request
            # under its own owner and what keeps one account from cancelling another's entry.
            'user_id': _owner_id(),
            'username': getattr(account_context.current(), 'username', ''),
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
    """The waiting requests of THIS account, oldest first — without their payloads."""
    owner = _owner_id()
    with queue_lock:
        return [
            {key: entry[key] for key in ('id', 'workflow_name', 'nodes', 'queued_at')}
            for entry in _RUN_QUEUE
            if str(entry.get('user_id') or '') == owner
        ]


def cancel_queued(queue_id: str) -> bool:
    """Drop one waiting request of THIS account by its queue id. True when it is gone."""
    owner = _owner_id()
    with queue_lock:
        for position, entry in enumerate(_RUN_QUEUE):
            if entry['id'] == queue_id and str(entry.get('user_id') or '') == owner:
                del _RUN_QUEUE[position]
                break
        else:
            return False
    mirror_queue()
    return True


def clear_queue() -> int:
    """Empty THIS account's waiting requests. Other accounts keep theirs."""
    owner = _owner_id()
    with queue_lock:
        keep = [entry for entry in _RUN_QUEUE if str(entry.get('user_id') or '') != owner]
        count = len(_RUN_QUEUE) - len(keep)
        _RUN_QUEUE[:] = keep
    mirror_queue()
    return count


def _save_owner_mirror(user_id: str, entries: list) -> None:
    """Write one account's queue slice into that account's own ``runs.db``."""
    account = None
    if user_id:
        from services.accounts.service import get_account_service

        row = get_account_service().store.get_user(user_id)
        if row is None:
            return
        account = Account(row['user_id'], row['username'], row['role'])
    with account_context.use(account):
        get_run_store().save_queue(list(entries))


def mirror_queue() -> None:
    """Write each account's waiting requests to its own ``runs.db`` so a restart does not lose them.

    The in-memory queue is shared; the mirror is not. Writing the whole queue into whichever
    account happened to be active would both leak another account's workflow names into that
    database and restore them under the wrong owner.
    """
    try:
        with _mirror_lock:
            with queue_lock:
                groups: dict[str, list] = {}
                for entry in _RUN_QUEUE:
                    groups.setdefault(str(entry.get('user_id') or ''), []).append(entry)
                owners = sorted(set(groups) | _MIRRORED_OWNERS)
                snapshot = {owner: list(groups.get(owner, [])) for owner in owners}
            for owner, entries in snapshot.items():
                _save_owner_mirror(owner, entries)
            with queue_lock:
                _MIRRORED_OWNERS.clear()
                _MIRRORED_OWNERS.update(groups)
    except Exception:
        logger.exception(t('run.queueMirrorFailed'))


def _owner_scopes() -> list:
    """Every account whose queue mirror should be restored (``None`` = the local owner)."""
    from services.accounts.service import accounts_mode, get_account_service

    if not accounts_mode():
        return [None]
    rows = get_account_service().store.list_users()
    scopes = [Account(row['user_id'], row['username'], row['role']) for row in rows if row['status'] == 'active']
    return scopes or [None]


def load_pending_queue() -> int:
    """Re-populate ``_RUN_QUEUE`` from every account's mirror after a restart (called at boot).

    Only fills an empty queue: a process that already has live in-memory entries (a test
    harness, or a re-entrant boot) must not have them clobbered by an older disk snapshot.
    Returns how many requests came back."""
    with queue_lock:
        if _RUN_QUEUE:
            return 0
    restored_requests = []
    for account in _owner_scopes():
        with account_context.use(account):
            try:
                rows = get_run_store().load_queue()
            except Exception:
                logger.exception(t('run.queueLoadFailed'))
                continue
        for row in rows:
            row.setdefault('user_id', account.user_id if account is not None else '')
            row.setdefault('username', account.username if account is not None else '')
            restored_requests.append(row)
    restored_requests.sort(key=lambda row: str(row.get('queued_at') or ''))
    with queue_lock:
        _RUN_QUEUE.extend(restored_requests)
        _MIRRORED_OWNERS.update(str(row.get('user_id') or '') for row in restored_requests)
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

    ``start_run`` is injected because it is :func:`engine.run.begin_run`: the queue may not import the
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
        account = _account_for(entry)
        if entry.get('user_id') and account is None:
            # The owner was deleted or disabled while this request waited. Its data tree may have
            # moved, so the request is dropped BY NAME instead of writing into a stranger's tree.
            logger.warning(t('run.queueOwnerGone', name=name, user=str(entry.get('user_id') or '')))
            continue
        try:
            with account_context.use(account):
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
