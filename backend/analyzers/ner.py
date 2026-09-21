import logging
import re

import pandas as pd

from i18n import t

logger = logging.getLogger(__name__)

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


class NamedEntityRecognizer:
    """Rule-based Chinese NER using regex patterns — zero external dependencies.

    Covers four entity types:
      - PERSON  : name + title/honorific patterns
      - ORG     : organisation suffix patterns
      - LOC     : location (省/市/县…) after 在/到/位于/来自
      - DATE    : Chinese date formats (2024年1月1日 etc.)
    """

    def analyze_dataframe(self, df: pd.DataFrame, text_column: str = '正文') -> pd.DataFrame:
        if text_column not in df.columns:
            logger.error(t('analysis.col_missing', col=text_column))
            return df

        all_entities = []
        for idx, raw in df[text_column].items():
            if pd.isna(raw) or not str(raw).strip():
                continue
            text = str(raw)
            seen = set()
            for m in _CHINESE_PERSON_PAT.finditer(text):
                key = (m.group(), m.start(), m.end())
                if key not in seen:
                    seen.add(key)
                    all_entities.append(
                        {
                            'row': idx,
                            'text': m.group(),
                            'label': 'PERSON',
                            'start': m.start(),
                            'end': m.end(),
                        }
                    )
            for m in _CHINESE_ORG_PAT.finditer(text):
                key = (m.group(), m.start(), m.end())
                if key not in seen:
                    seen.add(key)
                    all_entities.append(
                        {
                            'row': idx,
                            'text': m.group(),
                            'label': 'ORG',
                            'start': m.start(),
                            'end': m.end(),
                        }
                    )
            for m in _CHINESE_LOC_PAT.finditer(text):
                key = (m.group(1), m.start(1), m.end(1))
                if key not in seen:
                    seen.add(key)
                    all_entities.append(
                        {
                            'row': idx,
                            'text': m.group(1),
                            'label': 'LOC',
                            'start': m.start(1),
                            'end': m.end(1),
                        }
                    )
            for m in _CHINESE_DATE_PAT.finditer(text):
                key = (m.group(), m.start(), m.end())
                if key not in seen:
                    seen.add(key)
                    all_entities.append(
                        {
                            'row': idx,
                            'text': m.group(),
                            'label': 'DATE',
                            'start': m.start(),
                            'end': m.end(),
                        }
                    )

        cols = ['row', 'text', 'label', 'start', 'end']
        if not all_entities:
            return pd.DataFrame(columns=cols)
        return pd.DataFrame(all_entities, columns=cols)
