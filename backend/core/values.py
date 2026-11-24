"""Numeric values typed by a person, read the way every layer must read them.

These five readers used to live in ``api/http.py``, so a service or a node that
needed one imported the HTTP layer — eleven modules did, which is why
``backend/services`` could not be exercised without Flask. Nothing here touches
Flask: the question is "what number did the human mean", not "what did the
request body say".

The rules are deliberately narrow, and each one is a bug that was found in
production:

* unparseable text, ``inf`` and ``nan`` are not numbers — they fall back to the
  caller's default instead of escaping as a 500 or poisoning a pandas frame;
* a **blank** box means "not configured" (``optional_*`` answers ``None``), which
  is a different answer from "0";
* a threshold's typed ``0`` is a real answer, so ``float_with_default`` never
  swallows it into the default (``optional_float(x) or default`` did).
"""

from __future__ import annotations

import math


def _finite_number(value) -> float | None:
    """The float a person typed, or ``None`` when it is not a finite number."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def safe_int(value, default: int = 0, minimum: int = None, maximum: int = None) -> int:
    """``int()`` for numbers typed into the UI, clamped to the caller's bounds.

    Every settings field arrives as a string, so "abc" used to raise a bare
    ValueError from inside a request handler (HTTP 500) or from a node (opaque
    node failure). A malformed value now falls back to the default.

    ``inf`` / ``nan`` are the same class of mistake and used to escape it:
    ``float('inf')`` parses fine and only ``int()`` then refuses it with an
    OverflowError, which no ``except (TypeError, ValueError)`` catches — so
    ``/api/history/series?limit=inf`` answered 500. Anything not finite is
    rejected up front, exactly like unparseable text.
    """
    number = _finite_number(value)
    if number is None:
        return default
    result = int(number)
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def safe_float(value, default: float = 0.0) -> float:
    """``safe_int`` for a float field.

    ``inf``/``nan`` poison every pandas call downstream instead of failing here, so they
    are not usable numbers any more than "abc" is — both fall back to ``default``.
    """
    number = _finite_number(value)
    return default if number is None else number


def optional_int(value):
    """Like :func:`safe_int`, but blank or unparseable means "not configured" (``None``)."""
    raw = str(value or '').strip()
    if not raw:
        return None
    number = _finite_number(raw)
    return None if number is None else int(number)


def optional_float(value):
    """``optional_int`` that keeps the fraction.

    ``frac=inf`` reached ``df.sample`` as a ValueError and ``frac=nan`` as a silent
    no-op; both mean "no fraction configured".
    """
    raw = str(value or '').strip()
    if not raw:
        return None
    return _finite_number(raw)


def float_with_default(value, default: float) -> float:
    """A rate/threshold field with a default, where a typed ``0`` is a real answer.

    ``optional_float(x) or default`` swallows a typed 0 into the default — the mistake the
    forecast block's own comment warns about ("swallowing it into the default would answer a
    question the user did not ask"). Unlike a COUNT (where 0 is "not configured", so ``or`` is
    right), a threshold's 0 is meaningful, so the default is only for an ABSENT box; a typed 0
    is forwarded to the step, which honours or refuses it. Blank/unparseable → ``default``.
    """
    parsed = optional_float(value)
    return default if parsed is None else parsed
