"""Topic bake-off v2 (deps now installed): LDA vs sentence-embed+KMeans vs BERTopic.

Scores all three with the SAME metric (mean NPMI coherence of each topic's top-W words over the
corpus document co-occurrence) and reports wall-clock per method, so the pick is "fast AND good",
not just good. Sentence embeddings use a real small Chinese model (default BAAI/bge-small-zh-v1.5)
via sentence-transformers; BERTopic reuses those embeddings (UMAP+HDBSCAN+c-TF-IDF) and is fed the
same jieba-tokenised documents so its keywords are comparable.

Run:  python ml_train/scripts/topic_bakeoff.py [--corpus CSV --text-col text --n 800 --k 6 \
            --emb BAAI/bge-small-zh-v1.5]
Prints a JSON summary. Downloads the sentence model on first use.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

EPS = 1e-12


def tokens(texts, jieba):
    return [' '.join(w.strip() for w in jieba.cut(str(t)) if len(w.strip()) >= 2) for t in texts]


def npmi(top_words, binary, index):
    # No document count: every p below is a mean over the binary matrix's own rows, so the
    # corpus size is already in it (and an unused parameter here would read like a normalisation
    # the formula skipped).
    idx = [index[w] for w in top_words if w in index]
    if len(idx) < 2:
        return None
    cols = binary[:, idx]
    p_single = cols.mean(axis=0)
    vals = []
    for a in range(len(idx)):
        for b in range(a + 1, len(idx)):
            p_joint = min(max(float(((cols[:, a] == 1) & (cols[:, b] == 1)).mean()), EPS), 1.0)
            vals.append(
                np.log(p_joint / (max(float(p_single[a]), EPS) * max(float(p_single[b]), EPS))) / (-np.log(p_joint))
            )
    return float(np.mean(vals)) if vals else None


def avg_coherence(groups, binary, index):
    sc = [c for c in (npmi(g, binary, index) for g in groups) if c is not None]
    return float(np.mean(sc)) if sc else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--corpus', default='ml_train/datasets/controversy_labeled.csv')
    ap.add_argument('--text-col', default='text')
    ap.add_argument('--n', type=int, default=800)
    ap.add_argument('--k', type=int, default=6)
    ap.add_argument('--topw', type=int, default=6)
    ap.add_argument('--emb', default='BAAI/bge-small-zh-v1.5')
    a = ap.parse_args()

    import jieba
    from sklearn.cluster import KMeans
    from sklearn.decomposition import LatentDirichletAllocation
    from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer

    df = pd.read_csv(Path(a.corpus))
    texts = [t for t in df[a.text_col].astype(str).tolist() if len(t.strip()) >= 6][: a.n]
    texts_tok = tokens(texts, jieba)

    cv = CountVectorizer(min_df=2, max_features=4000)
    counts = cv.fit_transform(texts_tok)
    names = cv.get_feature_names_out()
    index = {w: i for i, w in enumerate(names)}
    binary = (counts.toarray() > 0).astype(np.int8)

    out = {'corpus': a.corpus, 'n_texts': len(texts), 'k': a.k, 'emb_model': a.emb}

    # 1) LDA (the app's current method), timed.
    t0 = time.perf_counter()
    lda = LatentDirichletAllocation(n_components=a.k, random_state=0, max_iter=15, learning_method='online').fit(counts)
    out['lda_seconds'] = round(time.perf_counter() - t0, 2)
    out['lda_topics'] = int(a.k)
    out['lda_coherence'] = avg_coherence(
        [list(names[c.argsort()[::-1][: a.topw]]) for c in lda.components_], binary, index
    )

    # 2) sentence-transformer embeddings + KMeans, timed (embed time separate from cluster).
    from sentence_transformers import SentenceTransformer

    t0 = time.perf_counter()
    st = SentenceTransformer(a.emb, device='cuda')
    vectors = st.encode(texts, batch_size=64, show_progress_bar=False, normalize_embeddings=True)
    emb_seconds = round(time.perf_counter() - t0, 2)
    t0 = time.perf_counter()
    labels = KMeans(n_clusters=a.k, random_state=0, n_init=10).fit_predict(vectors)
    out['embed_seconds'] = emb_seconds
    out['embed_cluster_seconds'] = round(time.perf_counter() - t0, 2)
    tfidf = TfidfVectorizer(min_df=2, max_features=4000).fit(texts_tok)
    tf = tfidf.transform(texts_tok)
    tn = tfidf.get_feature_names_out()
    groups = []
    for c in range(a.k):
        m = np.where(labels == c)[0]
        if len(m) < 2:
            continue
        centroid = np.asarray(tf[m].sum(axis=0)).ravel()
        groups.append(list(tn[centroid.argsort()[::-1][: a.topw]]))
    out['embed_topics'] = len(groups)
    out['embed_coherence'] = avg_coherence(groups, binary, index)

    # 3) BERTopic on the SAME embeddings (UMAP+HDBSCAN+c-TF-IDF), timed.
    try:
        from bertopic import BERTopic

        t0 = time.perf_counter()
        # ``vectorizer_model`` is the keyword BERTopic takes (0.17.x); ``vectorizer=`` was never a
        # parameter of its constructor, so the call raised TypeError on every run and the except
        # below filed it as ``bertopic_error`` — the bake-off scored two methods and printed a
        # BERTopic row that had never actually been computed. An explicit CountVectorizer is also
        # how the same vocabulary floor (min_df=2, 4 000 terms) reaches c-TF-IDF: handing BERTopic
        # a vectorizer skips its English ``stop_words`` default, which is right for jieba tokens.
        topic_model = BERTopic(
            nr_topics=a.k,
            verbose=False,
            vectorizer_model=CountVectorizer(min_df=2, max_features=4000),
        )
        _docs, _topics = topic_model.fit_transform(texts_tok, embeddings=vectors)
        out['bertopic_seconds'] = round(time.perf_counter() - t0, 2)
        reps = topic_model.get_topics()
        bgroups = [list(w[: a.topw]) for t, w in reps.items() if t != -1]
        out['bertopic_topics'] = len(bgroups)
        out['bertopic_coherence'] = avg_coherence(bgroups, binary, index)
    except Exception as e:  # noqa: BLE001 - bake-off script: report, do not crash the sweep
        out['bertopic_error'] = str(e)[:200]

    ranked = sorted(
        [
            (k.replace('_coherence', ''), out.get(k))
            for k in ('lda_coherence', 'embed_coherence', 'bertopic_coherence')
            if out.get(k) is not None
        ],
        key=lambda kv: -kv[1],
    )
    out['coherence_ranking'] = ranked
    print(json.dumps(out, ensure_ascii=False))


if __name__ == '__main__':
    sys.exit(main())
