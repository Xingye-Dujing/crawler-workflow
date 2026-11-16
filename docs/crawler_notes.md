# 采集端平台契约（当前状态）

改爬虫、它的列或真站断言前，先读本文件对应平台小节。这里只写**现在必须遵守的契约**：模式、会话需求、列表/评论入口、
身份列、已知拒绝与节奏。要复测就用一次性 `backend/test_<平台>_<事>.py`，载荷进 `scratchpad/`；下文的数字就是结论，
不复述测量过程。

**已删除模块**：`engine/menu.py`（抖音筛选菜单的 hover 助手，随搜索模式一起删除，勿按旧文重加）。

旧文按“测量步骤”命名的小节（如“微博第 0 步”“抖音热榜”）现分别对应本文件的平台小节，以及该小节里同名的加粗入口。

## 平台总表

| 平台 | 模式 | 会话 | 列表 / 评论入口 | 身份列 |
|---|---|---|---|---|
| 抖音 | 作者、热榜、评论 | 作者需 profile（建议），热榜需 Cookie | `/user/<sec_uid>` 网格；视频详情；评论面板 | `sec_uid` / 视频ID / 评论ID |
| B 站 | 关键词、作者、热榜、评论 | 需 | 搜索 `&page=`；space 页；`x/v2/reply/main` | BV 号 / `rpid` |
| 微博 | 搜索、作者、热榜、评论 | 搜索/作者/评论需；热榜匿名 | 搜索 URL 翻页；`mymblog`；`hotSearch` | `mid` / 评论ID |
| 知乎 | 搜索、作者、热榜、评论 | 需 | 滚动信息流；profile meta；热榜 API；评论容器 | 回答/文章 id / 评论 |
| YouTube | 搜索、作者、评论 | 需（匿名也可读部分） | innertube POST；`/@handle/videos` 文档 | videoId / 评论 id |
| X | 搜索、作者、评论 | 需 | 虚拟化时间线 | status id |
| 微信 | 正文 | 无 | 文章 URL | 文章 URL |
| 小红书 | 搜索、评论 | 需平台 profile | 虚拟化网格；笔记评论面板 | 笔记ID / `评论ID` |
| 红果短剧 | 热榜、评论 | 匿名 | loader 载荷；播放器 + mitmproxy | 剧/`分集ID` / `评论ID` |
| 中国知网 | 检索导出 | 需 profile（滑块） | `kns8s/search`；`manage/export.html` | `记录ID` |

## 抖音

- **模式**：作者 / 热榜 / 评论。关键词搜索与右上角“筛选”排序已删除（站点供给太浅，同一关键词两次只给 26 / 16 条，
  且 `search()`、`engine/menu.py`、`_SORT_FIELD`/`SORTS` 与真站用例一并删）；不要再按旧文重建搜索框、`/search/<kw>` 或
  hover 菜单。无头可用，无头即按所选。
- **会话**：`profile_recommended`——一次性浏览器 + 种入保存 Cookie 8.8 秒被弹验证码中间页；平台自己的 profile 24.8 秒交出
  5 行。热榜读反方向：profile 被弹验证码、一次性浏览器能读，所以这个标记**只是建议与提醒，绝不强制**。热榜
  `needs_session=True`，live 用例显式 `use_profile=False`。
- **作者入口**：`/user/<sec_uid>`（数字 id 不是路由，显示名拒绝）。窗口滚动只长 footer 推荐链接；作品网格
  `[data-e2e="user-post-list"]` 要把可滚祖先拖到 `scrollTop = scrollHeight`（`feed.jump_to_bottom`）。懒网格**第一次触底
  常常不发请求**，预算内重复触底直到真长；`[data-e2e="user-tab-count"]` 是分母。`_published_count()` 读不到答 **-1**
  （空串走 `parse_count` 会答 0，而 0 是一个主张）。
- **作者行**：点网格卡片在**同一文档**弹预览遮罩（URL 变 `?modal_id=`），一切读取限定
  `[data-e2e="feed-active-video"]` 子树，否则读到邻条；正文 `video-desc`，作者 `feed-video-nickname`（去 `@`）；发布时间只在
  `video-info` 且更粗，**只认带年份的绝对日期**，相对词/标签/无年份一律留空；粉丝/获赞不在遮罩里，从个人页
  `user-info-fans`/`user-info-like` 读一次套用。卡片点不开就跳过该 id，绝不回退去 `/video` 整页导航；整轮 0 行而卡片确曾
  存在 → `UNDER_TARGET`；遮罩内见验证码 → `risk_blocked`。
- **详情页**：每行来自打开视频。既无作者又无发布时间 → `crawl.dy.detailNoIdentity`（只有计数条不是行；无文案但有作者与日期
  仍是行）；被站点重定向到 `/note/<id>` 的图文页常是验证码中间页 → 逐行 `crawl.dy.detailWalled`，**不 latch** `login_wall`；
  id 被换成另一条视频（地址 id 与要的不一致）→ `comment.dyGone` + DEAD，绝不念替身视频的计数。四个计数选择器
  （`video-player-digg`/`feed-comment-icon`/`video-player-collect`/`video-player-share`）有效；`detail-video-info` 的第二个数
  就是赞数，所以**没有播放数**——加一列就是名字对、值错。粉丝/获赞页面不发布时留空。
- **评论**：面板挂载与每次滚动都由爬虫内部轮询，绝不靠调用方 `nap`。列表**虚拟化**（滚过去即卸载），身份按
  `(作者,正文,时间)` 全局去重；回复也是 `[data-e2e="comment-item"]` 但嵌在父项 `.replyContainer` 里，用
  `closest('[class*="replyContainer"]')` 跳过顶层读取。`楼层` 整栏连续编号，`父楼层` 指向父评论楼层，`子回复数` = 实际展开
  到的子行数（打不开退回站点自报 N）。展开只认真按钮 `button[class*="comment-reply-expand"]` + 原生 ActionChains；点过的项打
  `data-dy-tried`、只试一次绝不重（重点会把线程合回去），一轮批量点完只 `nap(1.3)` 一次，收工看“还有没有**没试过**的
  opener”；已删除/不可见的线程直接跳过；`_dismiss_douyin_popup` 关掉 `.semi-modal`/`.semi-toast`。“是否保存登录信息超过5天”
  遮罩到货后按 取消 关掉。`评论地区` 是逐视频的站点数据，没印就留空（不要用 `any(评论地区)` 作硬断言）。
  `comment.dyShort` 的欠额按 `declared − Σ子回复数` 判，不拿行数直接对站点数。
