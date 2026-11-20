"""One heavy model in memory at a time inside this process.

The laptop has 8 GB of video memory and a browser already holding 1.4 GB. A run that keeps a BERT
session, an embedding encoder and an Ollama 9B model resident at once does not fail politely -- it
OOMs or thrashes. The lease is the single place that says "hold this model while you read rows";
the underlying runtime still owns the real session cache, this just serialises the decision.
"""

import contextlib
import threading

_ACTIVE: dict[str, int] = {}
_LOCK = threading.Lock()


class ModelBusyError(RuntimeError):
    """A second heavy model was requested while one is already held."""


@contextlib.contextmanager
def hold(model_id: str):
    """Serialise heavy model work; a second, DIFFERENT model waits for the first to leave."""
    wanted = str(model_id or '').strip()
    with _LOCK:
        if _ACTIVE and wanted not in _ACTIVE:
            raise ModelBusyError(f'model {wanted!r} cannot load while {", ".join(_ACTIVE)} is in use')
        _ACTIVE[wanted] = _ACTIVE.get(wanted, 0) + 1
    try:
        yield
    finally:
        with _LOCK:
            remaining = _ACTIVE.get(wanted, 0) - 1
            if remaining <= 0:
                _ACTIVE.pop(wanted, None)
            else:
                _ACTIVE[wanted] = remaining


def active() -> tuple[str, ...]:
    return tuple(_ACTIVE)
