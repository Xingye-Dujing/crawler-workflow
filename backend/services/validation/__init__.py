"""Validation: the one evaluator for declared rules and node-specific validators.

A capability's manifest says which parameters/inputs it refuses without a run; a validator it names
handles the rest. This package runs both for every caller (the workflow engine today, the canvas
badge and the AI tools as they move off their own copies). The rules stay data and the validators
stay with the capability: a new refusal never becomes a branch in a shared function.
"""

from services.validation.engine import ValidationContext, static_problems, validation_problems

__all__ = ['ValidationContext', 'static_problems', 'validation_problems']
