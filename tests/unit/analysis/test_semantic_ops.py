"""The two model-backed text steps: semantic dedupe and similarity search.

The encoder is replaced with a deterministic fake here; the tests pin the CONTRACT (columns, order,
refusals, bounded top-k), not a particular model's numbers. A real-encoder smoke test belongs to the
device tier where the small Chinese model is present.
"""

import numpy as np
import pandas as pd
import pytest

from services.analysis.contracts import STEP_PARAMS, validate_step
from services.analysis.kernels import UnknownOperationError
from services.analysis.ops import OPS

pytestmark = pytest.mark.unit

VECTORS = {
    'good phone': [1.0, 0.0],
    'good phone!': [0.99, 0.01],
    'bad service': [0.0, 1.0],
    'query': [1.0, 0.0],
}


def _fake_encode(texts, model_name='', batch_size=64):
    return np.asarray([VECTORS.get(str(text), [0.5, 0.5]) for text in texts], dtype=np.float32)


@pytest.fixture(autouse=True)
def fake_encoder(monkeypatch):
    import analyzers.backends.encoder as encoder

    monkeypatch.setattr(encoder, 'encode', _fake_encode)


def test_new_ops_are_registered_with_contracts():
    assert {'semantic_dedupe', 'similar_to'} <= set(OPS)
    assert STEP_PARAMS['semantic_dedupe']['one'] == ('column',)
    assert STEP_PARAMS['similar_to']['nonblank'] == ('query',)


def test_validate_step_refuses_a_missing_query():
    frame = pd.DataFrame({'正文': ['good phone']})
    with pytest.raises(UnknownOperationError):
        validate_step(frame, 'similar_to', {'column': '正文', 'query': ''})


def test_semantic_dedupe_keeps_the_first_of_a_near_duplicate_pair():
    frame = pd.DataFrame({'正文': ['good phone', 'good phone!', 'bad service']})
    result = OPS['semantic_dedupe'](frame, '正文', threshold=0.95)
    assert result['正文'].tolist() == ['good phone', 'bad service']


def test_semantic_dedupe_threshold_is_bounded_by_name():
    frame = pd.DataFrame({'正文': ['good phone']})
    with pytest.raises(UnknownOperationError, match='0'):
        OPS['semantic_dedupe'](frame, '正文', threshold=1.5)


def test_similar_to_returns_the_fixed_contract_in_score_order():
    frame = pd.DataFrame({'正文': ['good phone', 'bad service', 'good phone!']}, index=['a', 'b', 'c'])
    result = OPS['similar_to'](frame, '正文', query='query', top_k=2)
    assert list(result.columns) == ['rank', 'row_index', 'text', 'similarity']
    assert result['rank'].tolist() == [1, 2]
    assert result['row_index'].tolist()[0] in ('a', 'c')
    assert result['similarity'].tolist()[0] >= result['similarity'].tolist()[1]