- **热榜**：`HOT_API` 写 18 个公开参数，**不需要签名**（假 `webid` 不改结果，退到 6 个会丢整列 `view_count`）；一次回答就是
  整块榜，不翻页、不逐条开话题页。`word` 既是标题也是话题，所以不设话题列；链接用榜自身的
  `douyin.com/hot/<sentence_id>/<词>`；榜首站点没给数字就留空、不给 0（`_published()`）。判墙只能用抖音自己的判定：
  `验证码中间页` 标题下通用 `check_intercept()` 说 `ok`，而 `_wait_for_page()` 说 captcha；读到墙时**一次请求都不发**。
  作者网格没到这一处才 latch `risk_blocked` 并具名提示等待；**不在走查末尾复查**（逐详情页验证码会留下过期标题而误杀）。

## Bilibili

- **模式**：关键词 / 作者 / 热榜（含排行榜）/ 评论。
- **关键词**：搜索不无限滚动（8 轮 42 卡 / 34 视频不变），行预算靠 `&page=N`，**`page=1` 渲染 0 张卡**，第一页必须用裸
  `all?keyword=` URL。卡片上的万标签只是取整标签，每个数来自 `x/web-interface/view?bvid=`（`code=0`、未签名、可从搜索页
  跨源）。`cm.bilibili.com` 的广告卡由 `--ad/--cheese` 过滤，不是漏采。`code is None`（非 JSON/WAF 体）要
  `crawl.bili.fetchEmpty`，`-404` 要 `crawl.bili.goneVideo`，否则一条请求既不出行也不出一字。
- **评论**：评论区**没有 DOM**，只走 `x/v2/reply/main`；它的 `next` 是游标：`next=0` 报 `cursor.next=2`，`next=1` 逐字节重放
  第 0 页——必须按服务端的值走，并在没有新 `rpid` 的页停。错误码按“怪谁”分：视频级 `-404`/`-400`/`62002` 是该链接自己的
  DEAD；只有会话/IP 码 `-352`/`-412`/`-101` 是 BLOCKED（可 latch `cookieExpired`）。限流时 `is_end=True`/空页不能当线程结束：
  用已读 `stat.reply` 当分母，未达上限且收到 < 分母 → `comment.biliShort`；收到 == 分母或达上限则一字不说。
- **作者**：space **页面**，不是 API（`x/space/wbi/arc/search` 回 `-403 访问权限不足`，旧 un-wbi 路径 `-799` 限流）。投稿页靠
  `下一页` 换屏：滚动与元素滚动都不加卡，点它整屏换成另外 40 张、交集 0、URL 不变，所以哨兵是**当前屏 BV 集合**而不是卡片数。
  `use_profile=False` 只给 0/25 卡（生产托管 profile 首屏 40）。数字仍来自未签名的 `x/web-interface/view`，两种模式的行一致。
  `bilibili_mid()` 只收数字或 space 链接，其余拒绝。
- **热榜**：`x/web-interface/popular` 每页 20、第 2 页与第 1 页不相交；`x/web-interface/ranking/v2` 一次回整榜（实测 100 条），
  条目自带 `owner`/`stat`/`pubdate`，所以 `hot()` 复用 `_row()`、不逐行请求。`target > 100` 打 `crawl.bili.rankingCapped`
  点名榜单真实大小。排行榜跨浏览器稳定（两次 first-10 顺序一致、集合交集 10），是合法的去重供给。
- **跨运行水位**：只允许“最新在前 + 稳定身份”的作者走查停在上一完整运行的最新 BV；边界条目不请求；只有干净结束推进；
  与 重新采集 互斥；其它平台/模式按名拒绝。

## 微博

- **模式**：搜索 / 作者 / 热榜 / 评论。搜索、作者、评论需登录；热榜匿名可读（见下）。
- **搜索**：列表靠 URL 翻页，不靠滚动（`.page-info` 印“共50页/500条”，窗口滚 4×1600px 后卡数不变）。一个 timescope 小时窗
  自己也分页（`ul.page-list a` 给 page=1..10，页间 mid 交集 0），必须逐页走，不能因“窗口已窄”停。空窗会**同时**给
  `.card-no-result`（“抱歉，未找到相关结果”）和 5 张带作者的推荐卡，祖先链与结果卡同构、没有容器可隔离：**判据顺序必须先看
  plate 再看卡片**。正文不截断（`feed_list_content_full` 已在 DOM；`text_raw` 完整）；搜索卡没有浏览数。
- **作者**：`https://weibo.com/ajax/statuses/mymblog?uid=<UID>&page=<N>&feature=0`，在已加载页内用 `credentials:'include'`
  fetch（不是独立请求）。page 1 可回 28 行、其余 20；page 1 多于 20 是事实，不要归一化。结束形状是**空页** → `site_end`
  （0 行则 `empty`）；`no_new`（游标重放）与 mid-walk 403 仍留下行 → `UNDER_TARGET`。首行 `user.id == uid` 是区分“真作者”
  与“首页时间线镜像”的唯一锚（两者都 200、同信封）。`text_raw` 是完整正文，**不需要逐条详情**；话题在 `topic_struct` 的
  `topic_url` 的 `q=%23…%23`（title 是空的）；行有 `pic_num`/`pic_ids` 但没有 `pics[]`，所以图片数有、图片链接留空；
  视频数不伪造。身份是数字 `mid`/`id`，链接按搜索模式 `weibo.com/detail/<mid>`。作者走 JSON、不抄搜索卡的 DOM。
  该端点会回 `<h2>403 Forbidden</h2>`（每会话 edge/WAF），必须**出声拒绝**，绝不空表。
