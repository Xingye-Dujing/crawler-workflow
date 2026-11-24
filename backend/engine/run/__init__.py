"""The run package: one run's life, split by the question each part answers.

The single ``engine/run.py`` this replaced was 1900 lines of claim, loop, record and stop code, so
"where does a node's result become a record row" had to be answered by reading all of it. The split
is along the questions, not along the lines:

``decide``    which record this attempt writes, and whether it splits — pure functions, no I/O.
``node``      ONE node, durably: dispatch it, store its rows, grade it (Stop, failure, partial,
              reuse, skip, the memory warning, the after-run check).
``walk``      the graph walk: one component's nodes level by level, plus the parallel pool wrapper
              and the "this workflow is dead" verdict.
``records``   the rows one attempt writes: a component's record opened, closed, adopted, erased.
``worker``    the worker thread's whole life: store open, components, verdict, queue hand-off.
``claim``     the ONE start path (``begin_run``): validate, park, or own the slot and start it.
``stop``      Stop: the guard, the flags, and the browsers that must die in their own thread.

What is NOT here, because it answers a different question: the console's write paths
(``engine.run_logs`` — the print() tee and the durable per-run log) and the scheduler's seam
(``engine.run_schedule`` — may this canvas run unattended). Both moved out on 2026-10-29;
``begin_run`` is still the only path that starts a run, and the queue drains by calling it.

Two rules survive the split verbatim. A helper that needs no state from the claim lives at module
scope, where a test can reach it and a reader can see its inputs — ``tests/unit/gates/
test_run_worker_module_scope.py`` refuses a move back into ``_run_worker``/``begin_run``. And every
module that prints imports ``add_log`` itself, so the API tests' console forwarding lists each one
(``tests/unit/gates/test_console_seam_census.py`` enumerates them).
"""

from engine.run.claim import begin_run, cloud_refusal_response
from engine.run.decide import choose_record, record_belongs, record_has_component, split_records
from engine.run.node import (
    HEAVY_RESULT_ROWS,
    NON_INPUT_NODES,
    _postcheck_node,
    execute_node,
    note_heavy_result,
    run_node_durable,
    settle_node_as_stopped,
)
from engine.run.records import (
    _close_component_record,
    _component_run,
    _invalidate_rerun_nodes,
    _rerun_request,
    record_export_stamp,
)
from engine.run.stop import stop_run
from engine.run.walk import (
    _inputs_for,
    _mark_dead_workflow,
    _node_of,
    _run_single_workflow,
    _run_workflow_wrapper,
    _stopping,
    _wf_display_name,
)
from engine.run.worker import (
    _contract_columns,
    _notify_run_outcome,
    _preflight_samples,
    _run_worker,
    start_next_queued,
)
from services.runs.store import RUN_COMPLETED, RUN_FAILED, RUN_INTERRUPTED

__all__ = [
    'HEAVY_RESULT_ROWS',
    'NON_INPUT_NODES',
    'RUN_COMPLETED',
    'RUN_FAILED',
    'RUN_INTERRUPTED',
    '_close_component_record',
    '_component_run',
    '_contract_columns',
    '_inputs_for',
    '_invalidate_rerun_nodes',
    '_mark_dead_workflow',
    '_node_of',
    '_notify_run_outcome',
    '_postcheck_node',
    '_preflight_samples',
    '_rerun_request',
    '_run_single_workflow',
    '_run_worker',
    '_run_workflow_wrapper',
    '_stopping',
    '_wf_display_name',
    'begin_run',
    'choose_record',
    'cloud_refusal_response',
    'execute_node',
    'note_heavy_result',
    'record_belongs',
    'record_export_stamp',
    'record_has_component',
    'run_node_durable',
    'settle_node_as_stopped',
    'split_records',
    'start_next_queued',
    'stop_run',
]
