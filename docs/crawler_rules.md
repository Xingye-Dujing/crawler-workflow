# 采集端规则

`AGENTS.md` 只装每次会话都要的规则；本文件装**动采集代码、平台列或真站断言时**才需要的契约。先读本文件，再读
`docs/crawler_notes.md` 对应平台小节。每条都是真机付过钱的现状，不是历史。

## §1 唯一口径：能力矩阵与设置
- **先读页面，再读代码。** 任何审计、修复或扩展都先用一次性 `backend/test_<平台>_<事>.py`（载荷进 `scratchpad/`）重测
  页面模型：列表按什么翻页（按钮 / 窗口 / 元素自己的滚动盒）、嵌套内容是否只在展开器后、哪个容器装行、页面真印了哪些列。
  错的页面模型不会报错，它会让汇总、存储、预览三方对一张页面从未给过的表达成一致。**向页面要分母（它自己印的计数），
  按那个分母判分。**
- **矩阵是“这个平台能采什么”的唯一答案。** `capabilities/platforms/<id>.py` 声明模式、每模式字段（控件、默认、下限、
  上限、必填、`fed_by`）、跑哪个爬虫方法、`region`；`registry.py` 回答查询；`nodes/executors/source.py` 派发；
  `engine/workflow.py::validate` 拒绝；`GET /api/capabilities` 把同一份描述交给面板。新平台/模式是**一条矩阵项**，
  不是四个文件里的 `if platform == …`。字段标签是前端键、必填名是后端键（`field.*`），由
  `test_frontend_contract.py::TestCrawlMatrixParity` 对齐；字段名会进内联处理器，不匹配 `/^[\w.-]{1,64}$/` 的整项丢弃。
- **平台是插件，共享层不认识任何一个站。** `crawlers/platforms/<id>/` 与 `capabilities/platforms/<id>.py` 是站点
  事实的唯一住处（选择器、端点、页面内 JS、列名、节奏基线、表单给哪个开关）；`crawlers/engine/`、`crawlers/core/`、
  `crawlers/commenting/`、`capabilities/fields.py` 里不得出现按平台名分支的代码。共享工厂可以收一个通用参数，由
  平台文件传自己的答案（如 `comment_mode(..., replies=True)`）；平台专属逻辑出现在共享模块就是架构缺陷。
- **没有平台自己的用户旋钮。** 站点基线（卡片等待、滚动预算、卡住轮数）可以放在平台旁边，但必须经
  `crawlers/engine/pacing.py` 消费（`nap`/`scroll_scale`/`scroll_interval`/`expand_scale`/`click_scale`/
  `wait_scale`/`arrival_scale`/`patience_scale` 与 `*_nap`/`*_wait`）。平台模块不得 `get_setting` 读采集行为，不得手写
  `time.sleep`；`tests/unit/gates/test_settings_schema.py` 两条都拒。用户选择只在 `runtime/settings_schema.py` 声明一次。
- **一个间隔一个旋钮。** 每个停顿按动作命名：`scroll_*` 滚动、`expand_*` 展开/更多、`click_*` 其它点击、`arrival_*`
  页面到达、`between_pages`/`page_nap` 两页之间、`wait`/`wait_nap` 元素注水、`nap` 礼貌、`rounds` 重试。
  `poll_tick` 故意不缩放（循环次数来自固定预算）。**`crawl_jitter` 抖动节奏、不抖动预算**：滚动/展开/点击/翻页乘
  `1 ± jitter`，元素等待与到达预算是承诺，不是节奏。
- **滚动是“一下一间隔”，不是“一批一间隔”。** `scroll_nap` 一次付两笔：这一下滚动的挂载时间（乘
  `crawl_scroll_scale`）加上用户自己填的 `crawl_scroll_interval` 秒（**不乘倍数**，两笔不叠）。所以
  `scroll_down(steps=3)` 是 3 个间隔 + 落地那一下的间隔，不是 0.12 秒连发三下再停一次；步数是站点事实，
  **绝不随 `patience` 变大**（`pacing.rounds(SCROLL_STEPS)` 曾让慢速采集把一批滚得更长，而不是更慢）。
  付这一笔的是走 `scroll_nap` 的滚动：知乎/小红书搜索与作者、公众号正文、知乎/小红书/X/抖音评论面板、红果播放器；
  X 时间线与抖音作品网格每轮只滚一次、本来就有自己的礼貌停顿（`pace`），不叠这一项。
