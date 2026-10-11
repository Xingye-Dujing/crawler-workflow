# Topic-method bake-off (2026-10) — embedding clustering vs sklearn LDA

Decision rule agreed with the user: *evaluate, then add the embedding/BERTopic-style method only if
it measurably beats LDA.* It did not. Keeping LDA as the topic engine; **no new method and no new
dependencies were added to the app.**

## Setup
- Script: `compare_topic_methods.py` (this folder). Dependency-free — only jieba / sklearn /
  transformers / torch, all already used elsewhere. **Not** sentence-transformers / umap / hdbscan /
  bertopic (this repo deliberately keeps those out; they are not installed).
- Fair scoring: both methods' groups are reduced to their top-W keywords and scored by the **same
  NPMI coherence** over the corpus document co-occurrence. Silhouette is reported for the clusters.
- Encoder used for embeddings = a *local fine-tuned classifier* (`emotion_ewect_six`, a
  chinese-roberta-wwm-ext base) mean-pooled — the best encoder available offline here.
- corpora (gitignored, on disk): `datasets/controversy_labeled.csv`, `datasets/weibo_clean_265k.csv`.
- device: cuda; `--max_length 96`; k=6, topw=6.

## Results (mean NPMI coherence; higher is better)

| corpus          | n   | k | LDA    | Embed+KMeans | silhouette | winner        |
|-----------------|-----|---|--------|--------------|------------|---------------|
| controversy     | 200 | 6 | -0.256 | -0.461       | 0.105      | LDA           |
| controversy     | 800 | 6 | -0.288 | -0.272       | 0.105      | embed (+0.016)|
| weibo_clean_265k| 800 | 6 | -0.212 | -0.333       | 0.081      | LDA           |

## Reading
- Embedding clustering is **not reliably better** (2 LDA wins, 1 near-tie embed win).
- Cluster silhouette is uniformly low (0.08–0.11): short, noisy micro-text does not separate into
  clean macro-clusters, which is exactly what LDA-style soft topic assignment handles better.
- Embedding "topics" surfaced junk tokens (`http`, `doge`, `cn`) — partly because the only local
  encoder is a task-specific classifier, not a general sentence model.

## Reproduce
```
python ml_train/scripts/compare_topic_methods.py --corpus ml_train/datasets/controversy_labeled.csv --n 800 --k 6
python ml_train/scripts/compare_topic_methods.py --corpus ml_train/datasets/weibo_clean_265k.csv --text-col text --n 800 --k 6
```

## What would change the conclusion
A genuine BERTopic (`sentence-transformers` + `umap-learn` + `hdbscan`) with a real sentence encoder
is a different proposition from the mean-pooled-classifier proxy tested above.

## UPDATE — proper encoder installed and re-tested (v2, same day)
Per the user's go-ahead, `sentence-transformers`/`hdbscan`/`umap-learn`/`bertopic` were installed and
the bake-off re-run with a REAL small Chinese sentence model (`BAAI/bge-small-zh-v1.5`), scored by
the same NPMI coherence. Script: `topic_bakeoff.py`.

| corpus | LDA | Embed+KMeans (bge-small-zh) | embed time (GPU, 800) | winner |
|---|---|---|---|---|
| controversy | -0.288 | **-0.189** | ~8s (+1.7s cluster) | embed |
| weibo_clean_265k | -0.212 | **-0.157** | ~10s (+1.8s cluster) | embed |

With a proper encoder, embedding clustering **beats LDA on coherence on both corpora** while running
in seconds — this supersedes the v1 (classifier-proxy) result. **Chosen method: sentence-transformer
embeddings (default `BAAI/bge-small-zh-v1.5`) + KMeans**, added as an opt-in topic `method` with LDA
kept as the default (back-compat). BERTopic is NOT adopted: it only adds UMAP+HDBSCAN latency over a
path that already wins, and its 0.17.x API kept rejecting the vectorizer kwarg during the sweep.
Integrating the chosen method imports `sentence-transformers` → declared in `requirements-optional.txt`
(never CI-installed); product code refuses BY NAME when it is absent and never falls back to LDA.
