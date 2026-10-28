"""The numeric machinery behind the analysis ops: tokenisation, topic fitting, stage ordering,
review facts, co-occurrence weights and forecast rows.

Moved out of ``pipeline.py`` (Stage 9) so one op module can use it without importing the service.
"""

import logging
import math
import re

import pandas as pd
from core.refs import split_names

from i18n import t
from services.analysis.kernels import UnknownOperationError, _to_datetime

logger = logging.getLogger(__name__)


# Module-level, not lambdas: sklearn's vectorisers keep the callable they were built with,
# and these two are handed to one inside ``topic_model``. They are also what makes the
# tokenisation explicit — jieba has already cut the text into space-separated tokens, so the
# vectoriser only has to split, and doing that here keeps the same convention the ML
# classifiers use (``analyzers.ml_base``).
def _split_tokens(text: str) -> list:
    return str(text).split()


def _keep_text(text: str) -> str:
    return text


def _tokenized(texts: list) -> list:
    """Cut each document with the shared stop-word rule and hand back space-joined tokens.

    This is the vocabulary the topic models are fitted on, so it is also the list of words a
    特征词 cell can contain. The rule used to be "has a letter or digit in it", which let
    自己/一直/成为/一个 into the top words of a phase — see :mod:`analyzers.stopwords` for why the
    list lives in one place.
    """
    from analyzers.stopwords import cut

    return [' '.join(cut(text)) for text in texts]


def _token_set(text: str) -> frozenset:
    """The same cut as a set, for the co-occurrence counts that must agree with the model."""
    from analyzers.stopwords import cut

    return frozenset(cut(text))