- **慢速采集是预设，不是第二乘数。** `PRESETS` 三档（`standard` 1.2 秒、`slow` 4/3/**3 秒**/3/3/2/1.6/3/30%/2、
  `night` 6/5/**5 秒**/5/5/3/2/6/50%/3）各写具体值加队列/预检/上限，并快照被替换的值；恢复精确，切换保留最初快照。
  绝不叠一个全局因子。
- **一个 worker 已消失的记录由面板收尾。** `/api/runs/list` 结算“本进程开过、从未关闭、已无 worker”的行。加一个运行
  状态要同时改 `RESUMABLE_RUN_STATUS`、`purge` 的保护、面板 `known` 与两份 app.js 词表。

## §2 走查机制与停止
- **`crawlers/engine/` 是机械，平台模块是站点。** `engine.counters.parse_count`、`engine.wall`（四种判定）、
  `engine.popup.Prompt`、`engine.feed.walk_feed`/`wait_for`/`jump_to_bottom`、`engine.pager.walk_pages`、
  `engine.jsonpath` 不认识任何平台；平台只声明选择器、端点、列名。**走查没有轮/页预算**：“多少”是用户目标。
- **点击循环也是走查。** 展开器点到页面不再提供为止，不是“点 N 次”；控件按它自己的文字（或 `data-*-tried` 戳）记住，
  顽固控件不能把循环空转；没有计数可结束时，每个循环都要问 停止。**列表是一份文档，不是书签**：逐行进详情页前先把列表
  收完。
- **`Crawler.open(url)` 是唯一导航入口。** 它扛过渲染超时并**记录导航是否落地**；没落地是慢网不是拒绝。它清弹窗，
  **复读之后仍在的墙**才上锁。`Crawler._drive_off_internal_page` 在浏览器停在自己页面时重发 `get`
  （`never_arrived`），`open` 与 `_load_cookies` 共用，`NAV_RETRY` 实测为 **1**；只对这种形状重试，已提交页面、真墙、
  `chrome-error://` 各只判一次；模板预热器故意进 `about:blank`，走裸 `driver.get`。
- **慢不是拒绝；慢网络不是拒绝，只有拒绝才可被命名为拒绝。** 一页首屏内容给 `Config.PAGE_WAIT_TIMEOUT`
  （`Crawler.wait_for_first_content`，可停、见证据早退、同一浏览器看满两次过期才拒）；“还有新行吗”保持短预算。
  `wall.classify` 只答四种（`VERDICTS` 封闭）；`unreachable` 从 `documentURI` 读（`current_url` 仍报请求地址），
  **不置任何墙旗**。
- **停止是请求，不是判决。** 停止在**请求线程**写 `stopping`（worker 的判决覆盖它），`stop_requested()` 读它，绝不读
  “不在运行”。每次抓取在下一行经 `Crawler.emit` 问（`BaseException`，`except Exception` 会把它吞成“站点没有更多”），
  手写逐卡循环自己问 `may_stop()`（杀之前拿到的 `WebElement` 仍连着原会话）。走查可以用**返回已采行**来服从停止，所以
  执行器在它返回后要再问一次，调用方也不得把这次停止花在下一步上，更不许改写成“采得不足”。`driver.quit()` 打断不了
  进行中的命令，停止要杀掉那个驱动进程。**没交给连接的超时不是上限**：`ollama.Client` 的 `timeout=None` 是永不超时。
- **分批输出的 stem 是存储键，必须跨同一运行的所有尝试一致。** `PartWriter` 按 `{stem}.part` 前缀认领已落盘分片
  （`services/ingest/parts.py`），`run.progress_file` 宣告合并文件。所以“创建时间”取自运行记录的 `started_at` 加
  `run_id`（`core.refs.export_stamp`），绝不取写入时的钟；`window_tag` 是节点参数，安全。
