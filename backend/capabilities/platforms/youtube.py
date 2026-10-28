"""YouTube: search, a channel's videos, and comment walks, each with the per-row facts."""

from capabilities.fields import WITH_FACTS, author_mode, comment_mode, posts_mode
from capabilities.model import Capability

CAPABILITY = Capability(
    platform='youtube',
    region='overseas',
    modes=(
        posts_mode(WITH_FACTS, collects='fetch', note_key='settings.fetchQuietNote'),
        author_mode(WITH_FACTS, collects='fetch', note_key='settings.fetchQuietNote'),
        comment_mode('youtube', 'https://www.youtube.com/watch?v=...'),
    ),
)
