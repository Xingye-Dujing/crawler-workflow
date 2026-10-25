"""Spectral clustering and cluster labels for the bibliometric graph.

CiteSpace's cluster view is a spectral partition labelled by terms from the
cluster's own documents. The partition here is computed from the normalized
Laplacian directly (no sklearn ``SpectralClustering`` on a disconnected graph,
which warns and can return a component split nobody asked for). Labels support
LLR / LSI / MI / TF-IDF; every choice is explicit and the chosen method is
reported by the caller.
"""

import math
from collections import Counter
from typing import TYPE_CHECKING

import networkx as nx
import numpy as np

from i18n import t

# sklearn is imported inside the three functions that cluster or label (``_tfidf_matrix``,
# ``_label_cluster``, ``cluster_graph``): this module is reachable from ``app``'s import, and
# loading all of sklearn to boot costs seconds even when no canvas asks for clustering.
# networkx stays top-level because ``nx.Graph`` is evaluated in signatures at def time.
if TYPE_CHECKING:
    # Only the return annotation of ``_tfidf_matrix`` names this class, and a quoted forward
    # reference has to resolve somewhere for the reader (and ruff) to trust it.
    from sklearn.feature_extraction.text import TfidfVectorizer

SEED = 42
MAX_AUTO_K = 10
#: Dense eigendecomposition is O(n^3); a graph this large is refused by name
#: rather than hanging a run. Narrow TopN / the time range, or turn clustering off.
MAX_CLUSTER_NODES = 2000


def _relabel(labels: np.ndarray, names: list[str]) -> tuple[np.ndarray, list[list[str]]]:
    """Number clusters by size (0 = largest), with a stable tie-break.

    Cluster IDs are storage-facing (the node table and every chart use them),
    so an arbitrary KMeans label would make two identical runs look different.
    """
    groups: dict[int, list[str]] = {}
    for name, label in zip(names, labels.tolist(), strict=True):
        groups.setdefault(int(label), []).append(name)
    ordered = sorted(groups.items(), key=lambda item: (-len(item[1]), min(item[1])))
    mapping = {old: new for new, (old, _) in enumerate(ordered)}
    relabelled = np.array([mapping[int(label)] for label in labels], dtype=int)
    members = [sorted(group) for _, group in ordered]
    return relabelled, members


def _choose_k(eigenvalues: np.ndarray, n: int) -> int:
    """The largest eigengap in the first few normalized-Laplacian eigenvalues."""
    upper = min(MAX_AUTO_K, n - 1)
    if upper < 2:
        return 1
    gaps = [float(eigenvalues[k] - eigenvalues[k - 1]) for k in range(2, upper + 1)]
    if not gaps:
        return 1
    return 2 + int(np.argmax(gaps))