- **文件名组件是“在选一个名字”，歧义按名拒绝。** “文件名带时间范围”的区间经运行期
  `execution_state['_time_windows']`（按工作流键，与 console 缓冲同构）传递；零个或两个不同区间都失败并说明，绝不按一段
  这张表并不描述的区间命名。解析出的名字不回写 `node['params']`。

## §3 浏览器、Profile 与 Cookie
- **无头就是无头，没有东西能强开窗口。** 每个节点/评论面板逐字尊重 无头/窗口；`无头→窗口`/`forced_visible` 已退役；
  `Mode.collects` 是“可见窗口有没有东西可看”的唯一答案。存下的 profile 偏好活得比一次抓取久，所以 取/验证 Cookie 与运行前
  探测都显式写 允许（`crawlers/core/browser.py::content_prefs`）。
- **浏览器为页面而生：从本地文档起步，不留用不上的设备。** 每次启动开 `about:blank`（`browser.STARTUP_PREFS`，
  `session.restore_on_startup=4`），不开 `chrome://newtab/`（它拉 Google 服务，受限网络里启动导航永不完成，chromedriver 把
  每条命令排在它后面）；组件更新器关掉（`--disable-component-update`，CRX 会堆进 user-data-dir）。每次启动都用**一次**有界
  UA 读取做渲染健康检查（`Config.RENDERER_PROBE_TIMEOUT`），不应答就**按名拒绝**（`crawl.rendererUnresponsive`）并经
  `browser.close_driver`（有界 `quit` + 该会话 PID 收树）关掉；可见窗口不豁免。只有“伪装”是无头专属。
- **一个 profile 一个浏览器。** chromedriver 预写 `Preferences`，同目录两个会话起不来：`sessions/profiles.py::acquire_profile`
  是**不可重入** `Lock`，持有整只爬虫的生命（侧线程在关闭时释放）。用户答 用 Profile per run＝`use_profile`；真排队已替整个
  程序回答。站点限流是第二重碰撞，`runtime/gate.py`（`hold` 缝）按 (平台, 账号) 分道：一个登录轮流、两个登录并行（真排队
  持道到抓取**结束**，错峰只隔开起步）；`serial_only` 平台无论开关都排队，浏览器先警告。**首行之前的墙**退避后重试一次，
  **有行之后的墙**是 Cookie 将死、走 继续。**缺省＝跟随设置，绝不把缺失强制成 `False`。** `Config.PROFILE_LOCK_TIMEOUT`
  限制等待，节点失败并点名目录。
- **爬取跑在平台自己的 Chrome profile 里，profile 拥有自己的 Cookie。** `get_crawler` 传
  `data/chrome_profile/<平台>[/<账号>]` 作为 `--user-data-dir`：登录窗口与爬取是同一台设备，**一个 Cookie 一个 profile**
  （账号标签同时进文件名与目录名，`lock_for` 按路径，同平台两账号是两台可并行的设备）。保存的 Cookie 文件**只导入一次**。
  **保存 Cookie 本身就是更新**：`POST /api/cookies/save` 当场种进该账号 profile
  （`sessions/routes.py::_plant_saved_cookie_into_profile`）；“把 Cookie 更新进 Profile”按钮与
  `POST /api/cookies/refresh-profile` 已删除。浏览器被占用时保存仍成功并说明，下次抓取按 `needs_refresh`（文件戳新于标记）
  导入。**绝不把浏览器活 jar 写回 Cookie 文件。** `Capability.profile_recommended` 是“这个平台惩罚一次性浏览器”的唯一来源。
- **新账号的设备目录是生成的，不是复制的。** 程序用空的无头 Chrome 造一次 `data/chrome_profile/_template`
  （`crawlers.base.warm_profile_dir`），之后每个账号目录从它克隆。四条：**“干净”由行数回答，不由文件名**（空跑也写空的
  `Cookies`/`Login Data`/`History`/`Preferences`）；**拷贝拒绝自己的黑名单**——所有会话存储、`Local State`（机器绑定密钥）、
  `.crawler-profile.json`（会骗过只导入一次）；**只在首次创建时播种**（`os.makedirs(exist_ok=False)`，非空目录不碰）；
  **模板一旦不干净就销毁重建**。`_template` 是保留平台名。
