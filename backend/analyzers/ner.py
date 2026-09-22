import logging
import re

import pandas as pd

from analyzers.llm_client import ABORT_MARK, run_llm_dataframe
from i18n import t

logger = logging.getLogger(__name__)

#: The node's output contract, identical in both modes. visualize/export read
#: ``label`` and ``text``, and ``row``/``start``/``end`` are what lets a UI
#: highlight an entity inside the source text.
COLUMNS = ['row', 'text', 'label', 'start', 'end']

#: The node's output contract, identical in both modes: one row per entity hit,
#: pointing back into the source row it came from.
COLUMNS = ['row', 'text', 'label', 'start', 'end']

# The bare 2-4 character prefix used to miss the single most common Chinese
# mention form — a lone surname before the honorific (张先生, 李女士). The
# one-character branch is therefore restricted to a whitelist of common
# surnames: any CJK character there would fabricate hits like 的先生.
_COMMON_SURNAMES = (
    '王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾肖田董袁潘于蒋蔡余杜叶程苏魏吕丁任沈姚卢'
    '姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤'
)
_HONORIFICS = '先生|女士|同志|教授|医生|老师|局长|主任|经理|总裁|董事长|主席|委员|部长|省长|市长|县长|书记'
_CHINESE_PERSON_PAT = re.compile(rf'(?:[\u4e00-\u9fa5]{{2,4}}|[{_COMMON_SURNAMES}])(?:{_HONORIFICS})')
_CHINESE_ORG_PAT = re.compile(
    r'[\u4e00-\u9fa5]{2,}'
    r'(?:大学|学院|医院|集团|公司|银行|协会|基金会|委员会|局|部|办|社|中心|研究院|研究所|厂)'
)
_CHINESE_LOC_PAT = re.compile(
    r'(?:在|到|位于|来自)'
    r'([\u4e00-\u9fa5]{2,}(?:省|市|县|区|镇|乡|村|路|街|大道|广场|湖|山|河))'
)
_CHINESE_DATE_PAT = re.compile(
    r'\d{4}年\d{1,2}月\d{1,2}日'
    r'|\d{4}年\d{1,2}月'
    r'|\d{1,2}月\d{1,2}日'
)

#: Which group a match is in. LOCATION captures the place *after* the cue word
#: (在/到/位于/来自), so its own group is dropped and only group 1 is a place —
#: recording 在深圳 as the entity would put a preposition in the entity table.
#: ``group`` is the capture to read, defaulting to the whole match.
_PATTERNS: tuple[tuple[str, re.Pattern, int], ...] = (
    ('PERSON', _CHINESE_PERSON_PAT, 0),
    ('ORG', _CHINESE_ORG_PAT, 0),
    ('LOC', _CHINESE_LOC_PAT, 1),
    ('DATE', _CHINESE_DATE_PAT, 0),
)

#: The labels the panel offers, in the order it shows them.
ENTITY_TYPES = tuple(label for label, _pattern, _group in _PATTERNS)

# A model that was asked for PERSON/ORG answers in more than one vocabulary —
# its own English tag names, the Chinese ones from the prompt, and the
# CoNLL-style spellings small models were trained on. Anything outside this map
# is dropped instead of guessed at: an entity filed under the wrong label is
# worse data than a missing one.
_LABEL_ALIASES = {
    'PERSON': 'PERSON',
    'PER': 'PERSON',
    '人物': 'PERSON',
    '人名': 'PERSON',
    'ORG': 'ORG',
    'ORGANIZATION': 'ORG',
    'ORGANISATION': 'ORG',
    '机构': 'ORG',
    '组织': 'ORG',
    'LOC': 'LOC',
    'LOCATION': 'LOC',
    'GPE': 'LOC',
    'PLACE': 'LOC',
    '地点': 'LOC',
    '位置': 'LOC',
    'DATE': 'DATE',
    'TIME': 'DATE',
    'DATE-TIME': 'DATE',
    '时间': 'DATE',
    '日期': 'DATE',
}

