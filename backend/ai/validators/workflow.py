"""The workflow-draft validator: structure plus the engine's own run validation.

A thin adapter over ``workflow_draft.validate``. Its ``{ok, structural, engine}`` report is a
published shape — the ``workflow_validate`` tool and ``/api/workflow/validate`` both return it — so
the validator carries it through unchanged instead of redefining a second contract.
"""

from ai import workflow_draft
from ai.validators.base import Validation, Validator, register
from i18n import t


def _check(payload: dict) -> Validation:
    report = workflow_draft.validate(payload)
    problems = (report['structural'] + report['engine'])[:8]
    if report['ok']:
        return Validation(ok=True, report=report)
    return Validation(
        ok=False,
        problems=problems,
        message=t('ai.workflowDraftInvalid', detail='; '.join(problems)),
        report=report,
    )


register(Validator('workflow_draft', _check))
#: ``workflow`` is the kind older harnesses and ``apply_workflow`` still send.
register(Validator('workflow', _check))
