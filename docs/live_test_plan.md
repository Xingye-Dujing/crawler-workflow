# 全平台真机验收测试计划（live test plan）

> 状态：**执行中**。本文是三份文档里的「执行计划与判定标准」：`AGENTS.md` 只放红线，
> `docs/crawler_notes.md` 只放实测证据，本文放**要测什么、怎么判、怎么跑、修谁**。
>
> 行号会漂移，**按符号名找，不要按行号改**。采集分派入口在
> `backend/nodes/executors/source.py::execute_source_node`，评论分派在
> `backend/nodes/executors/comment.py::execute_comment_node`；`app.py` 现仅 579 行、只做路由，
> 采集/续跑/收尾的判决都在执行器与 `crawlers/` 里——**别再用 `app.py:` 行号定位**。
> 评论走路从 `crawlers/commenting/session.py::crawl_<平台>` 经 `crawlers/commenting/walks.py`
> 注册表分派到 `crawlers/platforms/<平台>/comments.py::walk`；下文提到的旧符号名是**测量当时的位置**，
> 不要求今天还能按同名方法找到。

---

## 一、怎么跑（命令 + env + 网络询问规则）

**前置检查**（每平台开跑前）：
1. 端口 5000 无自己起着的服务器（`netstat -ano | findstr :5000`；有则先问用户，**绝不杀**）；
2. 网络：国内 6 平台关 VPN，X / YouTube 开 VPN——**先问用户在哪个网络**，跑完这一侧再问另一侧
   （`live_cn` / `live_os` 由 marker 分开，一次只跑当前网络能跑的那侧）；
3. `tasklist chromedriver.exe` 确认**只有一个真机进程**（同一 profile 一浏览器锁，并存即假红，见 §2）；
4. cookie 新鲜。

**命令**（`.venv/Scripts/python.exe` 是 Windows 拼法；Linux/macOS 为 `.venv/bin/python`）：

```bash
# 知乎全矩阵（真·用户登录态；一次性约 1.5–2.5h，建议按组分批）
CIXI_LIVE_USE_USER_PROFILE=1 .venv/Scripts/python.exe -m pytest -q \
  -m "live_site and live_cn" tests/live_site/test_live_zhihu_workflow.py -rA

# 单例——node id 带引号，且必须重写 -m，否则整条被默认过滤器静默 deselected
CIXI_LIVE_USE_USER_PROFILE=1 .venv/Scripts/python.exe -m pytest -q \
  "tests/live_site/test_live_zhihu_workflow.py::test_a3_forty_rows_prove_the_scroll_loop_and_nothing_else" \
  -m "live_site and live_cn"

# 海外阶段（先问用户在 VPN 侧）
CIXI_LIVE_USE_USER_PROFILE=1 .venv/Scripts/python.exe -m pytest -q -m "live_site and live_os" -k "x or youtube" -rA
```

**环境变量**（全平台通用）：
- `CIXI_LIVE_USE_USER_PROFILE=1`：单浏览器用例用用户本人登录的 profile，全面模拟真实使用（D2）。
  并行用例的真实 profile 无法共用，**改用一次性 profile**（payload `use_profile:false`，cookie 快照照常注入，D3）。
- `CRAWLER_REQUIRE_BROWSER=1` / `CRAWLER_REQUIRE_OLLAMA=1` / `CRAWLER_REQUIRE_NODE=1`：浏览器/Ollama/Node
  缺失时默认**跳过**，会让一档绿得像「从没存在过」；设 1 把跳过变**失败**，这样「green 即证据」。
  `live_quick`（每平台一次访问）/ `live_site`（完整一轮）**绝不无人值守跑**——花用户账号。
- `CRAWLER_DATA_ROOT`：给测试进程自己的 `data/`+`logs/`；不带它**别同时开第二个服务器**，**绝不杀 5000**。

**产物**：`scratchpad/live_audit/<case>.console.txt` + `verdicts.csv`（每轮先读这两样再读 pytest 结论——
用户点名要求：**看过程不看绿灯**）。CSV 列：case,platform,mode,headless,use_profile,target,rows,verdict,reasons,wall_flags,cookie_expired,seconds。

**捕获机制**（`tests/live_run_harness.py::ConsoleRecorder`）：以 2.0s 轮询 `GET /api/workflow/status`，
用 `log_total` + 200 行尾窗做增量折叠（每行恰好收一次；尾窗被跑穿置 `overflow`、换 run 置 `resets`）。
自证即 `recorder.complete()` == `_log_total == len(captured)`。**不改 `_push_log`、不提 `LOG_KEEP`**——
产品读的就是浏览器读的那一扇窗，另开漏斗会测到用户看不到的通道。捕获只写 `scratchpad/`，绝不写 `logs/`（隔离守卫会整场红）。
共享件：`tests/live_acceptance.py`（H 组公版件，读用户 `测试：<平台>.json`、按连接分量发现组件、逐组件判决、导出 CSV 三一致）、
`tests/live_run_driver.py`（运行级矩阵驱动）、`tests/real_paths.py`（真实 cookie 目录的唯一答案，用产品 `CookieManager` 判存在）。

