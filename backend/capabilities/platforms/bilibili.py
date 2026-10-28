"""哔哩哔哩: search videos, a UP's timeline, the board (popular/ranking), comments."""

from capabilities.fields import author_mode, comment_mode, hot_mode, posts_mode
from capabilities.model import Capability

CAPABILITY = Capability(
    platform='bilibili',
    # Paged search reads one account's pages independently and comments come from a
    # reply API that tolerates two sessions crawling at once (measured), so parallel
    # is the recommended shape here, named as such rather than inferred.
    parallel_recommended=True,
    modes=(
        posts_mode(label_key='settings.collectVideos', collects='dom_read'),
        author_mode(
            placeholder='https://space.bilibili.com/<UID>',
            hint_key='settings.authorHintBili',
        ),
        hot_mode(),
        comment_mode('bilibili', 'https://www.bilibili.com/video/BV...'),
    ),
)