- **评论**：`flow=0&fetch_level=0` 只给主楼；`count=100` 被服务端无视（仍 20/页）；`total_number`（信封）是唯一可信分母，
  `trendsText`“已加载全部评论”不可信。`楼层` 用站点 `floor_number`（全楼层号，不是每页从 1 数）；赞数是 `like_counts`；
  `评论时间` 过 `_normalise_weibo_time`；`评论者主页` 用同对象的 `profile_url` 拼 `https://weibo.com`（不是头像 URL）；
  `评论内容` 先读 `text_raw` 再剥 HTML（纯表情评论剥完是空串）。楼中楼只有父行 `comments[]` 的行内预览能白拿，其余端点形状
  都拿不到整批 → 按名报差额。游标页耗尽打 `comment.weiboShort`，站点复读打 `comment.weiboReplay`，取数失败打
  `comment.weiboFetchDied`（差额只对“游标收到的行数”判，收到==站点数则一字不说）。
- **热榜**：`weibo.com/ajax/side/hotSearch` 在已加载的 `weibo.com` 文档里读（`pagefetch.fetch_json`）：`ok:1`，`data.realtime`
  51–52 行，`num` 是精确整数（所以选 JSON 不选 DOM 表）。必须等引导把浏览器送回 `weibo.com` 再发请求
  （`_await_home_frame`，每 tick 问 停止），等不到打 `crawl.weibo.hotNoHost` 并打出所在帧——从 passport 帧发同源 fetch
  会被浏览器拒，长得跟“站点不给数据”一样。三种会话都答（含完全无 Cookie），所以 `needs_session=False`。一条热搜不一定是
  `#话题#`（`word_scheme == word` 真存在），话题列存站点自己的串，按它去搜索。
- **墙与节奏**：绝不在 `get()` 后立刻看 URL 判墙（passport 一闪再弹回，`_await_search_page` 等终态）。同账号并行深翻页会
  互相撞 → 矩阵 `serial_only`，2+ 微博抓取的并行画布运行前警告；真正的并行只能靠分账号。墙是**间歇风控**（单次一到两成），
  与发车间隔无关，`runtime/gate.py` 不加冷却；真机层撞墙重试 3 次，每次等 `Config.WALL_RETRY_BACKOFF`。
  **绝不把浏览器活 jar 写回 Cookie 文件**（登录页会重发 `SUB`/`SUBP`，写回一次就降级一次）。

## 知乎

- **模式**：搜索 / 作者 / 热榜 / 评论。无头按天限流（risk 40362），无头搜索 0 行是**合法结局**，不要放松断言；它也**不是**
  `never_headless` 平台。
- **作者分母**：profile tab **不渲染**“没有更多”footer（6 个 tab、最深 637 项滚到顶全 `footer=False`），但 profile 页 meta 带
  `zhihu:answerCount`/`zhihu:articlesCount`（站点亲口的作品总数）。`collected < 总数 且 < target 且非墙/风控/停止` →
  `UNDER_TARGET`；`collected ≥ 总数` → `site_end`；meta 读不到 → 分母 -1、跳过（读不到 ≠ 0）；到达 target 的普通爬两条都不
  触发，`None`，判完成。
- **搜索卡是摘要，不是答案**：摘要不是 CSS 截断，是内联 span 的真实长度；回答卡的 `button.ContentItem-more`（阅读全文，
  无 href）原地重渲染同一节点（74→308、75→782、69→1067、71→2103 字符），URL 不变、不产生第二份。**只有行自己链接是
  `/answer/` 的卡可点**，列卡的控制是导航，不点；锚点没挂上的卡种类未知，也不点。展开同时把日期标签从 `.SearchItem-time`
  移到 `.ContentItem-time`、去掉 `作者名：` 前缀，所以**行在首次读取时冻结，只替换 正文**。每张回答卡一次有界等待（上限 4 秒）；
  连续三次点了不出内容就停（`crawl.zhihu.expand_stopped`）；用户关闭展开只打一次 `crawl.zhihu.excerpt_only`，仍留摘要的行计
  `crawl.zhihu.bodies_short`。API 路线可用但不需要。
- **评论**：面板是 position:fixed 覆盖层，首屏 10–12 条；**没有“更多”按钮**，分页靠**面板自己的滚动容器**懒加载（滚窗口无效）。
  子回复在“展开其中 N 条回复”/“查看 N 条回复”后。作者只在“仍只包含这一个 `.CommentContent` 的最深祖先”里找，找不到打
  `comment.zhihuNoAuthor`，绝不按固定深度取（会取到邻座名字）。`评论时间` 真读（近期相对词、远期绝对日期），`点赞数` 留空
  （页面不发布；0 会被用户拿去排序画图）。滚动目标选“含 `.CommentContent` 最多的盒子”，不是第一个（子回复列表自己也合格）。
  展开后**绝不能 `driver.back()`**（面板整个消失）。收工只有三件事：连续 3 轮零新增且无未点开回复、用户 停止、用户 评论上限；
  **没有轮次预算**。不到页面自印数字打 `comment.zhihuPanelShort`（写着 N 条，取到 M 条），每轮打 `comment.zhihuRound`。
- **热榜**：`www.zhihu.com/api/v3/feed/topstory/hot-lists/total?limit=50`，页内 fetch；恰好 30 行，`paging.is_end=true`。
  `limit=100`/`offset=30`/`page=2`/猜的 cursor 都回同一批 30 个 id，所以**没有翻页循环**；`target > 30` 时日志明说榜单只有
  这么多。无 Cookie 直接 `401` 且首页跳 `/signin`，所以 `login_wall` 在问接口前就成立（一次请求都不发）。有 Cookie 时无头与
  窗口同答案。`target.author.name` 30/30 都是字面量“用户”、`target.comment_count` 30/30 都是 0 → **不成列**；`answer_count`/
  `follower_count` 有值，保留。`target.url` 是 `api.zhihu.com/questions/<id>`，重写成 `www.zhihu.com/question/<id>`；热度在
  `detail_text`（“398 万热度”），走 `parse_count`。

## YouTube

- **模式**：搜索 / 作者 / 评论；JSON 优先，无头本来就行，`page_load_strategy='eager'` + 拦图片（不读像素）。
- **入口**：打开**一页**读 `ytcfg`（`INNERTUBE_API_KEY` + `INNERTUBE_CONTEXT`，**绝不硬编码**，会轮换），然后在页内 POST
  `youtubei/v1/{search,browse,next,player}`（`crawlers/platforms/youtube/innertube.py`）：同源、未签名、带 Cookie。
