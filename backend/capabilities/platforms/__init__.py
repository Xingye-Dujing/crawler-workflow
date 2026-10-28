"""Every platform's declaration, one file each, front to back in the panel's order.

The tuple's order IS the Data Source panel's order; a platform's modes, fields and advice
live together in its own module, so adding one is a new file and one line here — not an
edit in five places. ``tests/unit/test_capabilities_layout.py`` pins the two together.
"""

from capabilities.model import Capability
from capabilities.platforms import (
    bilibili,
    douyin,
    hongguo,
    twitter,
    wechat,
    weibo,
    xiaohongshu,
    youtube,
    zhihu,
)

CAPABILITIES: tuple[Capability, ...] = (
    zhihu.CAPABILITY,
    weibo.CAPABILITY,
    xiaohongshu.CAPABILITY,
    wechat.CAPABILITY,
    bilibili.CAPABILITY,
    douyin.CAPABILITY,
    hongguo.CAPABILITY,
    # The overseas three come last on purpose: they are the newest entries and the
    # panel's order is this tuple's order, so the platforms a Chinese-language
    # user reaches for first stay at the top of the list.
    youtube.CAPABILITY,
    twitter.CAPABILITY,
)