def _stage_key(value) -> str:
    """One stage cell as the name it is matched by; ``''`` for "this row got no phase"."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return ''
    return str(value).strip()


def _stage_order(df: pd.DataFrame, stage_col: str, order_col: str, op: str = 'topic_by_stage') -> list:
    """The lifecycle order of the stage names in this table, or a refusal naming the fix.

    :meth:`DataAnalysisService.bin_time` builds an ORDERED categorical, so a phase column that
    never left its own node carries the order the user typed. The moment the table crosses a
    node boundary it is rebuilt from records (``pd.DataFrame(current_input)``) and the ordering
    is gone: what remains is a column of Chinese strings whose code-point order puts 二次爆发期
    before 发酵期. Sorting by that would reprint 表 1 out of sequence and renumber every Topic
    numeral, so this asks for the order instead of guessing one.
    """
    values = df[stage_col]
    if getattr(values.dtype, 'name', '') == 'category' and values.cat.ordered:
        return [str(name) for name in values.cat.categories if str(name).strip()]
    if order_col:
        if order_col not in df.columns:
            raise UnknownOperationError(t('analysis.stage_order_col', op=op, col=order_col))
        # Two kinds of column answer this, in this order of preference. A NUMBER is the phase's
        # own position — which is exactly what :meth:`DataAnalysisService.topic_by_stage` writes
        # into ``stage_order`` so the lifecycle survives the records round trip that erases the
        # categorical. A TIME places each phase at its earliest post, which is the only way to
        # recover the order from a table that has never been modelled yet.
        ranks = pd.to_numeric(df[order_col], errors='coerce')
        if ranks.notna().any():
            return _stage_order_by_rank(values, ranks, order_col, op, 'rank')
        stamps = _to_datetime(df[order_col])
        if stamps.notna().any():
            return _stage_order_by_rank(values, stamps, order_col, op, 'time')
        raise UnknownOperationError(
            t(
                'analysis.stage_order_unparsed',
                op=op,
                col=order_col,
                stages='、'.join(key for key in dict.fromkeys(_stage_key(value) for value in values.tolist()) if key),
            )
        )
    raise UnknownOperationError(t('analysis.stage_order', op=op, col=stage_col))


def _stage_order_by_rank(values, ranks, order_col: str, op: str, kind: str) -> list:
    """Order the phase names by the earliest rank (or timestamp) any of their rows carries.

    ``kind`` only reaches the refusal: "no row of this phase has a number" and "no row of this
    phase has a date" are different mistakes to fix, and a message that says ``{col}`` without
    saying which reading of it failed sends the user to re-type a column that was right.
    """
    first_seen: dict = {}
    names: list = []
    for value, rank in zip(values.tolist(), ranks.tolist(), strict=True):
        key = _stage_key(value)
        if not key:
            continue
        if key not in names:
            names.append(key)
        if pd.notna(rank) and (key not in first_seen or rank < first_seen[key]):
            first_seen[key] = rank
    adrift = [key for key in names if key not in first_seen]
    if adrift:
        # A phase that cannot be placed on the ordering column has no position in the numbering,
        # and appending it at the end would invent one.
        raise UnknownOperationError(
            t(
                'analysis.stage_order_unranked' if kind == 'rank' else 'analysis.stage_order_unparsed',
                op=op,
                col=order_col,
                stages='、'.join(adrift),
            )
        )
    return sorted(names, key=lambda key: first_seen[key])


def _stage_topic_counts(value, stages: list) -> list:
    """Per-stage topic numbers aligned to the lifecycle order the caller resolved.

    One number applies to every stage; a list is matched position by position, because the
    study's own table runs 5/6/4/4/4. A length that does not fit is refused rather than
    truncated or padded — the position is the meaning, and a padded list would silently put
    four topics on the stage the user asked five questions about.
    """
    items = value if isinstance(value, (list, tuple)) else split_names(str(value or ''))
    picked = []
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        try:
            number = int(text)
        except (TypeError, ValueError):
            raise UnknownOperationError(t('analysis.topic_stage_number', value=text)) from None
        if number < 2:
            raise UnknownOperationError(t('analysis.topic_count', value=number))
        picked.append(number)
    if not picked:
        raise UnknownOperationError(t('analysis.need_param', op='topic_by_stage', param='topics'))
    if len(picked) == 1:
        return picked * len(stages)
    if len(picked) != len(stages):
        raise UnknownOperationError(
            t('analysis.topic_stage_counts', stages=len(stages), counts=','.join(str(n) for n in picked))
        )
    return picked


#: The separators a 特征词 cell can be written with (see :func:`_word_cells`).
_WORD_CELL_RE = re.compile(r'[、,，;；/|]+')

#: The ceiling on candidate words for :meth:`DataAnalysisService.cooccur`. A co-occurrence
#: network is complete: every candidate is compared with every other, so ``topn`` costs
#: ``topn·(topn−1)/2`` pair counters per document — 30 words is 435 pairs, 120 is 7,140, and
#: 500 would be 124,750 per post on a corpus of tens of thousands.
COOCCUR_WORD_CAP = 120


def _whole(value, op: str, param: str) -> int:
    """A count the step reads as an integer, or a named refusal.

    The panel cannot send junk here (``_optional_int`` in ``app.py`` drops an unreadable box to
    the step's default), but a hand-written workflow file and ``/api/analysis/run`` both reach
    this module directly — and ``int('abc')`` arriving at the executor is the opaque node
    failure this repo keeps converting into a sentence that names the parameter.
    """
    if isinstance(value, bool):
        raise UnknownOperationError(t('analysis.need_number', op=op, param=param, value=value))
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        raise UnknownOperationError(t('analysis.need_number', op=op, param=param, value=value)) from None
    if not math.isfinite(number):
        raise UnknownOperationError(t('analysis.need_number', op=op, param=param, value=value))
    return int(number)


def _word_cells(value) -> list:
    """One 特征词 cell as the ordered list of words it names, without repeats.

    :meth:`DataAnalysisService.topic_by_stage` writes its words joined by 、 and the keyword
    node writes them space-separated, so both spellings (plus the comma and semicolon forms a
    hand-edited CSV picks up) are read here. Order is kept because the paper's table is read
    as a *ranked* list — the first word is the one the topic is most about — and a set would
    throw that away before it reached the comparison.
    """
    words: list = []
    for token in _WORD_CELL_RE.split(str(value if value is not None else '')):
        word = token.strip()
        if word and word not in words:
            words.append(word)
    return words


def _word_weights(value) -> dict:
    """A ``word:weight`` cell as ``{word: weight}``; words without a number are dropped.

    The weights :meth:`topic_by_stage` files are the ones a distribution comparison needs, and
    a cell that parses to nothing is not a flat distribution: treating it as one would compare
    a topic nobody scored against a topic that was, and report the result as a flow. The caller
    refuses on an empty result instead.
    """
    weights: dict = {}
    for chunk in str(value if value is not None else '').split():
        word, _, raw = chunk.rpartition(':')
        if not word:
            continue
        try:
            number = float(raw)
        except ValueError:
            continue
        weights[word.strip()] = number
    return weights


def _standard_deviation(values) -> float:
    """Sample standard deviation (n−1), or 0.0 when there is nothing to spread.

    Written here rather than taken from numpy because the two callers need the SAME convention
    as each other: a band computed with n and one computed with n−1 are different widths, and a
    forecast table whose intervals came from two rules would not be one model's answer.
    """
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return (sum((float(value) - mean) ** 2 for value in values) / (len(values) - 1)) ** 0.5


def _forecast_row(stamp, actual, centre, band, horizon: int) -> dict:
    """One row of the forecast table: a past point with its fit, or a future point alone.

    A future row's ``actual`` is ``None`` and never a repeat of the last number: an export that
    fills the cell the reader is looking for would claim the period was observed.
    """
    label = stamp.strftime('%Y-%m-%d') if hasattr(stamp, 'strftime') else str(stamp)
    return {
        'period': label,
        'actual': None if actual is None else round(float(actual), 4),
        'predicted': None if centre is None else round(float(centre), 4),
        'lower': None if centre is None or band is None else round(float(centre) - float(band), 4),
        'upper': None if centre is None or band is None else round(float(centre) + float(band), 4),
        'horizon': horizon,
    }


def _prepare_topic_model(df, column, n_topics, max_features, method='lda', embedding_model=''):
    """The guards and the fit that every topic-VISUALISATION step shares.

    Refusals live here rather than in each step because the two views ask the same question of
    the same table, and a ``topic_map`` that answers "not enough texts" in different words from
    ``topic_salience`` is two bugs pretending to be one contract.
    """
    topics = int(n_topics)
    if topics < 2:
        raise UnknownOperationError(t('analysis.topic_count', value=topics))
    method = _resolve_topic_method(method)
    usable = df[df[column].notna() & (df[column].astype(str).str.strip() != '')]
    texts = [str(value) for value in usable[column].tolist()]
    if len(texts) < topics:
        raise UnknownOperationError(t('analysis.topic_rows', rows=len(texts), topics=topics))
    try:
        model, matrix, doc_topic, vocabulary = _fit_topic_model(texts, topics, max_features, method, embedding_model)
    except ValueError as e:
        raise UnknownOperationError(t('analysis.topic_features', err=e)) from e
    return texts, model, matrix, doc_topic, vocabulary


def _embed_missing_packages() -> str:
    """The optional packages the embedding topic path needs but this machine lacks, or ``''``.

    ``find_spec`` not ``import``: this decides whether to REFUSE, and importing a multi-GB torch to
    discover it is absent is exactly the cost the bert path avoids. The embedding method never
    falls back to LDA — a topic claimed from one model must not be answered by another.
    """
    from importlib.util import find_spec

    need = {'torch': 'torch', 'transformers': 'transformers', 'sentence_transformers': 'sentence-transformers'}
    return ', '.join(pip for mod, pip in need.items() if find_spec(mod) is None)


#: The encoder every embedding topic step defaults to — chosen by the bake-off
#: (``ml_train/scripts/topic_bakeoff.py``) as the fast, coherence-beating small Chinese model.
DEFAULT_EMBED_MODEL = 'BAAI/bge-small-zh-v1.5'

#: Loaded encoders, keyed by model name. One embedding run embeds once per stage AND once per
#: figure step, so without this ``bge-small-zh-v1.5`` is constructed a dozen times and reloads its
#: weights each time. Cleared between tests in ``conftest.clean_globals``, exactly like
#: ``ml_base._shared_classifiers`` — a fake installed by one case must not be reused by the next.
_EMBED_MODEL_CACHE: dict = {}


def _embed_vectors(texts, embedding_model: str) -> tuple:
    """``(vectors, model_name)`` for the embedding topic path, or a named refusal.

    Refuses BY NAME when the optional encoder stack is absent (see :func:`_embed_missing_packages`)
    and never falls back to LDA — a topic claimed from one model must not be answered by another.
    ``normalize_embeddings=True`` so KMeans' Euclidean split tracks the cosine similarity the bake-off
    scored on. Shared by EVERY embedding-capable topic step (``topic_model``'s table and the three view
    steps) so the refusal, the default model name, the weight cache and the encode call are defined once,
    not copied per op.
    """
    import numpy as np

    missing = _embed_missing_packages()
    if missing:
        raise UnknownOperationError(t('analysis.topic_embed_unavailable', packages=missing))
    model_name = (embedding_model or DEFAULT_EMBED_MODEL).strip()
    model = _EMBED_MODEL_CACHE.get(model_name)
    if model is None:
        from sentence_transformers import SentenceTransformer

        try:
            model = SentenceTransformer(model_name)
        except Exception as e:  # a model that will not load is a named failure, not an empty table
            raise UnknownOperationError(t('analysis.topic_embed_failed', model=model_name, err=e)) from e
        _EMBED_MODEL_CACHE[model_name] = model
    try:
        vectors = model.encode(texts, batch_size=64, show_progress_bar=False, normalize_embeddings=True)
    except Exception as e:  # a model that will not run is a named failure, not an empty table
        raise UnknownOperationError(t('analysis.topic_embed_failed', model=model_name, err=e)) from e
    return np.asarray(vectors), model_name


def _resolve_topic_method(method: str) -> str:
    """Turn the ``auto`` topic default into a concrete ``'lda'``/``'embedding'`` and SAY which ran.

    ``auto`` (the untouched default) picks the encoder when the optional stack imports and LDA when it
    does not — but unlike a silent fallback it logs the method that ACTUALLY ran, so an ``auto`` result
    is never mislabeled as embedding when it was really LDA. An EXPLICIT ``'embedding'`` on a machine
    without the encoder is NOT resolved here: it stays ``'embedding'`` and the embedding path refuses
    BY NAME downstream, because a model the user specifically asked for must never be substituted.
    Only ``auto`` degrades, and only with a printed line naming the resolved method.
    """
    resolved = str(method or 'lda').strip()
    if resolved != 'auto':
        return resolved
    if _embed_missing_packages():
        logger.info(t('analysis.topic_method_auto_lda'))
        return 'lda'
    logger.info(t('analysis.topic_method_auto_embedding', model=DEFAULT_EMBED_MODEL))
    return 'embedding'


def _embedding_topic_rows(texts, tokenized, topics, topn, embedding_model) -> pd.DataFrame:
    """Embed each text with a sentence model, KMeans into ``topics`` clusters, and report each
    cluster's top TF-IDF terms as ``{topic, rank, keyword, weight}`` — the SAME contract as the
    LDA table, so the keyword chart and the 概括 step read either method unchanged.

    Refuses BY NAME when the optional encoder stack is absent (see :func:`_embed_missing_packages`).
    """
    missing = _embed_missing_packages()
    if missing:
        raise UnknownOperationError(t('analysis.topic_embed_unavailable', packages=missing))

    import numpy as np
    from sklearn.cluster import KMeans
    from sklearn.feature_extraction.text import TfidfVectorizer

    vectors, model_name = _embed_vectors(texts, embedding_model)

    labels = KMeans(n_clusters=topics, random_state=42, n_init=10).fit_predict(vectors)
    tfidf = TfidfVectorizer(tokenizer=_split_tokens, preprocessor=_keep_text, token_pattern=None, max_features=4000)
    tf = tfidf.fit_transform(tokenized)
    names = tfidf.get_feature_names_out()

    rows: list = []
    lines: list = []
    empty_clusters: list[str] = []
    for cluster in range(topics):
        members = np.where(labels == cluster)[0]
        if len(members) == 0:
            # An unused topic is the MODEL's answer, not the user's mistake (the same rule
            # 分阶段 LDA files a zero-doc row for). KMeans has no centroid to describe an empty
            # cluster, so there is no row to emit — but the run must say which topic it left out
            # and that the requested count was not what came back, rather than print 「{n} 个主题」
            # over the gap it just skipped.
            empty_clusters.append(f'Topic-{cluster + 1}')
            continue
        centroid = np.asarray(tf[members].sum(axis=0)).ravel()
        best = centroid.argsort()[::-1][: max(1, topn)]
        words = [str(names[position]) for position in best]
        lines.append(f'Topic-{cluster + 1}: {" ".join(words)}')
        denom = float(centroid[best[0]]) if centroid[best[0]] > 0 else 1.0
        for rank, position in enumerate(best):
            rows.append(
                {
                    'topic': f'Topic-{cluster + 1}',
                    'rank': rank + 1,
                    'keyword': str(names[position]),
                    'weight': round(float(centroid[position]) / denom, 6),
                }
            )
    if not rows:
        raise UnknownOperationError(t('analysis.topic_rows', rows=len(texts), topics=topics))
    logger.info(t('analysis.topic_embed_done', model=model_name, n=topics, rows=len(texts)))
    for gone in empty_clusters:
        logger.warning(t('analysis.topic_empty_cluster', topic=gone, n=topics, got=topics - len(empty_clusters)))
    for line in lines:
        logger.info(line)
    return pd.DataFrame(rows, columns=['topic', 'rank', 'keyword', 'weight'])


class _EmbeddingTopicModel:
    """The small slice of an LDA model's surface the topic-VIEW steps actually read.

    ``topic_map``/``topic_salience``/``topic_by_stage`` use only ``.components_`` (the topic-word
    distribution) and ``.perplexity``. The first is answered from the embedding clustering; the second
    is an LDA quantity with no meaning here, so it reports ``nan`` rather than inventing a number the
    log line would present as comparable to LDA's. Keeping the same attribute names is what lets those
    three steps fit either method without branching any of their downstream math.
    """

    def __init__(self, components):
        self.components_ = components

    def perplexity(self, _matrix):
        return float('nan')


def _embedding_assignment(vectors, matrix, n_topics):
    """KMeans the embeddings into ``n_topics`` clusters, returned in LDA's shape.

    ``doc_topic`` is the one-hot assignment (``argmax`` gives each document's cluster, ``sum(axis=0)``
    is that cluster's document count — the map's prevalence), and ``components_`` is each cluster's
    row-summed term counts normalised to a distribution over the SAME vocabulary the LDA path vectorises
    with, so a term's overall/within frequency stays comparable between methods. Deterministic
    ``random_state``/``n_init``, matching :func:`_fit_topic_model`; an empty cluster keeps an all-zero
    row, which the caller's "unused topic" path already handles.
    """
    import numpy as np
    from sklearn.cluster import KMeans

    wanted = int(n_topics)
    labels = KMeans(n_clusters=wanted, random_state=42, n_init=10).fit_predict(vectors)
    n_terms = matrix.shape[1]
    doc_topic = np.zeros((len(labels), wanted), dtype=float)
    doc_topic[np.arange(len(labels)), labels] = 1.0
    components = np.zeros((wanted, n_terms), dtype=float)
    for cluster in range(wanted):
        members = np.where(labels == cluster)[0]
        if len(members):
            components[cluster] = np.asarray(matrix[members].sum(axis=0)).ravel()
        total = float(components[cluster].sum())
        if total > 0:
            components[cluster] /= total
    return doc_topic, components


def _fit_topic_model(texts, n_topics, max_features, method='lda', embedding_model=''):
    """Fit the topic model both topic-view steps read, with the same conventions as the table.

    Same tokenizer, same ``random_state`` and the same vectoriser as
    :meth:`DataAnalysisService.topic_model`: a term's frequency in the map, in the salience
    table and in the exported topic list has to be the same number, or the three artifacts
    describe three different models while reading like one analysis. ``method='embedding'`` swaps only
    the document→topic assignment and the topic-word distribution (KMeans on sentence vectors over the
    SAME CountVectorizer matrix) for the LDA fit; the returned bundle keeps ``(model, matrix, doc_topic,
    vocabulary)``, so ``topic_map``/``topic_salience`` fit either method unchanged.
    """
    from sklearn.decomposition import LatentDirichletAllocation
    from sklearn.feature_extraction.text import CountVectorizer

    tokenized = _tokenized(texts)
    vectorizer = CountVectorizer(
        tokenizer=_split_tokens,
        preprocessor=_keep_text,
        token_pattern=None,
        max_features=max(10, int(max_features)),
    )
    matrix = vectorizer.fit_transform(tokenized)
    vocabulary = vectorizer.get_feature_names_out()
    if str(method) == 'embedding':
        vectors, _name = _embed_vectors(texts, embedding_model)
        doc_topic, components = _embedding_assignment(vectors, matrix, int(n_topics))
        return _EmbeddingTopicModel(components), matrix, doc_topic, vocabulary
    model = LatentDirichletAllocation(n_components=int(n_topics), random_state=42, learning_method='batch')
    doc_topic = model.fit_transform(matrix)
    return model, matrix, doc_topic, vocabulary


def _kl2(p, q):
    """KL(p‖q) in bits, over the support where both carry mass (a zero is not a ratio)."""
    import numpy as np

    mask = (p > 0) & (q > 0)
    return float(np.sum(p[mask] * np.log2(p[mask] / q[mask])))


def _jsd(p, q):
    """Jensen-Shannon divergence between two vectors over the SAME vocabulary, in bits.

    Both sides are normalised here, so a caller can hand it raw counts. The vectors have to be
    aligned first: two topics from different stages each carry their own vocabulary, and
    numpy's elementwise arithmetic would either fail on the length difference or — worse,
    because it returns a number — line the two word lists up by position and call the result a
    distance. :meth:`DataAnalysisService.topic_flow` builds the union vocabulary for exactly
    this reason.
    """
    import numpy as np

    left = np.asarray(p, dtype=float)
    right = np.asarray(q, dtype=float)
    if left.sum() <= 0 or right.sum() <= 0:
        return 0.0
    left = left / left.sum()
    right = right / right.sum()
    mixture = (left + right) / 2.0
    return 0.5 * _kl2(left, mixture) + 0.5 * _kl2(right, mixture)


def _jsd_matrix(distributions):
    """Pairwise Jensen-Shannon divergence between topic-word distributions.

    Euclidean distance on the probability vectors is not what this picture needs: two topics
    that differ mostly in rare words are further apart in meaning than their raw distance
    says. The divergence is the symmetric, bounded form of the KL comparison the topic-model
    literature uses for exactly this plot (Sievert & Shirley's intertopic distance map).
    """
    import numpy as np

    rows = np.asarray(distributions, dtype=float)
    rows = rows / rows.sum(axis=1, keepdims=True)
    size = len(rows)
    out = [[0.0] * size for _ in range(size)]
    for left in range(size):
        for right in range(left + 1, size):
            out[left][right] = out[right][left] = _jsd(rows[left], rows[right])
    return out


def _mds_2d(distances):
    """Classical (Torgerson) MDS of a distance matrix, as two stable-signed columns.

    Eigendecomposition of the double-centred squared distances rather than scikit-learn's
    iterative ``MDS``: it is deterministic, and a map whose bubbles move between two runs of
    the SAME table is a figure nobody can cite. Eigenvector signs are arbitrary up to a flip,
    so each axis is turned to make its largest-magnitude coordinate positive — the layout
    then repeats byte for byte, which is what the test asserts.
    """
    import numpy as np

    matrix = np.asarray(distances, dtype=float)
    size = matrix.shape[0]
    if size < 2:
        return [[0.0, 0.0] for _ in range(size)]
    centering = np.eye(size) - np.ones((size, size)) / size
    doubled = -0.5 * (matrix**2) @ centering
    # Symmetrised before the eigensolver: floating-point drift in the product above is real,
    # and ``eigh`` on a non-symmetric input answers with numbers that mean nothing.
    gram = (doubled + doubled.T) / 2.0
    values, vectors = np.linalg.eigh(gram)
    order = np.argsort(values)[::-1][:2]
    coordinates = []
    for position in range(size):
        point = [vectors[position, axis] for axis in order]
        coordinates.append(
            [
                # The eigenvalue of the axis actually chosen (``order`` is a descending
                # permutation of an ASCENDING solver output), not of the solver's first slots:
                # indexing ``values`` by ``axis`` reads the two SMALLEST eigenvalues, which are
                # the noise floor, and silently flattens the map onto one line.
                point[axis] * float(np.sqrt(max(values[order[axis]], 0.0))) if values[order[axis]] > 0 else 0.0
                for axis in range(len(order))
            ]
        )
    for axis in range(len(order)):
        # The axis' own column, read into a list first: a ``max(key=...)`` lambda naming the loop
        # variable would capture the cell rather than its value, and the tallest row of the WRONG
        # axis would decide the sign.
        deviations = [abs(point[axis]) for point in coordinates]
        tallest = deviations.index(max(deviations))
        if coordinates[tallest][axis] < 0:
            for row in coordinates:
                row[axis] = -row[axis]
    return [list(point) + [0.0] * (2 - len(point)) for point in coordinates]


def _fallback_topic_label(weights_str, words_str, topn: int = 6) -> str:
    """A deterministic 概括 from the topic's OWN weighted words when no model answer exists.

    The weights column (``word:weight`` tokens, space-separated) is what :meth:`topic_by_stage`
    already computed; ordering it by weight and joining the top terms with '·' names the topic the
    way a reader of 表 1 would, without inventing a sentence. With no weights it falls back to the
    plain feature-word list. This never asks the model — it is a recall device, not a classifier.
    """
    parts = []
    for token in str(weights_str or '').split():
        word, _, weight = token.partition(':')
        if word:
            try:
                w = float(weight)
            except ValueError:
                w = 0.0
            parts.append((word, w))
    if parts:
        parts.sort(key=lambda item: -item[1])
        return '·'.join(word for word, _ in parts[:topn])
    words = [x.strip() for x in re.split('[、,]', str(words_str or '')) if x.strip()]
    return '·'.join(words[:topn])


def _label_from(answer) -> str:
    """The model's phrase as ONE cell: first non-empty line, decoration off, capped.

    A small local model wraps the phrase in quotes, in 【】, or prefixes it with 「概括：」 even
    when the prompt says not to. The cell goes straight into an exported table, so that is
    taken off here rather than in every reader's spreadsheet; the cap is what keeps one
    rambling answer from turning a 概括 column into a paragraph. An answer that leaves nothing
    returns ``''``, which the caller refuses instead of filing as a blank.
    """
    for line in str(answer or '').splitlines():
        phrase = line.strip().strip('"“”\'`「」 ').strip()
        for prefix in ('主题概括', '概括', 'Summary', 'summary', 'Label', 'label'):
            if phrase.startswith(prefix):
                phrase = phrase[len(prefix) :].lstrip('：: ').strip()
        phrase = phrase.strip('【】《》').strip('：:　').strip()
        # An answer with no letter, digit or ideograph in it is not a label: punctuation only
        # is what a small model returns when it has nothing to say, and filing it as a summary
        # would put 「。」 in the column the paper's findings are read from.
        if phrase and any(char.isalnum() for char in phrase):
            return phrase[:60]
    return ''


def _review_language() -> str:
    """The language the answer must be written in.

    A Chinese table read through an English prompt tends to come back in English, and the
    paragraph then has to be translated before it goes into the paper — so the run's own
    interface language is stated in the request."""
    from i18n import get_lang

    return '中文' if (get_lang() or 'zh') == 'zh' else 'English'


def _cluster_facts(
    slice_: pd.DataFrame,
    name_col: str,
    freq_col: str,
    first_col: str,
    last_col: str,
    label_col: str,
    take: int,
) -> dict:
    """What the graph already measured about one cluster, as the prompt's fact block.

    Only columns that exist contribute a line: a bibliometrics node table carries 频次/首年/末年
    and a cluster table does not, and inventing "年份跨度：未知" for a table that never had years
    would put a claim the data cannot support in front of the model."""
    names: list[str] = []
    pairs: list[tuple[str, float]] = []
    weights = slice_[freq_col].tolist() if freq_col and freq_col in slice_.columns else [0.0] * len(slice_)
    # The two lists are built from the same slice, so unequal length is a bug, not a shape.
    for value, freq in zip(slice_[name_col].tolist(), weights, strict=True):
        label = str(value or '').strip()
        if not label:
            continue
        try:
            weight = float(freq)
        except (TypeError, ValueError):
            weight = 0.0
        pairs.append((label, weight))
    pairs.sort(key=lambda item: (-item[1], item[0]))
    names = [name for name, _weight in pairs[: max(1, take)]]

    lines = [t('analysis.review_fact_size', n=len(slice_))]
    if label_col and label_col in slice_.columns:
        labels = [str(v).strip() for v in slice_[label_col].dropna().tolist() if str(v).strip()]
        if labels:
            lines.append(t('analysis.review_fact_label', label=labels[0]))
    if pairs:
        if freq_col and freq_col in slice_.columns:
            shown = '；'.join(f'{name}({weight:g})' for name, weight in pairs[: max(1, take)])
        else:
            shown = '；'.join(name for name, _weight in pairs[: max(1, take)])
        lines.append(t('analysis.review_fact_members', members=shown))
    span = _review_span(slice_, first_col, last_col)
    if span:
        lines.append(t('analysis.review_fact_span', span=span))
    return {'size': len(slice_), 'names': names, 'span': span, 'block': '\n'.join(lines)}


def _review_span(slice_: pd.DataFrame, first_col: str, last_col: str) -> str:
    years: list[int] = []
    for column in (first_col, last_col):
        if not column or column not in slice_.columns:
            continue
        for value in slice_[column].tolist():
            try:
                year = int(float(str(value).strip()))
            except (TypeError, ValueError):
                continue
            if 1000 < year < 3000:
                years.append(year)
    if not years:
        return ''
    low, high = min(years), max(years)
    return str(low) if low == high else f'{low}–{high}'


def _review_fallback(facts: dict) -> str:
    """The no-model answer: the cluster's own facts, in a sentence, with the method in it.

    AGENTS: a sanctioned degradation must PRINT the method that ran. This one also says so in
    the cell, because the table is what leaves the app — a paragraph that reads like a model
    wrote it, in a column called 簇综述, is how a fabrication reaches a footnote."""
    return t('analysis.review_fallback_text', size=facts['size'], members='；'.join(facts['names'][:6]))
