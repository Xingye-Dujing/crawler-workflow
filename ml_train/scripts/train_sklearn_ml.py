"""Train the sklearn classifiers the sentiment / emotion analyzers load, and MEASURE them.

This is the ml_train/ half of AGENTS.md: the labelled CSVs that produce the sklearn models live
here and are gitignored; nothing in backend/ points at this file. Run it from the backend dir so
``import analyzers`` resolves:

    cd backend && ../.venv/Scripts/python.exe ../ml_train/scripts/train_sklearn_ml.py

It trains two models against a held-out split and prints accuracy / macro-F1 / the confusion
matrix for each, then persists them through the SAME MLClassifier.fit contract the analyzer uses
(joblib-dumps {pipeline, label_map} to MODEL_DIR/<name>.pkl). A "better model" is therefore a
reported number, not a guess. tendency and aggression are deliberately NOT trained here: no
labelled corpus for their tag spaces exists yet (the user will supply data later); the analyzers
already expose an ml path (get_classifier('tendency')) so the interface is waiting for it.

Label mapping, decided with the user:
  * sentiment — two classes, neutral is left to SnowNLP's thresholding, not the ML path.
       datasets/weibo_senti_100k.csv  label 1 -> positive, 0 -> negative
       datasets/weibo_clean_265k.csv  label 0(喜悦) -> positive; 1(愤怒)/2(厌恶)/3(低落) -> negative
  * emotion   — the analyzer's five classes, from SMP2020-EWECT:
       angry->Anger happy->Joy sad->Sadness fear->Fear neutral->Neutral;  surprise is dropped
"""

import json
import os
import sys
import time

import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # ml_train
REPO = os.path.dirname(ROOT)  # repo root (holds backend/ and data/)
DATA = os.path.join(ROOT, 'datasets')
# backend/ is the project's import root (AGENTS.md: imports are top-level, e.g. `from config
# import Config`); the analyzers package is only reachable once that directory is on sys.path.
sys.path.insert(0, os.path.abspath(os.path.join(REPO, 'backend')))

from analyzers.ml_base import (  # noqa: E402 — sys.path is set up just above
    MLClassifier,
    build_tfidf_pipeline,
    get_classifier,
)

TEST_SIZE = 0.15
SEED = 42


def _load_sentiment():
    senti = pd.read_csv(os.path.join(DATA, 'weibo_senti_100k.csv'), usecols=['label', 'review'])
    texts = list(senti['review'].astype(str))
    labels = ['positive' if int(x) == 1 else 'negative' for x in senti['label']]

    clean = pd.read_csv(os.path.join(DATA, 'weibo_clean_265k.csv'), usecols=['label', 'text'])
    # 0 喜悦 -> positive; 1 愤怒 / 2 厌恶 / 3 低落 -> negative
    clean = clean[clean['label'].isin([0, 1, 2, 3])]
    texts += list(clean['text'].astype(str))
    labels += ['positive' if int(x) == 0 else 'negative' for x in clean['label']]
    return texts, labels


def _load_emotion():
    mapping = {'angry': 'Anger', 'happy': 'Joy', 'sad': 'Sadness', 'fear': 'Fear', 'neutral': 'Neutral'}
    texts, labels = [], []
    for name in ('usual_train.txt', 'virus_train.txt'):
        path = os.path.join(DATA, 'ewect_smp2020', 'train', name)
        with open(path, encoding='utf-8') as handle:
            rows = json.load(handle)
        for row in rows:
            label = mapping.get(str(row.get('label')))  # surprise -> None -> dropped
            content = str(row.get('content') or '').strip()
            if label and content:
                texts.append(content)
                labels.append(label)
    return texts, labels


def _train_and_report(model_name, texts, labels, valid_labels, pipeline=None):
    print('\n' + '=' * 72)
    print(f'{model_name}: {len(texts)} labelled rows; class balance:')
    print(pd.Series(labels).value_counts().to_string())

    tr_texts, te_texts, tr_labels, te_labels = train_test_split(
        texts, labels, test_size=TEST_SIZE, random_state=SEED, stratify=labels
    )
    start = time.time()
    # MLClassifier.fit + the shared pipeline persist MODEL_DIR/<model_name>.pkl. With no pipeline
    # the enhanced default applies (stopwords + class_weight='balanced' + sublinear TF).
    classifier = MLClassifier(model_name, pipeline=pipeline) if pipeline else get_classifier(model_name)
    classifier.fit(tr_texts, tr_labels)
    trained_seconds = time.time() - start

    predictions = classifier.predict(te_texts)
    pred_labels = [label for label, _confidence in predictions]
    got = sorted(set(labels))
    report = classification_report(te_labels, pred_labels, labels=valid_labels, digits=4, zero_division=0)
    print(f'\ntrained in {trained_seconds:.1f}s; held-out split: {len(te_texts)} rows')
    print(report)
    print('confusion matrix (rows=true, cols=pred, order=%s):' % got)
    print(confusion_matrix(te_labels, pred_labels, labels=got))
    print('accuracy=%.4f  macro-F1=%.4f' % (_acc(te_labels, pred_labels), _f1(te_labels, pred_labels, got)))


def _acc(y, yhat):
    return sum(a == b for a, b in zip(y, yhat)) / max(1, len(y))


def _f1(y, yhat, classes):
    macro = []
    for c in classes:
        tp = sum(1 for a, b in zip(y, yhat) if a == c and b == c)
        fp = sum(1 for a, b in zip(y, yhat) if a != c and b == c)
        fn = sum(1 for a, b in zip(y, yhat) if a == c and b != c)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        macro.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return sum(macro) / len(macro) if macro else 0.0


def main():
    # sentiment: word (1,3) plus a char n-gram branch (FeatureUnion) — the strongest no-
    # deep-learning features for Chinese micro-text. emotion keeps the default word pipeline
    # (a small corpus whose rare classes would only be over-fit by a 100k-char feature space).
    sentiment_pipeline = build_tfidf_pipeline(
        classifier=LogisticRegression(max_iter=3000, C=6.0, class_weight='balanced'),
        max_features=100000,
        ngram_range=(1, 3),
        char_features=True,
    )
    s_texts, s_labels = _load_sentiment()
    _train_and_report('sentiment', s_texts, s_labels, ['negative', 'positive'], pipeline=sentiment_pipeline)

    e_texts, e_labels = _load_emotion()
    _train_and_report('emotion', e_texts, e_labels, ['Anger', 'Fear', 'Joy', 'Neutral', 'Sadness'])


if __name__ == '__main__':
    main()
