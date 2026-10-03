"""Cyberbullying-speech detection — the object the study is actually about.

The paper's subject is not sentiment but 网络暴力言论: insults, personal attacks, privacy
disclosure (人肉) and rumour-transmission. Nothing in this project measured that until now, so
the curve of "how angry" stood in for "how violent", which are different things — a crowd can be
furious and non-abusive, which is precisely the distinction the study's governance section draws.

Two modes, deliberately unequal in what they can promise:

``lexicon`` (default, no model): pattern matching over four feature families — abuse, personal
attack, privacy disclosure and rumour framing. It is a **recall device, not a classifier**: the
lists are short, they are in the repository so their incompleteness is visible, and a comment
that attacks without using any listed word is simply missed. Nothing here can measure that miss
rate, and this module does not claim one. What it can do is rank the corpus by how much
explicitly violent speech it contains, which is what the study's per-phase comparison needs.

``llm`` (opt-in): asks the model, with the same batching, checkpointing, cancellation and
``未处理`` marking as every other row-by-row analyzer here, and grades the *kind* of violence as
well as its level.
"""

import logging
import re

import pandas as pd

from analyzers.llm_client import run_llm_dataframe
from i18n import t

logger = logging.getLogger(__name__)

#: The three levels a row can come back with. ``none`` is written by the detector for a clean row
#: and is NOT the same thing as "not measured": an unmatched comment is judged, and judged clean.
LEVELS = ('none', 'mild', 'severe')

#: Scores per hit, and the thresholds that turn a score into a level. A privacy disclosure is
#: weighted above a slur on purpose: doxxing is the step that turns online abuse into real-world
#: harm, and the study treats 人肉 as the escalation point of the whole lifecycle. A single slur
#: is therefore ``mild`` (0.45), two of them or a slur plus an attack reach ``severe``, and a
#: bare rumour framing (0.2) is NOT a verdict on its own — 听说 by itself is how people gossip.
WEIGHTS = {'abuse': 0.45, 'attack': 0.3, 'privacy': 0.6, 'rumour': 0.2}
#: What each further distinct hit of the SAME family adds, and its cap: repetition is one act of
#: abuse restated, not several, but a comment that invents four new slurs is worse than one.
REPEAT_STEP = 0.1
REPEAT_CAP = 0.2
#: The second family counts at half weight, because "insulted AND doxxed" is a different act from
#: "insulted twice".
SECOND_FAMILY_SHARE = 0.5
SEVERE_AT = 0.5
MILD_AT = 0.25

