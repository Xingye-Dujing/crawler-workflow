"""Zero-shot text classification with a small multilingual NLI model.

A temporary label set ("正面/质疑/辟谣/离题") is the case where training a head is wasteful but an
LLM is overkill. The NLI model scores every candidate label for one text in a single pass; the result
is a closed label plus a score, so it slots into the same chart/export contract as the other
per-row analyzers. No dependency-free fallback: an unavailable model is refused BY NAME.
"""

import logging
import threading

import pandas as pd

from i18n import t

logger = logging.getLogger(__name__)

DEFAULT_MODEL = 'MoritzLaurer/mDeBERTa-v3-base-mnli-xnli'
BATCH = 32
_PIPELINES: dict[str, object] = {}
_LOCK = threading.Lock()


class ZeroShotError(ValueError):
    """A missing label or runtime that cannot be answered with a manufactured class."""


def _pipeline(model_name: str):
    with _LOCK:
        cached = _PIPELINES.get(model_name)
    if cached is not None:
        return cached
    try:
        from transformers import pipeline
    except ImportError as exc:
        raise ZeroShotError(t('analysis.zero_shot_missing')) from exc
    try:
        made = pipeline('zero-shot-classification', model=model_name)
    except Exception as exc:
        raise ZeroShotError(t('analysis.zero_shot_failed', model=model_name, err=exc)) from exc
    with _LOCK:
        _PIPELINES[model_name] = _PIPELINES.get(model_name) or made
        return _PIPELINES[model_name]


def analyze_zero_shot(
    df: pd.DataFrame,
    text_column: str = '正文',
    labels: str = '',
    model: str = DEFAULT_MODEL,
    threshold: float = 0.0,
    label_column: str = 'zero_shot_label',
    score_column: str = 'zero_shot_score',
) -> pd.DataFrame:
    """Add one label column and one score column; refuse an empty candidate set."""
    import re

    candidates = [item.strip() for item in re.split(r'[,，、\n]', str(labels or '')) if item.strip()]
    if not candidates:
        raise ZeroShotError(t('analysis.zero_shot_no_labels'))
    if text_column not in df.columns:
        raise ZeroShotError(t('analysis.col_missing', col=text_column))
    work = df.copy()
    work[label_column] = ''
    work[score_column] = None
    name = str(model or DEFAULT_MODEL).strip()
    tagger = _pipeline(name)
    indices = [idx for idx, raw in work[text_column].items() if pd.notna(raw) and str(raw).strip()]
    for start in range(0, len(indices), BATCH):
        chunk = indices[start : start + BATCH]
        texts = [str(work.at[idx, text_column]).strip() for idx in chunk]
        try:
            answers = tagger(texts, candidate_labels=candidates, multi_label=False)
        except Exception as exc:
            raise ZeroShotError(t('analysis.zero_shot_failed', model=name, err=exc)) from exc
        if isinstance(answers, dict):
            answers = [answers]
        for idx, answer in zip(chunk, answers, strict=False):
            label = str(answer.get('labels', [''])[0])
            score = float(answer.get('scores', [0.0])[0])
            if score < threshold:
                continue  # unmeasured stays blank, never a manufactured class
            work.at[idx, label_column] = label
            work.at[idx, score_column] = round(score, 6)
    return work
