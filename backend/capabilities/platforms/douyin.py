"""抖音: a creator's videos, the board, and comment walks (a captcha answers headless)."""

from capabilities.fields import author_mode, comment_mode, hot_mode
from capabilities.model import Capability

CAPABILITY = Capability(
    platform='douyin',
    # Measured 2026-09-26, one network and one account, the session shape the only variable:
    # a cookie-planted throwaway browser was answered 验证码中间页 in 8.8 s (and refused to
    # file an empty table), while the same keyword ``IU`` crawl run through the platform's own
    # profile returned 5 rows in 24.8 s. That is the same "a copied login is a second device"
    # behaviour already written down for weibo, so douyin gets the recommendation too: the
    # visible window is necessary but not sufficient — the jar has to be the one the site
    # rotated. **One mode reads the other way**: the 热榜 board was answered the captcha BY
    # the profile and served by the throwaway browser (measured 2026-09-25, note on
    # ``_hot_mode`` below), which is why the recommendation is a warning and never a coercion,
    # and why #142 keeps the question open instead of resolving it into one sentence.
    profile_recommended=True,
    modes=(
        author_mode(
            placeholder='https://www.douyin.com/user/<sec_uid>',
            hint_key='settings.authorHintDouyin',
            collects='modal_per_row',
        ),
        # One answer is the whole board (measured 51 rows), and it needs no board
        # choice: douyin publishes this one list. It does need a session — measured
        # on the same day, the tool's own douyin profile was answered the captcha
        # interstitial while a cookie-planted throwaway browser read the board, so
        # 需要登录 here is the truth rather than a hedge.
        hot_mode(board=False),
        comment_mode('douyin', 'https://www.douyin.com/video/...', collects='dom_scroll'),
    ),
)
