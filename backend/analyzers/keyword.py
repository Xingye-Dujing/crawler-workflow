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

        extract_fn = self.extract_tfidf if method == 'tfidf' else self.extract_textrank

        if merge:
            all_text = ' '.join(df[text_column].dropna().astype(str).tolist())
            keywords = extract_fn(all_text, topk=topk)
            result = pd.DataFrame(keywords)
            result.insert(0, 'method', method)
            return result

        all_rows = []
        for idx, text in df[text_column].items():
            if pd.isna(text) or not str(text).strip():
                continue
            kw_list = extract_fn(str(text), topk=topk)
            for kw in kw_list:
                kw['row'] = idx
                all_rows.append(kw)

        result = pd.DataFrame(all_rows) if all_rows else pd.DataFrame()
        return result