- **Cookie 采集 ≠ 爬取能力。** `CookieManager.PLATFORMS` 是面板能登录谁，`crawlers.is_crawlable()` 是谁有爬虫。采到的 Cookie
  按平台过滤（`cookie_flow.retain_for_platform`），因为登录绕经 Google/Facebook；绝不把 YouTube 放宽到 `.google.com`。
  植入只在有 Cookie 需要的主机停一次（`_load_cookies` 保留被拒条目，空了就停）。

## §4 时间与列
- **相对时间只在读取那一刻解析。** 站点给“3小时前/昨天 21:30/2 days ago”，存原话会烂掉。每个平台把自己的时间格交给
  `engine/times.absolute`（RFC-822 → 站点中文展示形 → 相对词 → 原样）。**可识别集合封闭**，其余答 `''`，所以话题标签
  永远变不成时间戳；`douyin.publish_from_info`（`crawlers/platforms/douyin/rows.py`）**仍拒绝**相对词（那是 `·` 切分的
  片段，不是时间节点），`clean_publish`（页面标 发布时间 的格）转换。**精度照实说**：OFFSET（`3小时前`）答 `now − N`
  并保留时钟；只有日期名的（`昨天`）答当天 `00:00`；无年份日期（`09月26日`）**不推断**。Pinned：
  `tests/unit/foundation/test_times.py`。
- **列的含义属于它的来源。** 没有播放数就是没有播放数（抖音、微博搜索卡、小红书热榜）；站点没印的数字留空，不填 0
  （抖音粉丝/获赞、知乎点赞、红果空计数）；`parse_count` 把万/K/M 标签折成整数。评论台账键是站点身份
  （`平台`+`评论ID`），不是整行哈希（后者含会重编的 `楼层`）；`文章URL` 是八张评论表共用的 join 键，红果的剧集语义进
  `剧名`/`集序号`/`分集ID`，不改它。
- **楼中楼是节点自己的选择，不是平台的默认。** `include_replies` 只在真有子回复可采的评论表单上声明（知乎、微博、
  小红书、哔哩哔哩、抖音、红果；X/YouTube 的评论本身就是整张回复表，不声明）。关掉后必须三件事一起成立：不点
  “展开 N 条回复”一类开器、不把接口随行带回的子回复入表、父行 `子回复数` 保留站点自己的计数。短表的原因也要分开说：
  关闭导致的差额是用户的形状（不钉游标），**开器点了却没展开**才是由站点作证的缺口（钉游标、可继续）。

## §5 平台红线（机制与数字见 `docs/crawler_notes.md`）
- **抖音**：无头可用；搜索模式与“筛选”菜单已删除（`search()`、`_SORT_FIELD`/`SORTS` 与真站用例一并删）；**没有播放数列**；
  作者只有不透明 `sec_uid`；不要拦它的图片；作者网格靠容器触底（第一次触底常不拉），详情页只有身份（作者或发布时间）缺失
  才拒；作者读取走站内遮罩，限定 `[data-e2e="feed-active-video"]` 子树；评论虚拟化、按 `(作者,正文,时间)` 去重、回复嵌在
  父项 `.replyContainer`；`评论地区` 逐视频，不给就留空；`验证码中间页` 只在 tab 标题里，作者网格没到才 latch `risk_blocked`。
- **B 站**：`page=1` 渲染 0 张卡（第一页要裸 URL）；评论没有 DOM，只走 `x/v2/reply/main` 的服务端游标；作者模式是 space
  **页面**（`arc/search` 回 403-wbi），靠 `下一页` 换屏 + 当前屏 BV 集合当哨兵；热榜条目自带 `owner`/`stat`，`hot()` 不逐行
  请求；`view`/`reply` 错误码按“怪谁”分类（视频级码 DEAD，会话/IP 码 BLOCKED）。跨运行水位是**内容边界**：只有最新在前 +
  稳定身份可停在上一完整运行的最新 id，边界条目不请求，只有干净结束才推进，其它模式按名拒绝且与 重新采集 互斥。
