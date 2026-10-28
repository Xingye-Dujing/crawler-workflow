"""YouTube's EU consent sheet: 「在我们继续之前」, accepted — it blocks everything behind it.

Declared here because the sheet is a property of the site. Nothing mounts it yet (D9 in
docs/refactor_plan.md; wiring it changes real-site behaviour and needs its own live evidence).
"""

from crawlers.engine.popup import Prompt

#: Harmless to accept, and it blocks everything behind it when the session has no consent cookie.
CONSENT = Prompt(
    key='youtube_consent',
    selector='',
    markers=('Before you continue', '在我们继续之前', '管理设置'),
    choose=('接受全部', '全部接受', 'Accept all'),
    forbid=('拒绝', 'Reject all'),
)