def _embedding(graph: nx.Graph, names: list[str], k: int) -> np.ndarray:
    index = {name: i for i, name in enumerate(names)}
    matrix = np.zeros((len(names), len(names)), dtype=float)
    for source, target, data in graph.edges(data=True):
        if source not in index or target not in index:
            continue
        weight = float(data.get('weight') or 1.0)
        i, j = index[source], index[target]
        matrix[i, j] += weight
        matrix[j, i] += weight
    degree = matrix.sum(axis=1)
    inv = np.zeros_like(degree)
    inv[degree > 0] = 1.0 / np.sqrt(degree[degree > 0])
    laplacian = np.eye(len(names)) - (inv[:, None] * matrix * inv[None, :])
    values, vectors = np.linalg.eigh(laplacian)
    order = np.argsort(values)
    vectors = vectors[:, order]
    if k <= 1:
        return vectors[:, :1]
    embedding = vectors[:, :k].copy()
    norms = np.linalg.norm(embedding, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return embedding / norms


def _llr_scores(cluster_docs: list[int], other_docs: list[int], doc_terms: list[list[str]]) -> dict[str, float]:
    cluster_counts: Counter = Counter()
    other_counts: Counter = Counter()
    for doc in cluster_docs:
        cluster_counts.update(doc_terms[doc] if doc < len(doc_terms) else [])
    for doc in other_docs:
        other_counts.update(doc_terms[doc] if doc < len(doc_terms) else [])
    total_cluster = sum(cluster_counts.values())
    total_other = sum(other_counts.values())
    total = total_cluster + total_other
    if total == 0:
        return {}
    scores = {}
    for term in set(cluster_counts) | set(other_counts):
        a = cluster_counts.get(term, 0)
        b = other_counts.get(term, 0)
        if a == 0:
            continue
        expected_cluster = total_cluster * (a + b) / total
        expected_other = total_other * (a + b) / total
        score = 0.0
        if a > 0 and expected_cluster > 0:
            score += a * math.log(a / expected_cluster)
        if b > 0 and expected_other > 0:
            score += b * math.log(b / expected_other)
        scores[term] = 2.0 * score
    return scores


def _tfidf_matrix(doc_terms: list[list[str]]) -> tuple['TfidfVectorizer', np.ndarray] | None:
    from sklearn.feature_extraction.text import TfidfVectorizer

    documents = [' '.join(terms) for terms in doc_terms]
    if not any(document.strip() for document in documents):
        return None
    vectorizer = TfidfVectorizer(tokenizer=str.split, preprocessor=None, token_pattern=None, lowercase=False)
    try:
        matrix = vectorizer.fit_transform(documents)
    except ValueError:
        return None
    return vectorizer, matrix


def _label_cluster(
    members: list[str],
    docs: set[int],
    other_docs: set[int],
    doc_terms: list[list[str]],
    method: str,
    top_terms: int,
) -> tuple[str, str]:
    """The label AND the method that actually produced it.

    A table with no title/abstract/keywords cannot feed TF-IDF or LSI. The
    cluster still needs a label, so member names are used — but the summary
    reports ``members``, never the method the user picked. The caller prints
    that fallback; a label that pretends to be LLR is the silent degradation
    this project forbids.
    """
    from sklearn.decomposition import TruncatedSVD

    cluster_docs = sorted(docs)
    rest = sorted(other_docs)
    terms: list[str] = []
    used = method
    if method == 'llr':
        scores = _llr_scores(cluster_docs, rest, doc_terms)
        terms = [term for term, _ in sorted(scores.items(), key=lambda item: (-item[1], item[0]))]
    elif method in ('tfidf', 'lsi'):
        pair = _tfidf_matrix(doc_terms)
        if pair is not None:
            vectorizer, matrix = pair
            names = np.array(vectorizer.get_feature_names_out())
            if method == 'tfidf':
                weights = np.asarray(matrix[cluster_docs].sum(axis=0)).ravel() if cluster_docs else np.zeros(len(names))
            else:
                components = max(2, min(5, min(matrix.shape) - 1)) if min(matrix.shape) > 1 else 1
                try:
                    svd = TruncatedSVD(n_components=components, random_state=SEED)
                    svd.fit(matrix)
                    weights = np.abs(svd.components_[0])
                except ValueError:
                    weights = np.asarray(matrix.sum(axis=0)).ravel()
                    used = 'tfidf'
            order = np.argsort(-weights)
            terms = [str(names[i]) for i in order if weights[i] > 0]
    elif method == 'mi':
        # Presence of a term across clusters. A term that appears in every
        # cluster has zero MI and cannot label one, which is the point.
        all_docs = cluster_docs + rest
        labels = [0] * len(cluster_docs) + [1] * len(rest)
        counts: Counter = Counter()
        for doc in all_docs:
            counts.update(set(doc_terms[doc] if doc < len(doc_terms) else []))
        scores = {}
        total = len(all_docs) or 1
        for term, _ in counts.items():
            present = [1 if term in set(doc_terms[doc] if doc < len(doc_terms) else []) else 0 for doc in all_docs]
            if not any(present):
                continue
            # 2x2 contingency table; no sklearn metric needed and no warning for
            # a constant vector (a term in every document scores 0).
            a = sum(1 for label, has in zip(labels, present, strict=True) if label == 0 and has)
            b = sum(1 for label, has in zip(labels, present, strict=True) if label == 1 and has)
            c = len(cluster_docs) - a
            if a == 0:
                continue
            n = total
            expected = (a + b) * (a + c) / n
            if expected <= 0:
                continue
            scores[term] = (a / n) * math.log((a * n) / ((a + b) * (a + c)) + 1e-12)
        terms = [term for term, _ in sorted(scores.items(), key=lambda item: (-item[1], item[0]))]
    if not terms:
        terms = list(members)
        used = 'members'
    return ('；'.join(terms[:top_terms]) if terms else '—'), used


def cluster_graph(
    graph: nx.Graph,
    names: list[str],
    node_docs: dict[str, set[int]],
    doc_terms: list[list[str]],
    cluster_count: int | None,
    label_method: str,
    top_terms: int,
) -> dict:
    """Partition and label. Returns per-node cluster/label/silhouette and the summary."""
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_samples

    names = sorted(names)
    n = len(names)
    if n > MAX_CLUSTER_NODES:
        raise ValueError(t('biblio.cluster_too_many', n=n, cap=MAX_CLUSTER_NODES))
    if n <= 1:
        only = names[0] if names else ''
        return {
            'members': {only: {'cluster': 0, 'cluster_label': only, 'silhouette': 0.0}},
            'summary': {'k': 1 if names else 0, 'modularity': 0.0, 'silhouette': 0.0, 'method': label_method},
            'cluster_silhouette': {0: 0.0},
            'fallback': False,
            'clusters': 1 if names else 0,
        }

    requested_k = cluster_count or _choose_k(np.sort(np.linalg.eigvalsh(_laplacian(graph, names))), n)
    k = max(1, min(requested_k, n - 1, 50))
    if k == 1:
        labels = np.zeros(n, dtype=int)
        members = [names]
        embedding = None
    else:
        embedding = _embedding(graph, names, k)
        labels = KMeans(n_clusters=k, random_state=SEED, n_init=10).fit_predict(embedding)
        labels, members = _relabel(labels, names)
        embedding = _embedding(graph, names, len(members))

    communities = {index: members[index] for index in range(len(members))}
    try:
        modularity = float(nx.community.modularity(graph, communities.values(), weight='weight'))
    except Exception:
        modularity = 0.0
    if len(members) > 1 and n > len(members) and embedding is not None:
        try:
            samples = silhouette_samples(embedding, labels, metric='cosine')
            silhouette = float(np.mean(samples))
        except (ValueError, TypeError):
            samples = np.zeros(n)
            silhouette = 0.0
    else:
        samples = np.zeros(n)
        silhouette = 0.0

    position = {name: index for index, name in enumerate(names)}
    assigned: dict[str, int] = {}
    for cluster_id, group in enumerate(members):
        for name in group:
            assigned[name] = cluster_id
    member_docs = {index: set() for index in range(len(members))}
    for name, cluster_id in assigned.items():
        member_docs[cluster_id] |= node_docs.get(name, set())
    all_docs = set().union(*member_docs.values()) if member_docs else set()

    labels_by_node = {}
    methods: set[str] = set()
    cluster_silhouette: dict[int, float] = {}
    for cluster_id, group in enumerate(members):
        docs = member_docs.get(cluster_id, set())
        other = all_docs - docs
        label, used = _label_cluster(group, docs, other, doc_terms, label_method, top_terms)
        methods.add(used)
        indices = [position[name] for name in group]
        cluster_silhouette[cluster_id] = round(float(np.mean([samples[index] for index in indices])), 4)
        for name in group:
            labels_by_node[name] = {
                'cluster': cluster_id,
                'cluster_label': label,
                'silhouette': round(float(samples[position[name]]), 4),
            }
    return {
        'members': labels_by_node,
        'summary': {
            'k': len(members),
            'modularity': round(modularity, 6),
            'silhouette': round(silhouette, 6),
            'method': ','.join(sorted(methods)) or label_method,
        },
        'cluster_silhouette': cluster_silhouette,
        'fallback': bool(methods - {label_method}),
        'clusters': len(members),
    }


def _laplacian(graph: nx.Graph, names: list[str]) -> np.ndarray:
    index = {name: i for i, name in enumerate(names)}
    matrix = np.zeros((len(names), len(names)), dtype=float)
    for source, target, data in graph.edges(data=True):
        if source not in index or target not in index:
            continue
        weight = float(data.get('weight') or 1.0)
        i, j = index[source], index[target]
        matrix[i, j] += weight
        matrix[j, i] += weight
    degree = matrix.sum(axis=1)
    inv = np.zeros_like(degree)
    inv[degree > 0] = 1.0 / np.sqrt(degree[degree > 0])
    return np.eye(len(names)) - (inv[:, None] * matrix * inv[None, :])
