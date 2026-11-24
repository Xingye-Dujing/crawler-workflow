"""The one reader every tool needs before it trusts an argument a model wrote.

A tool's schema says ``integer``, but a model can still send ``"5 rows"``. Raising ValueError escaped
the tool event (only ``AIError`` is caught) and left a ``tool_use`` with no result, which made every
later turn fail the provider's tool-pair validation. So a number is bounded here, once, for every
domain.
"""

import re


def _int_arg(value, default: int = 0, minimum: int | None = None, maximum: int | None = None) -> int:
    """A model-supplied number as a bounded int; a malformed value takes the default."""
    try:
        number = int(float(value))
    except (TypeError, ValueError, OverflowError):
        # A number with a word after it ("5 rows", "10 行") is what a model actually writes; its
        # leading integer is the value it meant, and refusing it would spend a round for nothing.
        match = re.match(r'\s*([+-]?\d+)', str(value or ''))
        number = int(match.group(1)) if match else int(default)
    if minimum is not None:
        number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number
