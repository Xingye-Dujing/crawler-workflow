"""Cloud transport refusal — one sentence about a local-only model transport on a cloud host.

The flag is the server's (``python app.py cloud``), so this lives in one place both the run
executor (``app.py``) and the ``/api/llm/*`` Blueprint can call. Depends only on ``Config`` and
``i18n`` — no run state — so it splits out cleanly with no test seam to move.
"""

from config import Config
from i18n import t


def _local_transport_refusal(provider: str) -> str:
    """Why a cloud host answers 「没有这种传输」, or '' when the choice is one it can honor.

    The flag is the server's (`python app.py cloud`), because the panel only hides the
    Ollama controls — a request still arrives from a saved workflow, an old tab, or a
    hand-written POST, and hiding a button is not the same as permitting the thing it
    does. Every transport that wants a daemon on the machine that hosts the crawl is
    refused BY NAME here rather than being re-labelled or silently answered with one
    model name: the other shape of this bug is a run that "succeeds" with no analysis
    because nothing was ever listening on 11434.
    """
    if not Config.CLOUD_MODE or str(provider or '') == 'openrouter':
        return ''
    return t('api.cloudNoLocalModel', provider=str(provider or ''))
