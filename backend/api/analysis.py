"""分析 Blueprint — the ``/api/analysis/{run,train}`` cluster, split out of ``app.py``.

``run`` applies a cleaning pipeline to any resolvable table (file / node result / inline) and
stores the result; ``train`` fits a traditional ML classifier from LLM-labeled rows. The two
module constants (``_ML_MODEL_TYPES`` / ``_ML_LABEL_COLUMNS``) pin the trainable model names and
their label columns and are read by the frontend-contract test, so they move with the cluster.
Deps are all cycle-free (``api.resolution``/``stores``/``services.data_analysis``/``analyzers``/
``api.http``/``utils.helpers``/``i18n``); the handlers themselves have no monkeypatch seam.
"""

from flask import Blueprint, jsonify
from stores import _register_dataset

from analyzers import (
    EmotionAnalyzer,
    SentimentAnalyzer,
    TendencyAnalyzer,
    build_training_data,
    get_classifier,
)
from api.http import _bad_body, _json_body
from api.resolution import _resolve_payload_dataframe
from i18n import t
from services.data_analysis import DataAnalysisService
from services.dataset_store import SOURCE_ANALYSIS
from utils.helpers import json_safe_records as _json_safe_records

bp = Blueprint('analysis', __name__)

#: The classifiers ``/api/analysis/train`` may fit — derived from the analyzers that
#: consume them so a train name can never drift from what ``mode='ml'`` loads. Each
#: maps to ``data/models/<name>.pkl``, so an un-listed value was a filesystem write
#: (and a later ``joblib.load``) under an attacker-chosen path, not a choice to guess.
_ML_MODEL_TYPES = (
    EmotionAnalyzer._ML_MODEL_NAME,
    TendencyAnalyzer._ML_MODEL_NAME,
    SentimentAnalyzer._ML_MODEL_NAME,
)

#: The column each classifier's own operation writes its labels into, so training from
#: 「这一列就是答案」 does not have to be spelled out at every call site — and a fourth
#: model type added without a row here answers the first model's column, which the
#: frontend would then have to be trusted not to be wrong about.
_ML_LABEL_COLUMNS = {'emotion': 'emotion', 'tendency': 'tendency', 'sentiment': 'sentiment'}


@bp.route('/api/analysis/run', methods=['POST'])
def run_analysis():
    """Run a cleaning pipeline against a dataset (uploaded, pasted, or a
    workflow node's result) without needing to execute a full workflow."""
    data = _json_body()
    if data is None:
        return _bad_body()
    df, error = _resolve_payload_dataframe(data)
    if error is not None:
        return error

    steps = data.get('steps', [])
    # run_pipeline walks the list and calls ``step.get('op')`` on every element,
    # so a string ("abc" → its characters) or a list holding a bare number is an
    # AttributeError that no ValueError/TypeError wrapper can catch. Shape first,
    # with the reason, because "steps" is the one field the caller cannot guess.
    if not isinstance(steps, list) or any(not isinstance(step, dict) for step in steps):
        return jsonify({'ok': False, 'error': t('api.stepsMustBeObjects')}), 400
    try:
        cleaned, report = DataAnalysisService.run_pipeline(df, steps)
    except (ValueError, TypeError) as e:
        # UnknownOperationError (a ValueError), but also the steps whose
        # parameters only the node executor can supply — join_tables without a
        # second input reaches run_pipeline as a plain TypeError. A caller
        # error is a 400 with a reason, never an HTML 500.
        return jsonify({'ok': False, 'error': str(e)}), 400

    try:
        dataset_id = _register_dataset(cleaned, name='cleaned', source=SOURCE_ANALYSIS)
    except ValueError as e:
        return jsonify({'ok': False, 'error': t('api.datasetTooBig', err=e)}), 400
    return jsonify(
        {
            'ok': True,
            'dataset_id': dataset_id,
            'report': report,
            'row_count': len(cleaned),
            'preview': _json_safe_records(cleaned, 10),
        }
    )


@bp.route('/api/analysis/train', methods=['POST'])
def train_ml_model():
    """Train a traditional ML classifier (emotion or tendency) from existing
    LLM-labeled data. Uses the text and label columns specified to fit a
    TF-IDF + LogisticRegression pipeline, then saves the model to disk so
    subsequent runs can use ``mode='ml'`` for fast batch inference."""
    data = _json_body()
    if data is None:
        return _bad_body()
    df, error = _resolve_payload_dataframe(data)
    if error is not None:
        return error

    model_type = data.get('model_type', 'emotion')
    if model_type not in _ML_MODEL_TYPES:
        # A name that chooses a file is refused by name, never collapsed to option #0:
        # this value became ``MODEL_DIR/<name>.pkl`` and was read back with joblib.
        return jsonify(
            {
                'ok': False,
                'error': t(
                    'analysis.bad_option',
                    op='train',
                    param='model_type',
                    value=str(model_type),
                    allowed=', '.join(_ML_MODEL_TYPES),
                ),
            }
        ), 400
    text_column = data.get('text_column', '正文')
    label_column = data.get('label_column') or _ML_LABEL_COLUMNS.get(model_type, 'emotion')

    if text_column not in df.columns:
        return jsonify({'ok': False, 'error': t('api.columnMissing', column=text_column)}), 400
    if label_column not in df.columns:
        return jsonify({'ok': False, 'error': t('api.columnMissing', column=label_column)}), 400

    texts, labels = build_training_data(df, text_column, label_column)
    if len(texts) < 10:
        return jsonify({'ok': False, 'error': t('api.needLabeledRows', n=len(texts))}), 400

    classifier = get_classifier(model_type)
    try:
        classifier.fit(texts, labels)
    except ValueError as e:
        # One distinct label (or no usable rows) is a data problem the user can
        # fix — it used to escape as an HTTP 500 from inside sklearn.
        return jsonify({'ok': False, 'error': str(e)}), 400

    unique_labels = sorted(set(labels))
    return jsonify(
        {
            'ok': True,
            'model_type': model_type,
            'trained_on': len(texts),
            'labels': unique_labels,
            'label_count': len(unique_labels),
        }
    )
