"""Cross-encoder reranking: score a short list of candidates against one query.

A bi-encoder (the embedding steps) is fast for recalling candidates; a cross-encoder reads the pair
together and is the right small model for ordering those candidates. This is deliberately bounded to
dozens of short strings -- it is an AI workspace "small job", not a table-wide operator.
"""

import threading

DEFAULT_MODEL = 'BAAI/bge-reranker-base'
_PIPELINES: dict[tuple[str, str], tuple] = {}
_LOCK = threading.Lock()


def _load(model_name: str, device: str):
    key = (model_name, device)
    with _LOCK:
        loaded = _PIPELINES.get(key)
    if loaded is not None:
        return loaded
    try:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
    except ImportError as exc:
        raise RuntimeError('reranker needs torch and transformers') from exc
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSequenceClassification.from_pretrained(model_name).to(device)
    model.eval()
    with _LOCK:
        _PIPELINES[key] = _PIPELINES.get(key) or (tokenizer, model, torch)
        return _PIPELINES[key]


def rerank(
    query: str, candidates: list[str], model_name: str = DEFAULT_MODEL, top_k: int = 10, device: str = ''
) -> list[dict]:
    """Return ``[{rank, text, score}]`` in descending score order."""
    import torch

    if not str(query or '').strip() or not candidates:
        return []
    chosen = device or ('cuda' if torch.cuda.is_available() else 'cpu')
    tokenizer, model, torch = _load(model_name, chosen)
    pairs = [[str(query).strip(), str(text)] for text in candidates]
    encoded = tokenizer(pairs, padding=True, truncation=True, max_length=512, return_tensors='pt')
    encoded = {key: value.to(chosen) for key, value in encoded.items()}
    with torch.no_grad():
        scores = model(**encoded).logits.squeeze(-1).float().cpu().tolist()
    if isinstance(scores, float):
        scores = [scores]
    ordered = sorted(zip(candidates, scores, strict=True), key=lambda pair: -pair[1])[: max(1, int(top_k))]
    return [
        {'rank': rank, 'text': text, 'score': round(float(score), 6)}
        for rank, (text, score) in enumerate(ordered, start=1)
    ]