- **微博**：绝不在 `get()` 后立刻看 URL 判墙（passport 一闪再弹回）；`/ajax/statuses/mymblog` 是每会话 403，必须出声拒绝；
  窗口滚动不带新行；搜索页会在同一 `#pl_feedlist_index` 里塞推荐帖并同时印“未找到相关结果”，所以**先看无结果面板再看卡片**。
  评论只回主楼（`flow=0`），楼中楼只有父行 `comments[]` 预览；`serial_only`（同账号深翻页互相撞）。
- **知乎**：无头按天限流（40362），无头搜索 0 行是合法结局；评论面板靠**自己的滚动容器**懒加载，没有“更多”按钮，子回复在
  展开器后；搜索卡是摘要，只有链接是 `/answer/` 的卡可点开且**只替换 正文**；作者分母来自 profile meta
  （`zhihu:answerCount`/`zhihu:articlesCount`）。
- **YouTube**：JSON 优先，`crawlers/platforms/youtube/innertube.py` 在已加载页内 POST（绝不硬编码 `INNERTUBE_*`）；频道投稿读
  已加载的 `/@handle/videos` 文档；continuation 按“它属于哪个列表”选。搜索与投稿标签**每次加载都轮换**，不能当跨运行去重
  供给；只有一条视频的评论游标可以。
- **X**：时间线虚拟化，进度按保留行数与**status-id 集合**，不是索引；五个计数来自一个 `[role="group"]` aria-label，
  **浏览数只在那里**；每卡一次 `execute_script`；`f=live` 不要断言互动数，断言浏览数。
- **小红书**：回放的会话几分钟内被墙（必须用平台 profile）；作者模式已放弃；搜索网格虚拟化，进度按不同 `笔记ID` 集合；
  没有总数也没有可读的“没有更多”，短表一律 `UNDER_TARGET`；过期 `xsec_token` 是一条死链
  （`comment.xhsRedirected`/`crawl.xhs.deadNote`），不是会话拒绝；笔记 URL 按站点“复制链接”的写法补 `xsec_source=pc_feed`
  （`rows.with_feed_source`，非空原样保留），只改导航 URL，不改行里的身份。
- **微信**：按测量只做正文——没有评论/点赞/转发列，**没有 Cookie 行**，没有 `mp_logged_in`/`login_url`/`diagnose`/
  `MULTI_PURPOSE`，不做客户端冒充或会话重放；公众号后台搜索因 `freq control` 从未观测到字段形状，已删除而不再猜。
  `live_site` 只访问文章 URL；面板 harness 取样 B 站/知乎，绝不用微信。
