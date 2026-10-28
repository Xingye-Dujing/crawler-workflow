"""The login-state domain: saved sessions per account, the profiles the browser keeps, and
what a cookie can be trusted to still be worth.

Part of the zh/en message catalogue, merged by ``backend/i18n.py`` — the ``t()`` machinery,
the thread-local language and the audit live there, so this module is data with no imports.
Keys are sorted; the two tables in here must hold the same set (``tests/unit/test_i18n.py``).
"""

ZH = {
    'cap.requiresWindowsDesktop': '需要 Windows 桌面版：该模式要在本机驱动播放器或窗口',
    'cookie.allForeign': '{platform} 的 Cookie 一条都没保存：粘贴的内容全属于其它站点，请粘贴该平台自身的 Cookie',
    'cookie.bilibili.purpose': '解锁 B 站搜索、视频详情与评论区；未登录时搜索会被折叠，评论只给前几条。',
    'cookie.bilibili.steps': (
        '1. 点「浏览器生成」，在弹出的 Chrome 窗口里登录哔哩哔哩（扫码或手机号）\n'
        '2. 打开任意视频并滚到评论区，能看到评论列表即可\n'
        '3. 回到本面板点「已完成登录」'
    ),
    'cookie.delete.failed': '删除 Cookie 文件失败：{err}',
    'cookie.delete.none': '{platform} 没有已保存的 Cookie 可删除',
    'cookie.delete.profileHolds': '注意：{platform} 的浏览器 profile 仍是登录状态，删这个文件不会把它登出',
    'cookie.deleted': '已删除 {platform} 的 Cookie',
    'cookie.deletedAccount': '已删除 {platform}（账号：{account}）的 Cookie',
    'cookie.douyin.purpose': '解锁抖音网页版搜索、视频文案与评论区；未登录常常只给首屏且看不到评论。',
    'cookie.douyin.steps': (
        '1. 点「浏览器生成」，在弹出的 Chrome 窗口里登录抖音网页版（扫码或手机号）\n'
        '2. 打开任意视频，右侧能看到评论区即可\n'
        '3. 回到本面板点「已完成登录」\n'
        '提示：抖音网页版对自动化浏览器较敏感，若窗口里出现滑块验证，请在窗口内手动完成后再保存。'
    ),
    'cookie.droppedForeign': (
        '已忽略 {n} 条不属于 {platform} 的 Cookie：登录常会经过第三方站点，它们不进本平台的 Cookie 文件'
    ),
    'cookie.entryRejected': (
        '该链接不属于 {platform} 的域名，已改用平台登录页（不允许把别的站点的 Cookie 存进本平台的 Cookie 文件）'
    ),
    'cookie.instagram.purpose': '解锁 Instagram 的博主帖子、标签页与评论；未登录时页面只给登录墙，接口也会拒绝。',
    'cookie.instagram.steps': (
        '1. 点「浏览器生成」，在窗口里登录 instagram.com\n'
        '2. 打开任意一个帖子页，能看到评论区即可\n'
        '3. 回到本面板点「已完成登录」\n'
        '提示：若登录被转到 Facebook，请等它回到 Instagram 之后再点保存。'
    ),
    'cookie.jobCancelled': '{platform} 登录已取消',
    'cookie.noCookies': '等待结束仍未获得 Cookie——若登录未完成，请重试',
    # 保存即更新：粘贴成功的这一刻就把这份 Cookie 送进它自己的 profile，不再要用户按第二个按钮
    # （原来那个 /api/cookies/refresh-profile 与它的四句拒绝一起删掉了）。只有一种情况当场做不到——
    # 那个浏览器正被占用——而这句话必须说：「保存成功」与「这次没进到 profile」在粘贴框里长得一样。
    'cookie.plant.deferred': (
        '{platform} 的浏览器正被占用（可能有抓取在跑），这次没能更新进 profile；Cookie 已保存，下一次抓取会自动带上它'
    ),
    'cookie.pre.account': '（账号 {account}）',
    'cookie.pre.busy': '{platform} 的浏览器正被占用',
    'cookie.pre.expired': '{platform} 的 Cookie 已失效：页面被弹回登录页',
    'cookie.pre.noLogin': '{platform} 的抓取不需要登录',
    'cookie.pre.notCrawlable': '{platform} 目前只能取 Cookie，还不能采集',
    'cookie.pre.notListed': '这个平台谁都不认识，没有验证：{platform}',
    'cookie.pre.riskControl': '页面回的是验证码/风控',
    'cookie.pre.timeout': '验证超时（{n} 秒）',
    'cookie.pre.unknown': '{platform} 的 Cookie 无法核对（不代表有效，本次不拦截）',
    # 运行前自动验证（preflight）：三条结论对应三种下一步，合并任何一条都会把
    # 用户支到错误的动作上——重新登录，或者什么也不做地等待。
    'cookie.pre.valid': '{platform} 的 Cookie 可用',
    'cookie.profileDelete.none': '{platform} · {account} 没有可删除的浏览器 Profile',
    'cookie.profileDeleted': '已删除 {platform} · {account} 的浏览器 Profile（该设备已登出；Cookie 文件不动）',
    'cookie.refresh.done': '已把保存的 {platform} Cookie 更新进它的浏览器 profile（{n} 条）',
    'cookie.refresh.failed': '更新 profile 登录态失败：打不开该平台的浏览器（{err}）',
    # Measured: a cookie without an expiry is never written to the profile store, so it
    # dies with the window that was opened to plant it. The count is said because the
    # alternative is a promise the next restart will break.
    'cookie.refresh.sessionOnly': '其中 {n} 条没有有效期（会话 Cookie），关掉这个窗口后不会留在 profile 里',
    'cookie.renamed': '已把 {platform} 的登录改名：{old} → {new}（Cookie 文件与浏览器目录一起搬）',
    'cookie.renamedFileOnly': '已把 {platform} 的登录改名：{old} → {new}（该账号还没开过浏览器，只动了文件）',
    'cookie.saved': '已保存 {platform} 的 Cookie',
    # 一个平台可以多份登录：那句保存的话必须说出是**哪一份**，否则控制台里「已保存 微博 的 Cookie」
    # 指的是哪一个账号无从判断（用户要的正是逐个 Cookie 管理）。{account} 由 CookieManager 先取好
    # 词（空白=默认账号、default2=默认账号2、自己起的名字原样），这里只负责成句。
    'cookie.savedAccount': '已保存 {platform} 的 Cookie（账号：{account}）',
    'cookie.started': '已启动登录浏览器，请在弹出的窗口完成登录，然后点「已完成登录」',
    'cookie.twitter.purpose': (
        '解锁 X（推特）的搜索、用户时间线、推文正文与回复；未登录时这些页面基本只回一个登录引导页。'
    ),
    'cookie.twitter.steps': (
        '1. 点「浏览器生成」，在弹出的 Chrome 窗口里登录 x.com（账号密码或手机号+验证码）\n'
        '2. 随便打开一条推文，确认回复区能加载出来（auth_token 与 ct0 两条 Cookie 缺一不可）\n'
        '3. 回到本面板点「已完成登录」\n'
        '提示：X 对新设备登录常会追加一次验证码，请在同一个窗口里做完再保存。'
    ),
    'cookie.verify.checkedUrl': '验证地址：{url}',
    'cookie.verify.cloudHeadless': (
        '本机是无窗口的服务器：上面这次验证只能用无头浏览器完成，而部分站点对无头访问回的是验证码或空白，'
        '这不证明 Cookie 失效（要按登录态复核，请在有窗口的机器上验证）'
    ),
    'cookie.verify.loginWall': '{platform} 仍被挡在登录页：请重新登录并保存',
    'cookie.verify.noCookie': '{platform} 还没有 Cookie：请先登录保存',
    'cookie.verify.ok': '{platform} 的 Cookie 可用',
    'cookie.verify.unclear': '{platform} 的验证没有结论：页面回的是验证码/风控，与 Cookie 是否有效无关',
    # The page never came from the site at all, so nothing about the cookie was tested —
    # and 「可用」 here would be cached and reused by every later run.
    'cookie.verify.unreachable': '{platform} 无法验证：浏览器自己没能打开这个地址（本机网络或 DNS），未检验到 Cookie',
    'cookie.verifyFailed': '验证失败：{err}',
    'cookie.verifying': '正在用已保存的 Cookie 试探该平台…',
    'cookie.weibo.purpose': '解锁微博搜索（s.weibo.com）与评论 JSON 接口；未登录会被跳回 passport 二维码页。'
    '微博只认一份一直在用的会话：同账号并行翻页、或另开一个浏览器重放同一份 Cookie，都会被弹回登录页。'
    '所以抓取请始终用同一个 Profile，也不要同时跑两条微博。',
    'cookie.weibo.steps': (
        '1. 点「浏览器生成」，在窗口里登录微博\n2. 手动搜一次关键词，能看到微博列表即可\n3. 回到本面板点「已完成登录」'
    ),
    'cookie.windowClosed': '登录窗口被关闭，未捕获 Cookie；请重新发起登录',
    'cookie.xiaohongshu.purpose': '解锁小红书搜索、笔记正文与评论；未登录会撞登录墙且只给首屏。',
    'cookie.xiaohongshu.steps': (
        '1. 点「浏览器生成」，在窗口里登录小红书\n2. 打开任意一篇笔记，能看到评论区即可\n3. 回到本面板点「已完成登录」'
    ),
    'cookie.youtube.purpose': (
        '解锁 YouTube 的订阅、播放列表、历史记录与评论；未登录也能看公开视频，但这些页面常被限流或折叠。'
    ),
    'cookie.youtube.steps': (
        '1. 点「浏览器生成」，在弹出的 Chrome 窗口里登录 YouTube（Google 账号）\n'
        '2. 回到 youtube.com 首页，确认右上角已是你的头像\n'
        '3. 回到本面板点「已完成登录」——保存前浏览器会自动回到 YouTube 页面，'
        'Google 账号自身的 Cookie 不会被写进本平台文件'
    ),
    # ── Cookie 用途与获取步骤（面板直接把这些讲给用户） ──────────
    'cookie.zhihu.purpose': '解锁知乎搜索结果与回答、评论正文；未登录时知乎常常只回一个登录引导页。',
    'cookie.zhihu.steps': (
        '1. 点「浏览器生成」，在弹出的 Chrome 窗口里登录知乎（扫码或手机号）\n'
        '2. 随便翻一页，确认右上角已是你的头像\n'
        '3. 回到本面板点「已完成登录」'
    ),
    'cookies.accountDefault': '默认账号',
    'cookies.accountDefaultNumbered': '默认账号{n}',
}