# ─── the lists ─────────────────────────────────────────────────────────
#
# Kept in code, in the open, because a lexicon hidden in a data file is how an unstated recall
# rate starts looking like a measurement. These are the shapes a Chinese social comment uses;
# they will never be complete, and euphemism and homophone substitution (the watermark of abuse
# that dodges any fixed list) are exactly what the ``llm`` mode is for.
ABUSE = (
    r'傻[逼比逼叉]|滚[开蛋]?|去死|废物|垃圾|贱[人货]|狗东西|王八|畜生|婊子|荡妇|脑残|智障|弱智|神经病',
    r'死全家|断子绝孙|不得好死|早死|怎么不去死|活着浪费|去投胎',
    r'[\u4e00-\u9fa5]{0,4}玩意|不要脸|无耻|下贱|恶心透|令人作呕',
)
ATTACK = (
    r'(你|他|她|它|这|那)[们]?算(什么|哪个|哪门子)',
    r'有脸|配(上|做|当)?|也配|什么(学历|出身)|生个[孩子]|基因(有问题|缺陷)',
    r'(一家|全家|父母|爹妈|母亲|父亲|家人)(都|全)?(是|有|没|活该|该死)',
    r'(活该|该|早就该)(死|凉|滚|被封|被骂)|自作自受|不是人',
)
# Privacy disclosure: an identifiable contact handle, an address, or an explicit doxxing verb.
PRIVACY = (
    r'1[3-9]\d{9}',
    r'\d{17}[\dXx]|\d{15}',
    r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b',
    r'(\d{1,5}号楼?|[省市县区街道路巷小区栋单元室门牌])',
    r'人肉(搜索)?|扒(了)?(出来|出?来|光)|开盒|曝光(其|他的|她的)?(信息|住址|单位|学校|电话|身份)',
    r'(家庭住址|工作单位|就职|学籍|学校(是|在)|身份证(号)?|手机号?(码)?|户籍)(在|是|为|[:：])',
)
# Rumour framing: asserts a fact while attributing it to nobody. Deliberately WITHOUT the
# debunking vocabulary (造谣/辟谣/不实/假的): those words appear far more often in comments
# ACCUSING someone of rumour-mongering than in comments spreading one, and reading
# 「别听他造谣，警方已经辟谣了」 as violent speech would put a correction on the study's
# rumour curve. A missed rumour-spreader is the honest cost of that choice, and it is stated
# here rather than hidden in a score.
RUMOUR = (
    r'听说|据(说|传)|内部(消息|人)(说|透露)?|朋友(说|告诉我)|我认识(的)?(他|她|他们|家属)',
    r'被(安排|利用|当枪)|幕后(黑手|推手)|拿了(钱|好处)|收(了)?(钱|黑钱)',
    r'(真相|内幕)(是|其实)|其实(他|她|他们)(根本|并|早就)',
)

#: Each family is compiled once, joined by ``|`` so one pass over the text finds every variant.
PATTERNS = {
    'abuse': re.compile('|'.join(ABUSE)),
    'attack': re.compile('|'.join(ATTACK)),
    'privacy': re.compile('|'.join(PRIVACY)),
    'rumour': re.compile('|'.join(RUMOUR)),
}

#: The output columns. ``aggression_hits`` lists what fired, so a reader can check the verdict
#: against the evidence instead of trusting a number.
COLUMNS = ('aggression', 'aggression_score', 'aggression_hits')


#: A small local model answers in whichever language its prompt happened to be, and it says 严重
#: as often as ``severe``. Unmapped spellings fall to ``none``, which is why the raw answer is
#: kept in ``aggression_hits``: a reader can see the model said something this parser did not know.
_LEVEL_WORDS = {
    'severe': ('severe', '严重', '重度', '高度'),
    'mild': ('mild', '轻微', '轻度', '一般'),
    'none': ('none', '无', '没有', '正常', '无关'),
}


