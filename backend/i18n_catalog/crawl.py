"""The crawl itself: what a walk reports row by row, what each platform's wall and risk page
say, and what the machine must have for a browser to exist at all.

Part of the zh/en message catalogue, merged by ``backend/i18n.py`` — the ``t()`` machinery,
the thread-local language and the audit live there, so this module is data with no imports.
Keys are sorted; the two tables in here must hold the same set (``tests/unit/i18n/test_i18n.py``).
"""

ZH = {
    'crawl.bili.authorDone': '[哔哩哔哩] 投稿列表采集结束，共 {n} 条（原因：{reason}）',
    'crawl.bili.authorEmpty': '[哔哩哔哩] 没有填写 UP主（space.bilibili.com 链接或数字 mid）：{author}',
    'crawl.bili.authorNoVideos': '[哔哩哔哩] UP主 {mid} 的投稿列表没有渲染出视频（可能真的没投过稿）',
    'crawl.bili.authorStart': '[哔哩哔哩] 采集 UP主 {mid} 的投稿视频，目标 {n} 条',
    'crawl.bili.blocked': (
        '[哔哩哔哩] 接口拒绝返回数据（code={code}）：Cookie 可能已失效或触发了风控，'
        '请在 Cookie 面板重新登录并保存后继续运行'
    ),
    'crawl.bili.boardPopular': '热门榜',
    'crawl.bili.boardRanking': '周排行榜',
    'crawl.bili.duplicate': '[哔哩哔哩搜索] {i} 已存在于本次运行，跳过',
    'crawl.bili.empty_page': '[哔哩哔哩搜索] 第 {page} 页没有视频卡片，停止翻页',
    'crawl.bili.fetchEmpty': '[哔哩哔哩搜索] {i} 的稿件接口没有返回可读数据（非 JSON 或被 WAF 拦截），跳过这一条',
    'crawl.bili.finished': '[哔哩哔哩搜索] 搜索完成，共获取 {n} 条有效结果（目标 {total} 条）',
    'crawl.bili.goneVideo': '[哔哩哔哩搜索] {i} 稿件不存在或已失效（{code}），跳过这一条',
    'crawl.bili.hotDone': '[哔哩哔哩] 榜单采集结束，共 {n} 条（目标 {total} 条）',
    'crawl.bili.hotPage': '[哔哩哔哩] 榜单第 {page} 页：{n} 条（新 {fresh} 条，已收录 {done} 条）',
    'crawl.bili.hotStart': '[哔哩哔哩] 采集{board}，目标 {n} 条（榜单接口自带全部数字，不逐条请求）',
    'crawl.bili.no_more': '[哔哩哔哩搜索] 连续两页都是已抓过的视频，列表已到末尾（第 {page} 页）',
    'crawl.bili.page': '[哔哩哔哩搜索] 第 {page} 页：{n} 个视频（新 {fresh} 个，已收录 {done} 条）',
    'crawl.bili.processed': '[哔哩哔哩搜索] 已收录 {i}，当前有效数据: {n} 条',
    'crawl.bili.rankingCapped': '[哔哩哔哩] {board}本次只有 {n} 条（目标 {total} 条）：榜单大小由站点决定',
    'crawl.bili.start': '[哔哩哔哩搜索] 开始搜索关键词: "{kw}"，目标获取 {n} 条结果',
    'crawl.bili.target_reached': '[哔哩哔哩搜索] 已达到目标数量 {n} 条，停止翻页',
    'crawl.bili.url': '[哔哩哔哩搜索] 搜索URL: {url}',
    'crawl.bili.watermarkHit': '[哔哩哔哩] 遇到上次完成的边界 {i}，停止继续翻页',
    'crawl.browserBinaryMissing': '设置里的浏览器路径不存在：{path}。改正它，或清空让程序自己找 Chrome',
    'crawl.browserStartFailed': (
        '浏览器没有启动：{err}。常见原因是 chromedriver 与 Chrome 版本不匹配、'
        '首次自动取驱动需要联网、或该 Chrome 配置目录正被另一个 Chrome 占用'
    ),
    'crawl.chromeMissing': (
        '本机没有可用的 Chrome，采集打不开浏览器。安装 Chrome，'
        '或在「设置 → 浏览器路径」里指向它（本系统的可执行名：{browser}）'
    ),
    'crawl.cnki.emptyRecord': '[知网] 导出页有一条 RefWorks 记录没有题名，按导入器规则跳过',
    'crawl.cnki.downloadFailed': '[知网] 导出题录文件没有下载成功：{err}',
    'crawl.cnki.exportBatch': '[知网] 已导出本次选择 {n} 篇（第 {first}-{last} 页）',
    'crawl.cnki.exportForbidden': '[知网] 导出页被站点拒绝（{err}）：无头模式常被拒绝，请改用窗口模式并确认登录',
    'crawl.cnki.exportEmpty': '[知网] 导出页没有返回任何 RefWorks 记录（可能未登录或该批次无数据）',
    'crawl.cnki.finished': '[知网] 检索结束，共导出 {n} 篇（目标 {total} 篇）',
    'crawl.cnki.loginNeeded': '[知网] 导出前需要登录：请在 Cookie 面板保存知网登录（或机构 IP 权限）后再试',
    'crawl.cnki.noExportIds': '[知网] 结果行没有导出键（页面结构可能变了）：拒绝交空表，请先更新选择器',
    'crawl.cnki.noExportButton': '[知网] 导出页找不到「导出题录文件」按钮（{err}）',
    'crawl.cnki.noExportMenu': '[知网] 结果页找不到「导出文献」菜单（{err}）：页面结构可能变了',
    'crawl.cnki.noExportWindow': '[知网] 点了导出但没有打开导出窗口（可能被浏览器拦截，或会话不被接受）',
    'crawl.cnki.noPage': '[知网] 检索结果页没有出现（页面可能仍在加载、被拦截，或站点改了布局）',
    'crawl.cnki.noResults': '[知网] 检索 "{kw}" 没有结果（站点自己写 0 条）',
    'crawl.cnki.nothingSelected': '[知网] 勾选后站点的已选数为 0，导出被拒绝',
    'crawl.cnki.selectPage': '[知网] 第 {page} 页全选 {n} 条（累计已选 {selected} 条）',
    'crawl.cnki.pageError': '[知网] 检索页操作失败：{err}',
    'crawl.cnki.selectFailed': '[知网] 勾选文献失败：{err}',
    'crawl.cnki.start': '[知网] 开始检索 "{kw}"，目标 {n} 篇文献',
    'crawl.cnki.target_reached': '[知网] 已达到目标 {n} 篇，停止翻页',
    'crawl.cnki.verifyRequired': (
        '[知网] 站点要求安全验证（滑块）：请在 Cookie 面板「浏览器生成」里完成验证并保存登录，然后重试'
    ),
    'crawl.cookiesSeeded': 'Cookie 预置：{host} 接受 {n}/{total} 条',
    # ── 爬虫内部的调试信息 ────────────────────────────────────
    # 这些走 logging.debug，默认级别下不打印；仍走 i18n，别让控制台里
    # 混进写死的中文/英文。
    'crawl.cookies_failed': '{platform}：载入 Cookies 失败（{err}），本次爬取可能因未登录而结果为空',
    'crawl.debug.author_missing': '未找到作者/公众号元素',
    'crawl.debug.card_author': '卡片 {i}：发布者="{v}"',
    'crawl.debug.card_images': '卡片 {i}：图片={n} 张',
    'crawl.debug.card_len': '卡片 {i}：正文长度={v}',
    'crawl.debug.card_metrics': '卡片 {i}：转发={f} 评论={c} 点赞={l}',
    'crawl.debug.card_skip': '卡片 {i}：跳过（无发布者）',
    'crawl.debug.card_time': '卡片 {i}：发布时间="{v}"',
    'crawl.debug.comment_item': '第 {i} 条评论：{author} - {text}...',
    'crawl.debug.comments_missing': '评论区域未加载或不存在',
    'crawl.debug.content_missing': '未找到正文元素',
    'crawl.debug.content_retry': '正文未提取到，稍后重试一次',
    'crawl.debug.pager_missing': '未检测到分页按钮，只有一页',
    'crawl.debug.time_missing': '未找到发布时间元素',
    'crawl.debug.title_missing': '未找到标题元素',
    'crawl.disguisePartial': (
        '无头浏览器的伪装只应用了一部分（{err}）。这次可能仍以无头指纹被站点识别，行数偏少时先按这条排查'
    ),
    'crawl.disguiseUnreadable': (
        '无头浏览器的伪装没有生效：读不到自己的 User-Agent（{err}）。'
        '这次将以「裸无头」继续，部分站点会给出一张没有内容的空页'
    ),
    # Said by a session whose browser process was already reaped, so it must not claim a person did
    # anything: the same object answers a cookie window that was closed after its grace ran out.
    'crawl.driverDead': '这个浏览器进程已经关掉了，不再向它发送命令',
    'crawl.driverMissing': (
        '设置里的 chromedriver 路径不存在：{path}。'
        '它多半是与当前 Chrome 版本不匹配而失效了：换成匹配的驱动，'
        '或清空该设置让 Selenium 自己取（首次需要联网）'
    ),
    'crawl.dy.authorDone': '[抖音作者] 作品列表采集结束，共 {n} 条（主页自报 {works} 条）',
    'crawl.dy.authorDoneNoCount': '[抖音作者] 作品列表采集结束，共 {n} 条（主页未给出作品数，无法判断是否已到末尾）',
    'crawl.dy.authorEmpty': '[抖音作者] 没有给出作者（粘贴 douyin.com/user/… 链接或那串 sec_uid）：{author}',
    'crawl.dy.authorNoCards': (
        '[抖音作者] 该作者主页始终没有渲染出作品列表，本次未采集。页面自报：{page}；地址：{url}。'
        '主页自报作品数 {works} 条，所以这是被拦截或页面出错，不是「这个人没发过作品」'
    ),
    'crawl.dy.authorNoWorks': '[抖音作者] 该作者的主页自报作品数为 0，本就没有可采集的内容',
    'crawl.dy.authorNotMounted': (
        '[抖音作者] 该作者主页既没有渲染出作品列表、也没有给出作品数，本次未采集。'
        '页面自报：{page}；地址：{url}。这两种缺省同时出现只可能是被拦截或页面出错'
    ),
    'crawl.dy.authorStart': '[抖音作者] 开始采集该作者的作品，目标 {n} 条（计数在同页遮罩里逐条点开取，不整页跳转）',
    'crawl.dy.detailEmpty': '[抖音] 视频 {i} 的详情页没有渲染出数据，已跳过该行',
    'crawl.dy.detailNoIdentity': (
        '[抖音] 视频 {i} 的详情页只渲染出计数条，作者与发布时间都没有，已跳过该行：'
        '一条说不出是谁、什么时候发的记录不是数据，只是把额度花在一个空行上'
    ),
    'crawl.dy.detailSlow': (
        '[抖音] 视频 {i} 的详情页在加载超时内没加载完，已跳过该行：这是网络或站点响应慢，稍后重试可能就拿到了'
    ),
    'crawl.dy.detailSwapped': (
        '[抖音] 要打开的是 {i}，浏览器却给了另一条视频 {shown}（站点自己换了内容）'
        ' —— 这一行不入库：宁可少一行，也不把别人的文案和计数挂在这个链接下'
    ),
    'crawl.dy.detailWalled': (
        '[抖音] 视频 {i} 这一条被站点挡在「验证码中间页」（图文页在这台设备上就是这样，视频页不受影响）'
        '，已跳过该行：它不是「站点没内容」，也不是登录态失效'
    ),
    'crawl.dy.hotCapped': '[抖音热榜] 榜单本次只有 {board} 条，已按实际条数收尾（榜单大小由网站决定）',
    'crawl.dy.hotDone': '[抖音热榜] 榜单采集结束，共 {n} 条（目标 {total} 条）',
    'crawl.dy.hotRefused': '[抖音热榜] 榜单接口没有给出榜单（返回 {answer}）',
    'crawl.dy.hotStart': '[抖音热榜] 开始采集热榜，目标 {n} 条（榜单一次给全，不逐条打开）',
    'crawl.dy.hotTarget': '[抖音热榜] 已采集到目标 {n} 条，不再读取榜单',
    'crawl.dy.hotWall': '[抖音热榜] 打开榜单页时被挡在「验证码中间页」，本次未采集：请先在 Cookie 面板登录并保存抖音',
    'crawl.dy.modalDeferred': (
        '[抖音] 有 {n} 条作品卡片的遮罩打不开、本轮跳过：这不是「没有更多了」，是读不到，稍后可重试'
    ),
    'crawl.dy.noMore': (
        '[抖音] 列表自己写了「暂时没有更多了」：翻了 {screens} 屏，最后一屏 {cards} 张卡片，'
        '这一轮的供给就到这儿（不是滚动没生效）'
    ),
    # The one refusal on this page that needs no waiting and no probing: the document is
    # the browser's own, and it says which address it refused.
    'crawl.dy.noPageRefused': '[抖音] 浏览器自己拒绝了这一页，因此不可能有卡片：{url}{detail}',
    'crawl.dy.processed': '[抖音] 已收录视频 {i}，当前有效数据: {n} 条',
    'crawl.dy.round': '[抖音] 第 {i} 屏：{n} 张卡片（新 {fresh} 个，已收录 {done} 条）',
    'crawl.dy.target_reached': '[抖音] 已达到目标数量 {n} 条，停止',
    'crawl.dy.wall': (
        '[抖音] 浏览器被挡在「验证码中间页」：抖音网页版对无头浏览器与频繁请求都会弹验证。'
        '请确认已在 Cookie 面板用「可见窗口」登录并保存，稍后再重试本关键词'
    ),
    'crawl.hg.boardAiDrama': 'AI剧热播榜',
    'crawl.hg.boardComicDrama': '漫剧热播榜',
    'crawl.hg.boardHotDrama': '热播榜',
    'crawl.hg.boardRealDrama': '真人剧热播榜',
    'crawl.hg.boardUnknown': '[红果短剧] 没有这个榜单：{board}（可选：{options}）',
    'crawl.hg.cmt.caInstalled': '[红果短剧] 已把 mitmproxy 根证书装入当前用户受信任的根（播放器解密需要）',
    'crawl.hg.cmt.caNotTrusted': (
        '[红果短剧] mitmproxy 根证书未受信任且自动安装未成功。手动命令（PowerShell）：{command}'
    ),
    'crawl.hg.cmt.danmakuSkipped': '[红果短剧] 丢弃 {n} 条弹幕引导行（它们不是评论）',
    'crawl.hg.cmt.dramaNotFound': '[红果短剧] 在播放器里搜不到这部剧：{title}',
    # A drama the client would not open steps aside and is named; only a run that never
    # reached what the site counted is a failure, and the node says so at the end.
    'crawl.hg.cmt.dramaSkipped': (
        '[红果短剧] 界面树始终没有唤醒，本次跳过这部剧：{title}（点一下播放器窗口后「继续」可补采）'
    ),
    'crawl.hg.cmt.episode': '[红果短剧] 第 {n}/{total} 集：{have} 条评论（站点报 {site_total} 条）',
    'crawl.hg.cmt.episodeShort': (
        '[红果短剧] 《{title}》第 {ep} 集只拿到 {have} 条，站点报 {site_total} 条——该集不完整'
    ),
    # Named because the player's own feed walks away from the drama we entered: measured
    # 2026-10-20, after the first ↓ every following page belonged to the show the account had
    # been watching, and those rows would have been filed under the requested 剧名.
    'crawl.hg.cmt.feedDrifted': (
        '[红果短剧] 《{title}》走到第 {ep} 集时播放流已切到另一部剧（book {book}），'
        '该剧余下的集数不再尝试——已收的行属于所请求的剧'
    ),
    'crawl.hg.cmt.finished': '[红果短剧] 评论收割结束，共 {n} 行（{episodes} 集）',
    'crawl.hg.cmt.groupMismatch': '[红果短剧] 收到的评论页属于 {got} 而不是所请求的 {want}，已丢弃',
    'crawl.hg.cmt.groupShort': (
        '[红果短剧] 分集 {group}（第 {ep} 集）只拿到 {have} 条，站点报 {site_total} 条——该集不完整'
    ),
    'crawl.hg.cmt.needsExtras': (
        '[红果短剧] 评论收割是 Windows 桌面功能，'
        '本机缺少 {missing}（按 requirements-optional.txt 安装；云端模式不可用）'
    ),
    'crawl.hg.cmt.needsExtrasFrozen': (
        '[红果短剧] 桌面版未打包 {names}：评论收割要 mitmdump 与驱动桌面窗口的 UI Automation，只能在源码版运行该节点'
    ),
    'crawl.hg.cmt.noMitmdump': (
        '[红果短剧] 找不到 mitmdump（{detail}）——安装：pip install mitmproxy（见 requirements-optional.txt）'
    ),
    'crawl.hg.cmt.noPlayer': (
        '[红果短剧] 找不到红果短剧桌面播放器（{path}）——请在 设置 › 红果播放器路径 填写它的 exe 位置'
    ),
    'crawl.hg.cmt.noTraffic': (
        '[红果短剧] 等待 {seconds} 秒没有收到这一集的评论页（{title}）——播放器可能未登录、被弹窗挡住或版本过旧'
    ),
    'crawl.hg.cmt.off': '关',
    'crawl.hg.cmt.on': '开',
    'crawl.hg.cmt.playerBusy': (
        '[红果短剧] 红果播放器已经开着且不走本工具的代理——请先关闭它，本节点会自己带代理启动播放器'
    ),
    'crawl.hg.cmt.repliesExpanded': '[红果短剧] 已展开 {n} 处子回复',
    'crawl.hg.cmt.replyPage': '[红果短剧] 楼层 {floor} 的子回复：{n} 条',
    # Said because an expanded child thread prints its own total, and the walk clicks 展开 once
    # per thread: without this line a thread the site counts at 200 children and delivers 20
    # would still let the node claim the site said it was done.
    'crawl.hg.cmt.replyShort': (
        '[红果短剧] 第 {floor} 楼的子回复只收到 {have} 条，站点报 {site_total} 条——该楼子回复不完整'
    ),
    # Emitted per board during the search, so a drama that is absent from the client reads as
    # "working through the boards", not as a frozen window (the not-found case grinds every
    # board×scroll before dramaSkipped fires — without this line the user saw no progress).
    'crawl.hg.cmt.scanningBoard': '[红果短剧] 在《{label}》里查找《{title}》…',
    # Said from the SCREEN, not the traffic: the player prints the drama it is showing as
    # ``@剧名`` in its header. Asking that before harvesting keeps another show's comments out
    # of this table when a card click lands elsewhere or a ↓ walks off into the account's own
    # queue. The episode counter is NOT readable while the drawer is open (measured), so no
    # message here claims a position the walk cannot see.
    'crawl.hg.cmt.screenMismatch': (
        '[红果短剧] 屏幕上正在播的是《{have}》，不是所请求的《{want}》——本剧到此不再往下采'
        '（已收下的行仍属于所请求的剧；这不是搜不到，是播放器没把这部剧放在台上）'
    ),
    # ─── 评论收割（桌面播放器 + 本地代理；机制见 docs/crawler_notes.md 红果短剧）───
    'crawl.hg.cmt.start': '[红果短剧] 开始收割评论：{title}（{episodes} 集，子回复{replies}）',
    'crawl.hg.cmt.titleMissing': '[红果短剧] 详情页没有打印剧名，播放器里不知道该搜什么：{url}',
    'crawl.hg.cmt.treeCold': (
        '[红果短剧] 播放器窗口已打开，但界面树迟迟没有建立（WebView2 可访问性未唤醒）。'
        '用鼠标点一下播放器窗口再重跑本节点'
    ),
    'crawl.hg.finished': '[红果短剧] 采集结束，共 {n} 条（目标 {total} 条）',
    'crawl.hg.lastPage': '[红果短剧] 第 {page} 页是站点给出的最后一页，不再翻页（已收录 {n} 条）',
    'crawl.hg.noBoard': (
        '[红果短剧] 等待 {seconds} 秒后这一页仍没有榜单数据（页面上的数据键：{keys}）：{url}'
        '——可能是站点改版或网络没有把这一页送到'
    ),
    'crawl.hg.noDetail': '[红果短剧] 该平台没有「按链接采集」的模式，也还没有测量过详情页读取（{url}）',
    'crawl.hg.noFresh': '[红果短剧] 连续两页都没有新条目（第 {page} 页），翻页停住：按未采满处理',
    'crawl.hg.noPageRefused': '[红果短剧] 浏览器自己拒绝了这一页，因此不可能有榜单数据：{url}{detail}',
    'crawl.hg.page': '[红果短剧] 第 {page} 页：{n} 条（新 {fresh} 条，已收录 {done} 条）',
    'crawl.hg.replay': '[红果短剧] 第 {page} 页的「下一页」指回了当前地址（{url}），翻页停住：按未采满处理',
    'crawl.hg.searchUnsupported': '[红果短剧] 该站点只提供四个热播榜单，没有关键词搜索（收到关键词：{keyword}）',
    'crawl.hg.start': '[红果短剧] 开始采集{board}，目标 {n} 条（翻页只走站点自己给出的下一页地址）',
    'crawl.hg.target_reached': '[红果短剧] 已采集到目标 {n} 条，不再翻页',
    # Observation only — never a claim about what the crawl then did. This line is
    # written by ``check_login_wall``, which cannot know the caller's policy: weibo
    # and zhihu stop, while WeChat's batch skips that one article and carries on to
    # the next. Saying 「已停止本次抓取」 there told the user their batch had ended.
    # The stop, when it happens, is announced by the node refusing with
    # ``run.cookieExpired``, which also says what to do about it.
    'crawl.loginWall': '登录墙：{platform} 的 {where} 被重定向到登录页',
    'crawl.platformNotCrawlable': '该平台目前只支持保存登录 Cookie，还不支持采集（{platform}）——'
    '请先改用已支持的平台，或等待该平台的抓取实现完成',
    'crawl.profile_gave_up': '本次运行已停止：不再等待该 profile（{dir}），这次采集就此让路',
    'crawl.profile_stuck': (
        '等待 profile 释放超时（{seconds} 秒）：{dir} —— 可能有浏览器没被关闭，请在进程面板结束残留的 Chrome 后重试'
    ),
    'crawl.profile_wait': '已排队 {seconds} 秒：这个 profile 同时只能开一个浏览器，{dir}',
    'crawl.promptDismissed': '{label} 的首屏弹窗已自动点掉：「{button}」',
    'crawl.promptUnmatched': '{label} 的首屏弹窗无法对应按钮（页面提供：{buttons}），本次可能需等待其自动消失',
    'crawl.redrive': '页面没落到站点（停在 {where}），重发一次导航',
    # ── 断点续跑与去重（爬虫侧） ──────────────────────────────
    'crawl.resume_have': '断点续跑：已采集 {n} 条，接着往下采而不是重来',
    'crawl.riskBlocked': '风控拦截：{platform} 的 {where} 返回了安全验证而非内容（会话未必失效，稍后重试）',
    'crawl.sink_failed': '增量落盘失败（这条仍然在本次结果里，但可能没进库）：{err}',
    'crawl.stopReason.empty_page': '某一页是空的',
    'crawl.stopReason.end': '已到列表末尾',
    'crawl.stopReason.fetch_failed': '列表接口取数失败',
    'crawl.stopReason.no_cards': '页面没有渲染出列表',
    'crawl.stopReason.no_new': '翻了几页都没有新条目',
    'crawl.stopReason.risk': '站点风控拦住了后面的窗口（不是 Cookie 失效）',
    'crawl.stopReason.stopped': '用户停止了运行',
    'crawl.stopReason.stuck': '连续滚动没有新内容出现',
    # Why a crawl walk stopped, said to the user (engine/feed.py and engine/pager.py return the
    # machine token; stop_reason_label() maps it to one of these).
    'crawl.stopReason.target': '达到目标条数',
    'crawl.stopReason.unreachable': '浏览器根本没取到页面（网络或域名不可达，站点从未见到这个会话）',
    'crawl.stopReason.wall': '登录墙拦住了后面的窗口',
    'crawl.stopped': '收到「停止」，本次抓取到此为止',
    # Neither of the two above: the browser wrote this page itself, so the site never saw
    # the request and the session is not the thing in question.
    'crawl.unreachable': '浏览器自己拒绝了这次访问：{platform} 的 {where}{detail}',
    'crawl.unreachableToken': '（{token}）',
    'crawl.wechat.author': '作者（公众号）: {author}',
    'crawl.wechat.batch_done': '批量抓取完成：{n} / {total} 篇成功',
    'crawl.wechat.batch_start': '开始批量抓取 {n} 篇微信公众号文章',
    'crawl.wechat.content_len': '正文长度: {n} 字',
    'crawl.wechat.duplicate': '跳过重复的推文链接：{url}',
    'crawl.wechat.extracting': '正在提取文章字段',
    'crawl.wechat.failed': '第 {i}/{total} 篇抓取失败：正文没有取到',
    'crawl.wechat.loaded': '文章页面加载成功',
    'crawl.wechat.navigating': '正在打开文章链接',
    'crawl.wechat.no_content': '重试后仍未找到正文元素。',
    # ── crawlers: wechat ──────────────────────────────────────
    'crawl.wechat.no_urls': '未提供 URL，返回空结果。',
    'crawl.wechat.preview': '正文预览: {preview}',
    'crawl.wechat.processing': '正在抓取第 {i} / {total} 篇',
    'crawl.wechat.pub_time': '发布时间: {time}',
    'crawl.wechat.scroll': '滚动到底部以触发懒加载',
    'crawl.wechat.scroll_done': '滚动完成',
    # No 阅读/点赞/打赏: WeChat publishes none of the three to a browser that is not
    # the client (measured), so a line naming them would be a column with a plausible
    # face and no source — and this template once printed its own placeholders,
    # because the call site passed four keywords and the text asked for seven.
    'crawl.wechat.success': '第 {i}/{total} 篇已抓取：《{title}》（{author}）',
    'crawl.wechat.timeout': '页面加载超时: {url}',
    'crawl.wechat.title': '标题: {title}',
    'crawl.wechat.url': 'URL: {url}',
    'crawl.wechat.wait': '等待 1 秒后继续下一篇',
    'crawl.wechat.wait_title': '等待文章标题 (#activity-name) 加载',
    'crawl.weibo.accumulated': '当前累计数据: {n} 条',
    'crawl.weibo.authorDone': '作者作品采集结束：{n} 条（{reason}）',
    'crawl.weibo.authorEmpty': '「{author}」不是微博作者地址：填 weibo.com/u/<UID> 主页链接或数字 UID',
    'crawl.weibo.authorMirror': (
        'UID {uid} 的答复第一行不属于该作者——接口给的是首页时间线而不是作者作品，拒绝张冠李戴'
    ),
    'crawl.weibo.authorNoPosts': 'UID {uid} 没有返回任何作品：这个账号可能确实没发过微博',
    'crawl.weibo.authorRefused': (
        'mymblog 接口拒绝应答（状态 {status}，UID {uid}）：这是按会话的限流，Cookie 可能并未失效，请稍后再试'
    ),
    'crawl.weibo.authorStart': '开始采集作者 {uid} 的作品，目标 {n} 条',
    'crawl.weibo.authorWall': '微博把 UID {uid} 的主页弹回了登录页：这个会话进不去作者页',
    # ── 参数校验 / 接口错误（会直接显示在提示条里） ────────────
    'crawl.weibo.bad_date': '日期格式不对：{value}（应为 YYYY-MM-DD）',
    'crawl.weibo.bad_range': '结束时间（{end}）必须晚于开始时间（{start}）',
    'crawl.weibo.card_error': '    卡片 {i}: 处理出错，已跳过',
    'crawl.weibo.hotCapped': '热搜榜本次只有 {board} 条，已按实际条数收尾（榜单大小由网站决定）',
    'crawl.weibo.hotDone': '热搜采集结束：{n} 条（目标 {total} 条）',
    # Said when the request was never issuable: the browser was left on a frame that is not weibo.com, so
    # the same-origin fetch had no host to ask. Blaming the endpoint there would convict it of an answer
    # it never gave.
    'crawl.weibo.hotNoHost': '微博热搜未采集：浏览器还停在「{where}」，没回到 weibo.com（访客引导未完成，'
    '页面内请求发不出去；这是到场帧的问题，不是接口拒绝）',
    'crawl.weibo.hotRefused': '微博热搜接口没有给出榜单（返回 {answer}）',
    # 热搜: one answer is the whole board, so the three lines below are the only
    # things this mode can honestly say.
    'crawl.weibo.hotStart': '开始采集微博热搜，目标 {n} 条',
    # ── crawlers: weibo ───────────────────────────────────────
    'crawl.weibo.keyword': '关键词: {kw}',
    'crawl.weibo.keyword_plain': '关键词: {kw}（无时间范围，单链接搜索）',
    'crawl.weibo.link_done': '第 {i} 个链接爬取完成，获取 {n} 条数据',
    'crawl.weibo.link_error': '处理搜索链接时出错: {err}',
    'crawl.weibo.links': '共生成 {n} 个搜索链接（每小时1个）',
    'crawl.weibo.max_page': '最大页码: {n}',
    'crawl.weibo.navSettled': '已完成',
    'crawl.weibo.navUnsettled': '未完成，那是慢网络而不是站点的拒绝',
    'crawl.weibo.need_both_dates': '开始时间与结束时间必须同时填写（只填一个会被忽略，搜索范围会完全不同）',
    'crawl.weibo.no_result': '该时间段无搜索结果，跳过',
    'crawl.weibo.page_cards': '    本页共发现 {n} 个卡片',
    'crawl.weibo.page_crawling': '  正在爬取第 {i}/{total} 页...',
    'crawl.weibo.page_done': '  第 {i} 页爬取完成，共 {n} 条，累计 {total} 条',
    'crawl.weibo.page_empty': '  第 {i} 页无有效卡片，跳过',
    'crawl.weibo.page_gave_up': (
        '    这台浏览器已经有 {waits} 个搜索页一次内容都没交付：不再把整段预算花在新的窗口上'
        '（这是「取不到页面」，不是「这个窗口没有内容」）'
    ),
    'crawl.weibo.page_loaded': '页面加载完成',
    'crawl.weibo.page_timeout': (
        '    等了 {secs} 秒：这一页既没有给出卡片，也没有给出「无结果」牌（导航{settled}）'
        '—— 这一句只说代码看得见的东西，不能据此断定窗口里没有内容'
    ),
    'crawl.weibo.pages_fail': '获取总页数失败: {err}',
    'crawl.weibo.processing': '正在处理第 {i}/{total} 个搜索链接',
    'crawl.weibo.range': '时间范围: {start} 至 {end}',
    'crawl.weibo.target_reached': '已达到目标数量 {n} 条，停止翻页',
    'crawl.weibo.total_pages': '检测到总页数: {n}',
    'crawl.weibo.url': 'URL: {url}',
    'crawl.weibo.visiting': '访问搜索链接: {url}',
    'crawl.weibo.waiting': '等待页面加载...',
    'crawl.weibo.walk_done': '微博搜索收尾：{n} 条（目标 {target}，窗口走到第 {walked}/{total} 个，原因：{reason}）',
    'crawl.x.authorEmpty': '[X] 没有填写作者（@handle 或主页链接）：{author}',
    'crawl.x.authorStart': '[X] 作者「{author}」的推文，目标 {n} 条',
    'crawl.x.finished': '[X] 共保留 {n} 条（结束原因：{reason}）',
    'crawl.x.loadSlow': '[X] 页面未在预期时间内加载完，已按当前 DOM 继续：{url}',
    'crawl.x.no_cards': '[X] 时间线里一条推文都没有渲染出来（被拦截、关键词过窄或账号无推文）：{url}',
    # X（推特）只渲染一个虚拟列表：卡片数不增长而推文一直换血，所以它的日志说
    # 「留住了多少」，不说「页面上有几张卡」。
    'crawl.x.start': '[X] 关键词「{kw}」，目标 {n} 条（最新优先）',
    'crawl.x.target_reached': '[X] 已达目标 {n} 条，停止滚动',
    'crawl.x.wall': '[X] 被拒绝访问（登录墙或 403）：{url}',
    'crawl.xhs.author': '[爬取详情] 作者: {author}',
    'crawl.xhs.collect_done': '[收集链接] 收集完成，共 {n} 条链接',
    'crawl.xhs.comment_count': '[爬取详情] 评论列表: {n} 条',
    'crawl.xhs.comment_done': '[提取评论] 共提取 {n} 条评论',
    'crawl.xhs.comment_error': '[提取评论] 提取第 {i} 条评论时出错: {err}',
    'crawl.xhs.comment_found': '[提取评论] 共找到 {n} 个评论元素',
    'crawl.xhs.comment_skip': '[提取评论] 预览数=0，跳过评论面板（不等待）',
    'crawl.xhs.comment_start': '[提取评论] 开始提取评论，最多 {n} 条',
    'crawl.xhs.content_len': '[爬取详情] 正文长度: {n} 字',
    'crawl.xhs.deadNote': '[详情] 笔记被安全验证挡住（非会话失效），跳过：{url}',
    'crawl.xhs.detail_ready': '[爬取详情] 详情页加载完成',
    'crawl.xhs.detail_timeout': '[爬取详情] 详情页加载超时',
    'crawl.xhs.detail_visit': '[爬取详情] 正在访问详情页: {url}',
    'crawl.xhs.finished': '[小红书搜索] 搜索完成，共获取 {n} 条有效笔记数据',
    'crawl.xhs.links': '[小红书搜索] 共收集到 {n} 条笔记链接',
    'crawl.xhs.metrics': '[爬取详情] 互动数据 - 点赞: {likes}, 收藏: {favs}, 评论数: {comments}',
    'crawl.xhs.note_dup': '跳过重复的笔记：{url}',
    'crawl.xhs.note_error': '[小红书搜索] 处理笔记时出错: {err}',
    'crawl.xhs.note_ok': '[小红书搜索] 成功提取: {title}...',
    'crawl.xhs.page_ready': '[小红书搜索] 初始搜索结果页加载完成',
    'crawl.xhs.page_timeout': '[小红书搜索] 初始内容加载超时，可能没有搜索结果，将继续尝试滚动',
    'crawl.xhs.pub_time': '[爬取详情] 发布时间: {time}',
    # ── crawlers: xiaohongshu ─────────────────────────────────
    'crawl.xhs.start': '[小红书搜索] 开始搜索关键词: "{kw}"，目标数量: {n}',
    'crawl.xhs.target_reached': '[收集链接] 已达到目标数量 {n}，停止加载',
    'crawl.xhs.untitled': '无标题',
    'crawl.xhs.url': '[小红书搜索] 已访问搜索URL: {url}',
    'crawl.yt.authorEmpty': '[YouTube] 没有填写作者（@handle、频道链接或 UC… ID）：{author}',
    'crawl.yt.authorNoVideos': '[YouTube] 该作者的视频页没有作品：{author}',
    'crawl.yt.authorNotFound': '[YouTube] 该地址不是频道主页，读不到频道 ID：{author}',
    'crawl.yt.authorStart': '[YouTube] 作者「{author}」的作品，目标 {n} 条',
    'crawl.yt.badAnswer': '[YouTube] {endpoint} 返回 {status}，非 JSON',
    'crawl.yt.callFailed': '[YouTube] {endpoint} 接口调用失败',
    'crawl.yt.drained': '[YouTube] 接口不再给出下一页游标，列表已到末尾',
    'crawl.yt.finished': '[YouTube] 本次共采集 {n} 条（目标 {total} 条）',
    # YouTube is crawled as JSON from inside its own page, so its console lines
    # talk about rounds and answers, not about scrolling a list.
    'crawl.yt.noContext': '[YouTube] 页面未提供 innertube 配置（被拦截或结构已变）：{url}',
    'crawl.yt.noPage': '[YouTube] 第 {page} 轮没有返回条目，停止翻页',
    'crawl.yt.noResults': '[YouTube] 关键词「{kw}」没有匹配的公开视频（或本次会话被限制）',
    'crawl.yt.page': '[YouTube] 第 {page} 轮：{n} 条（{fresh} 条新增，已采 {done}）',
    'crawl.yt.processed': '[YouTube] 已存第 {i} 条：{title}',
    'crawl.yt.replay': '[YouTube] 第 {page} 轮没有新增，判定列表已耗尽',
    'crawl.yt.searchStart': '[YouTube] 关键词「{kw}」，目标 {n} 条',
    'crawl.yt.targetReached': '[YouTube] 已达目标 {n} 条，停止采集',
    'crawl.yt.wall': '[YouTube] 触发了人机验证页：{url}',
    'crawl.zhihu.authorEmpty': '[知乎] 没有填写作者（主页链接或 /people/ 后面的 id）：{author}',
    'crawl.zhihu.authorStart': '[知乎] 采集作者「{author}」的回答与文章，目标 {n} 条',
    'crawl.zhihu.authorTabDone': '[知乎] 「{tab}」标签页采集结束，累计 {n} 条（原因：{reason}）',
    'crawl.zhihu.authorTabEmpty': '[知乎] 作者「{author}」的「{tab}」标签页没有内容（这类作品他确实没发过），跳过',
    'crawl.zhihu.bodies_short': '另有 {n} 条回答未能展开，其正文仍为搜索页摘要',
    'crawl.zhihu.duplicate': '跳过重复的第 {i} 条回答',
    'crawl.zhihu.emptyOrBlocked': (
        '知乎搜索页未返回任何结果（触发风控/登录墙或页面失效）：'
        '请在执行设置中关闭无头模式，或稍后重试；已采集的数据不受影响'
    ),
    # One fact, one line: what the 正文 column actually holds. The search page only ever
    # carries an excerpt, so a crawl that did not expand has to say so once at the end.
    'crawl.zhihu.excerpt_only': '未展开正文：本次所有正文都是搜索页摘要（可在数据源节点勾选「展开全文」）',
    'crawl.zhihu.expand_stopped': '连续 {n} 次展开均无回应，本次剩余行改用搜索页摘要',
    'crawl.zhihu.fallbackSearch': '知乎深链搜索返回空壳，改用搜索框重新提交关键词',
    'crawl.zhihu.finished': '搜索完成，共获取 {n} 条有效结果（目标 {total} 条）',
    'crawl.zhihu.hotCapped': '热榜一共只有 {board} 条，已按实际条数收尾（榜单大小由网站决定）',
    'crawl.zhihu.hotDone': '热榜采集结束：{n} 条（目标 {total} 条）',
    'crawl.zhihu.hotRefused': '知乎热榜接口没有给出榜单（返回 {answer}）',
    # 热榜: measured as one answer of 30 questions with every paging parameter ignored,
    # so the mode never promises more than the board holds.
    'crawl.zhihu.hotStart': '开始采集知乎热榜，目标 {n} 条',
    'crawl.zhihu.hotWall': '知乎热榜需要登录：当前 Cookie 被挡在登录页，无法读取榜单',
    'crawl.zhihu.loaded': '搜索页面已加载，开始滚动加载更多内容...',
    'crawl.zhihu.no_growth': '卡片数未增长 ({n}/3)，再次滚动确认...',
    'crawl.zhihu.no_more': '检测到"没有更多了"，停止滚动（滚动 {i} 次）',
    'crawl.zhihu.phase_done': '滚动加载阶段完成，最终获取 {n} 个卡片',
    'crawl.zhihu.process_error': '处理第 {i} 条结果时出错: {err}',
    'crawl.zhihu.processed': '已处理第 {i} 条结果，当前有效数据: {n} 条',
    'crawl.zhihu.scroll_round': '滚动第 {i} 次完成，当前卡片数: {n} 条（目标: {total} 条）',
    'crawl.zhihu.scrolling': '滚动第 {i} 次，等待内容加载...',
    'crawl.zhihu.skipped': '第 {i} 条结果无有效内容，已跳过',
    # ── crawlers: zhihu ───────────────────────────────────────
    'crawl.zhihu.start': '开始搜索知乎关键词: "{kw}"，目标获取 {n} 条结果',
    'crawl.zhihu.stuck': '连续 {n} 轮滚动既无新卡片、页面也不再变高，且未出现「没有更多了」，停止滚动',
    'crawl.zhihu.target_reached': '已达到目标数量 {n} 条，停止滚动',
    'crawl.zhihu.url': '搜索URL: {url}',
}