- **红果短剧**：四个榜是**一个模式 + 一个榜选择**，值是存储标识（`crawlers/platforms/hongguo/crawler.py::BOARDS` 是唯一名单，
  顺序与矩阵钉住）。榜读文档自带 loader 载荷（不读渲染列，且延迟到货，用 `wait_for_first_content`，绝不固定 sleep）；集数是
  payload `episodeVids` 长度而非 DOM 的 25 个播放窗；翻页跟站点自己的 `pagination.nextUrl`，`?page=1` 是裸 URL，未服务的
  `?page=6` 只剩 `rank_layout` → `stalled` → `PageNotArrivedError` 按名拒绝。匿名（`needs_session=False`，无 Cookie 行）；
  计数走 `parse_count`，站点没印留空；分类保留原样 `205`；`search`/`get_detail` 按名拒绝。
  **评论只活在 App 协议里，本工具只说不动、只旁听**：签名覆盖请求体（复刻回 110001），所以驱动第三方播放器走 mitmproxy
  收割它合法取到的 JSON（`harvest.py`/`player_ui.py`/`naming.py`）。用户自己开的播放器窗口 `playerBusy` 按名拒绝，绝不杀；
  导航走排行榜页每卡的 `▶ 播放`（找剧页没有搜索框），评论触发是动作栏 `💬 <数量>`；弹幕引导行（`create_timestamp == 0`）
  丢弃并计数；`book_id` 非 0 且是别的剧按名丢弃（真行打 `"0"`）；`site_end` 只在算术闭合时给出，否则留 `UNDER_TARGET`
  并另报 `shortfall`；UIA 树不醒是 `treeCold`（绝不说“搜不到剧”）；**WebView2 CDP 是死路，别再试**。展开按钮名字必须
  **同时**含 回复 与 展开/查看/更多（裸 `回复` 会毁掉一集），每集点完所有可见展开项（不设上限），`{Esc}` 还焦点，一次静默
  不算完、分级重试后才具名 `kept` 对 `total`。网页榜与客户端榜是两套排序，所以评论模式也接受纯剧名
  （`Field.accepts_names` 唯一声明），名喂的行 `文章URL` **留空**，错剧守卫用本页首个非 0 `book_id`；中途冷树抛
  `TreeCold`、按名 `skipped_targets` 后继续。`reply/list` 是**另一套信封**（`data.comment_list_info` + `data.reply_list[]`，
  元素体大写 `Common`，自有 `reply_id`，无 `data_list`），归一化后共用一行构造器；“是哪部剧”只问请求体
  `req_body.business_param.book_id`；web `series_id` ≠ client `book_id`。屏幕先问再收行（头部 `@剧名` 是唯一事实，`N / M`
  抽屉一开就没了），两次 PROCEED 偏置规则，读不到不算确认。
- **Instagram**：只采 Cookie（`supports_crawl = False`），执行器 `run.notCrawlable`、校验更早拒绝；它仍要 `domain` +
  `login_url`，不进 `CAPABILITIES`，且要过 `TestCookiePanelParity` + `TestPlatformOrder`。

## §6 采得不足、风控与收尾许可
- **短表必须由站点授权，绝不由我们自己的循环授权（U1/U2）。** `walk_feed`/`pager` 的自述（`'stuck'`/`'no_new'`）与
  软限流同形，执行器不得悄悄许可。契约是 `crawler.end_reason` 三态：`None`（handler 未迁移，门沉默，逐平台迁移不半红）；
  `UNDER_TARGET`（跑短且没见站点收尾 → 执行器**按名拒绝** `run.underTargetShort`，settle partial/可续跑）；或
  `crawlers.base.LICENSED_ENDS`（`'site_end'`/`'capped'`/`'empty'`，各要站点作证：结束标记、固定榜大小、服务端 200 空表；
  **不许可**只是“看起来空”的未渲染 DOM）。登录墙与用户 停止 先结算；风控有自己更早的闸。`Crawler.note_end(reason)` 对
  三态之外的值与非字符串直接抛；被定罪的短表可带 `scanned/kept/refused` 漏斗，只在三个都量到才打印。
- **当前武装**：许可侧已接有真实收尾的平台（抖音作者 `empty`/`capped`/`site_end`，知乎搜索 `no_more` + 热榜 `capped`，
  微博热榜 `capped`，YouTube 搜索 `drained`，B 站热榜 `empty`/`capped`，**红果热榜 `site_end`/`empty`**）；**只有红果 `hot`
  会定罪 `UNDER_TARGET`**（`nextUrl` 指回本页、或连续两页无新条目；续跑允许首屏一次不出新）。其余平台许可已接（许可与
  `None` 都干净结算），定罪仍缓——滚动/游标走查的“不再增长”在软限流与诚实续跑上同样触发。无可靠收尾信号的平台完全未武装
  （`end_reason=None`）：微博搜索/作者、YouTube 作者、B 站搜索/作者、小红书、X、知乎作者。
  Pinned：`tests/api/test_under_target.py`、`tests/unit/crawlers/test_hongguo_crawler.py`。