class AggressionAnalyzer:
    """Score how violent a comment is, in four feature families and three levels."""

    _LLM_MODEL_NAME = 'qwen3.5:9b'

    def __init__(self, model_name: str = '', mode: str = 'lexicon'):
        self.model_name = model_name or self._LLM_MODEL_NAME
        self.mode = mode

    # ── lexicon mode ────────────────────────────────────────────

    @staticmethod
    def score_text(text: str) -> tuple:
        """``(level, score, hits)`` for one comment.

        A fired family contributes its own weight, plus :data:`REPEAT_STEP` for each further
        distinct hit (capped) — five variants of one slur are still one act of abuse, and
        summing them would rank a repetitive comment above a comment that both doxxes and
        slanders. The strongest second family counts at half weight on top of that.
        """
        body = str(text if text is not None else '')
        if not body.strip():
            return 'none', 0.0, []
        fired = []
        for family, pattern in PATTERNS.items():
            found = []
            for match in pattern.finditer(body):
                word = match.group(0).strip()
                if word and word not in found:
                    found.append(word)
            if not found:
                continue
            weight = WEIGHTS[family] + min(REPEAT_CAP, REPEAT_STEP * (len(found) - 1))
            fired.append((weight, family, found))
        if not fired:
            return 'none', 0.0, []
        fired.sort(key=lambda item: -item[0])
        score = fired[0][0]
        if len(fired) > 1:
            score += SECOND_FAMILY_SHARE * fired[1][0]
        level = 'severe' if score >= SEVERE_AT else ('mild' if score >= MILD_AT else 'none')
        hits = [f'{family}:{"、".join(found)}' for _weight, family, found in fired]
        return level, round(score, 4), hits

    def analyze_dataframe(self, df: pd.DataFrame, text_column: str = '正文', ctx=None) -> pd.DataFrame:
        """Add the three aggression columns to every row.

        ``lexicon`` never needs ``ctx``: no model, no cost, no checkpoint. That is the point of
        making it the default — a 10,000-row table runs in seconds and the same input always
        gives the same table, which the ``llm`` mode can only promise through its cache.
        """
        if text_column not in df.columns:
            raise ValueError(t('analysis.col_missing', col=text_column))
        work = df.copy()
        if self.mode == 'llm':
            return self._analyze_with_llm(work, text_column, ctx)
        levels, scores, hits = [], [], []
        for value in work[text_column].tolist():
            level, score, found = self.score_text(value)
            levels.append(level)
            scores.append(score)
            hits.append('；'.join(found))
        work['aggression'] = levels
        work['aggression_score'] = scores
        work['aggression_hits'] = hits
        violent = sum(1 for level in levels if level != 'none')
        logger.info(
            t(
                'aggression.lexicon_done',
                rows=len(levels),
                violent=violent,
                severe=sum(1 for level in levels if level == 'severe'),
            )
        )
        return work

    # ── llm mode ────────────────────────────────────────────────

    def build_prompt(self, text: str) -> str:
        return (
            '你是网络暴力言论判定员。判断下面这条中文评论是否属于网络暴力言论，并给出等级与类型。\n'
            '等级：none（无暴力）、mild（轻微攻击）、severe（严重：辱骂、人身攻击、人肉/隐私泄露、造谣）。\n'
            '类型只能从这些里选：abuse（谩骂）、attack（人身攻击）、privacy（隐私披露/人肉）、rumour（造谣转述）、none。\n'
            '只输出一行，格式为「等级|类型」，不要解释、不要引号。\n'
            f'评论：{text}'
        )

    @staticmethod
    def parse_answer(answer) -> tuple:
        """The model's line as ``(level, hits)``, with anything unrecognisable read as no verdict.

        A local model returns 「严重」 for ``severe``, a stray ``` in the level slot, or a whole
        sentence. The first field is matched against the level words (in both languages) and the
        rest is kept as the type list, so a reader can see what the model actually said rather
        than a coerced value.
        """
        text = str(answer or '').strip()
        if not text:
            return 'none', ''
        line = text.splitlines()[0]
        parts = [item.strip() for item in line.replace('｜', '|').split('|')]
        said = parts[0].lower()
        known = next((name for name, words in _LEVEL_WORDS.items() if any(word in said for word in words)), '')
        kinds = [item for item in parts[1:] if item and item.lower() not in ('none', '无')]
        if not known and not kinds and said:
            # Nothing in the answer was a level this parser knows, and no type came either: the
            # model replied with prose. Keeping its words is the only honest reading.
            kinds = [said[:40]]
        return known or 'none', '；'.join(kinds)

    def _analyze_with_llm(self, work: pd.DataFrame, text_column: str, ctx) -> pd.DataFrame:
        def parse(answer):
            # One argument, the model's reply: ``run_llm_dataframe`` calls ``parse(chat(prompt))``,
            # so the row's own text is already inside the prompt and does not come back here.
            level, kinds = self.parse_answer(answer)
            return [level, '', kinds]

        return run_llm_dataframe(
            work,
            text_column=text_column,
            op='aggression',
            result_columns=['aggression', 'aggression_score', 'aggression_hits'],
            blank=['none', '', ''],
            fail_value=('none', '', '模型未判定'),
            build_prompt=self.build_prompt,
            parse=parse,
            ctx=ctx,
            label=f'aggression:{self.model_name}',
            default_model=self.model_name,
        )
