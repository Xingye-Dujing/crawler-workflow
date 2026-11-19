"""The memory-artifact validator: non-empty text within the store's character cap.

This shape used to be a dedicated ``if`` in ``_artifact_event``. It now lives with the rule it
enforces, so the store's cap stays the single answer and the turn loop stays format-agnostic.
"""

from ai import store
from ai.validators.base import Validation, Validator, register
from i18n import t


def _check(payload: dict) -> Validation:
    source = payload if isinstance(payload, dict) else {}
    text = str(source.get('text') or '').strip()
    if text and len(text) <= store.MAX_MEMORY_CHARS:
        # The card carries the trimmed text, not the model's padding: that is the value the user
        # applies, so it must match what the store accepts.
        return Validation(ok=True, payload={'text': text})
    problems: list[str] = []
    if not text:
        problems.append('memory needs non-empty text')
    if len(text) > store.MAX_MEMORY_CHARS:
        problems.append(f'memory text exceeds {store.MAX_MEMORY_CHARS} characters')
    return Validation(
        ok=False,
        problems=problems,
        message=t('ai.memoryDraftRefused', limit=store.MAX_MEMORY_CHARS),
    )


register(Validator('memory', _check))
