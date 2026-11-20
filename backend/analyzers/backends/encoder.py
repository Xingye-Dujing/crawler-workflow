"""Sentence embeddings from a small Chinese encoder, with one in-process cache.

The topic step already embedded a document once per stage and once per figure; routing all of those
calls through one loader avoids paying a multi-second model load a dozen times in one run. A model
that will not load is a named failure -- no lexical fallback, because a column labelled "semantic
similarity" computed from shared words is a different measurement.
"""

import threading

import numpy as np

from i18n import t
from services.analysis.kernels import UnknownOperationError

_CACHE: dict[str, object] = {}
_LOCK = threading.Lock()

DEFAULT_EMBED_MODEL = 'BAAI/bge-small-zh-v1.5'


def _load(model_name: str):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise UnknownOperationError(t('analysis.embed_missing')) from exc
    try:
        return SentenceTransformer(model_name)
    except Exception as exc:
        raise UnknownOperationError(t('analysis.embed_failed', model=model_name, err=exc)) from exc


def encode(texts: list[str], model_name: str = DEFAULT_EMBED_MODEL, batch_size: int = 64) -> np.ndarray:
    """Normalised vectors for a batch of text; the cache is keyed by the exact model name."""
    name = str(model_name or DEFAULT_EMBED_MODEL).strip()
    with _LOCK:
        model = _CACHE.get(name)
    if model is None:
        model = _load(name)
        with _LOCK:
            _CACHE[name] = _CACHE.get(name) or model
    try:
        vectors = model.encode(
            list(texts),
            batch_size=max(1, int(batch_size)),
            show_progress_bar=False,
            normalize_embeddings=True,
        )
    except Exception as exc:
        raise UnknownOperationError(t('analysis.embed_failed', model=name, err=exc)) from exc
    return np.asarray(vectors, dtype=np.float32)
