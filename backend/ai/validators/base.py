"""Artifact validators: kind → a check that answers whether a draft is legal.

``_artifact_event`` used to carry one ``if kind == …`` per strict format. That is the wrong seam:
adding a format meant editing shared turn code. Here each kind with a strict shape registers one
validator in its own module and the agent does a lookup. A validator is server fact — the node
catalog and the engine own what "legal" means — never a script carried by a user skill.

A check never writes. It returns a bounded report; the agent turns a failed report into the call's
tool result so the model can repair its own draft in the same turn, with an unanswered call never
left behind.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

#: After this many refusals of one kind in a turn, the model is told to stop resending drafts.
MAX_ARTIFACT_REPAIRS = 3


@dataclass(frozen=True)
class Validation:
    """The answer of one validator.

    ``message`` is already localized by the validator: it is the refusal sentence the model reads.
    ``report`` is the structured detail embedded in the tool row under ``problems``; a validator
    whose shape has no published contract leaves it ``None``. ``payload`` lets a validator normalize
    a legal draft (a memory trims its text) without the agent knowing that format.
    """

    ok: bool
    problems: list[str] = field(default_factory=list)
    message: str = ''
    report: dict | None = None
    payload: dict | None = None


@dataclass(frozen=True)
class Validator:
    kind: str
    check: Callable[[dict], Validation]


VALIDATORS: dict[str, Validator] = {}


def register(validator: Validator) -> None:
    """Bind one artifact kind to its validator. A duplicate is refused, never silently replaced."""
    key = str(validator.kind or '').strip()
    if not key:
        raise ValueError('an artifact validator needs a kind')
    if key in VALIDATORS and VALIDATORS[key] is not validator:
        raise ValueError(f'artifact kind {key} already has a validator')
    VALIDATORS[key] = validator


def check(kind: str, payload: dict) -> Validation | None:
    """Validate *payload* for *kind*, or ``None`` when that kind has no strict shape to check."""
    validator = VALIDATORS.get(str(kind or ''))
    return validator.check(payload) if validator else None


def registered_kinds() -> frozenset[str]:
    """The kinds with a validator — so a contract test can pin the set."""
    return frozenset(VALIDATORS)