- **风控与 Cookie 死是两条相反的建议。** 短抓取且 `risk_blocked`、未达目标、无登录墙 → 抛 `run.riskControlled`：保留行、
  失败以便 继续、告诉用户**等**（明确建议 慢速采集），绝不建议立刻重跑或重存一个可能没问题的会话。抖音
  `_latch_risk_if_walled` 只在作者网格没到这一处置位，绝不在走查末尾复查。评论节点只在**每个**被挡平台都报风控、且无人报
  登录墙时抛风控；任何 Cookie 墙或无人认领都保留原 Cookie 判决与 `cookie_expired` 提示。Cookie 在抓取中死亡：`login_wall`
  + 不足行 → `execution_state['cookie_expired']` + `run.cookieExpired` 并**抛错**，节点 partial、运行 failed、继续 从游标
  重来；绝不降级成“少几行的完成”。
- **降低风控唯一被批准的手段是节奏，不是伪装。** `gentle_crawl` 缩放礼貌停顿（`Crawler._polite_pause`、抖音面板换屏等待）；
  评论引擎逐链接的 `nap` 是到达渲染预算，不缩放。不加 UA/`navigator`/指纹工作（伪装的输家是账号）。
- **零行不是证明。** 一条评论链接返回 `ok` + 0 行与“这条真没评论”是两件事：风控、Cookie 过期、登录跳转、面板未渲染、
  走到一半被停，都会得到一张读成“完成”的空表。只有站点自己说“就这么多”（小红书 `- THE END -`、B 站 `is_end`、站点印的
  “暂时没有更多了”）或用户 评论上限 命中时短表才合法；差额仍要 `comment.xhsShort`/`xhsNested` 点名。其余形状必须
  `session.mark_unproven(url)`，执行器当洞口（`url_index` 停在这条之前）并以 `run.commentsSkipped` settle partial，继续
  从这条重采。到达判定用共享 `wall.classify`：`login` → `login_wall`，`blocked`/`unreachable` → `risk_blocked`。
  Pinned：`tests/unit/crawlers/test_comments.py::TestXhsAdapter`、
  `tests/api/test_source_dispatch_matrix.py::test_an_ok_walk_that_names_itself_unproven_still_pins_the_cursor`。

## §7 机器边界 / 一个模式允许在哪台机器上跑
- **能不能跑只问 `capabilities.registry.requirement_met(token)` 一个问题，问四次。** 红果评论要驱动本机播放器并把
  mitmproxy CA 装进 Windows 证书库，所以标 `requires='windows_desktop'`：① `/api/capabilities` 的 `machine` 给出**这台
  服务器**的判定；② 面板把那一项**列着但置灰**并写明原因（节点存的正是那个模式，不列会画成“第一个模式”，那是面板在谎报）；
  ③ `engine/workflow.py::validate` 在**运行之前**按名拒绝；④ 执行器 `_ensure_stack` 仍自己拒一次。判定**缺失**时照常可见可用。
- **窗口类要求在 cloud 模式同样不满足**，哪怕系统是 Windows：没有可驱动的桌面不等于有桌面。这与“强制无头”“拒绝浏览器生成
  Cookie”“拒绝本地 Ollama”是同一个 `CLOUD_MODE` 的不同面。

## §8 第二采集后端 / The second crawl backend (CatBus)
- **能力清单只来自适配器。** `services/ingest/catbus.py` 读 `catbus-crawler-workflow capabilities` 并按 `PROBE_TTL` 缓存；
  `平台 × 模式` 的可用性、输出列、身份列全来自那份 JSON，Python 侧**不抄表**。新增平台/模式只改 CatBus。
- **拒绝按名，绝不静默降级；入口是构建产物，不是源码。** 缺 Node／缺适配器／Node 过旧／清单读不出／组合未适配／登录缺失／
  风控，各抛一句带 `catbus.*` 与适配器 hint 的拒绝，没有一条允许返回空表；后端切换不回退。填 `cli.ts`、`cli.js` 或 CatBus
  目录都合法：`core.machine.catbus_source_twin` 映射到同检出的 `dist/…/cli.js`，`catbus_entry_at` 给出入口，而
  `catbus_entry_usable` 拒绝源码后缀（Node 跑不了 TS）；缺构建产物按名说明（`catbus.sourceOnly`/`set.catbusSource`）。