- **作者**：频道投稿标签必须读**已加载的 `/@handle/videos` 文档**（`browse(browseId, params=videos)` 回的是频道**首页**，
  3.7 MB 货架、混着别家的视频），导航一次后从文档自己的游标翻页。
- **continuation 按“它属于哪个列表”选**，不按长度或位置：一轮评论里有两条 78 字符的排序菜单 token，各会重放第一页（台账吞掉
  重复、走查报成功、3000 条视频只出 20 条），另加每条有回复线程的 token；列表自己的翻页器是尾部元素。`next(videoId)` 更差：
  六个 token，评论那个一条视频 78 字符、另一条 146 字符，旁边还有 1412 字符的轨道 token，所以第一轮会**试**候选直到有一个回
  评论。
- **两种 view model 并存**：`lockupViewModel`（2025+）与 `videoRenderer`——搜索用前者（后者缺席）、频道 tab 用后者；只认一种
  的读取器在另一种上静默为空。
- **去重供给**：搜索与频道投稿标签**每次加载都轮换批次**（同一 NASA 两次给两个 10 行窗口），不能当跨运行去重供给；唯一稳定的是
  一条视频的**评论游标走查**。因此重复去重用例断言 `kept < limit`（两次之间可能有真新评论），不是 `== 0`。
- **评论 0 行要具名**：无法播放/地区限制的视频走 `comment.commentsClosed`，不是空线程；可播放线程的 0 才是游标用尽。
  评论节点与源节点共用台账，所以整轮都被去重时要打 `run.dedupe_skipped`/`..._all_skipped`（resume 与墙时不打），绝不只印
  “共 0 条评论”。

## X (twitter)

- **模式**：搜索 / 作者 / 评论；无头可用（曾因登录墙/403 被强制窗口，已退役）。
- **时间线虚拟化且慢**：`article[data-testid="tweet"]` 滚多远都只有 13–21 个节点，而 8 次滚动过了 139 条不同推文，所以进度按
  保留行数 + **status-id 集合**（`feed.walk_feed(window=…)` 看 `window_key()`），不是卡片数或索引。首屏实测 9.9 秒 0 卡、
  11.9 秒 11 卡，挂载轮询给 22 秒；短等待会把一次本该成功的搜索报成“没找到”。
- **计数**：五个数来自**一个** `[role="group"]` aria-label 句子（“1887 replies, …, 1.1M views”），走共享万/K/M 解析器；逐按钮
  标签只是回退，**浏览数只在这里存在**。`f=live` 的真实流几乎每条都读成“0 Likes. Like”，所以不要断言互动数，断言浏览数。
- **读法**：每卡**一次** `execute_script`，不是逐字段 `find_element`（`tests/integration/test_twitter_crawler.py` 两边都数）。
  卡节点可能在列举与读取之间脱离（`StaleElementReferenceException`），读到就保护、该推文留给下一轮。

## 微信

- **只有正文，按测量**：真实浏览器得到 `show_comment=0`、3.4 MB 文章 HTML 里 0 字节 `elected_comment`、`mp/appmsg_comment` 回
  HTML 验证页（“请在微信客户端打开链接”）；`MicroMessenger`/`XWEB` UA、客户端形状的 URL 参数、重放客户端解密 Cookie 都无效，
  因为门槛是服务端只为真实客户端会话签发的凭据。**不加客户端冒充或会话重放，也不加回评论/点赞/转发列**——浏览器里“没有评论”
  与“不被允许看”不可分，空表就是看着像真的假数据。所以数据源节点没有评论模式，`explainWechatLimits()` 与
  `settings.wechatLimits*` 说明原因。
- **没有任何 Cookie 行**：公众号后台关键词搜索是这套会话唯一解锁的东西，且实测 `appmsg?action=list_ex` 对三个账号、
  三种端点拼法、15 分钟冷却后的每次重试都回 `ret=200013 freq control`，字段形状一次都没观测到，所以删除而不上线。
  不要加回 `mp_logged_in`、`WechatCrawler.diagnose`、`WechatCrawler.login_url`、`cookie.wechat.*` 或 `MULTI_PURPOSE`，
  也不要按猜的字段名重写关键词搜索。因此没有任何东西可以“表现得像有登录”：`live_site` 微信文件只访问文章 URL（不访问
  公众平台、不等/跳 Cookie），cookie 面板 harness 取样真实登录平台（B 站/知乎），绝不用微信。
- **文章字段**：标题 `#activity-name`、公众号 `#js_name`、时间 `#publish_time`/`.rich_media_meta_text`、地区
  `#js_ip_wording`、正文 `#js_content`，每条各命中一次；正文完整保留（`WECHAT_BODY_MAX_CHARS=0`），设上限时以 `…` 收尾。
- **游标只记位置**：`url_index`/`url_total`/`done`，URL 由节点 textarea 重建；绝不把链接列表写进游标。已知低优先缺口：
  `get_detail` 用裸 `self.driver.get` 而非 `Crawler.open`，没记 settled，所以“页面没到”与“到了但某列为空”在此平台不可分。

## 小红书

- **模式**：搜索 / 评论。回放的会话几分钟内被墙（必须跑平台自己的 profile）；作者模式已放弃（需逐笔记 `xsec_token`，正在被
  风控的会话不能可靠拿到），不要靠猜 token 管线重建。
- **搜索**：网格是虚拟化信息流，首屏挂 22 卡，4 次滚动挂载数一直是 12/8/8/8——**进度按不同 `笔记ID` 集合**，不是卡片数。
  每轮重扫整个挂载批（`seen` 在详情导航前挡掉复用卡，不重付），滚动后给一个有界渲染节拍。走 `feed.walk_feed(window=…)`
  （共享引擎，不是第二份滚动循环）。网格不发布总数、也没有可读的“没有更多”，所以短表**绝不**被许可为完成：
  搜索 `note_end(UNDER_TARGET)`，执行器按名“采得不足”并允许继续；停/墙/风控在更上游结算。`crawl.xhs.exhausted` 已删除
  （它分不清真到底与慢页面），live 评分只看 `SHARED_EXITS`。
