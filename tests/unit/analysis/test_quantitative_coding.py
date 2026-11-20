"""Quantitative content analysis: codebook parsing, two-coder reliability and node contract."""

import pandas as pd
import pytest

from analyzers import quantitative
from services.analysis.process import OUTPUT_ADD_COLUMNS, PROCESS_ENUMS, PROCESS_OPS

pytestmark = pytest.mark.unit

BOOK = {
    'name': '舆情内容分析码本',
    'phase': 'quantitative',
    'codes': [
        {'code': '投诉', 'definition': '表达不满或要求解决', 'include': '客服、退款', 'exclude': '单纯提问'},
        {'code': '咨询', 'definition': '询问信息', 'include': '什么时候、怎么', 'exclude': '评价'},
        {'code': '好评', 'definition': '正面评价', 'include': '不错、满意', 'exclude': '投诉'},
    ],
}


def test_process_contract_declares_content_analysis():
    assert 'content_analysis' in PROCESS_OPS
    assert PROCESS_ENUMS['content_analysis']['mode'][1] == ('code', 'dual', 'report')
    assert 'content_analysis' not in OUTPUT_ADD_COLUMNS  # phase-dependent shape


def test_code_prompt_lists_every_code_and_rule():
    prompt = quantitative.build_code_prompt('文本', BOOK)
    for code in ('投诉', '咨询', '好评'):
        assert code in prompt
    assert 'EVIDENCE' in prompt and 'SCORE' in prompt


def test_parse_rejects_a_code_outside_the_codebook():
    assert quantitative.parse_code('CODE: 其他\nEVIDENCE: 任意', ['投诉', '好评'])[0] is None
    parsed = quantitative.parse_code('CODE: 投诉\nEVIDENCE: 客服不回复\nSCORE: 0.8', ['投诉'])
    assert parsed == ('投诉', '客服不回复', 0.8)


def test_kappa_is_one_when_coders_agree_and_negative_when_they_disagree():
    assert quantitative.cohen_kappa(['a', 'b', 'a'], ['a', 'b', 'a']) == 1.0
    assert quantitative.cohen_kappa(['a', 'a', 'b', 'b'], ['b', 'b', 'a', 'a']) < 0.0


def test_frequencies_counts_only_coded_rows():
    frame = pd.DataFrame({'qa_code': ['投诉', '投诉', None, '好评']})
    rows = quantitative.frequencies(frame)
    assert rows[0] == {'code': '投诉', 'n': 2, 'pct': 66.67}
    assert {row['code'] for row in rows} == {'投诉', '好评'}


def test_empty_codebook_is_refused():
    with pytest.raises(quantitative.ContentAnalysisError):
        quantitative.build_code_prompt('文本', {'codes': []})