- **后端是节点身份的一部分，两套登录态分开发问。** `services/runs/store/identity.py::stable_params` 把 `backend` 计入指纹，
  同时把 `selenium`/缺省折叠掉，两套去重账本与水位作用域永不混。CatBus 只认 `params.catbus_account` 与 `~/.catbus/`；
  `cookie_preflight.entry_of` 读 `(platform, account, backend)`，`entry_key` 只给非浏览器后端加 `#catbus`。清单
  `auth: required` 的 cell **每次执行前都问**（浏览器开关关掉也问），`auth: optional` 与机器采不了的 cell 不问；CatBus 下
  数据源节点的 `account` 不参与判定。
- **失败要带上适配器自己的话。** 列表拒绝在 summary 顶层 `error`，评论在 `articles[].error`，两边都要读并拼 `code`/`hint`；
  评论路径 `_refuse` 先拼好再抛（一条失败一行），无 summary 时 `_reason_of` 保留最后几行 stderr 与退出码。`login_wall`/
  `risk_blocked` 在后端**永不置位**，改为 `catbus <平台> auth login` 的拒绝。
- **不假装做不到的事。** CatBus 没有偏移/游标：源节点续跑重放清单、账本挡重复；跨运行水位只界定入库行，这必须打印
  （`catbus.watermarkNote`）；评论逐链接起进程，`url_index` 只记已证明的连续前缀，partial 链接进 `skipped_targets`。
- **只读能力才进清单，引擎是一等维度。** `write()` 声明的命令带 `mutating: true`，生成时机械排除，`msg *` 另按资源拒绝，
  适配器测试从 `vocab.ts` 清点 `write(` 与 `mutating` 双向核对。`capabilities/registry.py` + `capabilities/platforms/<id>.py`
  从清单物化 CatBus 独有模式，`modes_for/mode_for/mode_of_node/crawl_kwargs` 按引擎发问，`as_dict()` 给平台 `engines`、给模式
  `engines` + `cells`；不可运行的一对**列着、置灰、点名**；没被适配器消费的数据条件按名拒绝
  （`catbus_bridge.declared_params`），默认值不算条件。
- **进程边界写死 UTF-8 与进程树。** 参数经 stdin（`--params -`）不走 argv；stdout/stderr 按字节读回显式 decode；子进程按
  token 登记，停止与超时走 `utils/procs`（`CREATE_NO_WINDOW` 只在 Windows 存在，POSIX 返回空 kwargs）。
- **macOS 有 CatBus 官方构建**：在线安装器按 `darwin-arm64`/`darwin-x64` 下载并随主程序装好 Node，
  `CIXI_CATBUS_CLI`/`CIXI_NODE_BIN` 在导入配置前由启动器导出；自建用户仍可在设置里指向自己的 Node 与 `cli.js`。

## §9 账号池与出口池 / Account and exit pool
细节与归因表见 [account_pool.md](account_pool.md)。采集端守住三条：

- **只在“本次零行 + 登录墙/风控”时换号**（`SessionBlockedError`）。已有行落库走 PARTIAL + 继续；换号不能让账本、游标或
  “采得不足”看见第二个答案。**评论节点按链接换号**：失败链接本来就不在已证明的连续前缀里，重走不需要移动 `url_index`。
- **每次尝试重新 `gate.hold(account=该次真实账号)`**：`@pool` 是哨兵，永不进 `CookieManager.path_for`，但留在指纹里。
  池模式不对同一账号再撞 `wall_retry_backoff`；CatBus 按名拒绝 `@pool`。
- **评论模式的数据源节点只在每条链接取 lane，绝不整节点再取一次**（`source.run` 与池分支同一条规则：`handler == 'comments'`
  时不取节点级 turn）。出口按 `(平台, 账号)` 粘性；出口全坏且不允许直连时按名拒绝，绝不静默直连。
  Pinned：`tests/unit/crawlers/test_source_comments_lane.py`。
