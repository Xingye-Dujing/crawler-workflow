import logging
import re

import pandas as pd

from analyzers.llm_client import run_llm_dataframe
from i18n import t

logger = logging.getLogger(__name__)


class TendencyAnalyzer:
    """Media tendency analysis — three paths:

    Mode ``llm``: row-by-row via an LLM (local Ollama or an OpenRouter API
    model), batched and checkpointed so an interrupted run keeps everything it
    already finished.
    Mode ``ml``: batch classification via sklearn TF-IDF + LogisticRegression.
    """

    _ML_MODEL_NAME = 'tendency'

    def __init__(self, model_name: str = 'qwen3.5:9b', mode: str = 'llm'):
        self.model_name = model_name
        self.mode = mode
        self.valid_labels = [
            'Objective Statement',
            'Praise/Affirmation',
            'Criticism/Questioning',
            'Controversy/Reflection',
            'Advocacy/Call-to-action',
            'Satire/Mockery',
        ]
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

    def build_tendency_prompt(self, text: str) -> str:
        prompt_template = (
            """
Role: Media Content Analysis Expert (Academic Standard)

Goal: Analyze the tendency of the given news report text. Strictly distinguish between "objective factual reporting"
and "subjective stance/opinion". Classify based on the dominant tone and the presence of evaluative language,
rhetorical devices, or calls to action.

Tendency Categories & Definitions:
1. Objective Statement: The text primarily states facts, presents data, describes events without explicit
   positive/negative evaluation, or uses neutral, restrained language. Even if the topic is tragic (e.g., disaster),
   if no subjective judgment is expressed, classify as Objective Statement.
2. Praise/Affirmation: The text explicitly praises, compliments, or expresses approval of a person, organization,
   policy, or event. Uses words like "successful", "great", "commendable", "breakthrough".
3. Criticism/Questioning: The text clearly criticizes, questions, or condemns actions, policies, or behaviors. Uses
   rhetorical questions, exposes flaws, or uses negative evaluative language (e.g., "failure", "irresponsible",
   "flawed").
4. Controversy/Reflection: The text discusses various viewpoints on a contentious issue, reflects on societal
   problems, raises ethical dilemmas, or presents competing narratives. It often includes phrases like
   "sparked debate", "raises questions", "critics argue", "public opinion divided". This category is for texts that
   do not take a single strong stance but rather explore the controversy.
5. Advocacy/Call-to-action: The text urges readers to take action, donate, volunteer, or pay attention to an issue.
   Includes explicit requests or persuasive language aimed at mobilizing the public.
6. Satire/Mockery: The text uses irony, sarcasm, or exaggerated humor to ridicule a subject. Often includes playful
   language, puns, or obvious overstatement.

Processing Rules:
- Ignore artifacts: Filter out `##`, `#...#` tags or placeholders; analyze only the main text semantics.
- Fact vs. Stance Principle:
   - If the text says "The government announced a new policy." -> Objective Statement (fact).
   - If it says "The new policy is a step backward." -> Criticism (evaluative).
   - If it says "Many praised the move, but others feared its impact." -> Controversy/Reflection (multiple
     perspectives).
- If the text has mixed elements, choose the most dominant tone. For example, a report that starts with facts but
  ends with a strong critical comment should be classified as Criticism.
- Confidence Setting:
   - High confidence (0.9+) for clear, unambiguous cases.
   - Lower confidence (0.6-0.8) when there is mixture or subtlety.
   - For short or vague texts, set to Objective Statement with moderate confidence (0.6).

Output Format:
Strictly output ONLY a plain string (not JSON, not Markdown) with the following structure:
`Tendency: {label}, Confidence: {score}` where label is one of ['Objective Statement','Praise/Affirmation',
'Criticism/Questioning','Controversy/Reflection','Advocacy/Call-to-action','Satire/Mockery'] and score is a number
between 0-1 (with appropriate decimals). Do not include any additional text, explanations, or code blocks.

Input Text:
"""
            + text
            + """

Analyze strictly and output only the required plain string."""
        )
        return prompt_template

    def parse_tendency_response(self, content: str):
        content = content.strip()
        confidence_match = re.search(r'Confidence:\s*([0-9.]+)', content)
        if not confidence_match:
            return None, None
        label = self._match_label(content)
        if label is None:
            return None, None
        try:
            score = float(confidence_match.group(1))
        except ValueError:
            return None, None
        return label, max(0.0, min(1.0, score))

    def _match_label(self, content: str):
        """Find the label after ``Tendency:``.

        The labels contain spaces and slashes ("Criticism/Questioning"), so the
        old regex ``(.+?)(?=,|$)`` swallowed everything to the end of the string
        whenever the model forgot the comma, and the row was then counted as a
        parse failure. Matching against the known labels is exact — and the
        longest match wins so "Advocacy/Call-to-action" is not read as a prefix
        of something shorter.
        """
        for label in sorted(self.valid_labels, key=len, reverse=True):
            if re.search(r'Tendency:\s*' + re.escape(label), content):
                return label
        return None

    # ── ML mode ─────────────────────────────────────────────────

    def _ml_predict(self, texts: list[str]) -> list[tuple[str, float]]:
        return self._ml.predict(texts)

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
            op='tendency',
            result_columns=['tendency', 'tendency_confidence'],
            blank=['', None],
            skip_value=('Objective Statement', 0.6),
            fail_value=('Objective Statement', 0.5),
            build_prompt=self.build_tendency_prompt,
            parse=self.parse_tendency_response,
            ctx=ctx,
            label=t('label.tendency'),
            min_len=10,
            default_model=self.model_name,
        )

    def _analyze_ml(self, df: pd.DataFrame, text_column: str) -> pd.DataFrame:
        if text_column not in df.columns:
            logger.error(t('ml.missing_col', col=text_column))
            return df

        df['tendency'] = ''
        df['tendency_confidence'] = None

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
            logger.error(t('ml.tendency_failed', err=e))
            predictions = [('Objective Statement', 0.5)] * len(texts)
        for idx, (label, score) in zip(process_indices, predictions, strict=False):
            df.at[idx, 'tendency'] = label
            df.at[idx, 'tendency_confidence'] = score
        logger.info(t('ml.tendency_done', n=total))
        return df
