"""The memory-artifact validator: non-empty text within the product's character cap.

The cap is the product's promise about a memory row (the same number the panel shows); it lives here
because this is the one rule that enforces it on a model draft.
"""

from ai.validators.base import Validation, Validator, register
from i18n import t

#: The longest memory text the panel accepts, in characters.
MAX_MEMORY_CHARS = 2000


def _check(payload: dict) -> Validation:
    source = payload if isinstance(payload, dict) else {}
    text = str(source.get('text') or '').strip()
    if text and len(text) <= MAX_MEMORY_CHARS:
        # The card carries the trimmed text, not the model's padding: that is the value the user
        # applies, so it must match what the store accepts.
        return Validation(ok=True, payload={'text': text})
    problems: list[str] = []
    if not text:
        problems.append('memory needs non-empty text')
    if len(text) > MAX_MEMORY_CHARS:
        problems.append(f'memory text exceeds {MAX_MEMORY_CHARS} characters')
    return Validation(
        ok=False,
        problems=problems,
        message=t('ai.memoryDraftRefused', limit=MAX_MEMORY_CHARS),
    )


register(Validator('memory', _check))