EN = {
    'cap.requiresWindowsDesktop': 'it needs the Windows desktop build (a local player or window to drive)',
    'cookie.allForeign': (
        'Nothing was saved for {platform}: every cookie in that paste belongs to another site — paste the '
        'cookies of this platform itself'
    ),
    'cookie.bilibili.purpose': 'Unlocks Bilibili search, video metadata and comments; logged out, search is '
    'collapsed and only the first few comments show.',
    'cookie.bilibili.steps': (
        '1. Press "Generate via Browser" and sign in to Bilibili in the Chrome window (QR or phone)\n'
        '2. Open any video and scroll to the comment area until the list renders\n'
        '3. Come back here and press "Done \u2014 I logged in"'
    ),
    'cookie.delete.failed': 'Could not delete the cookie file: {err}',
    'cookie.delete.none': 'There is no saved {platform} cookie to delete',
    'cookie.delete.profileHolds': 'Note: {platform}\u2019s browser profile stays logged in — deleting this '
    'file does not sign that device out',
    'cookie.deleted': 'Cookies deleted for {platform}',
    'cookie.deletedAccount': 'Cookies deleted for {platform} (account: {account})',
    'cookie.douyin.purpose': 'Unlocks Douyin web search, video captions and comments; logged out you usually '
    'get only the first screen and no comments.',
    'cookie.douyin.steps': (
        '1. Press "Generate via Browser" and sign in to Douyin web in that window (QR or phone)\n'
        '2. Open any video until the comment panel on the right renders\n'
        '3. Come back here and press "Done \u2014 I logged in"\n'
        'Note: Douyin is quick to raise a slider captcha for automated browsers \u2014 finish it in that '
        'window before saving.'
    ),
    'cookie.droppedForeign': (
        'Ignored {n} cookie(s) that do not belong to {platform}: a login usually passes through a '
        'third-party site, and those cookies do not go into this platform’s file'
    ),
    'cookie.entryRejected': 'That link is not on a {platform} domain, so the platform login page was used instead '
    '(another site\u2019s cookies must never be stored in this platform\u2019s cookie file)',
    'cookie.instagram.purpose': 'Unlocks Instagram profiles, hashtag grids and comments; logged out the page shows '
    'a login wall and its endpoints refuse the request.',
    'cookie.instagram.steps': (
        '1. Press "Generate via Browser" and sign in to instagram.com in that window\n'
        '2. Open any post until the comment area renders\n'
        '3. Come back here and press "Done \u2014 I logged in"\n'
        'Note: if the login detours through Facebook, wait until Instagram is back before saving.'
    ),
    'cookie.jobCancelled': '{platform} login cancelled',
    'cookie.noCookies': 'No cookies captured before the wait ended — retry if the login was unfinished',
    # Saving IS the update now: the paste plants itself into that account's profile, and the
    # /api/cookies/refresh-profile route with its four refusal sentences went away with the
    # button. One case cannot be done on the spot — that browser is held — and it has to say so,
    # because 「saved」 and 「saved but not in the profile」 look identical from a paste box.
    'cookie.plant.deferred': (
        "{platform}'s browser is held by something else (a crawl may be running), so this cookie "
        'could not be planted into its profile yet — it is saved, and the next crawl will bring it in'
    ),
    'cookie.pre.account': ' (account {account})',
    'cookie.pre.busy': "{platform}'s browser is already held by something else",
    'cookie.pre.expired': '{platform} rejected the stored cookie: the page bounced to a login page',
    'cookie.pre.noLogin': '{platform} is crawled without a login',
    'cookie.pre.notCrawlable': '{platform} can hold a cookie but cannot be crawled yet',
    'cookie.pre.notListed': 'Nothing here knows that platform, so nothing was checked: {platform}',
    'cookie.pre.riskControl': 'the page answered with a captcha / risk control',
    'cookie.pre.timeout': 'the check ran past {n} seconds',
    'cookie.pre.unknown': '{platform} could not be checked (that is not a pass, and the run is not blocked)',
    # The pre-run check (preflight). Three conclusions, three next steps: merging
    # any pair would send the user off doing the wrong thing — re-logging in, or waiting.
    'cookie.pre.valid': 'The stored {platform} cookie works',
    'cookie.profileDelete.none': 'There is no browser profile to delete for {platform} · {account}',
    'cookie.profileDeleted': (
        'Deleted the browser profile for {platform} · {account} — that device is signed out; '
        'the saved cookie file is untouched'
    ),
    'cookie.refresh.done': 'Saved {platform} cookies were planted into its browser profile ({n} entries)',
    'cookie.refresh.failed': 'Could not update the profile session: this platform\u2019s browser did not open ({err})',
    # Measured: a cookie without an expiry is never written to the profile store, so it
    # dies with the window that was opened to plant it.
    'cookie.refresh.sessionOnly': 'Note: {n} of them carry no expiry, so they live only in that window and are not '
    'kept by the profile once it closes',
    'cookie.renamed': (
        'Renamed the {platform} login “{old}” to “{new}” (its cookie file and its own browser directory moved together)'
    ),
    'cookie.renamedFileOnly': (
        'Renamed the {platform} login “{old}” to “{new}” — that account has never opened a '
        'browser of its own, so only the cookie file moved'
    ),
    'cookie.saved': 'Cookies saved for {platform}',
    # {account} is already a word by the time it reaches here (blank → "default account",
    # default2 → "default account 2", a typed label verbatim), so the sentence never prints a key.
    'cookie.savedAccount': 'Cookies saved for {platform} (account: {account})',
    'cookie.started': 'Login browser opened — finish the login in that window, then press Done',
    'cookie.twitter.purpose': 'Unlocks X (Twitter) search, user timelines, tweet bodies and replies; logged out '
    'those pages answer with a login wall.',
    'cookie.twitter.steps': (
        '1. Press "Generate via Browser" and sign in to x.com in the Chrome window (password or phone code)\n'
        '2. Open any tweet until the replies render — both auth_token and ct0 have to be present\n'
        '3. Come back here and press "Done \u2014 I logged in"\n'
        'Note: X often asks a new device for one more verification code — finish it in that window before saving.'
    ),
    'cookie.verify.checkedUrl': 'Verified against: {url}',
    'cookie.verify.cloudHeadless': (
        'this host is a windowless server: the check above could only run a HEADLESS browser, and some '
        'sites answer headless with a captcha or a blank page — that is not proof the cookie expired '
        '(verify on a machine with a window to judge the login state itself)'
    ),
    'cookie.verify.loginWall': '{platform} still redirects to a login page: log in again and save',
    'cookie.verify.noCookie': 'No {platform} cookie stored yet: log in and save first',
    'cookie.verify.ok': 'The stored {platform} cookie works',
    'cookie.verify.unclear': '{platform} could not be verified: the page answered with a captcha or risk '
    'control, which says nothing about whether the cookie is valid',
    # The page never came from the site at all, so nothing about the cookie was tested —
    # and 「可用」 here would be cached and reused by every later run.
    'cookie.verify.unreachable': '{platform} could not be verified: the browser never opened this address '
    '(this machine\u2019s network or DNS), so the cookie was not tested',
    'cookie.verifyFailed': 'Verification failed: {err}',
    'cookie.verifying': 'Probing this platform with the stored cookie\u2026',
    'cookie.weibo.purpose': 'Unlocks Weibo search (s.weibo.com) and the comment JSON API; logged out you are '
    'bounced back to the passport QR page. Weibo accepts one live session per account: paging in parallel, '
    'or replaying the same cookie from a second browser, is answered with the login page — so always crawl '
    'from the same profile, and never run two Weibo crawls at once.',
    'cookie.weibo.steps': (
        '1. Press "Generate via Browser" and sign in to Weibo in that window\n'
        '2. Search one keyword and confirm the post list renders\n'
        '3. Come back here and press "Done — I logged in"'
    ),
    'cookie.windowClosed': 'The login window was closed before cookies could be captured; start again',
    'cookie.xiaohongshu.purpose': 'Unlocks Xiaohongshu search, note bodies and comments; logged out you hit the '
    'login wall and only the first screen shows.',
    'cookie.xiaohongshu.steps': (
        '1. Press "Generate via Browser" and sign in to Xiaohongshu in that window\n'
        '2. Open any note and confirm the comment area renders\n'
        '3. Come back here and press "Done — I logged in"'
    ),
    'cookie.youtube.purpose': 'Unlocks YouTube subscriptions, playlists, history and comments; public videos play '
    'without a login, but those pages are throttled or collapsed.',
    'cookie.youtube.steps': (
        '1. Press "Generate via Browser" and sign in to YouTube (a Google account) in the Chrome window\n'
        '2. Return to the youtube.com home page and check your avatar is showing\n'
        '3. Come back here and press "Done \u2014 I logged in" — the browser is pulled back to YouTube first, '
        'so the Google account\u2019s own cookies never land in this platform\u2019s file'
    ),
    # ── cookie purposes and how to obtain them (shown in the panel) ──
    'cookie.zhihu.purpose': 'Unlocks Zhihu search plus answer and comment bodies; logged out, Zhihu often '
    'returns nothing but a login prompt.',
    'cookie.zhihu.steps': (
        '1. Press "Generate via Browser" and sign in to Zhihu in the Chrome window that opens (QR or phone)\n'
        '2. Browse one page and confirm your own avatar is in the top-right\n'
        '3. Come back here and press "Done — I logged in"'
    ),
    'cookies.accountDefault': 'default account',
    'cookies.accountDefaultNumbered': 'default account {n}',
}
