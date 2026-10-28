"""小红书: search (with a comment preview) and comment walks."""

from capabilities.fields import comment_mode, posts_mode
from capabilities.model import Capability, Field

CAPABILITY = Capability(
    platform='xiaohongshu',
    # Measured twice in one hour: search answered fine, then the same saved
    # session was redirected to the login page minutes later while the user's own
    # browser was still logged in and working.
    profile_recommended=True,
    modes=(
        posts_mode(
            Field(
                key='comment_preview',
                control='number',
                label_key='settings.commentPreview',
                default=5,
                hint_key='settings.commentPreviewHint',
                minimum=0,
                coerce='number',
            ),
            collects='dom_scroll',
        ),
        comment_mode('xiaohongshu', 'https://www.xiaohongshu.com/explore/...', collects='dom_scroll'),
    ),
)
