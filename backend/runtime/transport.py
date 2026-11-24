"""Cloud transport refusal — one sentence about a local-only model transport on a cloud host.

The flag is the server's (``python app.py cloud``), so this lives in one place both the run
orchestration (``engine/run/claim.py``) and the ``/api/llm/*`` Blueprint can call. Depends only on
``Config`` and ``i18n`` — no run state — so it sits in ``runtime/`` as a process-wide policy with
no test seam to move.
"""

from core.config import Config


def _local_transport_refusal(provider: str) -> str:
    """Why a cloud host answers “没有这种传输”, or '' when the choice is one it can honor.

    The flag is the server's (`python app.py cloud`), because the panel only hides the
    Ollama controls — a request still arrives from a saved workflow, an old tab, or a
    hand-written POST, and hiding a button is not the same as permitting the thing it
    does. Every transport that wants a daemon on the machine that hosts the crawl is
    refused BY NAME here rather than being re-labelled or silently answered with one
    model name: the other shape of this bug is a run that "succeeds" with no analysis
    because nothing was ever listening on 11434.
    """
    from ai.providers.registry import local_transport_refusal

    refusal = local_transport_refusal(provider)
    if refusal:
        return refusal
    if not Config.CLOUD_MODE:
        return ''
    # Unknown names are validated by the run door and the /api/llm/test route; this helper
    # only answers the local-daemon question. A name outside the catalog is not a local
    # transport, so it must not be refused here as one.
    return ''