**全局决定**（用户已拍板）：D1 网络顺序（先 `live_cn`，X/YouTube 由用户开 VPN 跑 `live_os`）；
D2/D3 身份与并行例外（见上）；D4 无头从严（风控 40362 采不满：具名入审计表但按 bug 追修，不长期豁免）；
D5 原文件只读（`测试：xxx.json` 永不改写，变体在内存副本上 deepcopy 后改 payload）；
D6 数量硬判据（充足供给关键词下 `rows==target`，无声少交一律红）；D7 微信链接取自现有测试的 `mp.weixin.qq.com/s/…`；
D8 续跑不重不漏；D9 微博窗口不开长测专项（验收副本取最近数天，断言「target 先满即收工且剩余窗口零付费」）；
D10 X/YouTube 各 3 组件工作流已由代理建设、`validate()` 零错误。

---

## 二、规则（真机付过钱的）

### 三层判据（都要过）
- **L1 状态**：run 必须 `completed`；cookie 死亡只许走设计路径（node `partial` + run `failed` + `继续` 横幅 +
  `run.cookieExpired` 行在场），不许悄悄「少采也算完成」。
- **L2 数量**：`FULL`（rows≥target）→ 绿；`NAMED_SHORT`（控制台打出闭集具名行）→ 视平台策略；`SILENT_SHORT` → 一律红并归因。
- **L3 过程**：逐行审计三件事——该有的都在（行序 `run.started→executing_node→结论行→node_completed→run.finished`）、
  不该有的一根没有（无漏刷 `{placeholder}`、无一句话双打、无 Traceback、无虚报行）、说了的都对（行数/目标/原因与库内
  `node_runs.row_count`、`cursor_json` 互证）。

### 合法收尾白名单（**闭集**，其余少交=红）
**判决词来自 `Crawler.end_reason`**（`backend/crawlers/core/crawler.py`）：
`LICENSED_ENDS = frozenset({'site_end','capped','empty'})`——只有**站点自己说了**才算合法；`UNDER_TARGET` 是被定罪的短收；
一个都不带（`None`）= 未迁移 handler，维持宽松、不误伤续跑。`Crawler.note_end` **拒绝把循环自述登记成许可**：
一条「翻了几轮 / 已到末尾」的总结句永不 `site_end`。新增合法终局必须先在此登记出处（实测证据进 `crawler_notes.md`）。

- **通用合法具名行**（i18n 键）：各模式 `crawl.*.target_reached`；真 `crawl.zhihu.no_more`；`run.dedupe_skipped` /
  `run.dedupe_all_skipped`；`run.nodeStopped`；`run.cookieExpired`（设计路径）；`crawl.riskBlocked` / `crawl.loginWall`；
  榜单 `crawl.zhihu.hotCapped` / `crawl.dy.hotCapped` / `crawl.weibo.hotCapped`（微博 ≈52、抖音 ≈51）/ `crawl.bili.rankingCapped`；
  评论 `comment.status.blocked` / `comment.zhihuNoPanels` / `comment.commentsClosed` / `comment.dyNone` / `comment.dyNoPanel` / `comment.xNoList`；
  跨切 `run.wallRetry`、`run.platformQueued` / `platformStaggered` / `serialForced`、`crawl.profile_wait`、`run.pagePending`。
- **明确不算合法**（给自己发满分的总结行、逐行句、本机没走到门口的句）：`crawl.*.finished` / `processed` / `round` /
  `authorDone` / `walk_done` / `crawl.stopReason.end` / `no_new` / `no_cards` / `stuck` / `unreachable`；
  `crawl.dy.sortUnknown`（off-list `sort` 早在 `engine.workflow.validate`→`engine.source_bad_option` 被拒、执行器在建 record 前 return，爬虫那句打不出来）；
  `crawl.weibo.hotNoHost`（说的是本机停在 `passport.weibo.com/visitor`，站点从没被问过——运行必须红并打出那个帧）。
- **一条行能不能被观察到取决于开关**：`run.serialForced` 只在 `same_platform_queue=False` 时打
  （`runtime/gate.py::hold`：`forced_serial = serial_only and not 该开关`），排队开着时说的是 `run.platformQueued`。
  G1/G2 因此显式改这两个全局开关（不从 run payload 读，canvas `settings.same_platform_stagger` 没人看），跑完还原。

