"""抖音's first-run dialog: 「是否保存登录信息超过5天」, answered 取消.

This is the one site fact the shared dismisser needs from douyin. It lives beside the crawler
that declares ``prompts = (dialogs.TRUST_LOGIN,)`` rather than in ``crawlers/engine/popup.py``,
which now holds only the mechanism.
"""

from crawlers.engine.popup import Prompt

#: Read off the live DOM: the title is 「是否保存登录信息超过5天」 and the two leaves are
#: 「保存」 and 「取消」. Only 取消 is ever pressed — the user reports that 保存 leads on to a
#: phone-verification step, so declining is both the safer answer and the one that leaves the
#: session alone. The mask is not cosmetic: measured, it intercepts the search button's click
#: (``ElementClickInterceptedException``), and it mounts several seconds *after* the page,
#: which is why the crawler also dismisses on a blocked click rather than only on arrival.
TRUST_LOGIN = Prompt(
    key='douyin_trust_login',
    selector='.trust-login-dialog-mask',
    markers=('是否保存登录信息', '保存登录信息', '保存到设备', '将信息保存'),
    choose=('取消',),
    forbid=('保存', '是', '同意', '确定'),
)
