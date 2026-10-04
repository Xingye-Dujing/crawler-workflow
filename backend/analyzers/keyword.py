"""Keyword extraction over a text column — jieba TF-IDF, TextRank and corpus TF-IDF.

The three methods share one output shape, because the downstream nodes address the columns
rather than the algorithm: ``keyword``, ``weight``, ``method``, plus ``row`` in the per-row
(``merge=False``) layout.

``tfidf_corpus`` exists because jieba's built-in IDF table was measured on news text: a Weibo
colloquialism is weighted by how rare it is in a newspaper, which is the opposite of how rare
it is in the table the user is analysing. That method therefore fits a ``TfidfVectorizer``
over the rows it was handed and scores against the user's own corpus.

Domain user dictionary
----------------------
jieba's own dictionary also comes from news text, so Weibo slang and 超话/明星 names are cut
into pieces. An optional dictionary at ``<Config.DATA_DIR>/jieba/userdict.txt`` fixes exactly
those words. The directory is derived from ``Config.DATA_DIR`` at call time — never from this
file's own location — so ``CRAWLER_DATA_ROOT`` and the test harness's redirect both move it
and there is only one answer to "where does the domain dictionary live". The file is read once
per path (see :func:`_ensure_userdict`); a missing file is normal, not an error, and this
module never creates it.

File format: UTF-8, one entry per line, ``word [freq [tag]]`` — jieba's own ``load_userdict``
format, tags from the ICTCLAS set (``n``, ``nz``, ``nr``, ``v``, …). For example::

    绝绝子 200 nz
    超话 150 n

``allow_pos`` speaks that same tag vocabulary, as the comma/、-separated text the node panel
and ``/api/analysis/run`` store (a list is accepted too).
"""

import logging
import os
import re

import jieba
import jieba.analyse
import jieba.posseg
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

from config import Config
from i18n import t

logger = logging.getLogger(__name__)

#: The one method that scores against the user's own corpus instead of jieba's news IDF table.
CORPUS_METHOD = 'tfidf_corpus'

#: The domain dictionary's own directory inside ``Config.DATA_DIR``.
USERDICT_RELPATH = os.path.join('jieba', 'userdict.txt')


# ─── Domain user dictionary ───


#: The path already handed to ``jieba.load_userdict``. This is the guard a per-row loop needs:
#: a 5000-row table calls an extractor once per row, and re-reading the file each time would be
#: 5000 file opens for one dictionary. It records the PATH rather than a bool on purpose — the
#: test harness (and a second process) points ``Config.DATA_DIR`` at another root, and a bool
#: would make that root invisible to this module after the first root had been seen.
_loaded_userdict: str | None = None


def _ensure_userdict() -> None:
    """Load ``<Config.DATA_DIR>/jieba/userdict.txt`` once, if it is there.

    ``jieba.load_userdict`` mutates the process-wide tokenizer, so this is deliberately not
    re-run on every call; see the module-level ``_loaded_userdict`` note above.
    """
    global _loaded_userdict
    path = os.path.join(Config.DATA_DIR, USERDICT_RELPATH)
    if path == _loaded_userdict:
        return
    # Marked before the read: a missing file is an answer too, and stat-ing it per row would be
    # the same per-row cost this guard exists to remove.
    _loaded_userdict = path
    if os.path.isfile(path):
        jieba.load_userdict(path)


# ─── POS filtering ───


def _pos_tags(allow_pos: str | list | None) -> frozenset[str] | None:
    """Normalize the stored ``allow_pos`` into a tag set; ``None`` means "do not filter".

    One string (``'n,v'`` or ``'n、v'``) is the form the node panel and ``/api/analysis/run``
    send, so that is the form that matters; a list is accepted too because a saved workflow
    file may hold one. Blank — the default — returns None, which every caller reads as "leave
    jieba's own default alone" rather than as an empty filter.
    """
    if not allow_pos:
        return None
    if isinstance(allow_pos, str):
        pieces = [allow_pos]
    elif isinstance(allow_pos, (list, tuple, set, frozenset)):
        pieces = [str(item) for item in allow_pos]
    else:
        pieces = [str(allow_pos)]
    tags = {tag.strip() for piece in pieces for tag in re.split('[,、]', piece) if tag.strip()}
    return frozenset(tags) or None