- **笔记入口**：链接按站点“复制链接”的写法补 `xsec_source=pc_feed`（`rows.with_feed_source`：缺就补，**非空原样保留**，
  `pc_search`/`pc_user` 是站点为那个入口签发的）；只改导航 URL，行里的 `笔记链接`/`文章URL` 保持用户给的身份。只处理
  `xiaohongshu.com` 主域，`xhslink.com` 短链原样交给站点跳转，`xsec_token` 逐字符透传。`xsec_token` 过期/被剥掉会被送回
  feed：落地没有笔记 id → `comment.xhsRedirected`（带实际落点）+ `DEAD`，不滚首页、不读不存在的面板；落地在别的主机（短链）
  仍可重试。单篇详情同样用 `judge=False` + 非上锁的 `verdict`：被墙的详情是具名死笔记 `crawl.xhs.deadNote`，保留网格卡真实
  字段，一个过期 token 不拖死整轮；会话墙仍在搜索页每轮检查。
- **评论结构**：一条顶层评论是 `.parent-comment` 包装层（内含自己的 `.comment-item` + `.reply-container`），子回复是
  `.reply-container` 里的 `.comment-item.comment-item-sub`——父子是**兄弟不是包含**，按 `.comment-item` 平铺读会收进子回复却说不出
  它属于谁。每个父默认只挂 1 条回复，其余在 `div.show-more`（“展开 N 条回复”）后面。`.comments-container .total`（“共 N 条
  评论”）**含楼中楼**，是唯一诚实的完成分母。两级都有 `id="comment-<24hex>"` → `评论ID`；作者链接 token 每次访问都变，列里
  只留路径；`.date` + `.location`，日期走 `times.absolute`，地区单列；点赞可能是 `1千+`/`3,204`/`赞`，走 `parse_count`。
- **走法与列**：一屏一次页内 `PANEL_JS` 读回整屏分组；`楼层` **只给顶层评论**编号 1..N，回复位置由 `父楼层` 表达；`父楼层`
  顶层空、回复指向父楼层；`子回复数` = 实际落库子行数，展开失败退回站点数；去重键 `评论ID`，退路
  `(作者,正文,时间,地区)`（旧的 `(作者,正文)` 会吞同一作者连发的两条“谢谢”）。展开器认元素 `.show-more`（登录后文案会变成
  “展开更多回复”，不能认句子），原生 ActionChains **点到该线程不再长为止**（站点分批给）；被拒弹 `.login-modal` → 关掉、
  停手、`comment.xhsLoginGate`。滚动**含评论最多**的可滚容器（实测 `.note-container`；`.note-scroller` 只推动正文栏，
  旧写法因此停在前 30 条）。收工 = 连续 3 屏无新行 + 展开器不再长 + 滚动没换出新卡；站点印 `- THE END -` 时记为已到末尾。
  对账 `共 N 条` vs 本表 + 未展开数 → `comment.xhsShort`；数字对得上但仍有回复未展开 → `comment.xhsNested`。地址里的笔记 ID
  变了 → `DEAD` + `comment.xhsGone`。点击前用**站点自己的关闭控件**关掉 `.comments-login`/首访 `.login-modal`（`ESC` 会关掉
  整篇笔记）。
- **`ok + 0 行` 不是完成**：评论区的墙可能不出现在页面正文里，所以走查返回 `ok` 0 行也会越过游标。现在：URL 跳 passport/
  `chrome://`/错误页 → BLOCKED 并 latch 对应墙旗；面板 `.comments-login` → BLOCKED + `login_wall`（保留已读父评论）；展开被
  `.login-modal` 拒 → 收尾 BLOCKED、游标钉住；面板没渲染/走到一半被停/差额对不上且站点没印 THE END → `mark_unproven(url)`
  （节点 partial，继续从这条重走）；印了 `- THE END -` 的差额照旧点名但**算采完**；用户 评论上限 命中不报也不算未证明。

## 红果短剧（hongguo）

- **模式**：热榜（一个模式 + 一个榜选择，值是存储标识，`crawlers/platforms/hongguo/crawler.py::BOARDS` 是唯一名单）/
  评论。`search`/`get_detail` 是按名拒绝（没有测量过这种模式）。四个榜匿名（一次性浏览器、无 Cookie 都给），所以
  `needs_session=False`、面板没有 Cookie 行、节点没有账号字段；`live_crawler` 与微信同列免 Cookie 豁免。
- **榜单在文档自带 loader 载荷里，且延迟到货**：`window._ROUTER_DATA.loaderData['rank_<slug>/page']`。站点当前把数据放在 `content`
  本身（旧的 `content._data` 仍接受），读取器接受两种形状（`content._data !== undefined ? content._data : content`），thenable 仍
  按“没到货”处理；用 `wait_for_first_content`（`state=='ready'`）轮询，**不固定 sleep**。一行 20 条自带
  title/cover/href/playHref/heatText/statusTags/scoreText/favoriteText/likeText/tags/description/episodeVids/seriesId，任何字段都不
  需要再点一次。`?page=1` 与裸 URL 同页，所以第一页不带参数。
- **翻页与收尾**：跟站点自己的 `pagination.nextUrl`（那个 URL 就是游标）：为空 → `site_end`；`isSuccess is True` 但 `rankList`
  为空 → `empty`；`nextUrl` 指回本页、或连续两页无新条目（续跑允许首屏一次不出新）→ `UNDER_TARGET`。`?page=6` 是“这一页
  不存在”：只渲染 `rank_layout`、0 卡、导航已 settled，`wait_for_first_content` 的 `stalled` 判据是“loader 里没有 `/page` 键
  **且** 导航已 settled”，触发即 `PageNotArrivedError` 具名拒绝（带 URL 与实际键），既不读成空表也不当成循环自述。
- **列**：集数 = `episodeVids` 的条数（实测 222/69 与播放窗 25 个链接对不上，按屏数少一个数量级）；热度/收藏/点赞是站点四舍五入
  的万标签，走 `parse_count`，没印数字的格子留空不填 0；分类保留站点原样数字标签（`205`），不是解析失败。
