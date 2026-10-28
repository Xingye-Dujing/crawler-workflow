"""X / Twitter: search, a user's posts, and comment walks behind a login wall."""

from capabilities.fields import author_mode, comment_mode, posts_mode
from capabilities.model import Capability

CAPABILITY = Capability(
    platform='twitter',
    region='overseas',
    modes=(
        posts_mode(),
        author_mode(),
        comment_mode('twitter', 'https://x.com/.../status/...', collects='dom_scroll'),
    ),
)