def _jieba_options(pos_tags: frozenset[str] | None) -> dict:
    """Translate a normalized tag set into jieba's ``allowPOS`` keyword, or into nothing.

    Omitting the keyword on a blank filter is the whole point. jieba's two analyzers do NOT
    share a default: ``extract_tags`` allows every POS, while ``textrank`` defaults to
    ``('ns', 'n', 'vn', 'v')`` and treats an explicit empty tuple as "nothing passes", so
    passing ``allowPOS=()`` would silently make TextRank return no keyword at all.
    """
    return {'allowPOS': tuple(pos_tags)} if pos_tags else {}


# ─── Extraction ───


class KeywordExtractor:
    """Extract keywords from text columns using TF-IDF / TextRank / corpus TF-IDF.

    All three methods use jieba (already a project dependency); the corpus method adds
    scikit-learn, which the project already ships for clustering and ML.
    """

    @staticmethod
    def _tokenize(text: str, pos_tags: frozenset[str] | None) -> list[str]:
        """Split one document into candidate terms, keeping only the requested POS categories.

        The shape rule (two characters or more, some letter or digit) and the stop-word list are the
        shared ones from :mod:`analyzers.stopwords`, because this tokenizer also feeds 共词网络 —
        a graph built on 自己/一个 is a graph of grammar. Dropping the particles here is not optional:
        jieba's own stop-word list is English, and its IDF table is not consulted on this path, so
        的/了 would otherwise be the top-scoring term of every corpus.
        """
        from analyzers.stopwords import filter_tokens

        if pos_tags:
            tokens = [word.word for word in jieba.posseg.cut(text) if word.flag in pos_tags]
        else:
            tokens = list(jieba.cut(text))
        return filter_tokens(tokens)

    @staticmethod
    def extract_tfidf(text: str, topk: int = 10, allow_pos: str | list | None = '') -> list[dict]:
        if not text or len(text.strip()) < 5:
            return []
        _ensure_userdict()
        keywords = jieba.analyse.extract_tags(text, topK=topk, withWeight=True, **_jieba_options(_pos_tags(allow_pos)))
        return [{'keyword': kw, 'weight': round(w, 4)} for kw, w in keywords]

    @staticmethod
    def extract_textrank(text: str, topk: int = 10, allow_pos: str | list | None = '') -> list[dict]:
        if not text or len(text.strip()) < 5:
            return []
        _ensure_userdict()
        keywords = jieba.analyse.textrank(text, topK=topk, withWeight=True, **_jieba_options(_pos_tags(allow_pos)))
        return [{'keyword': kw, 'weight': round(w, 4)} for kw, w in keywords]

    def tfidf_corpus(
        self,
        df: pd.DataFrame,
        text_column: str = '正文',
        topk: int = 10,
        merge: bool = True,
        allow_pos: str | list | None = '',
    ) -> pd.DataFrame:
        """Score keywords against the IDF of ``df`` itself, not jieba's news corpus.

        Every non-blank row is one document: jieba tokenizes it (``allow_pos`` filters the
        tokens), a ``TfidfVectorizer`` is fitted over the tokenized rows, and the IDF therefore
        describes how rare a word is in THIS table.

        ``merge=True`` sums each term's TF-IDF across the documents and returns the top ``topk``;
        ``merge=False`` returns each row's own top ``topk`` with its ``row`` index. Both return
        the same columns as the other methods, so a downstream node cannot tell them apart.
        """
        if text_column not in df.columns:
            logger.error(t('analysis.col_missing', col=text_column))
            return df

        _ensure_userdict()
        pos_tags = _pos_tags(allow_pos)
        documents = [(idx, str(text)) for idx, text in df[text_column].items() if pd.notna(text) and str(text).strip()]
        tokenized = [self._tokenize(text, pos_tags) for _, text in documents]

        # sklearn raises "empty vocabulary" for a corpus with no token at all — which is a real
        # answer here (every row blank, or every token filtered out), not an error condition.
        # Return the method's empty table so the caller's column contract still holds.
        if not any(tokenized):
            return self._empty_result(merge)

        vectorizer = TfidfVectorizer(
            # The tokens were produced above and joined with spaces, so this tokenizer is the
            # exact inverse of that join. ``token_pattern=None`` keeps sklearn from warning that
            # its own pattern is ignored.
            tokenizer=lambda doc: doc.split(),
            preprocessor=lambda doc: doc,
            token_pattern=None,
        )
        matrix = vectorizer.fit_transform([' '.join(tokens) for tokens in tokenized])
        names = vectorizer.get_feature_names_out()

        if merge:
            # ``.tolist()[0]`` unpacks scipy's 1 x n_vocab result without densifying the whole
            # document-term matrix, which for a large Weibo table would not fit in memory.
            totals = matrix.sum(axis=0).tolist()[0]
            # Sorted on the score alone, and stable: equal scores keep the vectorizer's own
            # (alphabetical) order, so two runs of the same table give the same list.
            ranked = sorted(zip(names, totals, strict=True), key=lambda pair: -pair[1])[:topk]
            result = pd.DataFrame(
                [{'keyword': kw, 'weight': round(float(w), 4)} for kw, w in ranked],
                columns=['keyword', 'weight'],
            )
            result.insert(0, 'method', CORPUS_METHOD)
            return result

        records = []
        for position, (idx, _text) in enumerate(documents):
            row = matrix.getrow(position)
            # ``indices``/``data`` are the row's non-zero terms only, so a row is never
            # densified across the whole vocabulary.
            ranked = sorted(
                ((names[col], float(value)) for col, value in zip(row.indices, row.data, strict=True)),
                key=lambda pair: -pair[1],
            )[:topk]
            records += [
                {'keyword': kw, 'weight': round(weight, 4), 'row': idx, 'method': CORPUS_METHOD}
                for kw, weight in ranked
            ]

        # Same column set as the merged mode (plus the originating row), so a downstream node
        # can address 'keyword'/'weight' either way.
        return pd.DataFrame(records, columns=['keyword', 'weight', 'row', 'method'])

    @staticmethod
    def _empty_result(merge: bool) -> pd.DataFrame:
        """The columns this node owes its children, with no rows."""
        if merge:
            return pd.DataFrame([], columns=['method', 'keyword', 'weight'])
        return pd.DataFrame([], columns=['keyword', 'weight', 'row', 'method'])

    def analyze_dataframe(
        self,
        df: pd.DataFrame,
        text_column: str = '正文',
        method: str = 'tfidf',
        topk: int = 10,
        merge: bool = True,
        allow_pos: str | list | None = '',
    ) -> pd.DataFrame:
        if text_column not in df.columns:
            logger.error(t('analysis.col_missing', col=text_column))
            return df

        # ``tfidf_corpus`` needs the whole column (it fits an IDF over it), so it is named here
        # to keep the refusal contract in one place: every method this node knows is listed, and
        # anything else is refused by name below.
        methods = ('tfidf', 'textrank', CORPUS_METHOD)
        wanted = str(method or '').strip()
        if wanted not in methods:
            # Was `self.extract_tfidf if method == 'tfidf' else self.extract_textrank`,
            # which answered a name it did not know with TextRank — and then wrote
            # whatever it guessed into the table's own `method` column, so the rows
            # claimed to be TF-IDF while jieba's co-occurrence graph produced them.
            # Clustering has refused its methods by name from the start; this is the
            # same contract, one level below the node check that also refuses it.
            allowed = ', '.join(methods)
            raise ValueError(t('analysis.bad_option', op='keyword', param='method', value=wanted, allowed=allowed))

        if wanted == CORPUS_METHOD:
            return self.tfidf_corpus(df, text_column=text_column, topk=topk, merge=merge, allow_pos=allow_pos)

        extract_fn = self.extract_tfidf if wanted == 'tfidf' else self.extract_textrank

        if merge:
            all_text = ' '.join(df[text_column].dropna().astype(str).tolist())
            keywords = extract_fn(all_text, topk=topk, allow_pos=allow_pos)
            result = pd.DataFrame(keywords, columns=['keyword', 'weight'])
            # `wanted`, not `method`: the column states which algorithm produced the row,
            # and a spelling that only differed in padding must not read as a third one.
            result.insert(0, 'method', wanted)
            return result

        all_rows = []
        for idx, text in df[text_column].items():
            if pd.isna(text) or not str(text).strip():
                continue
            kw_list = extract_fn(str(text), topk=topk, allow_pos=allow_pos)
            for kw in kw_list:
                kw['row'] = idx
                kw['method'] = wanted
                all_rows.append(kw)

        # Same column set as the merged mode (plus the originating row), so a
        # downstream node can address 'keyword'/'weight' either way.
        return pd.DataFrame(all_rows, columns=['keyword', 'weight', 'row', 'method'])