# ``entity|LABEL`` on its own line, the form the prompt asks for. The last
# separator wins, because the entity itself may hold anything: brackets, a
# colon, an English comma. Tab and → are accepted because models that were
# trained on other annotation formats reach for them unprompted.
_ANSWER_SEPARATORS = ('|', '\t', '→', '：', ':', ' - ', ' — ')
_ANSWER_BULLET_RE = re.compile(r'^\s*(?:[-*+]\s+|\d+[.)]\s+|[#*`>]+)')
_LABEL_TAIL_RE = re.compile(r'([A-Za-z][A-Za-z-]*|[\u4e00-\u9fa5]{1,4})[\s.。,，;；:：]*$')
_ANSWER_PAREN_RE = re.compile(
    r'^(?P<entity>.+?)[（(]\s*(?P<label>[A-Za-z][A-Za-z-]*|[\u4e00-\u9fa5]{1,4})\s*[)）][\s.。]*$'
)
_EMPTY_ANSWERS = frozenset({'NONE', 'NO', '无', '没有', 'N/A', 'NA', '-'})

#: Separators for the per-row answer cell. The cell is a working column that
#: only ever appears mid-run (the node's own output is the exploded table), so
#: readability loses to not colliding with entity text.
_PAIR_SEP = '\x1e'
_LABEL_SEP = '\x1f'


def answer_pair(line: str):
    """One model answer line as ``(entity, LABEL)``, or None when it is not one.

    A line with neither a separator nor a bracketed category is not an entity
    either — that is how a model restating the text reads, and keeping it would
    put whole sentences in the entity table. A label outside the known
    vocabulary is dropped for the same reason: guessing at it invents data.
    """
    text = _ANSWER_BULLET_RE.sub('', str(line or '')).strip().strip('`*」』】)')
    if not text or text.upper().strip('.。,，;；') in _EMPTY_ANSWERS:
        return None
    for sep in _ANSWER_SEPARATORS:
        if sep in text:
            entity, _, tail = text.rpartition(sep)
            entity = entity.strip().strip('`*"」』】')
            return entity, _label_of(tail)
    # Models trained on Chinese annotation formats write 张伟（人名）, which has
    # no separator at all — the category is bracketed onto the end.
    bracketed = _ANSWER_PAREN_RE.match(text)
    if bracketed:
        return bracketed.group('entity').strip(), _label_of(bracketed.group('label'))
    return None


def _label_of(raw: str):
    """The category token at the end of an answer line, normalised."""
    match = _LABEL_TAIL_RE.search(raw or '')
    if not match:
        return ''
    return _LABEL_ALIASES.get(match.group(1).strip().upper(), '')


def wanted_types(entity_types) -> set:
    """The requested labels, upper-cased; empty/None/garbage means 'all'.

    A filter, not a switch: the panel lets the user type the list, and a typo in
    it should not fail a run that has already crawled thousands of rows.
    """
    if isinstance(entity_types, str):
        items = entity_types.replace('，', ',').split(',')
    elif isinstance(entity_types, (list, tuple, set)):
        items = [str(part) for part in entity_types]
    else:
        items = []
    picked = {str(item).strip().upper() for item in items if str(item).strip()}
    valid = picked & set(ENTITY_TYPES)
    return valid or set(ENTITY_TYPES)


