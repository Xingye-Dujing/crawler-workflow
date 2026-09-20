import logging
import re

import pandas as pd

from analyzers.llm_client import run_llm_dataframe
from i18n import t

logger = logging.getLogger(__name__)


class ContentCleaner:
    """Data cleaning service - filters ads, irrelevant content, and artifacts
    using an LLM (local Ollama or an OpenRouter API model)."""

    def __init__(self, model_name: str = 'qwen3.5:9b'):
        self.model_name = model_name

    def build_prompt(self, text: str, topic: str = '') -> str:
        """Build prompt for the LLM using the detailed template from the reference implementation."""
        topic_str = topic if topic else 'the specific topic'
        return f"""
Role: Data Cleaning & Relevance Expert (Strict Filtering)

Goal: Clean user review texts by removing artifacts, advertising content, low-quality spam, and any content
unrelated to the specific "{topic_str}". Only output valid text if it is a genuine organic comment discussing the
Target Topic. Strictly distinguish between "organic user feedback" and "noise/ads/reposts". If the text is primarily
an advertisement, contains obvious placeholders (like O网页链接), lacks substantive review value regarding the
event, or discusses completely irrelevant news topics (e.g., random finance data unrelated to the topic),
classify as [Delete].

Target Topic Definition: The primary focus for this cleaning task is content related to "{topic_str}".

Content Criteria & Definitions:
1. Irrelevant Content / General News (Action: Delete):
   - Text containing only official announcements copied verbatim with no user commentary/critique on the
     specific event's fairness or impact.
   - Financial data, commodity prices, unrelated news headlines that do not explicitly connect to the topic.
2. Advertising/Spam (Action: Delete):
   - Promotes specific products/services without relation to the topic.
   - Contains URLs, contact information (phone numbers), pricing schemes for sale.
3. Artifact Removal (Action: Clean & Keep ONLY if valid text remains):
   - Automatically filter out placeholder tags like `##`, `#...#`, `[...]` and system markers like "O网页链接",
     timestamps ("May 6"), etc., BUT ONLY IF the surrounding text still constitutes a coherent opinion on the
     Target Topic. If removal leaves only noise, mark as [Delete].
4. Valid Review (Action: Clean & Keep):
   - Contains subjective experience descriptions about the topic (good/bad points), logical reasoning about why
     something is too harsh/too lenient, clear emotional expression related to the topic.

Processing Rules:
- Relevance Principle:
   - If a user says "Look at this finance report." -> Delete (Irrelevant).
   - If a user says "This is completely unacceptable and needs to be addressed!" -> Keep (Valid opinion on
     Target Topic).
- Artifact Handling Principle: Detect strings like `##` or `O网页链接`. Remove them immediately while preserving
  the original meaning. If the text after cleaning becomes irrelevant news summary without user sentiment, mark as
  [Delete].
- Ad Detection Special Rule: Even if disguised with "user experience" wording, if the primary intent is sales
  promotion rather than feedback, classify immediately as Advertisement -> Delete.
- Empty/Irrelevant Input Principle: Text containing only symbols, random dates without narrative voice, or purely
  informational snippets lacking an opinion stance on the specific event must be deleted.

Output Format:
Strictly output ONLY a plain string (not JSON, not Markdown) with the following structure:
- If KEEP: return "KEEP: " followed by the cleaned text (after removing artifacts, preserving coherent opinion
  on the target topic).
- If DELETE: return "DELETE: null".
Do not include any additional text, code blocks, or explanations.

Input Text:
{text}

Think silently about whether this meets the Target Topic criteria, then output strictly in the required plain
string format."""

    def parse_model_output(self, content: str):
        """Parse model KEEP:/DELETE: response, returning (action, cleaned_text) or (None, None).

        action: '保留' or '删除'
        cleaned_text: cleaned text or None
        """
        content = content.strip()
        # Direct match: starts with KEEP:
        keep_match = re.match(r'^KEEP:\s*(.*)', content, re.DOTALL)
        if keep_match:
            cleaned = keep_match.group(1).strip()
            if not cleaned:
                return ('删除', None)
            return ('保留', cleaned)

        # Direct match: starts with DELETE: null
        delete_match = re.match(r'^DELETE:\s*null', content, re.DOTALL)
        if delete_match:
            return ('删除', None)

        # Fallback: search for KEEP: anywhere in text
        keep_search = re.search(r'KEEP:\s*(.*?)(?=DELETE:|$)', content, re.DOTALL)
        if keep_search:
            cleaned = keep_search.group(1).strip()
            if cleaned:
                return ('保留', cleaned)

        # Fallback: search for DELETE: null anywhere in text
        delete_search = re.search(r'DELETE:\s*null', content)
        if delete_search:
            return ('删除', None)

        return (None, None)

    def clean_dataframe(
        self,
        df: pd.DataFrame,
        text_column: str = '正文',
        topic: str = '',
        ctx: dict = None,
    ) -> pd.DataFrame:
        """Clean the dataframe row by row — one message per row — with the
        shared batching / checkpoint / abort semantics of ``run_llm_dataframe``.

        ``ctx`` (built by app.py from the AI settings panel) selects the
        transport and carries the batch size, the partial-result publisher and
        the cancel event; without it the run uses the local Ollama default.
        """
        return run_llm_dataframe(
            df,
            text_column,
            op='clean',
            result_columns=['action', 'cleaned_text'],
            blank=['', None],
            skip_value=('删除', None),
            fail_value=('删除', None),
            build_prompt=lambda text: self.build_prompt(text, topic),
            parse=self.parse_model_output,
            ctx=ctx,
            label=t('label.clean'),
            min_len=20,
            default_model=self.model_name,
            extra_key=topic or '',
        )
