"""One definition of "the run I started is over" — and of "nothing is running".

Every module that posts ``/api/workflow/execute`` needs to block until the worker
has finished, and the naive version — capture ``execution_state['thread']`` after
the POST and wait for it to die — is wrong in one specific way. A request that
found the slot busy is *queued*, and a queued request has no thread yet: the
handle such a helper is polling belongs to whoever ran before it. So the test
either returns the moment that unrelated thread dies (and reads a console the next
run had not written to yet), or, if the handle was ``None``, polls nothing at all
for 30 seconds and fails with an assertion that mentions a timeout but not the
queue it actually got stuck in. That is the shape of the order-dependent failures
this repo used to blame on "flaky machines".

Two questions, deliberately kept apart:

* :func:`run_finished` — has *my* run stopped? Flag down and worker gone. A test
  that intentionally parks a second request still needs to wait for the first one,
  so this must not care about the queue.
* :func:`wait_until_quiet` — may a test start a run at all? Adds the empty queue,
  which matters because the finishing worker hands the slot over *after* it has
  cleared its own ``thread`` handle: a two-condition check can declare the server
  quiet a moment before a stranger's run starts inside the next test.
"""

import time


def _slot_free(module) -> bool:
    state = module.execution_state
    thread = state.get('thread')
    return not state.get('running') and (thread is None or not thread.is_alive())


def run_finished(module, timeout: float = 30.0) -> bool:
    """True once the worker in flight has settled (see :mod:`run_wait`)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _slot_free(module):
            return True
        time.sleep(0.02)
    return False


def wait_until_quiet(module, timeout: float = 30.0) -> bool:
    """True once nothing is running *and* nothing is waiting to start."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _slot_free(module) and not module._RUN_QUEUE:
            return True
        time.sleep(0.02)
    return False


def describe_state(module) -> str:
    """A failure message that names what is actually blocking the test."""
    state = module.execution_state
    thread = state.get('thread')
    queue = [entry.get('workflow_name') or entry.get('id') for entry in module._RUN_QUEUE]
    return (
        f'running={state.get("running")} thread_alive={thread is not None and thread.is_alive()} '
        f'queued={queue} outcome={state.get("outcome")!r}'
    )
