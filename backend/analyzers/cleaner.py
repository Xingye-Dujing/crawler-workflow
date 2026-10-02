import logging
import re

import pandas as pd

from analyzers.llm_client import run_llm_dataframe
from i18n import t

logger = logging.getLogger(__name__)


class ContentCleaner:
    """Data cleaning service - filters ads, irrelevant content, and artifacts
    using an LLM (local Ollama or an OpenRouter API model).

    Two modes. ``llm`` reads one comment at a time and judges both artifacts and
    relevance; ``regex`` washes the artifacts a repost leaves behind for free, which is
    the only mode that is usable over a Weibo comment table of any real size on a machine
    without a GPU. The two share the output contract (``action`` + ``cleaned_text``) so
    everything downstream reads either one without knowing which ran.
    """

    def __init__(self, model_name: str = 'qwen3.5:9b'):
        # Only the llm mode reads this; the regex mode constructs no client and pays for
        # no model file, which is the whole point of having it.
        self.model_name = model_name

    # ─── Weibo artifacts ───
    # Compiled once at class level: these run per row over tables that can hold hundreds of
    # thousands of comments, and re-compiling a dozen patterns per row is pure waste.
    #
    # A 转发 (repost) stores the whole chain in one string, and the REPOSTER'S OWN words
    # come FIRST: `我也觉得//@A:原文//@B:...`. Everything from the first `//@name:` onward
    # belongs to somebody else, so dropping that tail is not cosmetic — leaving it in makes
    # a sentiment node judge whoever was quoted and a keyword node count their words.
    _FORWARD_PAT = re.compile(r'//\s*@\S{1,30}?\s*[:：]')
    _REPLY_PAT = re.compile(r'回复\s*@\S{1,30}?\s*[:：]')
    _MENTION_PAT = re.compile(r'@[A-Za-z0-9_\-\u4e00-\u9fa5]{1,30}')
    # The topic words are kept and only the `#` markers go: 话题 is often the most useful
    # token in the comment, and a keyword node should see it.
    _TOPIC_PAT = re.compile(r'#([^#\n]{1,40})#')
    # URLs in every shape the crawlers actually emit, including the sites' own link text.
    _URL_PAT = re.compile(r'https?://\S+|www\.\S+')
    _PLACEHOLDER_PAT = re.compile(r'O?网页链接|L微博视频|微博视频|查看图片')
    # The 展开/收起 control, whose text the card carries inside the body node.
    #
    # Two measured facts shape this pattern, and the first one is why the old spelling
    # missed most of the corpus: weibo appends ONE ASCII letter to the word, and it is not
    # always 'c' — a real 10k-row export measured '收起d' on 23–29% of its rows while the
    # pattern hard-coded 'c'. The second is that the site writes 「展开全文」, and the old
    # standalone '全文' alternative merely ate that tail and left a bare 「展开」 behind —
    # a leftover that reads like a word, which is worse than not matching at all.
    #
    # The trailing boundary is what keeps prose: 「请展开说说」 and 「展开讨论」 are text, not
    # controls, so the marker only goes where a sentence cannot follow it. Same distinction
    # `engine/times.py` makes for relative labels — recognise the shape, never the bare word.
    _EXPAND_PAT = re.compile(r'(?:展开|收起)(?:全文|[A-Za-z])?(?=$|[\s，。！？、,.!?;；:：~～|])')
    # 表情代码. Dropped from the washed text because `[笑cry]` tokenises into keyword noise;
    # the raw column keeps them, so a sentiment node can still read the emoji signal.
    _EMOJI_PAT = re.compile(r'\[[^\[\]\n]{1,10}\]')
    _CONTACT_PAT = re.compile(r'(?:[Vv]信|微信|QQ|qq|扣扣)\s*[:：]?\s*[A-Za-z0-9_\-]{4,20}|[1-9]\d{4,11}')
    _ZERO_WIDTH_PAT = re.compile(r'[\u200b-\u200f\u2028\u2029\u2060\ufeff]')
    # 哈哈哈哈哈哈 → 哈哈. Three or more identical characters in a row carry no more meaning
    # than two, and a run of them is exactly what a 水军 copies to look busy.
    _REPEAT_PAT = re.compile(r'(.)\1{2,}')
    _SPACE_PAT = re.compile(r'\s+')

    #: Shorter than this after washing is not a review of anything. Counted in characters
    #: and deliberately low: a real Weibo comment can be 「绝了」 and still be an opinion.
    MIN_KEPT_CHARS = 2

    @classmethod
    def wash_text(cls, text: str) -> str:
        """One comment with its artifacts taken out, or ``''`` when nothing survives.

        Order matters, not cosmetically: the 转发链 is cut BEFORE the bare @提及, because the
        chain's own `@name:` is what says where the quoted text starts — strip mentions
        first and the quoted text is stranded with nothing marking where it began.

        The HEAD of a forward chain is kept, never the tail: Weibo puts the reposter's own
        words first (`我也觉得//@A:原文`), so the tail is somebody else's text. A row that is
        nothing but a chain has no head at all, and is an artifact rather than a comment.
        """
        if not text:
            return ''
        out = cls._ZERO_WIDTH_PAT.sub('', str(text))
        out = cls._URL_PAT.sub(' ', out)
        out = cls._PLACEHOLDER_PAT.sub(' ', out)
        out = cls._EXPAND_PAT.sub(' ', out)
        out = cls._REPLY_PAT.sub(' ', out)
        out = cls._FORWARD_PAT.sub('\n', out)
        out = out.split('\n', 1)[0]
        out = cls._MENTION_PAT.sub(' ', out)
        out = cls._TOPIC_PAT.sub(r'\1', out)
        out = cls._EMOJI_PAT.sub(' ', out)
        out = cls._CONTACT_PAT.sub(' ', out)
        out = cls._REPEAT_PAT.sub(r'\1\1', out)
        out = cls._SPACE_PAT.sub(' ', out).strip()
        # Punctuation-only leftovers: `[泪][泪]` becomes spaces and then nothing, and a row
        # like that is an artifact, not a comment with an opinion in it.
        if not any(ch.isalnum() for ch in out):
            return ''
        return out if len(out) >= cls.MIN_KEPT_CHARS else ''

    def clean_dataframe_regex(self, df: pd.DataFrame, text_column: str = '正文') -> pd.DataFrame:
        """Wash a text column with :meth:`wash_text`, keeping the app's column contract.

        What this DOES: removes the shapes a repost leaves behind, and settles a row that
        was nothing but those shapes as 删除 — the same two answers the model path gives.

        What this deliberately does NOT do: judge whether a comment is about the user's
        topic. That needs the reading the ``llm`` mode pays for, and a keyword list standing
        in for it would be a guess wearing a verdict's clothes. The 主题 box is therefore
        ignored here, and the console says so by naming the mode that ran.

        The source column keeps its text — the washed version is written to
        ``cleaned_text`` beside it, exactly as the model path writes it — so nothing is
        destroyed and a downstream node may read either column.
        """
        df['action'] = ''
        df['cleaned_text'] = None
        if text_column not in df.columns:
            logger.error(t('ml.missing_col', col=text_column))
            return df
        kept = 0
        seen = 0
        for idx, raw in df[text_column].items():
            if pd.isna(raw) or not str(raw).strip():
                continue
            seen += 1
            cleaned = self.wash_text(str(raw))
            if cleaned:
                df.at[idx, 'action'] = '保留'
                df.at[idx, 'cleaned_text'] = cleaned
                kept += 1
            else:
                df.at[idx, 'action'] = '删除'
        logger.info(t('clean.regex_done', kept=kept, dropped=seen - kept))
        return df

    def clean_dataframe(
        self,
        df: pd.DataFrame,
        text_column: str = '正文',
        topic: str = '',
        ctx: dict = None,
        mode: str = 'llm',
    ) -> pd.DataFrame:
        """Clean the dataframe row by row, in the mode the node asked for.

        ``llm`` — one message per row with the shared batching / checkpoint / abort
        semantics of ``run_llm_dataframe``. ``ctx`` (built by app.py from the AI settings
        panel) selects the transport and carries the batch size, the partial-result
        publisher and the cancel event; without it the run uses the local Ollama default.

        ``regex`` — no model, no context, no topic: see :meth:`clean_dataframe_regex`.

        Named one at a time, never branched on "not this one": ``mode='Regex'`` reaching an
        ``else`` branch is how a node silently runs an algorithm nobody chose (and how the
        keyword node once stamped TextRank's output with the name TF-IDF).
        """
        if mode == 'regex':
            return self.clean_dataframe_regex(df, text_column)
        if mode != 'llm':
            raise ValueError(t('clean.unknown_mode', mode=mode))
        return run_llm_dataframe(
            df,
            text_column,
            op='clean',
            result_columns=['action', 'cleaned_text'],
            blank=['', None],
            fail_value=('删除', None),
            build_prompt=lambda text: self.build_prompt(text, topic),
            # The lambda only forwards; the version that invalidates the cache is
            # the real template method, whose source a wording edit changes.
            prompt_template=self.build_prompt,
            parse=self.parse_model_output,
            ctx=ctx,
            label=t('label.clean'),
            default_model=self.model_name,
            extra_key=topic or '',
        )

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
