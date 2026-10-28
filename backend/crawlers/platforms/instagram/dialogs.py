"""Instagram's notification ask: 「打开通知」, answered 以后再说.

Declared here for the same reason douyin's trust-login prompt is: the dialog's wording is a
property of the site. Nothing mounts it yet (the platform is cookie-capture only in this app),
which is stated in docs/refactor_plan.md's D9 rather than papered over.
"""

from crawlers.engine.popup import Prompt

#: 「以后再说」 is the "no". 「打开」 is refused because it opens a *browser-level* permission
#: dialog no DOM click can close.
NOTIFICATIONS = Prompt(
    key='instagram_notifications',
    selector='',
    markers=('打开通知', '接收通知', 'Enable notifications', 'Get notifications'),
    choose=('以后再说', '稍后', 'Not Now', 'Not now', 'Later'),
    forbid=('打开', 'Allow', 'Not yet'),
)
