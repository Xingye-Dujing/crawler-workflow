"""An empty result still owes its readers the columns it declares.

A zero-column frame settles the node DONE and the next step then refuses with “column word /
platform missing”, which sends the user to the field picker instead of saying the corpus (or the
upstream table) produced nothing.
"""

import pandas as pd
from nodes.executors import tokenize as tokenize_node

from services.analysis.ops.compare_platform import compare_platform


def test_an_empty_tokenize_result_keeps_its_declared_columns(monkeypatch):
    monkeypatch.setattr(tokenize_node.VisualizationService, 'tokenize_frequency', lambda *a, **k: ([], []))
    frame = pd.DataFrame({'正文': ['的', '了']})
    out = tokenize_node._tokenize_dataframe(frame, {'text_column': '正文', 'output_mode': 'word_freq'})
    assert out.empty and list(out.columns) == ['word', 'frequency']


def test_an_empty_tokenize_result_honours_words_only(monkeypatch):
    monkeypatch.setattr(tokenize_node.VisualizationService, 'tokenize_frequency', lambda *a, **k: ([], []))
    frame = pd.DataFrame({'正文': ['的']})
    out = tokenize_node._tokenize_dataframe(frame, {'text_column': '正文', 'output_mode': 'words_only'})
    assert out.empty and list(out.columns) == ['word']


def test_an_empty_platform_comparison_keeps_its_declared_columns():
    out = compare_platform(
        pd.DataFrame({'platform': pd.Series(dtype=str), 'score': pd.Series(dtype=float)}), value_col='score'
    )
    assert out.empty and list(out.columns) == ['platform', 'n', 'score_mean']
