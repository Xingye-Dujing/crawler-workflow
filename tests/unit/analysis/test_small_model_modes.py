"""The new model-backed process modes keep the existing output contracts.

The heavy pipelines are replaced with deterministic fakes; these tests pin the mapping, the offsets
and the refusal behaviour, not a particular checkpoint's numbers.
"""

import sys
import types

import pandas as pd
import pytest

from analyzers import NamedEntityRecognizer, zero_shot
from services.analysis.process import OUTPUT_ADD_COLUMNS, PROCESS_OPS, READ_PARAMS

pytestmark = pytest.mark.unit


def test_process_registry_declares_both_new_ops():
    assert {'zero_shot'} <= PROCESS_OPS
    assert 'zero_shot' in OUTPUT_ADD_COLUMNS
    assert READ_PARAMS['zero_shot'] == ('text_column',)


def test_ner_bert_mode_keeps_the_five_column_contract(monkeypatch):
    fake = types.ModuleType('transformers')
    fake.pipeline = lambda *args, **kwargs: (
        lambda texts: [
            [{'entity_group': 'PER', 'start': 0, 'end': 2, 'word': '张伟'}]
            if '张伟' in text
            else [{'entity_group': 'ORG', 'start': 0, 'end': 3, 'word': '新华社'}]
            for text in texts
        ]
    )
    monkeypatch.setitem(sys.modules, 'transformers', fake)
    monkeypatch.setattr('analyzers.sentiment.resolve_bert_model', lambda name: '/models/ner')

    frame = pd.DataFrame({'正文': ['张伟在新华社工作', '没有实体']})
    result = NamedEntityRecognizer(mode='bert', model_name='/models/ner').analyze_dataframe(frame, '正文')
    assert list(result.columns) == ['row', 'text', 'label', 'start', 'end']
    assert result['label'].tolist() == ['PERSON', 'ORG'] or set(result['label']) <= {'PERSON', 'ORG'}
    for _, row in result.iterrows():
        assert str(frame.at[row['row'], '正文'])[row['start'] : row['end']] == row['text']


def test_ner_bert_mode_refuses_an_empty_model(monkeypatch):
    monkeypatch.setattr('analyzers.sentiment.resolve_bert_model', lambda name: '')
    with pytest.raises(ValueError, match='模型名为空|no model name'):
        NamedEntityRecognizer(mode='bert', model_name='').analyze_dataframe(pd.DataFrame({'正文': ['x']}), '正文')


def test_zero_shot_adds_label_and_score_columns(monkeypatch):
    monkeypatch.setattr(
        zero_shot,
        '_pipeline',
        lambda name: (
            lambda texts, candidate_labels, multi_label: [
                {'labels': ['质疑', '正面'], 'scores': [0.8, 0.2]} for _ in texts
            ]
        ),
    )
    frame = pd.DataFrame({'正文': ['这是真的吗', '很好']})
    result = zero_shot.analyze_zero_shot(frame, '正文', labels='正面,质疑')
    assert result['zero_shot_label'].tolist() == ['质疑', '质疑']
    assert result['zero_shot_score'].tolist() == [0.8, 0.8]
    assert '正文' in result.columns


def test_zero_shot_refuses_an_empty_label_set():
    with pytest.raises(zero_shot.ZeroShotError, match='labels|标签'):
        zero_shot.analyze_zero_shot(pd.DataFrame({'正文': ['x']}), '正文', labels='')
