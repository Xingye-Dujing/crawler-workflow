"""Instagram's notification ask: “打开通知”, answered 以后再说.

Declared here for the same reason douyin's trust-login prompt is: the dialog's wording is a
property of the site. Mounted by ``InstagramCrawler.prompts`` — the platform is
cookie-capture only, but the panel's 验证 probe opens ``login_url`` through the shared
``Crawler.open`` hook, and the ask appears right after a login there. (The pre-flight gate
answers this platform as not-crawlable without opening a browser.)
"""

from crawlers.engine.popup import Prompt

#: “以后再说” is the "no". “打开” is refused because it opens a *browser-level* permission
#: dialog no DOM click can close.
NOTIFICATIONS = Prompt(
    key='instagram_notifications',
    selector='',
    markers=('打开通知', '接收通知', 'Enable notifications', 'Get notifications'),
    choose=('以后再说', '稍后', 'Not Now', 'Not now', 'Later'),
    forbid=('打开', 'Allow', 'Not yet'),
)
