"""Validation: the one evaluator for declared rules.

A capability's manifest says which parameters it refuses without a run; this package runs those
rules for every caller (the workflow engine today, the canvas badge and the AI tools as they move
off their own copies). The rules stay data: a new refusal is a ``Rule`` in the manifest, not a
branch in a shared function.
"""

from services.validation.engine import static_problems

__all__ = ['static_problems']