class NamedEntityRecognizer:
    """Chinese named-entity recognition, in two modes that share one output.

    Mode ``regex`` (the default) matches four rule families and needs no model
    at all:
      - PERSON  : name + title/honorific patterns
      - ORG     : organisation suffix patterns
      - LOC     : location (省/市/县…) after 在/到/位于/来自
      - DATE    : Chinese date formats (2024年1月1日 etc.)
    Mode ``llm`` asks a model instead, so a text that names people and places
    without any of those surface cues still yields entities. It is opt-in
    because it costs a request per row.

    Both modes return the *same* five columns (row/text/label/start/end), which
    is what lets a downstream chart or export survive a mode switch — and both
    guarantee that ``text[start:end]`` reproduces the entity in its source row.
    For the model that guarantee is earned by discarding anything it reports
    that is not literally in the text, which is also the cheapest defence
    against a plausible-looking invented name.
    """

    def __init__(self, model_name: str = 'qwen3.5:9b', mode: str = 'regex'):
        self.model_name = model_name
        # Anything but an explicit 'llm' stays on the rules: an older saved
        # workflow has no mode field and must not start paying for a model.
        self.mode = 'llm' if str(mode or '').strip().lower() == 'llm' else 'regex'

    def analyze_dataframe(
        self,
        df: pd.DataFrame,
        text_column: str = '正文',
        entity_types=None,
        ctx: dict = None,
    ) -> pd.DataFrame:
        """Find entities, optionally restricted to the named types.

        ``entity_types`` is a filter, not a switch (see :func:`wanted_types`).
        A filter that matched nothing returns an empty table with the columns
        intact, which is the honest answer.
        """
        wanted = wanted_types(entity_types)
        if self.mode == 'llm':
            return self._analyze_llm(df, text_column, wanted, ctx)
        return self._analyze_regex(df, text_column, wanted)

    # ── regex mode ──────────────────────────────────────────────

    @staticmethod
    def _analyze_regex(df: pd.DataFrame, text_column: str, wanted: set) -> pd.DataFrame:
        if text_column not in df.columns:
            # The other rule-based analyzers answer the same way: an empty
            # table plus a console line naming the column. (The LLM path raises
            # instead — see the docstring on run_llm_dataframe.)
            logger.error(t('analysis.col_missing', col=text_column))
            return _empty_table()
        all_entities = []
        for idx, raw in df[text_column].items():
            if pd.isna(raw) or not str(raw).strip():
                continue
            text = str(raw)
            seen = set()
            for label, pattern, group in _PATTERNS:
                if label not in wanted:
                    continue
                for match in pattern.finditer(text):
                    key = (match.group(group), match.start(group), match.end(group))
                    if key in seen:
                        continue
                    seen.add(key)
                    all_entities.append({'row': idx, 'text': key[0], 'label': label, 'start': key[1], 'end': key[2]})
        return _table(all_entities)

    # ── llm mode ────────────────────────────────────────────────

    #: What each category means, in the prompt's words. Only the requested ones
    #: are ever sent: a model shown the ORG definition will find organisations,
    #: so a run that asked for dates only would be answering a question it never
    #: asked — and paying for it.
    _CATEGORY_HINTS = {
        'PERSON': 'a person, or a form of address that names one (张伟, 张先生)',
        'ORG': 'a company, institution, government body or media account (北京大学, 新华社)',
        'LOC': 'a place, including addresses and regions (上海, 中华人民共和国)',
        'DATE': 'a date or time expression (2024年5月, 上周五)',
    }

    def build_ner_prompt(self, text: str, labels=ENTITY_TYPES) -> str:
        wanted = [label for label in ENTITY_TYPES if label in set(labels or ENTITY_TYPES)] or list(ENTITY_TYPES)
        lines = '\n'.join(f'  {label}: {self._CATEGORY_HINTS[label]}' for label in wanted)
        return (
            'Role: Chinese named entity recognition.\n'
            f'\nExtract every named entity of these categories only: {", ".join(wanted)}.\n' + lines + '\n\nRules:\n'
            '- Copy each entity exactly as it appears in the text, as one contiguous run of'
            ' characters. Never normalise, translate, complete or invent an entity.\n'
            '- Report no category but the ones listed above.\n'
            '- Output one entity per line as `entity|CATEGORY`, with no other text, no numbering and no explanation.\n'
            '- If the text holds no such entity, output exactly: NONE\n'
            '\nInput text:\n' + text + '\n\nAnswer:\n'
        )

    def parse_ner_response(self, content: str) -> tuple:
        """Model answer -> one cell holding the accepted ``entity LABEL`` pairs.

        Offsets are not computed here: the parse step is given only the model's
        text, not the row it came from, so the literal-in-source check (and with
        it start/end) happens once the frame is in hand — see :meth:`_explode`.
        """
        pairs = []
        for line in str(content or '').splitlines():
            pair = answer_pair(line)
            if pair is None:
                continue
            entity, label = pair
            if entity and label:
                pairs.append(f'{entity}{_LABEL_SEP}{label}')
        return (_PAIR_SEP.join(pairs),)

    def _analyze_llm(self, df: pd.DataFrame, text_column: str, wanted: set, ctx: dict) -> pd.DataFrame:
        cfg = dict(ctx or {})
        labels = [label for label in ENTITY_TYPES if label in wanted]

        def build_prompt(text: str) -> str:
            return self.build_ner_prompt(text, labels)

        # The entity table is this node's product, so what the runner publishes
        # mid-run has to be the table too — not the frame with one extra working
        # column, which would change shape the moment the node settled.
        publish = cfg.get('publish')
        if callable(publish):
            cfg['publish'] = lambda frame: publish(_explode(frame, text_column, wanted)[0])
        enriched = run_llm_dataframe(
            df,
            text_column,
            op='ner',
            result_columns=['entities'],
            blank=[''],
            skip_value=('',),
            fail_value=('',),
            build_prompt=build_prompt,
            parse=self.parse_ner_response,
            ctx=cfg,
            label=t('label.ner'),
            # Nothing to skip: a two-character comment can still name someone,
            # and the runner's own mask already drops empty cells.
            min_len=1,
            default_model=self.model_name,
            # The category list is a closure value the prompt-version digest
            # cannot see, so a PERSON-only answer is never served to a run that
            # asked for every type.
            extra_key=','.join(labels),
        )
        table, rejected = _explode(enriched, text_column, wanted)
        if rejected:
            logger.warning(t('ner.dropped', n=rejected))
        return table


