"""Quantitative content analysis: deductive coding against a fixed codebook.

Unlike grounded-theory open coding, the categories exist BEFORE the run. The researcher owns the
codebook; the LLM is a coder that must choose one defined code per row and quote the evidence. Two
independent passes give a Cohen's kappa the paper can report, and disagreements stay in the table
for adjudication instead of being silently averaged away.
"""

import logging
import re

import pandas as pd

from analyzers.llm_client import run_llm_dataframe
from i18n import t

logger = logging.getLogger(__name__)

CODE_RE = re.compile(r'^\s*CODE\s*[:：]\s*(.+?)\s*$', re.M)
EVIDENCE_RE = re.compile(r'^\s*EVIDENCE\s*[:：]\s*(.+?)\s*$', re.M)
SCORE_RE = re.compile(r'^\s*SCORE\s*[:：]\s*([0-9.]+)\s*$', re.M)


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
    """Two independent passes; the result table keeps BOTH codes and flags disagreements."""
    first = code_rows(df, text_column, codebook, ctx=ctx, coder='a')
    second = code_rows(df, text_column, codebook, ctx=ctx, coder='b')
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
    total = int(frame[code_column].notna().sum()) if code_column in frame.columns else 0
    rows = []
    for code, count in frame[code_column].value_counts().items():
        if pd.isna(code) or not str(code).strip():
            continue
        rows.append({'code': str(code), 'n': int(count), 'pct': round(100.0 * int(count) / max(1, total), 2)})
    return rows