### 通用 under-target 判据（U1，**已落地**）
旧缺陷：全程序只有登录墙分支比过 行数 vs 目标，`login_wall=False` 时短表与满表无法区分、照样 DONE。
现 `execute_source_node` 在收尾三段判决（`backend/nodes/executors/source.py`）：墙短 → `raise run.cookieExpired`（保行、run failed、出 `继续`）；
风控短 → `raise run.riskControlled`（禁止立刻重跑，「会话可能好好的、只能退避」）；无墙无风控且 `end_reason==UNDER_TARGET` 的短 →
`raise run.underTargetShort`（带 `have/want`，漏斗量全时并带 `run.underTargetWalk scanned/kept/refused`）。
**未迁移 handler 传 `end_reason=None` 维持宽松**，所以每平台仍需一个正向「确实没采完」信号才能上判（见 §4）。

### 续跑 / 游标 / 去重（红线）
- 游标只记**位置**（`scanned`/`done`/`url_index`/`keyword`），掺入 id 或链接列表即红（漏采根因，见 §3 微信/小红书）。
- 去重具名：source 与 comment 节点都用 `row_sink` 账本按 `item_key` 去重，重跑命中不落库——两个执行器都要补打
  `run.dedupe_skipped(n)`、全空补 `run.dedupe_all_skipped`（续跑不打、墙不打）。
  针：`tests/api/test_source_dispatch_matrix.py::test_a_repeated_comment_run_names_the_ledger_skip`。
- 断点续跑不重不漏：最终 `rows==target`、item 唯一数==行数、`cursor_json` 只含位置字段。
- 并行=一次 execute 里的多组件；**两次 POST 永远排队**（一 run 一名额）。评论节点**不受平台闸**：source+comment 同平台真并发可行。

### 重试与拒绝的时机（闭集规则）
- `live_site` 一轮里**只当爬虫自己报了 `login_wall` 才重试一次**；断言要**点名**墙/风控——一个无名空表是真的「found nothing」，保持红。
- 一切「选数据、选成本、选名字」的入参**按名拒绝**、绝不猜（mode/select/缺列经 `data_analysis.validate_step`，方法/模式经 `app.enum_param`；
  拒绝走 `raise` 不走返回 `[]`，否则节点在空表上 settle DONE）。
- **任何 live 数字算自站点、绝不选死**：阈值取自爬虫报告（卡的评论数、页面自己印的分母、榜的大小），两侧都有话。
- 无头被风控 40362 采不满：具名入审计表但按 bug 追修（伪装先穷尽），不长期豁免（D4）。

### 滚动节奏等式（fake driver 数出的 scroll 命令，非真机测量）
`scroll_down(steps=3)` 一次发 **4** 条 scroll 命令（3 步 + 1 次底部跳转），所以搜索的一个 stalled round
= 2 次 `scroll_down`（轮首 + 轮内那次确认）= 8 条；连停 `STUCK_ROUNDS=3` 轮收工共 **20 条**，
时间成本 ≈ 每轮 2×`CARD_WAIT`(1.5s) + 2×礼貌间隔(~1.1s)。作者模式走 `crawlers/engine/feed.py::walk_feed`，一个 round 只有 1 次 scroll 调用——
**两条模式的分页节奏不同，按行数换算滚动次数时不要混用**
（`tests/integration/test_zhihu_crawler.py::test_stuck_pages_end_the_loop` 把这个 20 钉成等式，改了循环形状就会红）。

### 冷启动导航（U58，已修）
冷启动首帧 `driver.get` 可能没换文档（`current_url` 停在 `chrome://new-tab-page`），`wall.classify` 把这张内部页判 `blocked` →
误报风控、把有结果的关键词收成空表。修法：`Crawler.open` 与 `_load_cookies` 共用 `_drive_off_internal_page`，`never_arrived` 且导航未 settle 时
按 **`NAV_RETRY=1`** 重发 `get` 再判墙（预算 = `NAV_RETRY+1`；一次回车即好，且压在 `COOKIE_PREFLIGHT_TIMEOUT` 内）；故意 `about:blank` 的 `warm_profile_dir` 留裸、不被重发。

### Profile 与会话并发（硬约束）
- **同一 profile 一浏览器锁**：真机层与 app 运行不能同时持有同一平台（`sessions/profiles.py::acquire_profile` / `is_busy` + `runtime/gate.py::hold` 双排队 900s）。
  开跑前 `tasklist chromedriver.exe` 只留一个真机进程；日志别共用同一文件名。
- `runtime/gate.py::reset()` 在 `live_site` 下**不自愈**（`tests/conftest.py` 只在**非** live_site 用例里复位平台闸 `platform_gate.reset()`）——
  排队冷却**跨用例真实存在**，排期时按它；cookie 快照按 `_cookie_snapshot` 逐用例存/取。
- 真 profile 与 cookie 一一对应：一账号 = 一 `data/cookies/<platform>@<account>.json` + 一 `chrome_profile/<platform>/<account>`；
  `sessions/profiles.py::needs_refresh` 决定是否带登录态重取。断言全走 `i18n.t()`，`{platform}` 槽是词不是键。