- **评论只活在 App 协议里，本工具只旁听**：网页端没有评论区；签名覆盖请求体且绑时间戳（原样/换新鲜 ticket/换剧集三种重放都回
  `Code 110001`），所以驱动第三方桌面播放器（Wails/Go）走我们自己的 mitmproxy，收割它合法取到的明文 JSON
  （捕捉 `harvest.py`、驱动 `player_ui.py`、纯命名规则 `naming.py`）。播放器的 Go HTTP 客户端认 `HTTPS_PROXY`、不做证书
  pinning；信息流每切一集且每 60 秒拉一次 `comment/list`（`count=90`、`comment_source=601`）。**用户自己开的播放器窗口**
  `playerBusy` 按名拒绝，绝不杀；只有本节点的 Popen 子进程在 `finally`/停止时收掉。导航走**排行榜页**每张卡的 `▶ 播放`
  （找剧页没有搜索框，是浏览流）；评论的确定性触发是动作栏 `💬 <数量>` 点击开抽屉（信息流的静默预取死于接口更新）。
- **解析与守卫**：`data_list` 混着弹幕引导行（`comment_id` 小数字、`create_timestamp==0`、带 `expand.danmaku_activity_info`）——
  丢弃并计数（`danmakuSkipped`），真评论 `comment_id` 是大 id 且是身份。未登录只有 `user_id`（评论者留空），登录后名字在
  `base_info.user_name`。`expand.book_id` 是剧的 series_id；“这页属于哪部剧”**只问请求体**
  `req_body.business_param.book_id`（响应体兜底），`book_id` 非 0 且不同 → 按名丢弃（`groupMismatch`/`feedDrifted` 并停该剧），
  真行打 `"0"` 表示“未命名”不是“错剧”。web `series_id` ≠ client `book_id`（同剧两个 id 空间），参照只能是本页之外第一页自己的
  book。`reply/list` 是**另一套信封**：`data.comment_list_info` + `data.reply_list[]`，元素体大写 `Common`、自有 `reply_id`、
  父评论 `reply_to_comment_id`、父正文在 `data.comment`、**没有 `data_list`**——归一化回 `comment/list` 形状，两边共用一个行构造器。
- **走查纪律**：展开按钮名字必须**同时**含 回复 与 展开/查看/更多（`is_expand_control`；裸 `回复` 打开输入框会抢走键盘，一集 698 条
  只回家 20 行），每集点完所有可见展开项（不设点击数上限：按 (类型,名字) 记住已点，页面没有新项或播放器拒绝才收工），点完
  `SendKeys {Esc}` 还焦点。一次静默不算完：分级重试（滚轮 ×2 → `Esc`+硬滚 ×5 → `{PageDown}` ×2，`_page_wait` 随 stall 增），
  吃满 `_MAX_STALLS=3` 才判不完整并具名 `kept` 对 `total`；`site_end` 还要 `kept >= total`，不足即 `UNDER_TARGET`；harness 另报
  `shortfall`（本轮站点计数了但没留下的行），因为回复行不在任何一集印的总数里。UIA 树不醒是 `TreeCold`（≠“搜不到剧”），
  先 `wait_content(120)` 再试，仍冷按名跳过、记 `skipped_targets`，已采行保留。树冷中途复发同样 `TreeCold`，绝不比消息文案。
  `_click` 只在**严格落在播放器窗口矩形内**时点（防打到任务栏/用户桌面）；合成输入前先 `_activate`
  （`BringWindowToTop`+`SetForegroundWindow`），因为滚轮/键盘只作用于前台窗口。`Invoke`/`DoDefaultAction` 实测打不动这个
  Wails+WebView2 SPA，所以驱动方式是坐标点击，安全靠窗口边界守卫。**WebView2 CDP 是死路**（启动参数被 Wails 覆盖），
  别再试。`_visible_boards` 不截断（切换器列 11 个榜，砍到 8 个会静默跳过目标所在榜），成本控制在“每榜最多三次滚动、命中即停”。
- **屏幕先问再收行**：`PlayerUI.screen_drama_title` 读头部 `@剧名`（`@` 前缀、一次 dump 恰好一个），进剧后与每次 `↓` 后确认
  （`_confirm_position`）；`N / M` 集计数器只在视频页存在、抽屉一开就消失，拿 `第N集` 当闸门会误杀正常剧；`+` 表示“至少这么多”。
  两次 PROCEED 偏置规则：单次读到陌生剧名再问一次；剧名按**双向前缀、不限长度**匹配。读不到=没确认，下面的流量门照旧。
  `next_episode()` 没落地要计入未完成（`_count_unfinished`），因为没走到的集数站点不报总数。
- **列名**：`剧名` / `集序号` / `分集ID`（原名 `剧集ID` 装的是单集 `group_id`，名不副实已改）；`文章URL` **保留不动**——它是
  8 张评论表共同的 join 键（66 处引用），改名会让已采数据集的分析列全部找不到。剧名与集序号不在 payload 里，由 walker 注入。
- **两套榜单排序**：网页榜与客户端榜不同，所以评论模式也接受纯剧名（`Field.accepts_names` 唯一声明，面板检查、`engine/workflow`
  校验与评论路由共读）；名喂的行 `文章URL` **留空**（没开页面、没编链接），错剧守卫用本页 first-seen 非 0 `book_id` 作参照；
  榜名不硬编码：`_board_labels` 开“▾”读实际列出的榜（`_FALLBACK_BOARDS` 兜底），`_pick_board` 先看是否已在屏上。

## 中国知网（CNKI）

- **入口是 profile/Cookie，不是搜索**：新设备用本项目浏览器打开 `kns.cnki.net/kns8s/search` 会落到
  `verify/home?captchaType=blockPuzzle`（“安全验证”），`wall.classify` 判 `blocked`，爬虫按名拒绝而不交空表。在 Cookie 面板登录窗口
  完成一次滑块并保存后，同一持久 profile 检索页直接可用（导出菜单先查 `islogin()`）。
- **检索与选择**：搜索页 `input.search-input` + `input.search-btn`（`type=button`，需 JS `.click()`）；结果表
  `.result-table-list tbody tr`，复选框 `input.cbItem`（`value` 是加密导出键），总数 `.pagerTitleCell`，页码 `.countPageMark`，
  下一页是 `.pages a` 里文字为 `下一页` 的那个。页首“全选”`#selectCheckAll1` **只勾当页**，站点把跨页选择累积在 localStorage
  （`#selectCount` 显示累计）；单次上限 500（第 501 条被拒），所以**每页都点全选、最后导出一次**，到 500 前分批。
