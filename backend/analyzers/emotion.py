import logging
import re

import pandas as pd

from analyzers.llm_client import run_llm_dataframe
from i18n import t

logger = logging.getLogger(__name__)


class EmotionAnalyzer:
    """Sentiment analysis — three modes:

    Mode ``llm``: row-by-row classification via an LLM (local Ollama or an
    OpenRouter API model), batched and checkpointed so an interrupted run keeps
    everything it already finished.
    Mode ``ml``: batch classification via sklearn TF-IDF + LogisticRegression.
    """

    _ML_MODEL_NAME = 'emotion'

    def __init__(self, model_name: str = 'qwen3.5:9b', mode: str = 'llm'):
        self.model_name = model_name
        self.mode = mode
        self.valid_labels = ['Anger', 'Joy', 'Sadness', 'Fear', 'Neutral']
        # Lazily built: LLM mode never touches sklearn, and constructing the
        # classifier here would pull it in (and touch the model file) for
        # every run even when it is never used.
        self._ml_instance = None

    @property
    def _ml(self):
        if self._ml_instance is None:
            from analyzers.ml_base import get_classifier

            self._ml_instance = get_classifier(self._ML_MODEL_NAME)
        return self._ml_instance

    # ── LLM mode ────────────────────────────────────────────────

    def build_emotion_prompt(self, text: str) -> str:
        prompt_template = (
            """
Role: Fine-Grained Sentiment Analysis Expert (Academic Standard)

Goal: Conduct fine-grained sentiment analysis on the provided text. Strictly distinguish between "social context
implied emotion" and "actual expressed emotion in the text". Only assign corresponding labels when the text
explicitly expresses subjective pain, joy, or fear. If the text primarily states facts, explains causes, verifies
information, or objectively reports news (even if involving death), classify as [Neutral].

Emotion Categories & Definitions:
1. Anger: Expresses strong dissatisfaction, accusation, condemnation, wrath, or uses aggressive/insulting language
   against a behavior or entity (e.g., mocking the deceased).
2. Joy: Expresses happiness, excitement, satisfaction, love, or humor.
3. Sadness: Explicitly expresses mourning, grief, crying, pain of loss using vocabulary like "heartbroken",
   "tears". Note: Mere notification of death without strong subjective sorrow descriptions is not this category.
4. Fear: Expresses panic, worry, threat perception, or physiological fear reactions.
5. Neutral:
   - Objective statement of facts (news style).
   - Explanation of reasons, logical reasoning, information verification process.
   - Use of calm, rational, restrained tone even if the topic involves negative events (e.g., death), as long as
     there are no strong subjective emotion words like "sorrow" or "grief".

Processing Rules:
- Ignore artifacts: Automatically filter out `##`, `#...#` tags or placeholders; analyze only the main text semantics.
- Fact vs. Emotion Principle:
   - If a user says "Someone died." -> Neutral (stating fact).
   - If a user says "I'm very sad hearing the news..." -> Sadness (expressing subjective sorrow).
   - If a user uses rhetorical exaggeration like "The sky fell!" -> Fear/Sadness (expression of strong emotion via
     rhetoric).
- Anger Detection Special Rule: Even if no words like "angry" or "crazy" are used, if the text accuses someone of
  disrespecting a tragedy (e.g., treating death as a "joke/meme"), criticize behavior with rhetorical questioning
  ("Why do you...?") implying moral outrage, or use sarcastic tone to condemn actions related to a negative event,
  classify immediately as Anger.
- Confidence Setting:
   - High confidence for Neutral when facts are stated objectively without subjective emotion words.
   - For Anger/Joy/Sadness/Fear, only give near 1.0 if the expression is direct and strong; if there is ambiguity
     between neutral description and weak mixed emotions, lower confidence accordingly or judge based on dominant
     tone (e.g., rhetorical questioning about disrespect = high anger).

Output Format:
Strictly output ONLY a plain string (not JSON, not Markdown) with the following structure:
`Emotion: {label}, Confidence: {score}` where label is one of ['Anger','Joy','Sadness','Fear','Neutral'] and score
is a number between 0-1 (with appropriate decimals). Do not include any additional text, explanations, or code
blocks.

Input Text:
"""
            + text
            + """

Analyze strictly and output only the required plain string."""
        )
        return prompt_template

    def parse_emotion_response(self, content: str):
        content = content.strip()
        emotion_match = re.search(r'Emotion:\s*([A-Za-z]+)', content)
        confidence_match = re.search(r'Confidence:\s*([0-9.]+)', content)
        if emotion_match and confidence_match:
            label = emotion_match.group(1)
            if label in self.valid_labels:
                try:
                    score = float(confidence_match.group(1))
                    if 0 <= score <= 1:
                        return label, score
                    return label, max(0.0, min(1.0, score))
                except ValueError:
                    return None, None
        return None, None

    # ── ML mode ─────────────────────────────────────────────────

    def _ml_predict(self, texts: list[str]) -> list[tuple[str, float]]:
        return self._ml.predict(texts)

    def _train_ml(self, texts: list[str], labels: list[str]):
        self._ml.fit(texts, labels)

    # ── Main entry ──────────────────────────────────────────────

    def analyze_dataframe(
        self,
        df: pd.DataFrame,
        text_column: str = '正文',
        max_retries: int = 2,
        ctx: dict = None,
    ) -> pd.DataFrame:
        if self.mode == 'ml':
            return self._analyze_ml(df, text_column)

        return run_llm_dataframe(
            df,
            text_column,
            op='emotion',
            result_columns=['emotion', 'confidence'],
            blank=['', None],
            skip_value=('Neutral', 0.6),
            fail_value=('Neutral', 0.5),
            build_prompt=self.build_emotion_prompt,
            parse=self.parse_emotion_response,
            ctx=ctx,
            label=t('label.emotion'),
            min_len=10,
            default_model=self.model_name,
        )

    def _analyze_ml(self, df: pd.DataFrame, text_column: str) -> pd.DataFrame:
        df['emotion'] = ''
        df['confidence'] = None

        if text_column not in df.columns:
            logger.error(t('ml.missing_col', col=text_column))
            return df

        mask = df[text_column].notna() & (df[text_column].astype(str).str.strip() != '')
        process_indices = df[mask].index.tolist()
        if not process_indices:
            logger.info(t('ml.no_rows'))
            return df

        total = len(process_indices)
        texts = [str(df.at[idx, text_column]).strip() for idx in process_indices]
        try:
            predictions = self._ml_predict(texts)
        except Exception as e:
            logger.error(t('ml.emotion_failed', err=e))
            predictions = [('Neutral', 0.5)] * len(texts)
        for idx, (label, score) in zip(process_indices, predictions, strict=False):
            df.at[idx, 'emotion'] = label
            df.at[idx, 'confidence'] = score
        logger.info(t('ml.emotion_done', n=total))
        return df
