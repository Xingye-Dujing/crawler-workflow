"""Regression: dual coding and codebook edits must not replay cached answers.

The prompt builder is a closure, so ``prompt_version`` cannot see the codebook or the coder. Without
an explicit cache scope, coder B replayed coder A's answers (kappa 1.0 by construction) and editing
a codebook replayed the previous version's codes. Both are correctness failures for a study.
"""

import pandas as pd
import pytest

from analyzers.quantitative import code_rows, dual_code, frequencies

pytestmark = pytest.mark.unit


class FakeClient:
    provider = 'ollama'
    model = 'fake'
    host = ''
    max_chars = 0
    label = 'fake'

    def __init__(self, answer_code=None):
        self.prompts = []
        self.answer_code = answer_code

    def truncate(self, text):
        return text

    def chat(self, prompt, max_retries=2, on_delta=None):
        self.prompts.append(prompt)
        if self.answer_code:
            code = self.answer_code
        elif 'coder A' in prompt:
            code = 'A_CODE'
        elif 'coder B' in prompt:
            code = 'B_CODE'
        else:
            code = 'NEW_CODE'
        return f'CODE: {code}\nEVIDENCE: x\nSCORE: 0.9'


BOOK_A = {'name': 'A', 'codes': [{'code': 'A_CODE', 'definition': 'a'}, {'code': 'B_CODE', 'definition': 'b'}]}
BOOK_B = {'name': 'B', 'codes': [{'code': 'NEW_CODE', 'definition': 'new'}]}


def _ctx(store):
    return {'client': FakeClient(), 'store_for_cache': store, 'node_id': 'n1'}


def test_dual_coders_are_independent(data_root):
    from services.runs.store import RunStore

    store = RunStore(str(data_root / 'dual_runs.db'))
    frame = pd.DataFrame({'正文': ['文本一', '文本二']})
    coded, reliability = dual_code(frame, '正文', BOOK_A, ctx=_ctx(store))
    assert coded['qa_code'].tolist() == ['A_CODE', 'A_CODE']
    assert coded['qa_code_b'].tolist() == ['B_CODE', 'B_CODE']
    assert coded['qa_agree'].tolist() == [False, False]
    assert reliability['kappa'] != 1.0


def test_edited_codebook_repays_answers(data_root):
    from services.runs.store import RunStore

    store = RunStore(str(data_root / 'codebook_runs.db'))
    frame = pd.DataFrame({'正文': ['文本一']})
    client = FakeClient(answer_code='A_CODE')
    ctx = {'client': client, 'store_for_cache': store, 'node_id': 'n1'}
    first = code_rows(frame.copy(), '正文', BOOK_A, ctx=ctx)
    assert first['qa_code'].tolist() == ['A_CODE']
    calls_after_a = len(client.prompts)
    client.answer_code = 'NEW_CODE'
    second = code_rows(frame.copy(), '正文', BOOK_B, ctx=ctx)
    assert len(client.prompts) > calls_after_a, 'a new codebook must call the model again'
    assert second['qa_code'].tolist() == ['NEW_CODE']


def test_report_on_raw_table_refuses_by_name():
    with pytest.raises(ValueError):
        frequencies(pd.DataFrame({'正文': ['x']}))


def test_report_percentages_ignore_blank_cells():
    frame = pd.DataFrame({'qa_code': ['A', 'A', '', None, 'B']})
    rows = frequencies(frame)
    assert {row['code'] for row in rows} == {'A', 'B'}
    assert round(sum(row['pct'] for row in rows)) == 100