- **导出链路**：`导出与分析 → 导出文献 → Refworks`（`a[exporttype="Refworks"]` 的父 `li`）打开
  `dm8/manage/export.html`；屏幕列表只是**预览**（勾 40 条只渲染 20 个 `li`），要点 `a[title="导出题录文件"]` 下载
  `CNKI-…txt`（CDP `Page.setDownloadBehavior` 落临时目录），不读预览。文件每字段之间夹一个空行，先去掉、按 `RT ` 切记录，再交给
  `services.biblio.importer.parse_cnki`（与上传件同一个解析器）。**`POST /dm8/API/GetExport` 即使登录也回 `code=0 暂无数据`，
  不要用。** Refworks 是项目支持格式里字段最全的（150 行 / 16 列，含摘要/关键词/DOI/文献类型/语言；NoteExpress/EndNote 15 列无
  语言；BibTex 连摘要关键词都没有），且**三份都不含参考文献列表与被引次数**，所以共被引/文献耦合/引文突现仍拒绝。
- **窗口与游标**：**必须用可见窗口**——同一登录 profile 无头跑检索正常，但导出页是“您无权查看此网页 / HTTP ERROR 403”，
  爬虫按名报 `exportForbidden`，不等满 20 秒找按钮。游标**只记页码**（结果按站点默认相关度排，页内行号是猜的，猜错会静默跳行），
  重复行靠台账按 `记录ID` 去重。**只有站点自己不再给 `下一页` 才算 `site_end`**；某批导出不足、解析为空、某页没画出行都是
  `refused`/`UNDER_TARGET`，有洞时游标不前进。逐页选择/翻页暂停 1.2 s / 1.5 s。

## Instagram / 只采 Cookie

- Instagram 是唯一的**只采 Cookie** 平台（`supports_crawl = False`；测量用的账号被封，真爬从未可能）。执行器按节点标签拒绝
  (`run.notCrawlable`)，校验更早拒绝（它不在矩阵里，`engine.source_unknown_platform`）。它仍要 `domain` + `login_url`，
  不进 `capabilities.registry.CAPABILITIES`，并要过 `TestCookiePanelParity` + `TestPlatformOrder`。

## 跨平台契约

- **Cookie 采集 ≠ 爬取能力**：`CookieManager.PLATFORMS`（8）是能登录谁，`crawlers.is_crawlable()`（8：知乎、微博、小红书、
  微信、B 站、抖音、YouTube、X）是谁有爬虫。采到的 Cookie 按平台过滤（`cookie_flow.retain_for_platform`），因为登录绕经
  Google/Facebook；绝不把 YouTube 放宽到 `.google.com`（那是 Gmail 和 Drive）。植入只在有 Cookie 需要的主机停一次（多一个
  主机就是一次真实页面加载）。
- **运行前 Cookie 预检**：开一次平台自己的 `login_url`，回答“这份会话还认不认”。必须与 验证 Cookie 用同一套选择
  （`headless=False`、`for_login=True`），否则面板按钮与运行前门会对同一平台给出不同答案。成本约 4–5 s/平台，所以
  `COOKIE_PREFLIGHT_TTL=300`、`MAX_PARALLEL=4`、外层 `TIMEOUT=45`。被占用的 profile 不等待（`is_busy()` 在门口答“无法核对”）。
  **“没有 Cookie 文件”不等于“没有会话”**：profile 只导入一次且不再重种，所以任一来源存在就探测，只有都不存在才答阻塞的
  `nocookie`。
- **浏览器选项**：`page_load_strategy='eager'`，默认拦图片，只有类声明 `needs_images` 才开（爬虫读文本与属性，不读像素）。
  页面可见的自动化面在每个浏览器上都遮：`crawlers/core/browser.py::apply_stealth` 只删 chromedriver 注入的 `cdc_` 全局，
  不重定义 webdriver/languages，也不伪造 `window.chrome.runtime`（正常页本来就是 undefined）。无头伪装
  （`disguise_headless`：去 Headless 的 UA + 用运行时读到的可见窗口真实值回填 screen/outer/inner/dpr）与可见窗口在 20 项指纹上
  逐项相等。三道上限不可越：CDP 附加本身可被感知；`addScriptToEvaluateOnNewDocument` 只到本 driver 打开的 tab（站点弹窗里的
  Google/Apple SSO 到不了）；全新未受信 profile 与 Apple 设备证明做不到。所以可靠登录路线仍是 X 原生邮箱/密码或 Cookie 导入。
- **profile 会记住会话偏好**：一次抓取后 `Preferences` 可能留着 `images=2`，于是登录窗口没有二维码可扫；`content_prefs` 每次
  会话都写 1（允许）或 2（封锁），从不什么都不写。任何请人读的窗口（取 Cookie、验证 Cookie）都是面向人的窗口。
- **空 profile 首跑就写像登录的文件**（`Cookies`/`Login Data`/`History`/`Preferences` 全是空 store），所以“干净”由
  `sessions/profiles.py::_SESSION_TABLES` 的行数回答，且要走进 `Default/Network/Cookies`；读不开的非空 store 按“有材料”处理。
  同目录同时开两次是崩溃，所以播种只在 `os.makedirs(exist_ok=False)` 成功的那一支。
- **不拦抖音图片**（拦与不拦截图一致，早先“拦图毁网格”是遮罩的账）；**不拦视频**——`Page.setBlockedURLs` 在 Chrome 148 不存在，
  `Network.setBlockedURLs` 有效但没有收益（七个平台 A/B 里拦截组等或更慢，六个平台抓取路径根本不下载媒体），唯一诚实的理由是
  计费流量（抖音每视频约 0.6 MB）。
- **采集成本是可测属性**：`Crawler.requests` 按顺序记每一次导航与页内 fetch，`open()` 在问 driver **之前**记 URL（超时的导航
  也算到过站点）。承诺“每页一次请求”的模式要在台账上钉住，不能只看表。

## 各模式在屏幕上的行为

数据路径：**(a)** 导航并读 DOM · **(d)** 滚动该页 · **(b)** 载入一页后页内 `fetch` · **(c)** 纯 HTTP。

