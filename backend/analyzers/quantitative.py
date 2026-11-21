"""Quantitative content analysis: deductive coding against a fixed codebook.

Unlike grounded-theory open coding, the categories exist BEFORE the run. The researcher owns the
codebook; the LLM is a coder that must choose one defined code per row and quote the evidence. Two
independent passes give a Cohen's kappa the paper can report, and disagreements stay in the table
for adjudication instead of being silently averaged away.
"""

import hashlib
import json
import logging
import re

import pandas as pd

from analyzers.llm_client import run_llm_dataframe
from i18n import t

logger = logging.getLogger(__name__)

CODE_RE = re.compile(r'^\s*CODE\s*[:：]\s*(.+?)\s*$', re.M)
EVIDENCE_RE = re.compile(r'^\s*EVIDENCE\s*[:：]\s*(.+?)\s*$', re.M)
SCORE_RE = re.compile(r'^\s*SCORE\s*[:：]\s*([0-9.]+)\s*$', re.M)


def _codebook_scope(codebook: dict, coder: str) -> str:
    """Cache scope for one coder's view of a codebook.

    The prompt builder passed to ``run_llm_dataframe`` is a closure: its *source* is identical for
    every codebook and every coder, so ``prompt_version`` cannot see the two values that actually
    decide the answer. Without this scope an edited codebook (a new version with different codes or
    decision rules) would replay the previous version's answers, and coder B would replay coder A's
    answers in a dual run — making kappa 1.0 by construction. The scope is therefore the digest of
    the codebook as the prompt renders it, plus the coder tag.
    """
    payload = json.dumps(codebook, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha1(payload.encode('utf-8')).hexdigest()[:20]
    return f'content_analysis|{coder.strip().lower()}|{digest}'


class ContentAnalysisError(ValueError):
    """A codebook or answer cannot be interpreted; refuse rather than invent a code."""


def _labels(codebook: dict) -> list[str]:
    rows = [str(code.get('code') or '').strip() for code in codebook.get('codes') or []]
    labels = [item for item in rows if item]
    if not labels:
        raise ContentAnalysisError(t('quant.no_codes'))
    return labels


def build_code_prompt(text: str, codebook: dict, coder: str = 'a') -> str:
    """One coder's instruction. A second pass uses a different coder tag so the prompts differ."""
    labels = _labels(codebook)
    lines = [
        f'You are content-analysis coder {coder.upper()}. Choose exactly ONE code for the text.',
        'Codes and their decision rules:',
    ]
    for code in codebook.get('codes') or []:
        name = str(code.get('code') or '').strip()
        if not name:
            continue
        lines.append(f'- {name}: {code.get("definition", "")}')
        if code.get('include'):
            lines.append(f'  Include: {code["include"]}')
        if code.get('exclude'):
            lines.append(f'  Exclude: {code["exclude"]}')
    lines += [
        f'Allowed codes: {" | ".join(labels)}',
        'Output exactly three lines, no markdown:',
        'CODE: <one allowed code, spelled exactly as above>',
        'EVIDENCE: <verbatim span from the text that justifies the code>',
        'SCORE: <0 to 1 confidence>',
        f'TEXT:\n{text}\n',
    ]
    return '\n'.join(lines)


def parse_code(content: str, labels: list[str]):
    """Return ``(code, evidence, score)`` or (None, None, None) when unreadable."""
    code_match = CODE_RE.search(str(content or ''))
    if not code_match:
        return None, None, None
    code = code_match.group(1).strip()
    if code not in labels:
        return None, None, None
    evidence = EVIDENCE_RE.search(str(content or ''))
    score = SCORE_RE.search(str(content or ''))
    try:
        value = float(score.group(1)) if score else 0.0
    except ValueError:
        value = 0.0
    return code, evidence.group(1).strip() if evidence else '', min(1.0, max(0.0, value))


def code_rows(df: pd.DataFrame, text_column: str, codebook: dict, ctx: dict | None = None, coder: str = 'a'):
    """Add ``qa_code`` / ``qa_evidence`` / ``qa_score`` columns, resume-safe via the shared runner."""
    if text_column not in df.columns:
        raise ContentAnalysisError(t('analysis.col_missing', col=text_column))
    labels = _labels(codebook)

    def build_prompt(text):
        return build_code_prompt(text, codebook, coder)

    def parse(content):
        return parse_code(content, labels)

    return run_llm_dataframe(
        df,
        text_column=text_column,
        op='content_analysis',
        result_columns=['qa_code', 'qa_evidence', 'qa_score'],
        blank=['', '', None],
        fail_value=(None, None, None),
        build_prompt=build_prompt,
        parse=parse,
        ctx=ctx,
        # The closure's source cannot distinguish codebooks/coders: pin the cache to both so an
        # edited codebook re-pays for its answers and the two coders stay independent.
        extra_key=_codebook_scope(codebook, coder),
        label=t('quant.code_label', coder=coder.upper()),
    )


def cohen_kappa(a: list[str], b: list[str]) -> float:
    """Agreement corrected for chance, over the SAME rows and only rows both coders answered."""
    pairs = [(x, y) for x, y in zip(a, b, strict=True) if x and y]
    if not pairs:
        return 0.0
    categories = sorted({label for pair in pairs for label in pair})
    observed = sum(1 for x, y in pairs if x == y) / len(pairs)
    if observed == 1.0:
        return 1.0
    expected = 0.0
    for category in categories:
        pa = sum(1 for x, _ in pairs if x == category) / len(pairs)
        pb = sum(1 for _, y in pairs if y == category) / len(pairs)
        expected += pa * pb
    if expected >= 1.0:
        return 1.0
    return (observed - expected) / (1.0 - expected)


def dual_code(df: pd.DataFrame, text_column: str, codebook: dict, ctx: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """Two independent passes; the result table keeps BOTH codes and flags disagreements.

    ``run_llm_dataframe`` writes its result columns into the frame it is handed and returns THAT
    same object. Passing the caller's ``df`` to both passes aliased them: coder B overwrote coder A's
    ``qa_code`` before ``first.copy()`` ran, so both columns held B's answer and kappa was 1.0 by
    construction. Each pass gets its own copy, and the two cache scopes differ by coder (see
    ``_codebook_scope``), so the two coders are genuinely independent.
    """
    first = code_rows(df.copy(), text_column, codebook, ctx=ctx, coder='a')
    second = code_rows(df.copy(), text_column, codebook, ctx=ctx, coder='b')
    result = first.copy()
    result['qa_code_b'] = second['qa_code'].tolist()
    result['qa_evidence_b'] = second['qa_evidence'].tolist()
    result['qa_agree'] = [bool(x and y and x == y) for x, y in zip(first['qa_code'], second['qa_code'], strict=True)]
    coded = [index for index, value in result['qa_code'].items() if value]
    reliability = {
        'coded_rows': len(coded),
        'agreement': round(sum(1 for idx in coded if result.at[idx, 'qa_agree']) / max(1, len(coded)), 4),
        'kappa': round(cohen_kappa(result.loc[coded, 'qa_code'].tolist(), result.loc[coded, 'qa_code_b'].tolist()), 4),
    }
    return result, reliability


def frequencies(frame: pd.DataFrame, code_column: str = 'qa_code') -> list[dict]:
    """Frequency table for one coding column; refuse by name when it is absent.

    A ``report`` node pointed at a raw table (no coding pass upstream) used to fall through to a
    pandas ``KeyError``. That is an unexplained node failure; the caller must be told that the
    column is produced by a coding node. Blank-string cells are excluded from BOTH the counts and
    the denominator, so percentages always sum to 100 over coded rows.
    """
    if code_column not in frame.columns:
        raise ContentAnalysisError(t('quant.report_needs_coding', col=code_column))
    coded = (
        frame[code_column]
        .astype('object')
        .map(lambda value: None if pd.isna(value) or not str(value).strip() else str(value))
    )
    counts = coded.dropna().value_counts()
    total = int(counts.sum())
    return [
        {'code': str(code), 'n': int(count), 'pct': round(100.0 * int(count) / max(1, total), 2)}
        for code, count in counts.items()
    ]