### 一个平台的完整复查流程（不许跳步）
1. **第 0 步读页面**（先于读代码）：一次性探针 `backend/test_<平台>_<物件>.py`（产物进 `scratchpad/`，结论进 `crawler_notes.md`），
   问清四件事：列表**靠什么分页**（按钮 / 窗口滚动 / 某元素自己的滚动盒）、有没有**藏在展开器后面的嵌套内容**、**哪个容器真装着行**、页面显示哪些列。
   **页面模型错了不会报错**——只会让控制台、汇总、库内行数、导出预览一起同意一张缺的表（内部自洽 ≠ 采全）。
2. 判据必须带**站点自己印出来的分母**；谎言行永不入白名单。
3. 写运行级矩阵（A 供给×目标 / B 作者 / C 榜单 / D 评论 / E 停止→继续 / F 预检 / G 并行与排队 / H 用户画布 / S 设置轴），
   标记 `[live_site, live_cn|live_os, enable_socket, serial]`，**零 `pytest.skip`**，评论按真实 ask（`limit × 链接数`）判满，多组件按组件切片评分，用例中途死靠 `harness.abort_run` 兜住。
4. 快层同步：每条新判据有假驱动针，并**当场验一次「退回即红」**（把旧代码装回去跑一遍再装回来）。
5. `@code-auditor` 审（只读、禁真机层）→ 修 Blocker/Major，欠账写明为何暂不修。
6. 真机开跑（命令见 §1，绝不无人值守）。7. 逐例读 `console.txt`+`verdicts.csv`（先于 pytest 结论）归因销号，产品缺陷修产品码。
8. H 组终验用户画布，然后快层 + 设备层 + ruff 全绿 → 分类提交。

### 六大维度（一个平台要覆盖的形状，浓缩）
A 采得够（数量档/站点上限具名收尾/单跑链接唯一/跨跑去重/续跑不重不漏）；B 采得对（CSV==库内==preview==target 三一致、行-页对账、计数 int 纪律、
列集合精确、时间窗内、正文≥页面 0.7）；C 设置全生效（每字段取值轴 + 全局开关双向、无头=真无头/窗口=真窗口）；
D 过程健壮（停止四种/续跑五种/复用四规则：0 行不复用、source 永不 adopt、restored 计完成、`dropped_stale` 取消复用）；
E 记录诚实（`run.finished` 计数==payload==记录列==面板 chips）；F 平台专轴（见 §3 各平台节）。

---

## 三、平台账目（当前判定 + 数字 + 钉住测试）

