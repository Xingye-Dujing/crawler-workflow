"""The scheduled fire's two questions: may this canvas run unattended, and what happened.

Moved out of ``engine/run.py`` on 2026-10-29. The scheduler clock is injected with these two
functions (``set_canvas_source`` / ``set_run_starter``) so it never imports the app, and the rule
stays ONE rule asked twice: the same :func:`scheduled_canvas` answers the panel at save time and the
clock at fire time.

:func:`start_scheduled_run` reaches :func:`engine.run.begin_run` as ``run_engine.begin_run`` — by
name, at call time. ``tests/api/test_run_races.py`` pins that: a by-value binding would give this
caller its own object, and a test that fakes the run start would then drive a real crawl while
reporting green. The import sits inside the function so neither module has to be loaded first.
"""

from runtime.state import add_log
from runtime.stores import get_workflow_manager

from engine.plan import workflow_needs_llm
from i18n import t
from services.workflows.expand import expand_reusable_workflow


def scheduled_canvas(name: str) -> dict:
    """The saved canvas a scheduled task will run, or the reason it may not run on a timer.

    One answer for two moments: the schedule form refuses a canvas that cannot run unattended
    while the user is still choosing, and the fire refuses it again if the file changed since.
    Both rules are enforced here rather than in the panel, because a hand-written POST would
    otherwise skip them: the file must exist, and its steps must not need a model — a timer has no
    browser request behind it, so there is nowhere for an API key to come from, and a run that
    quietly skipped its analysis would look exactly like one that analysed something.
    """
    if not name:
        return {'workflow': None, 'error': t('sched.workflowRequired')}
    workflow = get_workflow_manager().load(name)
    if not workflow:
        return {'workflow': None, 'error': t('sched.canvasMissing', name=name)}
    # The saved file keeps reusable nodes as groups; this gate asks what a run will
    # actually call, so expand before asking whether a model is needed. (The expanded
    # graph is also what begin_run receives; there it is already group-free.)
    workflow, reusable_error = expand_reusable_workflow(workflow)
    if reusable_error:
        return {'workflow': None, 'error': reusable_error}
    if workflow_needs_llm(workflow):
        return {'workflow': None, 'error': t('sched.canvasNeedsModel', name=name)}
    return {'workflow': workflow, 'error': ''}


def start_scheduled_run(task: dict, manual: bool) -> dict:
    """Start one scheduled run and say what happened (started / queued / refused).

    ``run_id`` comes back so the task's own history can point at the record: that id is how the
    user opens the console of the fire that just happened.

    ``run_engine.begin_run`` is looked up on the module, at call time, and that is the whole point:
    one patch of :func:`engine.run.begin_run` governs the manual route, the queue drain and this
    scheduled fire alike. Importing the name into this module would give the schedule its own
    binding, and a test that fakes the run start would then drive a real crawl while reporting green
    (``tests/api/test_run_races.py`` refuses that shape).
    """
    from engine import run as run_engine

    loaded = scheduled_canvas(str(task.get('workflow') or ''))
    if loaded['error']:
        return {'ok': False, 'error': loaded['error']}
    name = str(task.get('name') or '')
    answer = run_engine.begin_run(
        {'workflow': loaded['workflow'], 'workflow_name': name, 'lang': task.get('lang') or 'zh'},
        '',
    )
    body = answer.get('body') or {}
    if answer.get('status') != 200 or not body.get('ok'):
        return {'ok': False, 'error': str(body.get('error') or '')}
    queued = bool(body.get('queued'))
    if not queued:
        # Only a run that really started gets a console line. A queued fire has no console of its
        # own yet (the queue narrates when it starts) and a refusal has none at all — that one is
        # recorded in the task's own history, which is where the user looks for it.
        add_log(t('sched.firedManual' if manual else 'sched.fired', name=name))
    return {'ok': True, 'queued': queued, 'run_id': str(body.get('run_id') or ''), 'error': ''}
