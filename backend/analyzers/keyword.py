import logging

import jieba
import jieba.analyse
import pandas as pd

from i18n import t

logger = logging.getLogger(__name__)


class KeywordExtractor:
    """Extract keywords from text columns using TF-IDF / TextRank.

    Both methods use jieba (already a project dependency) — no extra ML
    framework required.
    """

    @staticmethod
    def extract_tfidf(text: str, topk: int = 10) -> list[dict]:
        if not text or len(text.strip()) < 5:
            return []
        keywords = jieba.analyse.extract_tags(text, topK=topk, withWeight=True)
        return [{'keyword': kw, 'weight': round(w, 4)} for kw, w in keywords]

    @staticmethod
    def extract_textrank(text: str, topk: int = 10) -> list[dict]:
        if not text or len(text.strip()) < 5:
            return []
        keywords = jieba.analyse.textrank(text, topK=topk, withWeight=True)
        return [{'keyword': kw, 'weight': round(w, 4)} for kw, w in keywords]

    def analyze_dataframe(
        self,
        df: pd.DataFrame,
        text_column: str = '正文',
        method: str = 'tfidf',
        topk: int = 10,
        merge: bool = True,
    ) -> pd.DataFrame:
        if text_column not in df.columns:
            logger.error(t('analysis.col_missing', col=text_column))
            return df

        extractors = {'tfidf': self.extract_tfidf, 'textrank': self.extract_textrank}
        wanted = str(method or '').strip()
        if wanted not in extractors:
            # Was `self.extract_tfidf if method == 'tfidf' else self.extract_textrank`,
            # which answered a name it did not know with TextRank — and then wrote
            # whatever it guessed into the table's own `method` column, so the rows
            # claimed to be TF-IDF while jieba's co-occurrence graph produced them.
            # Clustering has refused its methods by name from the start; this is the
            # same contract, one level below the node check that also refuses it.
            allowed = ', '.join(extractors)
            raise ValueError(t('analysis.bad_option', op='keyword', param='method', value=wanted, allowed=allowed))
        extract_fn = extractors[wanted]

        if merge:
            all_text = ' '.join(df[text_column].dropna().astype(str).tolist())
            keywords = extract_fn(all_text, topk=topk)
            result = pd.DataFrame(keywords, columns=['keyword', 'weight'])
            # `wanted`, not `method`: the column states which algorithm produced the row,
            # and a spelling that only differed in padding must not read as a third one.
            result.insert(0, 'method', wanted)
            return result

        all_rows = []
        for idx, text in df[text_column].items():
            if pd.isna(text) or not str(text).strip():
                continue
            kw_list = extract_fn(str(text), topk=topk)
            for kw in kw_list:
                kw['row'] = idx
                kw['method'] = wanted
                all_rows.append(kw)

        # Same column set as the merged mode (plus the originating row), so a
        # downstream node can address 'keyword'/'weight' either way.
        return pd.DataFrame(all_rows, columns=['keyword', 'weight', 'row', 'method'])