EN = {
    'crawl.bili.authorDone': '[Bilibili] upload list finished, {n} rows (stopped because: {reason})',
    'crawl.bili.authorEmpty': '[Bilibili] no UP given (a space.bilibili.com link or a numeric mid): {author}',
    'crawl.bili.authorNoVideos': '[Bilibili] the upload list of UP {mid} rendered no video (possibly none published)',
    'crawl.bili.authorStart': '[Bilibili] collecting uploads of UP {mid}, target {n} rows',
    'crawl.bili.blocked': (
        '[Bilibili] the endpoint refused to answer (code={code}): the cookie likely died or risk control '
        'kicked in — re-save the cookie in the Cookie panel, then resume this run'
    ),
    'crawl.bili.boardPopular': 'popular feed',
    'crawl.bili.boardRanking': 'weekly ranking',
    'crawl.bili.duplicate': '[Bilibili search] {i} already in this run, skipped',
    'crawl.bili.empty_page': '[Bilibili search] page {page} has no video cards, stop paging',
    'crawl.bili.fetchEmpty': '[Bilibili search] {i} returned no readable data (non-JSON or WAF-blocked), skipped',
    'crawl.bili.finished': '[Bilibili search] done, {n} valid rows (target {total})',
    'crawl.bili.goneVideo': '[Bilibili search] {i} is withdrawn or unavailable ({code}), skipped',
    'crawl.bili.hotDone': '[Bilibili] board finished, {n} rows (target {total})',
    'crawl.bili.hotPage': '[Bilibili] board page {page}: {n} items ({fresh} new, {done} collected)',
    'crawl.bili.hotStart': '[Bilibili] collecting the {board}, target {n} rows (items carry their own figures)',
    'crawl.bili.no_more': '[Bilibili search] two pages in a row held nothing new, list exhausted (page {page})',
    'crawl.bili.page': '[Bilibili search] page {page}: {n} videos ({fresh} new, {done} collected)',
    'crawl.bili.processed': '[Bilibili search] stored {i}, {n} valid rows so far',
    'crawl.bili.rankingCapped': "[Bilibili] the {board} had only {n} rows (target {total}): its size is the site's",
    'crawl.bili.start': '[Bilibili search] keyword "{kw}", target {n} results',
    'crawl.bili.target_reached': '[Bilibili search] target of {n} rows reached, stop paging',
    'crawl.bili.url': '[Bilibili search] URL: {url}',
    'crawl.bili.watermarkHit': "[Bilibili] reached the previous run's boundary {i}; stopped paging",
    'crawl.browserBinaryMissing': (
        'The configured browser path does not exist: {path}. Correct it, or clear it and let the app find Chrome'
    ),
    'crawl.browserStartFailed': (
        'The browser did not start: {err}. Usual causes: chromedriver does not match this Chrome build, the first '
        'automatic driver fetch needs network, or that Chrome profile directory is held by another Chrome'
    ),
    'crawl.chromeMissing': (
        'No Chrome on this machine, so a crawl has no browser to open. Install Chrome, or point '
        'Settings → browser path at it (the executable name on this system is {browser})'
    ),
    'crawl.cnki.emptyRecord': '[CNKI] an exported RefWorks record has no title; skipped by the importer rule',
    'crawl.cnki.downloadFailed': '[CNKI] the exported record file could not be downloaded: {err}',
    'crawl.cnki.exportBatch': '[CNKI] exported {n} records from this selection (pages {first}-{last})',
    'crawl.cnki.exportForbidden': (
        '[CNKI] the export page refused this session ({err}): headless is often refused here — use a window and '
        'confirm the login'
    ),
    'crawl.cnki.exportEmpty': '[CNKI] the export page returned no RefWorks records (not signed in, or an empty batch)',
    'crawl.cnki.finished': '[CNKI] search finished, {n} records exported (target {total})',
    'crawl.cnki.loginNeeded': (
        '[CNKI] the export needs a login: save a CNKI session (or institutional IP access) in the Cookie panel first'
    ),
    'crawl.cnki.noExportIds': (
        '[CNKI] the result rows carry no export key (the page model may have moved): refusing to hand back an empty '
        'table — update the selectors first'
    ),
    'crawl.cnki.noExportButton': '[CNKI] the export page has no "export record file" button ({err})',
    'crawl.cnki.noExportMenu': '[CNKI] the 导出文献 menu is gone from the result page ({err}): the page model moved',
    'crawl.cnki.noExportWindow': (
        '[CNKI] the export was clicked but no export window opened (blocked by the browser, or the session was refused)'
    ),
    'crawl.cnki.noPage': '[CNKI] the result page never appeared (still loading, blocked, or the layout changed)',
    'crawl.cnki.noResults': '[CNKI] "{kw}" returned no results (the site itself printed 0)',
    'crawl.cnki.nothingSelected': '[CNKI] the site still counts 0 selected rows, so the export was refused',
    'crawl.cnki.selectPage': '[CNKI] selected the whole page {page} ({n} rows, {selected} selected so far)',
    'crawl.cnki.pageError': '[CNKI] an action on the result page failed: {err}',
    'crawl.cnki.selectFailed': '[CNKI] ticking the result rows failed: {err}',
    'crawl.cnki.start': '[CNKI] searching "{kw}", target {n} records',
    'crawl.cnki.target_reached': '[CNKI] target of {n} records reached, stop paging',
    'crawl.cnki.verifyRequired': (
        '[CNKI] the site asked for its security check (a slider): finish it in the Cookie panel’s "Generate via '
        'Browser" window, save that login, then retry'
    ),
    'crawl.cookiesSeeded': 'Cookies seeded: {host} accepted {n}/{total}',
    # ── crawler internals (debug level) ───────────────────────
    'crawl.cookies_failed': '{platform}: could not load cookies ({err}) — the run may come back empty without a login',
    'crawl.debug.author_missing': 'Author element not found',
    'crawl.debug.card_author': 'card {i}: author="{v}"',
    'crawl.debug.card_images': 'card {i}: images={n}',
    'crawl.debug.card_len': 'card {i}: text length={v}',
    'crawl.debug.card_metrics': 'card {i}: reposts={f} comments={c} likes={l}',
    'crawl.debug.card_skip': 'card {i}: skipped (no author)',
    'crawl.debug.card_time': 'card {i}: time="{v}"',
    'crawl.debug.comment_item': 'comment #{i}: {author} - {text}...',
    'crawl.debug.comments_missing': 'Comment area not loaded / not present',
    'crawl.debug.content_missing': 'Content element not found',
    'crawl.debug.content_retry': 'Content not extracted yet — retrying once',
    'crawl.debug.pager_missing': 'No pager button found — single page',
    'crawl.debug.time_missing': 'Publish-time element not found',
    'crawl.debug.title_missing': 'Title element not found',
    'crawl.disguisePartial': (
        'The headless disguise was only partly applied ({err}). '
        'This run may still be recognised as headless — check here first when a crawl comes back short'
    ),
    'crawl.disguiseUnreadable': (
        'The headless disguise did not take: this browser could not read back its own User-Agent ({err}). '
        'This run continues as a bare headless Chrome, and some sites answer that with a page of nothing'
    ),
    # Said by a session whose browser process was already reaped, so it must not claim a person did
    # anything: the same object answers a cookie window that was closed after its grace ran out.
    'crawl.driverDead': 'This browser process is already closed, so no further commands are sent to it',
    'crawl.driverMissing': (
        'The configured chromedriver path does not exist: {path}. It usually went stale against a Chrome update — '
        'point it at the matching driver, or clear it and let Selenium fetch one (needs network the first time)'
    ),
    'crawl.dy.authorDone': '[Douyin author] post list finished, {n} rows (the profile publishes {works})',
    'crawl.dy.authorDoneNoCount': '[Douyin author] post list finished, {n} rows (the profile published no count)',
    'crawl.dy.authorEmpty': '[Douyin author] no author given (paste a douyin.com/user/… link or the sec_uid): {author}',
    'crawl.dy.authorNoCards': (
        '[Douyin author] the profile never rendered its post grid, so nothing was collected. The page said: '
        '{page}; URL: {url}. The profile publishes {works} posts, so this is a blocked or broken page — '
        'not an author who posted nothing'
    ),
    'crawl.dy.authorNoWorks': '[Douyin author] the profile publishes 0 posts, so there is nothing to collect',
    'crawl.dy.authorNotMounted': (
        '[Douyin author] the profile rendered no post grid and published no post count, so nothing was collected. '
        'The page said: {page}; URL: {url}. Both defaults at once means blocked or broken'
    ),
    'crawl.dy.authorStart': "[Douyin author] one creator's posts, target {n} (counters read from the in-page overlay)",
    'crawl.dy.detailEmpty': '[Douyin] video {i} rendered no detail data, row skipped',
    'crawl.dy.detailNoIdentity': (
        '[Douyin] video {i} rendered only its counter bar — no author and no publish time, row skipped: '
        'a record that cannot say whose it is or when it was posted is not data, just budget spent on a blank row'
    ),
    'crawl.dy.detailSlow': (
        '[Douyin] video {i} did not finish loading inside the page-load timeout, row skipped: that is the '
        'network or the site being slow, a retry may well get it'
    ),
    'crawl.dy.detailSwapped': (
        '[Douyin] asked for video {i} but the browser served a different one, {shown} (the site swapped the content)'
        " — row not stored: one row short beats somebody else's caption and counters filed under this link"
    ),
    'crawl.dy.detailWalled': (
        '[Douyin] video {i} was answered with the captcha interstitial (image-text posts are refused for this '
        'device; video pages are not) — row skipped: the site did not run out of content and the session is not dead'
    ),
    'crawl.dy.hotCapped': (
        '[Douyin hot board] the board held {board} rows this time, so the run ended there '
        '(the site decides how large a board is)'
    ),
    'crawl.dy.hotDone': '[Douyin hot board] finished with {n} rows (target {total})',
    'crawl.dy.hotRefused': '[Douyin hot board] the board endpoint gave no board (answered {answer})',
    'crawl.dy.hotStart': '[Douyin hot board] collecting the board, target {n} (one answer, no per-row page)',
    'crawl.dy.hotTarget': '[Douyin hot board] the target of {n} rows is already stored, the board is not read again',
    'crawl.dy.hotWall': (
        '[Douyin hot board] the board page was parked on the captcha interstitial, so nothing was collected: '
        'save the douyin cookie through the Cookie panel first'
    ),
    'crawl.dy.modalDeferred': (
        '[Douyin] the overlay would not open for {n} works cards, skipped this round: that is unreadable, '
        'not the site running out — retry later'
    ),
    'crawl.dy.noMore': (
        '[Douyin] the list wrote its own "no more for now": {screens} screens read, last screen held '
        '{cards} cards — that is the supply for this order, not a scroll that failed'
    ),
    # The one refusal on this page that needs no waiting and no probing: the document is
    # the browser's own, and it says which address it refused.
    'crawl.dy.noPageRefused': '[Douyin] the browser refused this page itself, so there can be no cards: {url}{detail}',
    'crawl.dy.processed': '[Douyin] stored video {i}, {n} valid rows so far',
    'crawl.dy.round': '[Douyin] screen {i}: {n} cards ({fresh} new, {done} collected)',
    'crawl.dy.target_reached': '[Douyin] target of {n} rows reached, stop',
    'crawl.dy.wall': (
        '[Douyin] the browser was parked on the captcha interstitial: Douyin web serves it to headless '
        'browsers and to bursty requests. Re-save the cookie through the Cookie panel (visible window) '
        'and retry this keyword a little later'
    ),
    'crawl.hg.boardAiDrama': 'AI drama hot board',
    'crawl.hg.boardComicDrama': 'comic drama hot board',
    'crawl.hg.boardHotDrama': 'hot board',
    'crawl.hg.boardRealDrama': 'live-action hot board',
    'crawl.hg.boardUnknown': '[Hongguo] there is no such board: {board} (available: {options})',
    'crawl.hg.cmt.caInstalled': "[Hongguo] installed the mitmproxy root certificate into the current user's "
    'trusted roots (the player needs it to decrypt)',
    'crawl.hg.cmt.caNotTrusted': (
        '[Hongguo] the mitmproxy root certificate is not trusted and auto-install did not succeed. '
        'Manual command (PowerShell): {command}'
    ),
    'crawl.hg.cmt.danmakuSkipped': '[Hongguo] dropped {n} danmaku-guide rows (they are not comments)',
    'crawl.hg.cmt.dramaNotFound': "[Hongguo] the player's search found no such drama: {title}",
    'crawl.hg.cmt.dramaSkipped': "[Hongguo] the player's UI tree never woke, skipping this drama: {title} "
    '(click the player window once, then 继续/Resume to harvest it)',
    'crawl.hg.cmt.episode': '[Hongguo] episode {n}/{total}: {have} comments (the site says {site_total})',
    'crawl.hg.cmt.episodeShort': '[Hongguo] {title} episode {ep}: kept {have} of the {site_total} the site counts '
    '— this episode is incomplete',
    # Named because the player's own feed walks away from the drama we entered: measured
    # 2026-10-20, after the first ↓ every following page belonged to the show the account had
    # been watching, and those rows would have been filed under the requested 剧名.
    'crawl.hg.cmt.feedDrifted': (
        '[Hongguo] during {title} episode {ep} the player feed moved to another drama (book {book}); '
        'the rest of this drama is not attempted — the rows already kept belong to the requested drama'
    ),
    'crawl.hg.cmt.finished': '[Hongguo] comment harvest done, {n} rows ({episodes} episodes)',
    'crawl.hg.cmt.groupMismatch': '[Hongguo] a comment page arrived for {got} instead of the requested {want} '
    'and was dropped',
    'crawl.hg.cmt.groupShort': '[Hongguo] episode group {group} (episode {ep}): kept {have} of the {site_total} the '
    'site counts — this episode is incomplete',
    'crawl.hg.cmt.needsExtras': (
        '[Hongguo] the comment harvest is a Windows desktop feature and this machine lacks {missing} '
        '(install per requirements-optional.txt; unavailable in cloud mode)'
    ),
    'crawl.hg.cmt.needsExtrasFrozen': (
        '[Hongguo] the desktop build does not carry {names}: the comment harvest needs mitmdump and '
        'UI Automation over a real desktop window, so that node runs only in a source checkout'
    ),
    'crawl.hg.cmt.noMitmdump': (
        '[Hongguo] mitmdump was not found ({detail}) \u2014 install it with: pip install mitmproxy '
        '(see requirements-optional.txt)'
    ),
    'crawl.hg.cmt.noPlayer': (
        '[Hongguo] the Hongguo desktop player was not found ({path}) \u2014 set its exe location in '
        'Settings \u203a Hongguo player path'
    ),
    'crawl.hg.cmt.noTraffic': (
        '[Hongguo] waited {seconds}s and no comment page arrived for this episode ({title}) \u2014 the '
        'player may be logged out, blocked by a dialog, or too old'
    ),
    'crawl.hg.cmt.off': 'off',
    'crawl.hg.cmt.on': 'on',
    'crawl.hg.cmt.playerBusy': (
        "[Hongguo] the Hongguo player is already running and does not carry this tool's proxy \u2014 close "
        'it first and this node will launch the player through the proxy itself'
    ),
    'crawl.hg.cmt.repliesExpanded': '[Hongguo] expanded {n} reply thread(s)',
    'crawl.hg.cmt.replyPage': '[Hongguo] replies under floor {floor}: {n}',
    # Said because an expanded child thread prints its own total and the walk clicks 展开 once
    # per thread: without this line a thread the site counts at 200 children and delivers 20
    # would still let the node claim the site said it was done.
    'crawl.hg.cmt.replyShort': (
        '[Hongguo] the child thread at floor {floor}: kept {have} of the {site_total} the site counts — '
        'its replies are incomplete'
    ),
    'crawl.hg.cmt.scanningBoard': '[Hongguo] looking for “{title}” in the {label} board…',
    # Said from the SCREEN, not the traffic: the player prints the drama it is showing as
    # ``@剧名`` in its header. Asking that before harvesting keeps another show's comments out
    # of this table when a card click lands elsewhere or a ↓ walks off into the account's own
    # queue. The episode counter is NOT readable while the drawer is open (measured), so no
    # message here claims a position the walk cannot see.
    'crawl.hg.cmt.screenMismatch': (
        '[Hongguo] the screen is showing “{have}”, not the requested “{want}” — the rest of this drama '
        'is not attempted (rows already kept belong to the requested show; this is not a search miss, '
        'the player did not put this drama on stage)'
    ),
    # ─── comment harvest (desktop player behind a local proxy; docs/crawler_notes.md Hongguo) ───
    'crawl.hg.cmt.start': '[Hongguo] harvesting comments: {title} ({episodes} episodes, replies {replies})',
    'crawl.hg.cmt.titleMissing': '[Hongguo] the detail page printed no drama name, so the player has nothing '
    'to search for: {url}',
    'crawl.hg.cmt.treeCold': (
        '[Hongguo] the player window is open but its UI tree never became walkable '
        '(WebView2 accessibility did not wake up). Click inside the player window once, then rerun this node'
    ),
    'crawl.hg.finished': '[Hongguo] done, {n} rows (target {total})',
    'crawl.hg.lastPage': '[Hongguo] page {page} is the last the site offers, stop paging ({n} collected)',
    'crawl.hg.noBoard': (
        '[Hongguo] after {seconds}s this page still carried no board data (data keys on the page: {keys}): {url} '
        '\u2014 the site may have changed, or this machine never received the page'
    ),
    'crawl.hg.noDetail': '[Hongguo] no link-based mode exists for this platform, and its detail page has not '
    'been measured yet ({url})',
    'crawl.hg.noFresh': '[Hongguo] two pages in a row held nothing new (page {page}), paging stopped: counted as short',
    'crawl.hg.noPageRefused': '[Hongguo] the browser itself refused this page, so no board can be there: {url}{detail}',
    'crawl.hg.page': '[Hongguo] page {page}: {n} items ({fresh} new, {done} collected)',
    'crawl.hg.replay': '[Hongguo] page {page} pointed "next" back at itself ({url}), paging stopped: counted as short',
    'crawl.hg.searchUnsupported': '[Hongguo] this site offers only its four hot boards, no keyword search '
    '(received keyword: {keyword})',
    'crawl.hg.start': '[Hongguo] collecting the {board}, target {n} rows (paging follows the next link the site gives)',
    'crawl.hg.target_reached': '[Hongguo] target of {n} rows reached, stop paging',
    'crawl.loginWall': 'Login wall: {platform} redirected {where} to a login page',
    'crawl.platformNotCrawlable': 'This platform only supports storing a login cookie so far, not crawling '
    '({platform}) \u2014 use a supported platform, or wait for its crawler to land',
    'crawl.profile_gave_up': 'this run was stopped: no longer waiting for the profile ({dir}), this crawl stands down',
    'crawl.profile_stuck': (
        'timed out waiting {seconds} s for the profile to free up: {dir} — a browser may have been left '
        'open; end the stray Chrome in the process panel and try again'
    ),
    'crawl.profile_wait': 'queued {seconds} s: this profile runs one browser at a time — {dir}',
    'crawl.promptDismissed': '{label}: dismissed the first-run dialog by pressing "{button}"',
    'crawl.promptUnmatched': (
        '{label}: the first-run dialog matched no known button (the page offers: {buttons}),'
        ' this run may wait for it to clear on its own'
    ),
    'crawl.redrive': 'page did not reach the site (parked on {where}), re-driving once',
    # ── resume and dedupe (crawler side) ────────────────────────
    'crawl.resume_have': 'Resuming: {n} item(s) already collected, continuing instead of starting over',
    'crawl.riskBlocked': 'Risk control: {platform} answered {where} with a security check instead of content',
    'crawl.sink_failed': 'Incremental save failed (this row is still in the results, but may not be stored): {err}',
    'crawl.stopReason.empty_page': 'a page came back empty',
    'crawl.stopReason.end': 'reached the end of the list',
    'crawl.stopReason.fetch_failed': 'the list request failed',
    'crawl.stopReason.no_cards': 'the page rendered no list',
    'crawl.stopReason.no_new': 'no new rows after paging',
    'crawl.stopReason.risk': "the site's risk control stopped the walk (not a dead cookie)",
    'crawl.stopReason.stopped': 'the run was stopped',
    'crawl.stopReason.stuck': 'scrolling produced nothing new',
    'crawl.stopReason.target': 'reached the target count',
    'crawl.stopReason.unreachable': 'the browser never fetched a page at all (network or DNS),'
    ' so the site never saw this session',
    'crawl.stopReason.wall': 'a login wall stopped the walk',
    'crawl.stopped': 'Stop received — this crawl ends here',
    # Neither of the two above: the browser wrote this page itself, so the site never saw
    # the request and the session is not the thing in question.
    'crawl.unreachable': 'The browser refused this visit itself: {platform} at {where}{detail}',
    'crawl.unreachableToken': ' ({token})',
    'crawl.wechat.author': 'Author (official account): {author}',
    'crawl.wechat.batch_done': 'Batch scrape complete: {n} / {total} succeeded',
    'crawl.wechat.batch_start': 'Starting batch scrape of {n} WeChat article(s)',
    'crawl.wechat.content_len': 'Content length: {n} characters',
    'crawl.wechat.duplicate': 'Skipping a duplicate article link: {url}',
    'crawl.wechat.extracting': 'Extracting article fields',
    'crawl.wechat.failed': 'Article {i}/{total} failed: no body was retrieved',
    'crawl.wechat.loaded': 'Article page loaded successfully',
    'crawl.wechat.navigating': 'Navigating to article URL',
    'crawl.wechat.no_content': 'Content element not found after retry.',
    # ── crawlers: wechat ──────────────────────────────────────
    'crawl.wechat.no_urls': 'No URLs provided, returning empty results.',
    'crawl.wechat.preview': 'Content preview: {preview}',
    'crawl.wechat.processing': 'Scraping article {i} / {total}',
    'crawl.wechat.pub_time': 'Publish time: {time}',
    'crawl.wechat.scroll': 'Scrolling to bottom to trigger lazy loading',
    'crawl.wechat.scroll_done': 'Scroll complete',
    'crawl.wechat.success': 'Article {i}/{total} scraped: "{title}" ({author})',
    'crawl.wechat.timeout': 'Page load timed out for: {url}',
    'crawl.wechat.title': 'Title: {title}',
    'crawl.wechat.url': 'URL: {url}',
    'crawl.wechat.wait': 'Waiting 1 s before the next article',
    'crawl.wechat.wait_title': 'Waiting for article title (#activity-name) to load',
    'crawl.weibo.accumulated': 'Total collected so far: {n}',
    'crawl.weibo.authorDone': 'Author walk finished: {n} rows ({reason})',
    'crawl.weibo.authorEmpty': (
        '"{author}" is not a weibo author address: give a weibo.com/u/<UID> profile link or the numeric UID'
    ),
    'crawl.weibo.authorMirror': (
        'the first row returned for UID {uid} is not theirs \u2014 the endpoint answered the '
        'home timeline, not this author\u2019s posts; refusing to file it as theirs'
    ),
    'crawl.weibo.authorNoPosts': 'UID {uid} returned no posts: this account may genuinely have none',
    'crawl.weibo.authorRefused': (
        'the mymblog endpoint refused (status {status}, UID {uid}): this is a per-session '
        'throttle, the cookie may be fine \u2014 try again later'
    ),
    'crawl.weibo.authorStart': 'Collecting author {uid}\u2019s posts, target {n}',
    'crawl.weibo.authorWall': (
        'weibo bounced UID {uid}\u2019s profile back to a login page: this session cannot reach the author page'
    ),
    # ── argument validation / API errors (surfaced in toasts) ──
    'crawl.weibo.bad_date': 'Bad date format: {value} (expected YYYY-MM-DD)',
    'crawl.weibo.bad_range': 'The end date ({end}) must be later than the start date ({start})',
    'crawl.weibo.card_error': '    Card {i}: error while processing, skipped',
    'crawl.weibo.hotCapped': (
        'The hot board held only {board} rows this time, so the walk stopped there (the site sets the board size)'
    ),
    'crawl.weibo.hotDone': 'Hot board finished: {n} rows (target {total})',
    # Said when the request was never issuable: the browser sat on a frame that is not weibo.com, so the
    # same-origin fetch had no host to ask. Blaming the endpoint there convicts it of an answer it never gave.
    'crawl.weibo.hotNoHost': 'weibo hot board not collected: the browser was still on 「{where}」 and never '
    'came back to weibo.com (the visitor bootstrap did not finish, so the in-page '
    'request had no host — an arrival-frame fact, not an endpoint refusal)',
    'crawl.weibo.hotRefused': 'The weibo hot-search endpoint gave no board (answered {answer})',
    'crawl.weibo.hotStart': 'Collecting the weibo hot search board, target {n}',
    # ── crawlers: weibo ───────────────────────────────────────
    'crawl.weibo.keyword': 'Keyword: {kw}',
    'crawl.weibo.keyword_plain': 'Keyword: {kw} (no time range, single search link)',
    'crawl.weibo.link_done': 'Link {i} done, {n} rows collected',
    'crawl.weibo.link_error': 'Error processing search link: {err}',
    'crawl.weibo.links': 'Built {n} search links (one per hour)',
    'crawl.weibo.max_page': 'Max page number: {n}',
    'crawl.weibo.navSettled': 'settled',
    'crawl.weibo.navUnsettled': 'did not settle, which is a slow network, not a refusal',
    'crawl.weibo.need_both_dates': 'Set both a start and an end date — a single one searches a different range',
    'crawl.weibo.no_result': 'No results in this time window, skipping',
    'crawl.weibo.page_cards': '    Found {n} cards on this page',
    'crawl.weibo.page_crawling': '  Crawling page {i}/{total}...',
    'crawl.weibo.page_done': '  Page {i} done: {n} rows, {total} accumulated',
    'crawl.weibo.page_empty': '  Page {i} has no usable cards, skipping',
    'crawl.weibo.page_gave_up': (
        '    This browser has already watched {waits} search pages deliver nothing: the budget is'
        ' not being spent on another window (that is "no page fetched", not "this window is empty")'
    ),
    'crawl.weibo.page_loaded': 'Page loaded',
    'crawl.weibo.page_timeout': (
        '    Waited {secs}s: this page gave neither a card nor the "no result" plate (navigation {settled})'
        ' — that is all this line can say; it does not mean the window holds nothing'
    ),
    'crawl.weibo.pages_fail': 'Could not determine page count: {err}',
    'crawl.weibo.processing': 'Processing search link {i}/{total}',
    'crawl.weibo.range': 'Time range: {start} to {end}',
    'crawl.weibo.target_reached': 'Reached the target of {n} rows, stopping the walk',
    'crawl.weibo.total_pages': 'Detected {n} pages in total',
    'crawl.weibo.url': 'URL: {url}',
    'crawl.weibo.visiting': 'Visiting search link: {url}',
    'crawl.weibo.waiting': 'Waiting for the page to load...',
    'crawl.weibo.walk_done': (
        'Weibo search walk closed: {n} rows (target {target}, window {walked} of {total} reached, reason: {reason})'
    ),
    'crawl.x.authorEmpty': '[X] no author given (@handle or profile link): {author}',
    'crawl.x.authorStart': '[X] author "{author}" posts, target {n} posts',
    'crawl.x.finished': '[X] kept {n} posts (stopped because: {reason})',
    'crawl.x.loadSlow': '[X] the page did not finish loading in time; continuing with what rendered: {url}',
    'crawl.x.no_cards': '[X] no tweet rendered at all (blocked, too narrow, or an empty account): {url}',
    # X renders a virtualized timeline: the card count never grows while tweets
    # stream through it, so its log lines speak of rows kept, not cards on screen.
    'crawl.x.start': '[X] keyword "{kw}", target {n} posts (latest first)',
    'crawl.x.target_reached': '[X] target of {n} rows reached, stop scrolling',
    'crawl.x.wall': '[X] access was refused (login wall or 403): {url}',
    'crawl.xhs.author': '[Note detail] Author: {author}',
    'crawl.xhs.collect_done': '[Collect links] Done, {n} links collected',
    'crawl.xhs.comment_count': '[Note detail] Comments: {n}',
    'crawl.xhs.comment_done': '[Comments] Extracted {n} comments',
    'crawl.xhs.comment_error': '[Comments] Error extracting comment {i}: {err}',
    'crawl.xhs.comment_found': '[Comments] Found {n} comment elements',
    'crawl.xhs.comment_skip': '[Comments] preview is 0, panel skipped (no wait)',
    'crawl.xhs.comment_start': '[Comments] Extracting up to {n} comments',
    'crawl.xhs.content_len': '[Note detail] Content length: {n} characters',
    'crawl.xhs.deadNote': '[Detail] note blocked by 安全验证 (session is fine) — skipped: {url}',
    'crawl.xhs.detail_ready': '[Note detail] Detail page loaded',
    'crawl.xhs.detail_timeout': '[Note detail] Detail page timed out',
    'crawl.xhs.detail_visit': '[Note detail] Opening detail page: {url}',
    'crawl.xhs.finished': '[XHS search] Done, {n} valid notes collected',
    'crawl.xhs.links': '[XHS search] Collected {n} note links',
    'crawl.xhs.metrics': '[Note detail] Engagement - likes: {likes}, saves: {favs}, comments: {comments}',
    'crawl.xhs.note_dup': 'Skipping a duplicate note: {url}',
    'crawl.xhs.note_error': '[XHS search] Error processing note: {err}',
    'crawl.xhs.note_ok': '[XHS search] Extracted: {title}...',
    'crawl.xhs.page_ready': '[XHS search] Initial results page loaded',
    'crawl.xhs.page_timeout': '[XHS search] Initial content timed out — may be no results, still scrolling',
    'crawl.xhs.pub_time': '[Note detail] Publish time: {time}',
    # ── crawlers: xiaohongshu ─────────────────────────────────
    'crawl.xhs.start': '[XHS search] Searching for "{kw}", target {n} notes',
    'crawl.xhs.target_reached': '[Collect links] Target of {n} reached, stopping',
    'crawl.xhs.untitled': 'untitled',
    'crawl.xhs.url': '[XHS search] Opened search URL: {url}',
    'crawl.yt.authorEmpty': '[YouTube] no creator given (@handle, channel link or UC… id): {author}',
    'crawl.yt.authorNoVideos': "[YouTube] this creator's video tab holds nothing: {author}",
    'crawl.yt.authorNotFound': '[YouTube] that address is not a channel page, so no channel id: {author}',
    'crawl.yt.authorStart': '[YouTube] creator "{author}" uploads, target {n} results',
    'crawl.yt.badAnswer': '[YouTube] {endpoint} answered {status}, not JSON',
    'crawl.yt.callFailed': '[YouTube] the {endpoint} call failed',
    'crawl.yt.drained': '[YouTube] the API stopped handing out a cursor, the list is exhausted',
    'crawl.yt.finished': '[YouTube] collected {n} rows (target {total})',
    # YouTube is crawled as JSON from inside its own page, so these lines talk
    # about rounds and answers rather than about scrolling a list.
    'crawl.yt.noContext': '[YouTube] the page exposed no innertube config (intercepted, or the DOM changed): {url}',
    'crawl.yt.noPage': '[YouTube] round {page} returned no items, stop paging',
    'crawl.yt.noResults': '[YouTube] no public video matches "{kw}" (or this session is throttled)',
    'crawl.yt.page': '[YouTube] round {page}: {n} items ({fresh} new, {done} collected)',
    'crawl.yt.processed': '[YouTube] stored {i}: {title}',
    'crawl.yt.replay': '[YouTube] round {page} added nothing new, list treated as exhausted',
    'crawl.yt.searchStart': '[YouTube] keyword "{kw}", target {n} results',
    'crawl.yt.targetReached': '[YouTube] target of {n} rows reached, stop paging',
    'crawl.yt.wall': '[YouTube] a human-verification page was served: {url}',
    'crawl.zhihu.authorEmpty': '[Zhihu] no author given (a profile link, or the id after /people/): {author}',
    'crawl.zhihu.authorStart': '[Zhihu] collecting answers and articles of "{author}", target {n} rows',
    'crawl.zhihu.authorTabDone': '[Zhihu] tab "{tab}" finished, {n} rows so far (stopped because: {reason})',
    'crawl.zhihu.authorTabEmpty': (
        '[Zhihu] the "{tab}" tab of "{author}" holds nothing (this kind was never published), skipped'
    ),
    'crawl.zhihu.bodies_short': '{n} answer(s) did not expand; their 正文 is still a search-page excerpt',
    'crawl.zhihu.duplicate': 'Skipping duplicate answer #{i}',
    'crawl.zhihu.emptyOrBlocked': (
        'Zhihu search returned nothing (risk control, login wall, or dead page): '
        'turn off headless mode in the run settings, or retry later; collected data is safe'
    ),
    'crawl.zhihu.excerpt_only': (
        'Bodies left collapsed: every 正文 is a search-page excerpt (tick "Expand full text" on the data source node)'
    ),
    'crawl.zhihu.expand_stopped': (
        '{n} expansions in a row answered nothing; keeping search-page excerpts for the rest of this crawl'
    ),
    'crawl.zhihu.fallbackSearch': (
        'Deep-linked search rendered an empty shell; resubmitting the keyword through the search box'
    ),
    'crawl.zhihu.finished': 'Search done: {n} valid results (target {total})',
    'crawl.zhihu.hotCapped': (
        'The board holds {board} questions in total, so the walk stopped there (the site sets the board size)'
    ),
    'crawl.zhihu.hotDone': 'Hot board finished: {n} rows (target {total})',
    'crawl.zhihu.hotRefused': 'The zhihu hot-list endpoint gave no board (answered {answer})',
    'crawl.zhihu.hotStart': 'Collecting the zhihu hot board, target {n}',
    'crawl.zhihu.hotWall': 'The zhihu hot board needs a login: the current cookie was held at the sign-in page',
    'crawl.zhihu.loaded': 'Search page loaded, scrolling for more content...',
    'crawl.zhihu.no_growth': 'Card count did not grow ({n}/3), scrolling once more to confirm...',
    'crawl.zhihu.no_more': 'Reached "no more content", stopping (after {i} scrolls)',
    'crawl.zhihu.phase_done': 'Scroll phase done, {n} cards in total',
    'crawl.zhihu.process_error': 'Error processing result {i}: {err}',
    'crawl.zhihu.processed': 'Processed result {i}, valid so far: {n}',
    'crawl.zhihu.scroll_round': 'Scroll #{i} done, {n} cards so far (target: {total})',
    'crawl.zhihu.scrolling': 'Scroll #{i}, waiting for content...',
    'crawl.zhihu.skipped': 'Result {i} has no usable content, skipped',
    # ── crawlers: zhihu ───────────────────────────────────────
    'crawl.zhihu.start': 'Searching Zhihu for "{kw}", target {n} results',
    'crawl.zhihu.stuck': (
        '{n} rounds with no new cards and no taller page, and no "no more content" marker seen — stopping the scroll'
    ),
    'crawl.zhihu.target_reached': 'Target of {n} reached, stopping scroll',
    'crawl.zhihu.url': 'Search URL: {url}',
}
