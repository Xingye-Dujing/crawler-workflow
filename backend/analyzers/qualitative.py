"""Grounded-theory coding: open, axial and selective passes.

An LLM is the right tool here because the categories EMERGE from the material; a fixed-label
classifier cannot do open coding. The passes are separate so a human can review and approve a
codebook between them. Every call goes through the run-level LLM client (local Ollama or an API
provider), so transport, model and key are the run's answer, never a second list in this module.
"""

import logging
import re

import pandas as pd

from analyzers.llm_client import LLMError, run_llm_dataframe
from i18n import t

logger = logging.getLogger(__name__)

MAX_CODES_PER_ROW = 5
LINE_RE = re.compile(r'^\s*(?:\d+[.)]\s*)?(.+?)\s*(?:[|｜\t]|::)\s*(.+?)\s*$')


class CodingError(ValueError):
    """A pass cannot run: no client, no approved codebook, or an unparseable model answer."""


def _client(ctx: dict | None):
    client = (ctx or {}).get('client')
    if client is None:
        raise CodingError(t('coding.no_client'))
    return client


# ── open coding: one pass per row, checkpointed by run_llm_dataframe ──


def build_open_prompt(text: str) -> str:
    return (
        'You are doing OPEN CODING of Chinese social-media text for a qualitative study.\n'
        'Propose short conceptual codes (2-8 characters each) that name what this text is doing. '
        'For each code, quote the exact span of the text that supports it.\n'
        f'At most {MAX_CODES_PER_ROW} codes. Output one code per line as: CODE | EVIDENCE QUOTE\n'
        'Do not explain, number the lines, or invent a quote that is not in the text.\n\n'
        f'TEXT:\n{text}\n'
    )


def parse_open(content: str):
    """One answer -> ``('code1|code2', 'quote1\\nquote2')`` or (None, None) when unreadable."""
    codes, quotes = [], []
    for line in str(content or '').splitlines():
        match = LINE_RE.match(line)
        if not match:
            continue
        code, quote = match.group(1).strip(), match.group(2).strip()
        # A quote is copied from the model answer, not verified against the source here: the row
        # text is not passed to this parser. The researcher audit step is the real guard, and the
        # trace conversation keeps the full answer so a fabricated quote can be found.
        if not code or not quote:
            continue
        if code not in codes:
            codes.append(code)
            quotes.append(quote)
        if len(codes) >= MAX_CODES_PER_ROW:
            break
    if not codes:
        return None, None
    return '|'.join(codes), '\n'.join(quotes)


def open_code(df: pd.DataFrame, text_column: str, ctx: dict | None = None) -> pd.DataFrame:
    """Attach ``open_codes`` and ``evidence`` to each row; resume-safe via the shared row runner."""
    return run_llm_dataframe(
        df,
        text_column=text_column,
        op='open_code',
        result_columns=['open_codes', 'evidence'],
        blank=['', ''],
        fail_value=('', ''),
        build_prompt=build_open_prompt,
        parse=parse_open,
        ctx=ctx,
        label=t('coding.open_label'),
    )


# ── axial coding: group the approved open codes into categories ──

AXIAL_LINE = re.compile(r'^\s*(?:\d+[.)]\s*)?(.+?)\s*[|｜]\s*(.+?)\s*[|｜]\s*(.+?)\s*(?:[|｜]\s*(.+?))?\s*$')


def build_axial_prompt(codebook: dict) -> str:
    rows = []
    for code in codebook.get('codes') or []:
        rows.append(f'- {code.get("code", "")} (n={code.get("count", 0)}): {code.get("evidence", "")[:120]}')
    return (
        'You are doing AXIAL CODING. Group the open codes below into categories and subcategories.\n'
        'Output one line per code: CATEGORY | SUBCATEGORY | CODE | RELATION (one short phrase).\n'
        'Use the existing code spelling exactly; do not invent codes. No prose.\n\n'
        'OPEN CODES:\n' + '\n'.join(rows) + '\n'
    )


def parse_axial(content: str, codebook: dict) -> dict:
    known = {str(code.get('code') or '') for code in codebook.get('codes') or []}
    categories: dict[str, dict] = {}
    for line in str(content or '').splitlines():
        match = AXIAL_LINE.match(line)
        if not match:
            continue
        category, subcategory, code, relation = (match.group(index) or '' for index in range(1, 5))
        code = code.strip()
        if code not in known:
            continue
        entry = categories.setdefault(
            category.strip(), {'name': category.strip(), 'subcategories': {}, 'relation': relation.strip()}
        )
        entry['subcategories'].setdefault(subcategory.strip(), []).append(code)
    if not categories:
        raise CodingError(t('coding.axial_unparseable'))
    result = dict(codebook)
    result['categories'] = [
        {
            'name': value['name'],
            'subcategories': [{'name': name, 'codes': codes} for name, codes in value['subcategories'].items()],
            'relation': value['relation'],
        }
        for value in categories.values()
    ]
    result['phase'] = 'axial'
    return result


def axial_code(codebook: dict, ctx: dict | None = None) -> dict:
    if not codebook.get('codes'):
        raise CodingError(t('coding.no_open_codes'))
    client = _client(ctx)
    try:
        answer = client.chat(build_axial_prompt(codebook))
    except LLMError as exc:
        raise CodingError(str(exc)) from exc
    return parse_axial(answer, codebook)


# ── selective coding: name the core category and write a memo ──


def build_selective_prompt(codebook: dict) -> str:
    rows = []
    for category in codebook.get('categories') or []:
        rows.append(f'- {category.get("name", "")}: {category.get("relation", "")}')
    return (
        'You are doing SELECTIVE CODING. Choose ONE core category that ties the categories together.\n'
        'Write a concise analytic memo (4-8 sentences) explaining the process, conditions and consequences.\n'
        'Output exactly two lines, no markdown:\n'
        'CORE: <core category>\nMEMO: <memo>\n\n'
        'CATEGORIES:\n' + '\n'.join(rows) + '\n'
    )


def parse_selective(content: str, codebook: dict) -> dict:
    text = str(content or '')
    core = re.search(r'^\s*CORE\s*[:：]\s*(.+)$', text, re.M)
    memo = re.search(r'^\s*MEMO\s*[:：]\s*([\s\S]+)$', text, re.M)
    if not core or not memo:
        raise CodingError(t('coding.selective_unparseable'))
    result = dict(codebook)
    result['core_category'] = core.group(1).strip()
    result['memo'] = memo.group(1).strip()
    result['phase'] = 'selective'
    return result


def selective_code(codebook: dict, ctx: dict | None = None) -> dict:
    if not codebook.get('categories'):
        raise CodingError(t('coding.no_axial_categories'))
    client = _client(ctx)
    try:
        answer = client.chat(build_selective_prompt(codebook))
    except LLMError as exc:
        raise CodingError(str(exc)) from exc
    return parse_selective(answer, codebook)


def aggregate_open_codes(frame: pd.DataFrame) -> list[dict]:
    """Turn the open-coding columns into a frequency-ranked candidate list with evidence."""
    counts: dict[str, dict] = {}
    for _, row in frame.iterrows():
        codes = str(row.get('open_codes') or '').split('|')
        quotes = str(row.get('evidence') or '').split('\n')
        for index, code in enumerate(codes):
            code = code.strip()
            if not code:
                continue
            entry = counts.setdefault(code, {'code': code, 'count': 0, 'evidence': ''})
            entry['count'] += 1
            if not entry['evidence'] and index < len(quotes):
                entry['evidence'] = quotes[index].strip()
    return sorted(counts.values(), key=lambda item: -item['count'])