def _entity_rows(cell, text, idx, wanted) -> tuple:
    """One row's answer cell as ``(records, rejected)`` entity-table entries.

    Rejected is counted, never kept: a model that reports an entity the source
    does not contain is wrong, and the only way to tell that apart from a good
    answer is to look for it in the text.
    """
    rows = []
    seen = set()
    rejected = 0
    for pair in str(cell or '').split(_PAIR_SEP):
        if not pair:
            continue
        entity, _, label = pair.partition(_LABEL_SEP)
        start = text.find(entity) if entity and label in wanted else -1
        if start < 0:
            # Either an unknown category, or an invention / a normalised
            # spelling (the model wrote 北京 where the text says 北京市).
            rejected += 1
            continue
        key = (entity, label, start)
        if key in seen:
            # Models repeat themselves across lines of one answer; one entity is
            # one row, exactly as the regex path dedupes per row.
            continue
        seen.add(key)
        rows.append({'row': idx, 'text': entity, 'label': label, 'start': start, 'end': start + len(entity)})
    return rows, rejected


def _explode(df: pd.DataFrame, text_column: str, wanted: set) -> tuple:
    """Turn the per-row ``entities`` answers into the shared entity table.

    Returns ``(table, rejected)`` — the count is the caller's to report, because
    this runs once per published batch as well as at the end.
    """
    if text_column not in df.columns or 'entities' not in df.columns:
        return _empty_table(), 0
    records = []
    rejected = 0
    for idx, raw in df[text_column].items():
        cell = df.at[idx, 'entities']
        if pd.isna(raw) or pd.isna(cell) or not str(cell).strip() or str(cell) == ABORT_MARK:
            # An empty cell is a legitimate answer (the text had no entity); a
            # 未处理 cell is a row the run never reached, which the runner
            # already reports and which must not be counted as a wrong answer.
            continue
        rows, dropped = _entity_rows(cell, str(raw), idx, wanted)
        records.extend(rows)
        rejected += dropped
    return _table(records), rejected


def _table(records: list) -> pd.DataFrame:
    if not records:
        return _empty_table()
    return pd.DataFrame(records, columns=COLUMNS)


def _empty_table() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUMNS)