| 平台 × 模式 | 路径 | 用户看到 |
|---|---|---|
| B 站 关键词 | (a)(b) | 每个 `page=` 重载搜索页，数字再静默到达（每行一次 `view`） |
| B 站 热榜 | (b) | 首页，然后什么都不动 |
| B 站 作者 | (a)(d)(b) | 真实滚动的 space 页（点 下一页 换屏） |
| B 站 评论 | (b) | 视频页打开后静止（游标走 `reply/main`，没有评论 DOM） |
| 知乎 搜索/作者/评论 | (a)(d) | 滚动信息流/profile；评论点 展开 |
| 微博 搜索 | (a)(d) | 每个小时窗一页搜索 |
| 微博 评论 | (b) | 只有首页 |
| 小红书 搜索/评论 | (a)(d) | 滚动网格 / 滚动评论面板 |
| 抖音 作者/评论 | (a)(d) | 每行一页（作者是遮罩）；滚动路由容器 |
| YouTube 全部 | (b) | 一次页面加载后 innertube POST，屏幕不动 |
| X 搜索/作者/评论 | (a)(d) | 滚动虚拟化时间线 |
| 微信 正文 | (a)(d) | 每篇文章页滚动 |
| 红果 评论 | 外部播放器 | 播放器窗口 + 抽屉滚动 |

**(b) 模式没有人的行为可演**：窗口模式是纯成本，运行前对话框必须说明并提供无头；模式必须声明自己属于哪类，前端不得持有
第二个意见。**只有两条路径都存在的模式**（B 站关键词既读 DOM 卡又逐行取 `view`）才可诚实提供“模拟人”与“直接取 JSON”；
只有一种实现的（B 站热榜＝纯 API）不提供选择。**(b) 仍然需要页面**：fetch 在已加载文档里跑，“无头”不是“没有浏览器”。

## 停止路径

- **停止必须杀进程**：跨线程 `driver.quit()` 排在 worker 当前命令之后（40 s 导航、30 s 页内 fetch 都只是等它自己超时）；
  chromedriver 148 的 `chromium/stopRequest` 已不存在（404 unknown command）。唯一可靠的打断是让驱动进程消失：
  `STOP_QUIT_GRACE=0.8` 给空闲浏览器体面退出，到点按 PID 收树，多浏览器各一线程并行收。
- **杀完立刻换成死驱动桩**：被杀的 in-flight 命令自己会以 socket RST 结束，但**之后**每条命令会在没人监听的端口上付 16.3 s
  （urllib3 默认重试 4 次 × ~4 s）；换成立即抛 `CrawlerStopped` 的桩是 0.00 s。不要归零 `pool.retries`（4.07 s/条，更差），
  也不要 `close()` 连接池（之后又回 16.3 s）。桩的 `quit()`/`close()` 必须静默（worker 的 `finally` 会再调），`close()` 清
  `driver` 必须比较后再清；`_close_login_browser` 重入要在入口返回且不替它放 profile 锁。
- **面板追看要比真实尾巴长**：一次真模型请求卡住时，记录定档可花 14.6/15.2 s；Ollama 传输的天花板是
  `300 s × 2 次尝试 = 600 s`，所以看门狗的 `tries` 由 `SETTLE_WATCH_MS`（660 s）除以实际步长导出，不是 240×0.5 s。

## 网络分区与海外平台

- **不挂 VPN 时 x.com / YouTube 打不开**：画布里出现海外平台，运行前问“外网开了吗”（`ask_overseas_network`，默认开；答没开就
  不启动，空表会被读成“这个关键词什么都没搜到”）。这一问排在 Cookie 预检之前（一次注定取消的运行不该付浏览器的钱）。
- **分区是数据不是路由**：`capabilities.registry.Capability.region`（`cn`/`overseas`）由矩阵一处声明、随 `/api/capabilities` 下发；
  `live_cn`/`live_os` 分组读它，`tests/unit/gates/test_test_tiers.py` 用矩阵 region 核对每条 live 用例的 marker；矩阵没说的平台按
  “不知道”处理（不提醒也不拦）。提醒是建议且可关。“挂 VPN 时抖音 502 所以一张画布不能混采”已被否掉（同一国内会话从海外出口
  3/3 正常），混采弹窗已删除；再遇 502 先用探针读出口，不当平台规律。

## 采集校验口径

- 采集校验节点比较**结果表里同一链接的行数**与**清单行上站点自己印的 `评论数`**。站点的数字统计整条 thread（微博 30 条的帖只回
  22 条顶层，差的是楼中楼，而走查会把能拿到的子回复也写成行），所以比较的不是“顶层评论”。匹配默认 `url`（协议/主机大小写、
  尾斜杠、`utm_*`/`spm` 等分享参数归一），评论表按 `文章URL` 对上帖子表的 `链接`。
- **万/千/亿与 K/M/B 是取整标签**，所以节点给“每篇允许少的条数”和“每篇上限”两个旋钮（默认 0/不设）；采集设了每篇上限就必须在校验
  节点填同一个数（期望值压到 `min(评论数, N)`）。**站点印 `评论数=1` 的帖不要拿来当 live 输入**（那一条常是楼中楼/已删除却仍计数，
  顶层合法为空），挑 `>= 2` 且最大的那条。
- **一个被审计发现的缺口是答案，不是节点失败**：采集校验 settle DONE，报告表带 `采集状态`/`缺失条数`，控制台点出缺口与重采
  清单；无法读取的 `评论数` 记 `无法核对`，不进缺口表（没有可重采的东西）。

## 账号池冷却（只记事实）

`data/pool.db` 的 `health` 同时装 `(account, 平台, 账号)` 与 `(exit, 平台, 出口 id)`：一个登录可以在微博被墙而在 B 站正常，一个出口
可以被知乎风控而给 YouTube 用。冷却写 `cool_until`（epoch），读取时和当前时间比较，**没有清扫线程**（服务器停一晚再开，过期自然
不在；清扫器会变成第二个写者）。`disabled` 是人工停用，时钟永远解不了。失败只冷却它指控的那一侧：登录墙冷却会话，验证码先冷却
出口，不可达两者都不冷却；未知失败从不冷却。