### 知乎（cn，模板本体）—— 真机 31/31 绿（2026-09-28）
- 搜索滚动循环 U3 已修（连停 `STUCK_ROUNDS=3` 轮、删不可达的 `crawl.zhihu.confirmed`）；`test_stuck_pages_end_the_loop` 钉 20 条等式。
- 评论面板**无「更多」按钮**、靠容器内滚动懒加载 + 子回复在 `展开其中 N 条回复` 后（U28/U29）：
  开面板 12/10 → 滚容器 36/109 → 展开 41/**138**；走 `PANEL_ROUNDS=60` 预算 + 逐轮 `comment.zhihuRound`，
  不足页面数字 `comment.zhihuPanelShort`、耗尽 `comment.zhihuPanelCapped`（U24）；新增 `父楼层` 列。
- 定深取作者曾横跨邻条挂错名（U22）→ 按结构定界 + `comment.zhihuNoAuthor`；评论时间/赞数曾写死（U23）→ 真读/留空。
- 站点否证：同一关键词两次搜索卡片会换（U26）→ 「不重采」判据改用**稳定供给**（热榜）。

### 微博（cn）—— serial_only；真机 22 格全绿（2026-09-28）
- 时间窗 4 态；**D9**：验收副本取最近数天，断「target 先满即收工且剩余窗口零付费」（`访问搜索链接` 行数 == 收尾句「窗口走到第 N/24 个」，A3/H1 真机成立）。
- 热搜 `needs_session=False` **声明为真**（跳完访客引导后无 cookie 回 `ok=1`）；U38 曾把「本机停在 passport 帧、同源请求发不出」误报成 `hotRefused`
  → 修 `_await_home_frame()`（0.5s tick、上限 `PAGE_WAIT*3`、每 tick 问停止），等不到抛 `crawl.weibo.hotNoHost`（**不算合法**）。
- U31：空窗同屏给 `.card-no-result` + 5 张**同构**推荐卡 → plate 优先，判据「空窗必须 0 行」。
- U12：小时窗第 2 页真有 6 条、mid 交集 0 → `_may_page` 一窗静默丢 40% → **允许窗口翻页**（非声明上限）；U11「9s 预算不够」前提被否证（首卡 0.42–0.85s）；
  U10 搜索路径无收尾行已补。
- U36：续跑把被停那窗的深层页永久丢（「无新增」当「无卡片」）→ `_harvest` 交回 `(kept, cards_seen)`，只看站点空（cards==0）；
  针 `tests/integration/test_weibo_crawler.py::…::test_a_page_with_nothing_new_on_it_is_not_a_page_with_nothing_on_it`。
- 评论：四列造假 U32（`like_counts` 读成 `like_count`→赞数恒 0、楼层每页重数、时间未规范化、主页填头像）全改真读；
  U33 楼中楼五种形状全拿不到、`trendsText` 在 22/30 时仍写「已加载全部评论」→ **判据只吃 `total_number`**；
  U37 取数失败静默返已有行 → `comment.weiboFetchDied`（针 `tests/unit/crawlers/test_comments.py::…::test_a_failed_comment_page_names_itself_instead_of_looking_finished`）；
  游标耗尽且分母更高 → `comment.weiboShort`、整页复读 → `comment.weiboReplay`；
  U40 纯表情评论被剥成空行 → 先读 `text_raw`（针 `test_an_emoji_only_comment_keeps_its_text`）；
  U41 把用户上限说成站点缺额 → 差额只对游标收到的行数判（针 `test_a_limit_crossed_on_the_last_page_does_not_blame_the_thread`）。
- 具名拒绝：`crawl.weibo.no_result` / `page_empty` / `authorNoPosts`；author 四条 raise：`authorRefused`（mymblog edge 403）/ `authorWall` / `authorMirror` /
  `authorEmpty`（uid 读不出开浏览器前就拒）。数字账：A4 24 空窗 0 行逐窗对齐；A6 目标 25 恰在第一小时窗取满（10+9+6）；C1 40 条精确整数热度；C2 `hotCapped` 51。

### 抖音（cn）—— 关键词搜索模式已**移除**（供给浅：两次复测只 26 / 16 条、都不到「暂时没有更多了」，用户判定无用）
- 真站矩阵 = **B 作者 / C 热榜 / D 评论**（A1–A8 随 `search()` 删；H1 三条搜索腿从 `测试：抖音.json` 删，旗舰现 3 组件）。
- U48：排序搜索列表停 14 张（目标 50）却 `crawl.dy.finished` 说数字不说原因 = SILENT_SHORT → `_harvest_pool` 读站点收尾句
  `LIST_END_MARKS=('暂时没有更多了','没有更多了')`，读到才打 `crawl.dy.noMore`（带几屏/末屏几张）；**没读到就一句不说、真机红**。
  随关键词搜索模式移除，这两枚 `noMore` 假驱动针也一并删；现存的「站点结束 vs 本机读法」判决由 `crawl.dy.noMore`
  与走路的 `end_reason`（`site_end` 才合法、无标记即 `UNDER_TARGET`）承担，对照 `crawl.zhihu.no_more`。
- U42/U44：作者列曾整列空/填成推荐栏别人（取第一个裸 sec_uid 锚点、页未注水完就读）→ 作者改 `[data-e2e="user-info"]` 读、读不到留空；
  行身份改认「文案或发布时间」（`detailNoIdentity`），粉丝/获赞页面不发布故**留空不填 0**；针 `tests/integration/test_douyin_detail_dom.py`（真 Chrome，推荐锚点故意排在作者块前）。
- U45：`/video/` 锚点服务端重定向到 `/note/` 图文页、本机一律验证码中间页 → 新增逐行句 `crawl.dy.detailWalled`、**不 latch `login_wall`**。
- U47：不存在的视频 id 被换成另一条视频、旧读法报 BLOCKED 并念**替身**的评论数 → 先比 `current_url` 里 id，不同即 `comment.dyGone`+DEAD。
- U43：评论面板曾带 40 轮预算、站点写 3388 却停在 406 行报 OK → `while True` 只由「无新行/盒子不长大/用户停止或 limit」收工；
  `comment.dyShort` 报 `declared/rows/nested/gap`（406+Σ1062≠3388 → 差额真没采到）。
- U46：楼层每滚一屏从 1 重数 → 先收完 `collected` 再统一编号（针 `test_the_floor_number_runs_across_the_panel_not_down_one_screen_at_a_time`）。
- U49/U50/U51/U52：作者腿借了搜索页 300s 等待（改只等这条列表自己 `feed.wait_for`）；去掉轮次上限后走路 O(n²)（只读新增尾巴、哨兵用头节点文字）；
  `comment.dyShort` 把「用户按了停止」说成站点欠额 + URL 漏进模板（走路记出口 `crawl.stopReason.*`）；评论按 `lines[1]` 取正文丢换行/误读数字 → 用面板「时间·地区」行当锚点。
- 白名单：墙在**标题**里、`check_intercept()` 会说 ok → 加 `crawl.dy.wall`（A2 遇墙才不红）；热榜**反向语义**（真 profile 被验证码、一次性浏览器反通）。
  具名：`noCards`（页面自报 502）/`authorNoWorks`/`authorNoCards`/`hotCapped{board}`（本次 51）/`hotRefused`/`hotWall`/`authorEmpty`（非 sec_uid 开浏览器前 raise）。
  数字账：B1 主页自报 145 条 → 问 12 得 12；C2 `hotCapped` 51；D1 楼层实测 1..40 连续。

### B站（cn）—— 第 0 步 + posts/author/hot 真机全绿，H1 旗舰绿，评论腿具名短收（2026-09-29）
- 搜索契约复核为真（`page=1` 0 卡、非互斥靠 `seen`、广告卡被正确排除）。`parallel_recommended` 可开真并行。
- U9（已修）：`fetch_json→{}`→`code is None` 被两道闸夹住 → 零行日志丢行 → 补 `crawl.bili.fetchEmpty`(warning) / `crawl.bili.goneVideo`(info)。
- U53（已修）：投稿页靠 **`下一页` 换页**（整屏替换、交集 0、URL 不变），旧 `author()` 按滚动+卡片数 → 首屏 40 卡就停还谎报「已到列表末尾」
  → 修 `scroll=self._click_next_page` + BV 集合当哨兵；针 `tests/integration/test_bilibili_crawler.py::…::test_a_second_page_that_keeps_the_card_count_is_not_read_as_the_end`；
  **B1 真机验**：向投稿过百的 UP 主 37974444 要 50 得 50（>40 一屏 = 走穿下一页）。排行榜 `board=ranking` 曾 ≤100 **无 cap 行=欠账** → 补 `crawl.bili.rankingCapped`；白名单把 `crawl.bili.blocked` 计入合法。
- U54：游标本身正确（分母 `stat.reply=47268`，每页 20/19/18、494 新行跨 26 页、is_end 恒 False）；「2194→7」是一次性设备深翻页限流。
  被限流时 `reply/main` 回 is_end=True/空页 → 旧代码 7 行静默返 OK → 收尾比对行数与分母，未达上限且少于分母 → `comment.biliShort`；
  针 `test_a_clean_end_under_the_denominator_is_named_short`（2194→7 必具名）/ `test_a_thread_that_holds_what_it_reports_says_nothing`（7→7 不说）。
  H1 评论腿现 **7/50 NAMED_SHORT**（凉账号未复前正解）；D1 硬 `>=40` 本身违背「算自站点」红线，已改单向（达上限=FULL、具名短收=WARN、静默短收仍红）。
- U55（已修）：`BV00000000000` 回 `code=-400` 被旧默认一律判 BLOCKED → latches `cookieExpired` 判死整条会话 →
  按「码在怪谁」分类：怪视频（-400/-404/62002）→ DEAD 逐链具名；怪会话/IP（-352/-412/-101）→ BLOCKED；
  针 `tests/unit/crawlers/test_comments.py::…::test_a_view_code_is_classified_by_who_it_blames`（六码三向）。

### 微信（cn）—— 正文型、无 cookie 行、`needs_session=False`；真机第一轮全绿（#17，2026-09-29）
- 探针只读公开文章页（不花登录账号）：三条 D7 链接全活，正文 2903/2332/93 字符完整、均未达 5000 上限故无截断标记（正确）。
- U5（同形真 bug，已修）：`crawler.py` 把整条 URL 列表写进续跑游标（`mark_position(urls=urls,…)`）→ 改位置-only（`url_index/url_total/done`）；
  针 `tests/integration/test_wechat_crawler.py::test_the_cursor_records_position_not_the_link_list`（装回 `urls=urls` 即红）。
- U56（**观察、暂不改**）：`crawler.py::get_detail` 用裸 `self.driver.get(url)` 绕开 `Crawler.open` → 丢 settled 记录（非漏采，正文匿名可读）；
  下次真机触碰该平台一并改 `self.open(url, judge=False)`。
- 无 target 语义（links 即预算，`cookieExpired` 分支对其不可达是设计事实）；验收副本把 ask 夹到链接数、逐篇导出三一致。H2（无头）与并行对本平台无新判据，不补跑。

### 小红书（cn）—— 全平台风控最高；U5/U59/U60 已离线修，H1 旗舰真机绿；矩阵待监督窗口（#16，2026-09-29）
- 重放会话几分钟内被墙（实测一小时内两次），探针刻意做小、**只在有人盯的窗口开**；2026-09-29 监督探针第一次导航即被安全验证挡（软风控、非死 cookie），
  当场停手、绝不连跑 → U5 的「按 `笔记ID` 播种」正确性仍待实测确认。
- U59（已修）：搜索流**虚拟化回收**（挂载数本就平、每滚换入新 `笔记ID`），旧走路按卡片数判停滞 + `_harvest_cards` 按 DOM 下标 `scanned` 跳卡 →
  后续每轮读 0 却仍报「没增长」= 静默大面积漏采 → 走路改认 `len(seen)`（去重后 `笔记ID`）增量、`_harvest_cards` 整屏重扫靠 `seen` 去重（不重付）；
  针 `tests/unit/crawlers/test_xhs_crawler.py::…::test_a_recycling_grid_is_walked_past_its_first_screen`；**不换 `feed.walk_feed`**（它同样按卡片数判停滞）。
  H1 旗舰 posts 腿 50/50、comments 腿 139/139 = FULL（per-component 三一致 file==store==preview）。
- U60（已修）：过期/缺 `xsec_token` 笔记被当空行入库 + 详情 `self.open(judge=True)` 把死链 latch 成 `risk_blocked` 中止整条走路 →
  详情改 `judge=False` + 不写标记的 `self.verdict(url)` 判，墙 → `crawl.xhs.deadNote` 具名 + `return None`，单条死链不得设 `risk_blocked`/`login_wall`；
  针 `test_a_walled_note_is_named_dead_and_does_not_abort_the_session` / `test_a_healthy_note_is_not_named_dead`。
- U5：游标改位置-only、`seen` 从已存行的 `笔记ID` 播种；针 `tests/unit/crawlers/test_xhs_crawler.py::TestResumeIdentityAndCursor`。专轴：`profile_recommended`；评论 `comment_preview` 三档。

### 红果短剧（cn）—— 匿名（无 cookie 行、无 account 字段，与微信同列免 cookie 豁免）
- 四个榜 = 一个模式一个 select（值即存储值，见 `crawlers/platforms/hongguo/crawler.py::BOARDS`）；榜单在文档自带 loader 载荷里（`_ROUTER_DATA`，延迟 ~2s 到货）；
  翻页只走站点自己的 `nextUrl`（`?page=1` 与裸 URL 同页）；`?page=6` 只有 `rank_layout` → **具名拒绝**不得读成空榜；集数 = `episodeVids` 长度。
- 评论模式另测（`tests/live_site/test_live_hongguo_comments.py`，live_cn + enable_socket，需用户在场）：真播放器 + 真 mitmdump + UIA，采热榜第 1 剧前 2 集，
  分母 = 响应自带 `total`（双向断言）；播放器/mitmproxy 未装 = 环境前置可跳过（已登记 `test_test_tiers` 白名单），采集结果类失败一律保持红。

### X（os·待 VPN）—— **未测**
- cookie 同为 09-26，X 会话比 YouTube 短得多、且 headless 被弹注册页 → #18 X 大概率要先**重新登录**才能跑 live。
- U61（已加遮罩，非「保证登录过」）：驱动页残留 chromedriver 注入的裸 `window.cdc_…` 全局 → `_create_driver` 对所有浏览器首导航前注册
  `_AUTOMATION_STEALTH_JS`，**仅删 cdc_ 全局**（刻意不改 webdriver/languages、不伪造 chrome.runtime）；
  针 `tests/integration/test_driver_surface.py::test_the_page_visible_automation_surface_is_masked`（+ 正控 globals 非空、blink 控 webdriver true）。
  **三道遮不住的上限**（诚实）：CDP 调试器附加；new-document 遮罩只作用启动标签页、**SSO 弹窗是另一 CDP target 够不到**（报错正在弹窗）；全新未信任 profile。**顽固 SSO 走邮箱密码/Cookie 导入**。
- 旧疑点 U15（settle 预算对自己「一屏 ~12s」偏紧、`finished` 无目标）/ U16（`crawl.loginWall` 双打违反一失败一行）待运行级矩阵逐行核。
- 专轴：虚拟时间线进度=保住的行；续跑身份=status-id 集（不许索引）；五计数同源 aria-label、浏览数唯一来源。

### YouTube（os·待 VPN）—— 运行级 11 格真机全绿（#18 收口，2026-09-29）
- innertube 页内 JSON-first 页面模型今日复核为真（search 出行、per-row player 回点赞/时长/正文、cursor 翻过首屏≥16、评论游标翻过 20、不存在视频具名拒付）；09-26 cookie 仍有效。
- U14（已修）：`crawl.yt.finished` 补 `{total}`（两调用点传 target）；author 短停打现成 `crawl.yt.drained`（游标耗尽语义无歧义）；
  针 `tests/integration/test_youtube_crawler.py::TestAuthorWalk::test_a_short_author_run_names_the_channel_running_out`。
- U57（已修，运行级 C1 抓到）：评论节点有账本却没嗓子 → `execute_comment_node` 补具名账本跳过；真机用 `jNQXAC9IVRw`（站内无地区墙，旗舰 `jGwWNGJdvx8` 被「该视频无法再播放」→ `commentsClosed` 0 行）。
- U26 也打在作者模式：频道 `/@handle/videos` 首文档两次加载换批 → 去重重复只能用评论线程。
- 专轴：**国内网络下先测反向用例——不可达必须报 `unreachable`，不许假空/拒绝**；with_facts 2×2。

### instagram —— 不爬：双层拒绝（校验 + `run.notCrawlable`）+ 不掏浏览器，快层已钉。

---

## 四、未结项

- **U1 正向 under-target 信号（#7）**：通用判决机制已落地（`execute_source_node`），但每平台需一个正向「确实没采完」信号才能上判
  （许可侧已接：douyin、zhihu-search + zhihu.hot、weibo.hot、youtube.search-drained、bilibili.hot）。误判会毁正常断点续跑。
  各站要找自己的「没有更多/到底」DOM 文案（像 douyin `LIST_END_MARKS`），测到才上 `UNDER_TARGET`，测不到长期许可/None；
  weibo 搜索的 `reason=='end'` 是循环兜底、非站点事实，须区分「所有小时窗真扫完」vs「某窗读页失败提前收」。
  接入前提：拿到正向信号后在其 handler 对「短 + 无许可 + 正向未完」emit `UNDER_TARGET`，live 白名单认 `run.underTargetShort` 为具名短收，加「续跑重放不触发判据」回归测。
- **小红书真机矩阵**：待监督窗口（有人盯、见风控即停）。先按探针结论判 U3（xhs 手抄滚动循环该换 `feed.walk_feed`），再运行级矩阵 + H 组 `测试：小红书.json`（posts `recrawl:true`）。
- **抖音 H1**：不能按原样收口（两条排序腿在用户判定暂停的搜索线上）；A7/A8「写好了、没跑过」。第 0-7 步逐例读控制台已收口。
- **B站评论 D1/D2**：硬计数断言需 `reply/main` 真凉账号（引擎现已正确具名 biliShort / risk-partial→BLOCKED，只差站点不 throttle）。
- **X VPN 阶段**：未测，大概率要先重新登录；先测反向 `unreachable`；改「所有浏览器」需补跑一平台 live_quick 不回归。
- **知乎 H 组折叠**：仍用它自己那份同名判决函数（搬已真机跑过的判决代码代价 = 重跑知乎 H1-H3 + cookie 会老），留到知乎下次真机触碰时折进 `tests/live_acceptance.py`；**新平台一律 `import live_acceptance`**。
- **task #28 账号无 Cookie 按名拒绝**：代码与双语键已写好，但跑出 84 格红后**在提交前回退**——真因是测试夹具顺序非规则：
  `seeded_cookies`（tests/conftest.py）只依赖 `app_module`，`client` 夹具随后重建 tmp 数据根把种下的 cookie 换掉。
  修法：让 `seeded_cookies` 依赖 `data_root`（或 `client`）再写文件、写完自证一次 `exists()`；只对真起爬取的模块 `usefixtures`，**不要全局 autouse**（`test_cookie_preflight`/`test_config_api` 要靠「没有 Cookie」说话）。
- **task #25/#26/#27 云端**：隐藏 Ollama 与「无头」设置项、隐私首弹、pristine Profile 模板。曾有一条错误告诫（「知乎评论区拒绝无头、云端按名拒绝」）
  是从过期 docstring 读来的——`NEVER_HEADLESS` 早在 #148 随「无头带桌面指纹」删掉（伪装无头 5/5 == 可见 5/5），**云端不需为任何模式加拒绝**。
- **不复制用户日常 Chrome 目录**做模板（`data/` gitignore 而仓库有 remote，手工剥离 Login Data/History 极易漏；
  `sessions/profiles.py` 记着目录独占 + Cookie 应用绑定加密 + Chrome 136 起禁远程调试）；云端模板由程序自启一次空白 Chrome 生成。
- **低优先/观察**：U56（微信 get_detail 绕 open，下次一并改）、U20（`jsonpath` 嵌套>60/命中≥5000 截断无行）、
  U21（`crawlers/engine/popup.py` 未知插页既不点也不报）、U6/U7（`base.py` 游标落盘异常 suppress / sink 失败行计入 collected 未入库）、
  U17（`crawlers/engine/wall.py` `about:blank`/`chrome://` 被判 blocked 谎称风控；unreachable 与 blocked 分流）、
  U18（碰撞重试清空 latch 后第二次返回 `[]` 且不重判墙 → 0 行 DONE）、U19（评论引擎其余平台硬预算那几格仍欠具名）。
- **data/workflows 快照**：验收原样跑 `测试：<平台>.json`（只读，D5 永不改写；变体在内存副本上改 payload）。
  各文件组件/启用位/recrawl/坑以 `data/workflows/` 现场为准（行号/组件会漂移，本文不再维护快照）。

**常驻事项**：`ml_train/` 是用户自己的东西，除明确授权外不得擅动；捕获机制不改 `_push_log`、不提 `LOG_KEEP`（已定，勿复议）；
凡是准备据此动手的结论先自己读一遍文件/`git log`（曾有过子代理报告的符号在仓库里并不存在）；闸门数字带退出码取、别凭记忆。

**每平台完成定义**：§二/§三 通用形状全绿 + 该平台嫌疑「修复并回归」或「真机证明为站点行为并入白名单」+ `测试：xxx.json` 原样通过 + 全组件副本通过。
任何一格 SILENT_SHORT、假行、对账不过 = 不过门，先修再跑。
