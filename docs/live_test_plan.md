# 全平台真机验收测试计划（live test plan）

> 状态：**执行中**。知乎程序实现在写（§8），其余平台按 §7 模板推进。
> 本文是三份文档里的「执行计划与判定标准」：`AGENTS.md` 只放红线，`docs/crawler_notes.md` 只放实测证据，
> 本文放**要测什么、怎么判、怎么跑、修谁**。下次要继续验收，从本文 §10 的口令直接开跑。
>
> 建立：2026-09-27。所有 file:line 以当日工作树为准；行号会漂移，**按符号名找，不要按行号改**。

---

## 1. 最终目的与全局决定（用户已拍板）

**最终目的**：七平台（知乎、微博、小红书、微信、B站、抖音、X、YouTube 中除 instagram 外全部）
每一种爬取功能、每一项设置都真机测到；数据**不漏采、不重采、完全符合要求**；采集准确性第一。
「通过」不等于绿——控制台信息逐行审计，过程也要对。

| # | 决定 | 内容 |
|---|---|---|
| D1 | 网络顺序 | 先国内 6 平台（`live_cn`）；X / YouTube 轮到时由用户开 VPN（`live_os`） |
| D2 | 身份 | 单浏览器用例一律 `CIXI_LIVE_USE_USER_PROFILE=1`，用用户本人登录的 profile，全面模拟真实使用 |
| D3 | 并行例外 | 并行用例真实 profile 无法共用（一 profile 一浏览器锁），**改用一次性 profile**（payload `use_profile:false`，cookie 快照照常注入） |
| D4 | 无头从严 | 无头被风控 40362 导致采不满：**具名入审计表，但按 bug 追查修复**（伪装手段先穷尽），不长期豁免 |
| D5 | 原文件只读 | `data/workflows/测试：xxx.json` 永不改写；全组件/无头/并行变体在**内存副本**上跑（deepcopy 后改 payload） |
| D6 | 数量硬判据 | 供给充足关键词下 `rows == target` 是红的唯一豁免=合法具名早退（§2/§5）；**无声少交一律红** |
| D7 | 微信链接 | 验收所需推文链接直接取自现有测试程序（`tests/live_site/test_live_wechat.py`、`backend/test_*.py` 里现成的 `mp.weixin.qq.com/s/…`） |
| D8 | 续跑硬判据 | 断点续跑**不重不漏**：最终 rows==target、item 唯一数==行数、`cursor_json` 只含位置字段（掺入 id/链接列表即红） |
| D9 | 微博时间窗 | **不开长测专项**：验收副本取最近数天窗口；「目标先满、窗口未轮完即收工」是微博常态——断言正着用它：`target_reached` 在场且**剩余窗口零付费**（不产生逐窗导航行） |
| D10 | 海外两档 | `测试：X.json`、`测试：YouTube.json` 由代理建设（各 3 组件=该平台全模式，已过 `validate()` 零错误），VPN 阶段随平台流程终验 |

---

## 2. 通过判据：三层都要过

| 层 | 判据 |
|---|---|
| **L1 状态** | run 必须 `completed`；cookie 死亡只许走设计路径（node `partial` + run `failed` + `继续` 横幅 + `run.cookieExpired` 行在场），不许悄悄「少采也算完成」 |
| **L2 数量** | 三分类：`FULL`（rows≥target）→ 绿；`NAMED_SHORT`（控制台打出 §5 白名单具名行）→ 视平台策略（窗口+充足供给下 stuck/no_growth **不算合法**，Z6 型假行=红）；`SILENT_SHORT` → 一律红并进 §6 归因 |
| **L3 过程** | 全量控制台留存（§8 捕获机制），逐行审计三件事：**该有的都在**（run.started→executing_node→crawl 结论行→node_completed→run.finished 的行序模板）；**不该有的一根没有**（无 `{placeholder}` 漏刷、无一句话双打、无 Traceback、无虚报行）；**说了的都对**（行数/目标/原因与库内 `node_runs.row_count`、`cursor_json` 互证） |

---

## 3. 六大维度组（一个平台要覆盖的全部形状）

- **A 采得够**：各数量档（10/20/40/50）、站点上限具名收尾、单跑内链接唯一、跨跑去重具名、续跑不重不漏（D8）。
- **B 采得对**：
  - **三一致**：导出 CSV 行数 == 库内 node_rows == `/api/data/preview` 返回 == target；
  - **行-页对账**：随机抽 2-3 行重开其链接比对标题/作者/计数/可打开性与域名归属（知乎 0.7 正文下限 `tests/live_site/test_live_zhihu.py:49-71` 的做法推广到全平台）；
  - **计数解析**：`int` 类型纪律；万/千分位/`'w'`（`engine/counters.py` 的 `_UNITS` 隐患）逐例；禁 None/字符串混入；
  - **列集合精确**：该有的列一根不少、不该有的没有（热榜无作者/评论数、抖音无播放数、微信无互动列、评论列集含楼层连续性）；
  - **属性校验**：时间窗内产出全在窗内；抖音 sort 的单调性质；发布时间格式合法；
  - **正文完整**：展开后 ≥ 页面实际长的 0.7；微信 5000 字截断标记在场。
- **C 设置全生效**：每模式每字段按其取值轴测——`target_count`（合法/0→1/垃圾→50）、`full_body` 双态、
  `sort`×3+非法拒付不掏浏览器、`board`×2+大小写非法拒付、`comment_limit` 0/N、`comment_preview` 0/5/大、
  `with_facts` 2×2、`per_article_file` 双态+文件数==文章数、`recrawl` 双态+续跑强制失效、
  `part_size` 0/分批+合并==全量、`format` csv/json、`account` 默认/具名缺文件按名拒绝、
  `input_column` 喂链/错列按名拒绝/空格子具名跳过；全局开关——`same_platform_queue` 双向、
  `use_browser_profile` 与 payload 三态（缺席=跟随设置）、`max_visible/headless_browsers` 池宽、
  `cookie_preflight_before_run`、`lang` zh/en 语义一致；无头=真无头、窗口=真窗口（#148）。
- **D 过程健壮**：停止四种（采集中途/并行中途/评论文章间/续跑后再停）；续跑五种（停止后续、模拟 cookie 死后续、
  改 keyword 后续=`dropped_stale` 清游标+行、改 target 后续、`断点续跑节点` adopt 存量入新图）；
  复用四规则（0 行存量不复用、source 永不 adopt、restored 计完成、dropped_stale 取消复用）；
  碰撞重试后空返回必须重判墙（不许 0 行 DONE，`app.py:2208-2233` 缺口）。
- **E 记录与展示诚实**：`run.finished` 计数 == status payload == runs 记录列 == 面板 chips
  （并行×N/串行×1/无头/窗口/跳过工作流点名）；`/api/runs/list` 状态词汇闭集+已存行数+孤儿自行结算；
  history.db 只记正常完成、停止不留档；`_log_total == 捕获行数`（捕获自证）。
- **F 平台专轴**：见 §7 表。

---

## 4. 知乎用例矩阵（第一份完整落地，其余平台的模板）

驱动方式统一：**走 `/api/workflow/execute` 真运行**（面板点「运行」同一条链），flask `client` fixture +
真 cookie 目录回填（`Config.COOKIE_DIR` → `data/cookies`，先例 `test_live_cookie_preflight.py:52-64`）+
`pytest.mark.serial`。直接调 crawler 的低层用例保留在既有 4 个 live 文件里不动。

| 组 | 用例 | 形态 | 目标 | 关键断言（L2/L3 补充） |
|---|---|---|---|---|
| posts | A1/A2/A3 | 窗口·串行·全文 | 10/20/40 | FULL；A3 另断言 `target_reached` 在场且 **无 stuck/no_growth**（Z6 判红）；三一致 |
| posts | A4 | 无头·串行·全文 | 10/20 | FULL；具名 40362 → 审计 WARN 表（D4：仍要修） |
| posts | A5 | 窗口·关展开全文 | 10 | FULL + `excerpt_only` 行 + 正文长度在摘要带 |
| posts | A6 | 窗口·冷僻词 | 20 | 必须 `NAMED_SHORT`（no_more/confirmed），无声 0 行=红 |
| posts | A7 | 同词连跑·recrawl 关 | 10 | 第二次 `dedupe_all_skipped` 具名 + 0 行 |
| author | B1 | 窗口·串行（token 现场发现） | 10 | FULL；错输入按名拒付（既有 B3） |
| author | B2 | 无头 | 5 | 行>0 或具名拒绝；`authorTabEmpty` 在高产作者=假行判红（Z16） |
| hot | C1 | 窗口·target=30 | 30 | 精确 30 + 7 列集合 + 链接重写正则 |
| hot | C2 | 窗口·target=40 | 40 | rows==30 + `hotCapped` 具名（超额索取的正确形态） |
| hot | C3 | 无头·target=30 | 30 | FULL |
| comments | D1 | 窗口·2 篇真链（现场选高评论数） | limit=20 | 每篇 `comment.article` + `comment.done` == 入库数；不测 评论时间/点赞数（结构常量） |
| comments | D2 | feed 链：posts(3)→comments(`input_column=链接`) | 3×limit3 | 喂入正确、textarea 豁免、行存在 |
| comments | D3 | D1 无头版 | 20 | FULL |
| comments | D4 | limit=0 单篇 | 全部 | 过程正确性：done==stored |
| 停止/续跑 | E1 | 窗口 target=40，≥5 行时按停止 | — | interrupted + partial + 保留行>0 + cursor `scanned>0` + 「被停止」计数≠失败 |
| 停止/续跑 | E2 | E1 之后 `resume_run_id`+`queue:false` 继续 | 40 | **补满 40**、`链接` 唯一==40、`resume_from`/`resume_have` 在场、游标只有位置 |
| 停止/续跑 | E3-E7（合并轮新增） | 并行中途停/评论文章间停/改 keyword 续跑（dropped_stale）/模拟 cookie 死续跑/断点续跑节点 | — | 各自 D 组语义（见 §3-D） |
| cookie | F1 | 真 jar 探测（四模式 needs_session） | — | 判决非 EXPIRED |
| cookie | F2 | 织入所有用例 | — | `cookie_expired` 恒 False |
| 并行形态 | G1 | 两组件·并行·一次性 profile + `same_platform_queue` 关（测后还原） | 10+10 | 一条记录 `A + B`、wf_count==2、各自 FULL、两 executing 行交错先于任一 completed |
| 并行形态 | G1b | 同画布·真排队默认开 | 10+10 | 两条都完成 + 排队行具名 + 无超时 |
| 并行形态 | G3 | 同画布·真实 profile | 5+5 | profile 锁串行化下两条全绿 |
| 终验 | H1 | `测试：知乎.json` 原样（仅 posts 启用·串行·窗口） | 50 | `skippedWorkflows` 点名三条禁用组件 + skipped_workflows 列 + FULL 50 + CSV 三一致 |
| 终验 | H2 | 内存副本·全组件启用·串行·窗口 | 各 stored | 四组件全过；NAMED_SHORT 仅带 WARN 清单 |
| 终验 | H3 | 内存副本·并行·无头 | 同上 | 全组件绿 |

**时区/语言**：`lang:'zh'` 为主、至少一条 `en` 对照（语义一致）；断言全部经 `i18n.t()` 解析，不粘整句。
**预算**：知乎全矩阵一轮 ≈ 1.5–2.5h 真机；A3/E2/H 为大头。

---

## 5. 判定基础：合法具名收尾白名单（每模式闭集，其余少交=红）

| 模式 | 合法具名行（i18n 键） | 语义 |
|---|---|---|
| 各平台 posts/author | `crawl.*.target_reached`；真 no_more（列表末尾标记在场）；`crawl.zhihu.no_more`；`run.dedupe_skipped`/`dedupe_all_skipped`；`run.nodeStopped`；`run.cookieExpired`（设计路径）；`crawl.riskBlocked`/`crawl.loginWall` | 站点真没有/去重/用户停/cookie 死/风控 |
| **知乎 posts 特别条款** | `crawl.zhihu.stuck`（Z6）**仍不算**合法：充足供给+窗口模式下的 stuck=bug 信号，等真机证明「连停 3 轮」确实是断供而非软风控再谈。**2026-09-27 已修**：旧代码首轮无增长就内层二次确认后 break（`stuck` 恒为 1，`STUCK_ROUNDS=3` 形同装饰，`crawl.zhihu.confirmed` 分支**不可达**=一条产品打不出来的行）；现改为**连续 3 轮**无增长才收工，`confirmed` 那句话说的是「内容已加载完毕」这种未经测量的断言，已随分支一并从双语目录删除 | 从严 D4/D6 |
| hot 类 | `crawl.zhihu.hotCapped`、`crawl.dy.hotCapped`、`crawl.weibo.hotCapped`（≈52）、douyin 热榜≈51；B站 `ranking` ≤100 **无 cap 行=欠账**（修复项） | 榜单大小由网站决定 |
| comments | `comment.status.blocked` 具名、`comment.zhihuNoPanels`、`comment.commentsClosed`、`comment.dyNone/dyNoPanel`、`comment.xNoList` | 关闭评论/真无评论/拒绝 |
| **微博 posts/author 登记（2026-09-28 写矩阵时）** | posts：`crawl.weibo.no_result`（站点自己印「抱歉，未找到相关结果」，实测它**与 5 张不相干推荐卡同屏**，故它是唯一判据 U31）、`crawl.weibo.page_empty`（某页**真的一张卡都没有**——U36 修复后这句话才成立：旧代码把「整页都是台账里的旧行」也报成空页）、`crawl.weibo.authorNoPosts`（200 + 空 list 是对一个账号的事实）。author 另加四条**raise 型拒绝**：`authorRefused`（mymblog edge 403，per-session 节流）、`authorWall`、`authorMirror`、`authorEmpty`（uid 读不出→开浏览器之前就拒，绝不猜一个人）。**明确不算合法**：`crawl.weibo.walk_done`/`authorDone` 与它们的 `{reason}` 槽（`crawl.stopReason.end`/`no_new`/`no_cards`/`stuck`）——那是**代码对自己循环的总结**，「窗走完」既可能是供给干涸也可能是 pager 少读一页，白名单收它=把每条 posts 用例的 `!= SILENT_SHORT` 变成不可证伪（知乎那表只收「站点自己的标记」，同一纪律）；`crawl.stopReason.unreachable` 也不收（AGENTS：浏览器没取到页面**不是**站点的拒绝）；`crawl.weibo.target_reached` 照旧不收（自己给自己发满分） | 站点 plate / 账号事实 / 具名拒绝；总结行不免责 |
| **微博 comments 登记** | `comment.weiboShowFailed`（statuses/show 取不回，带 URL）、`comment.status.dead`（逐文摘要里那格的 DEAD）、`comment.weiboReplay`（游标在动而整页复读）、`comment.weiboShort`（游标耗尽且 `total_number` 更高——差额是楼中楼 U33）、`comment.weiboFetchDied`（**新增**：某一页取数失败即收尾，带页数/本次条数/站点标注/差额，U37）。**不收** `comment.commentsClosed` 与 `comment.status.blocked`：`crawl_weibo` 没有墙判定，只可能返回 `OK`/`DEAD`，收进来就是 §5 末尾警告的那种「打死在名单里的行」（下一位读者会以为评论被墙是有判定的） | 具名拒绝/复读/分母差额；死链与墙分开说 |
| 跨切 | `run.wallRetry`、`run.platformQueued`/`platformStaggered`/`serialForced`、`crawl.profile_wait`、`run.pagePending`+`net.*` | 排队/重试/页面未到达 |

> 白名单是**闭集**：新增合法终局必须先在本文件登记出处（真机实测证据进 `docs/crawler_notes.md`）。
> 已知「说了但说谎」的行（在场也算红并归因 §6）：Z6 虚报次数、Z8 高水位数、Z16 慢渲染报"他没发过"、
> `crawl.bili.empty_page` 慢渲染报"没卡片"、`stopReason.stopped` 混判墙（E9）、`crawl.riskBlocked` 报在
> `about:blank`（W1）、`crawl.zhihu.emptyOrBlocked` 一句三个原因（Z3）、
> `crawl.weibo.page_empty` 曾把「整页都是本次已采过的行」报成「这页没有卡片」（U36，**已修**：
> `_harvest` 现在同时交出「看见几张卡」，收工只看卡片数为 0）。
> **一条行能不能被观察到，取决于开关**：`run.serialForced` 只在 `same_platform_queue=False` 时打
> （`crawl_gate.hold`：`forced_serial = serial_only and not 该开关`），排队开着时微博同样排队、但控制台说的是
> `run.platformQueued`——那是「用户的开关生效了」，不是「平台红线没被投票掉」。G1/G2 因此必须显式改这两个
> 全局开关（它们**不**从 run payload 读，写在 canvas `settings` 里的 `same_platform_stagger` 没人看），跑完还原。

---

## 6. 「数量采不满」已锁定嫌疑清单（代码级侦察 2026-09-27，待真机复现归因）

用户主诉：经常出现爬取数量不够目标。**结构性根因**：全程序只有登录墙分支比较过 行数 vs 目标
（`app.py:2395` `target_count = crawl_args.get('target_count') or 0`；`app.py:2549-2568` 唯一消费者）；
`login_wall=False` 时短表与满表无法区分，`finish_node(NODE_DONE)`（`app.py:3621`）照样 DONE；
`run.finished` 只数节点不数行。**程序没有任何通用「未达标即报警」。**

| 编号 | file:line | 问题 | 处置归属 |
|---|---|---|---|
| U1 | `app.py:2395,2549-2568,3621` | 无通用 under-target 判据 | **产品修复**：执行器对 source 节点统一比对 rows vs target，短了必须打具名结论行 |
| U2 | `engine/feed.py:99-116`、`engine/pager.py:23-36` | scanned/kept/refused/rounds/pages 算而**从不打印** | 产品修复：walk 收尾统一播报「扫X留Y拒Z」 |
| U3 | `crawlers/zhihu.py:232-272`（Z6）**已修 2026-09-27，待真机复验** | 搜索滚动循环手抄了第二份循环（AGENTS 禁止的形状）：旧代码一屏无增长后只等 `CARD_WAIT=1.5s` 再确认一次即 `crawl.zhihu.stuck` **break**，`stuck` 恒为 1、`STUCK_ROUNDS=3` 形同装饰、`crawl.zhihu.confirmed` 分支不可达。对照：**同平台作者模式没这个毛病**（`_walk_profile_tab` 走 `engine/feed.py:194-213` 的 `walk_feed`，连停 3 轮才收工）——同一站点两套放弃速度差 3 倍，收尾还打 `crawl.zhihu.finished n=<短表> total=<目标>` 自称正常。**修法**：内层那次「二次确认滚动」保留为**额外耐心**（不再附判词），只有 `stuck>=STUCK_ROUNDS` 才收工并打 `crawl.zhihu.stuck n=3`；说过头的 `crawl.zhihu.confirmed`（「内容已加载完毕」是未测量的断言）随分支删除（双语目录两行）。快层新钉：`tests/unit/test_crawler_zhihu_search.py` | 余账：把这条循环整体换成 `feed.walk_feed`（消掉第二份拷贝，顺带带出 U2 的 scanned/kept/refused）；`xiaohongshu.py:123-133` 同病，轮到该平台时同修 |
| U4 | `crawlers/zhihu.py:569-576,598-605`（Z9/Z10）| 卡片吞行只 `logger.debug`；根 logger INFO（`app.py:222-225`）→ 控制台与 logs/ 双不可见 | 产品修复：升 INFO 聚合行（「本轮跳过 n 张无效卡」） |
| U5 | `xiaohongshu.py:169-171,186`（XH6） | **seen 链接列表写进游标**（违反「游标只记位置」）→ 链接失败一次=之后每次续跑**永久静默跳过**=漏采 | 产品修复；D8 判据的现成红牌 |
| U6 | `base.py:383-385`（B9） | 游标落盘异常被 suppress → 续跑错位 | 产品修复：至少 WARNING |
| U7 | `base.py:355-361`（B6） | sink 写失败的行**计入 collected 但没入库**→ 报满实际缺 | 产品修复：计数与库内对账 |
| U8 | `run_store.py:907-909` vs `app.py:2536-2546` | 去重逐行静默；聚合行只在 app 运行路径打 | 测试判据+文档说明即可 |
| U9 | `bilibili.py:149-161,216-225`（BL2/BL7） | `fetch_json→{}`→`code is None`→**零行日志丢行**，最干净的一条静默欠采 | 产品修复 |
| U10 | `weibo.py:138-169`（WB1，**已修 2026-09-28**） | 全窗走完**无最终总结行**（n/目标/原因全无）——八平台最差控制台。**已证实（代码事实）**：同文件 `author()` 有 `crawl.weibo.authorDone`（n+reason），搜索路径收尾只有逐窗的 `link_done`/`accumulated` | 产品修复（补一条带目标的收尾行） |
| U11 | `weibo.py:480-513`（WB5，**已修**） | 「每窗 9 s 预算不够」这个前提**今天没复现**：实测三种 URL 都是 `driver.get` 0.42-0.85 s 返回、首卡 0.42-0.85 s、卡片数 2.47-2.92 s 稳定（`docs/crawler_notes.md`）。**成立的是另外两半**：① 该函数用裸 `driver.get`，绕开 `Crawler.open` → 不记「导航是否 settled」、renderer 超时直接抛；② 超时那句打成「页面加载超时，**可能无内容**」——把网络判断说成内容判断 | 产品修复（改走 `self.open`；超时行只许说代码看得见的东西） |
| U12 | `weibo.py:515-522`（WB8，**已修**） | **已量化证实**（2026-09-28 第 0 步）：同一个 timescope 小时窗第 1 页 9 张卡、**第 2 页 6 张、mid 交集 0**，`.page-info` 虽空但 `ul.page-list a` 给到 page=1..10 → `_may_page`「窗口已经窄了」的前提被否证，**一窗静默丢 40%**；而 `_get_total_pages` 的 href 回退本来就读得到第 2 页，只是永远走不到 | 产品修复（**允许窗口翻页**，不是"声明上限"）；测量出处 `backend/test_weibo_gaps.py` |
| U13 | `douyin.py:410-411,607-651`（DY5-DY8） | 列表重开为空/滚动 JS 异常 suppress→`drained=True`→报「列表翻完了」 | 产品修复 |
| U14 | `youtube.py:422-437,374,438`（YT6/YT7） | author 无原因行；`finished` 不带目标（全平台最安静收尾之一） | 产品修复 |
| U15 | `twitter.py:372-387`（TX3） | settle 预算 3×4s，对自己「一屏 ~12s」的测量偏紧；`finished` 无目标 | 产品修复（预算校准） |
| U16 | `twitter.py:390-391`（TX7） | `crawl.loginWall` 双打（违反 one failure one line） | 产品修复 |
| U17 | `engine/wall.py:175-182,254-258` → 五个 walk 谓词（W1/E9） | `about:blank`/`chrome://`→blocked→risk latch→整场 walk 收工；行还谎称风控；墙在 walk 谓词里被报成「用户停止」 | 产品修复（unreachable 与 blocked 分流；reason 拆分） |
| U18 | `app.py:2208-2233` | 碰撞重试清空 latch 后第二次返回 `[]` 且不重判墙 → **0 行 DONE**，无墙证据 | 产品修复 |
| U19 | `comments.py` CM1-CM6 | 评论引擎五处硬预算（weibo 30 页/xhs 12 轮/zhihu 面板 6 页/dy 40 轮/bili 200 页）**全部静默封顶**；xhs 未挂载面板报 `(0, OK)` | 产品修复（预算到达即具名；dy 的 `dyNone/dyNoPanel` 拆分是样板） |
| U20 | `jsonpath.py:61-62`（J1） | 嵌套>60 或命中≥5000 截断无行 | 低优先，出现即报 |
| U21 | `engine/popup.py:148-184`（O1） | 未知插页既不点也不报 | 低优先 |

| U22 | `crawlers/comments.py::_comment_author`（**已修 2026-09-28**，原 `ancestor::div[3]`） | 定深取作者：真机测到一个面板 **12 条里有 2 条**要在第 4 层祖先才找得到 `/people/` 链接——那一层已经横跨邻条，于是**一条评论可能挂上邻座的名字**（比空更坏）。改成页内一次读取、按结构定界（「仍只含一个 `.CommentContent` 的最深祖先」才作数），并新增 `comment.zhihuNoAuthor` 播报「本轮 {total} 条里 {n} 条自己子树内无作者链接」——匿名与选择器死亡从此可分 | 产品修复；测量出处 `backend/test_zhihu_comment_dom.py` → `scratchpad/zhihu_comment_dom.json` |
| U23 | `crawlers/comments_zhihu.py`（**已修**，原 `'评论时间': ''` / `'点赞数': 0`） | 两列**没读过页面就写死**：时间实测每条都有（近期「14 小时前」、远期「2019-08-15」）却存空；点赞在 22 条里既无按钮也无 aria-label 亦无裸数字，却被存成 **0**——用户在图表里读到「没人赞」。现改为真读时间、点赞留空 | 产品修复；同上一行的探针为证 |
| U24 | `crawlers/comments.py` 知乎面板翻页（**已修**，原 `range(6)` 静默） | 属于 U19 的知乎那一格：6 页预算走完、站点仍在给「更多」时**一声不响**，261 条的panel 报 6 条像报「就这些」。现到达即打 `comment.zhihuPanelCapped` | 产品修复（其余平台的那几格仍欠） |
| U25 | `app.py:1426-1447`（串行行名）＋ 用户画布实形 | **真机发现**：串行是「每条工作流各开一行」，而行名优先取**启用中的 name 节点**、否则退回画布/文件名。`测试：知乎.json` 四个组件里有三个的 name 节点是关的 → **三行同名**，按名回读必然错配（H2 首跑就报 `run … has no node 'node-12'`）。测试侧已按「谁含该 source 节点」定位（`_records_by_node`） | 产品待议：同名串行行是否该带组件标识（面板里三行无法区分 = 用户读不到的归因） |
| U26 | 站点行为（**非 bug**，改判据） | 同一关键词**两次搜索给的卡片会换**：A7 旧前提「同 ask 两次 = 同批条目」被真机否证（第二次交付 5 条全新行，台账没撒谎）。热榜才是稳定供给（30 问数分钟不变），故 A7 改用 `hot` 二跑验「已采过不得再存」 | 判据修订；给「不重采」一个可测的形状 |
| U27 | 站点/设置交互（**非 bug**，用例形状已改） | **12 s 错峰默认会把短目标的"并行"退化成串行**：G1/G3 实测 10 行的正文爬取活 ~10 s < 12 s 间隔 → 第一条在第二条被放行前就结束了，profile 锁压根没被问（G3 的 `crawl.profile_wait` 缺席即证据）。错峰归 S1 测；G1/G3 现在把间隔置 0，只留自己那把尺 | 判据修订 + 用户可见事实（面板讲「并行 ×N」时按目标行数折算真实并发） |

| U30 | `tests/integration/test_ui_layout.py::test_the_cookie_panel_fits...`（**已归因并修 2026-09-28**） | 「单跑绿、跟在同文件其它用例后面就红」**不是版式回归，也不是环境噪声，是测试自己没量到它声称的窗口**：`set_window_size/set_window_rect` 在这台 Windows 上都不生效（页面仍报 1920×1080），而面板 `max-height: calc(100vh-24px)` 与 `makeResizable` 的**一次性** cap 取的是**对话框首次打开那一刻**的视口——于是它带着一个 646px 的旧上限去量 703px 的内容。修法：用 CDP `Emulation.setDeviceMetricsOverride` 把 1366×768 **真的**变成布局视口，并按「浏览器测量必须报告自己量了多少」的规矩，量一个 `100vh` 探针元素来断言视口（`window.innerHeight` 在仿真下仍会谎报 1080，所以不能用它）；溢出消息里同时报 cap 与面板内最高的几个块 | 测试卫生修复（禁止放宽阈值）；改后面板在 1366×768 下 cap 744 / 内容 716，装得下 |

**微博第 0 步新登记的（2026-09-28，全部有 `scratchpad/weibo_*.json` 载荷为证；正文见 `docs/crawler_notes.md` 微博节）：**

| U31 | `weibo.py:499-513`（`_await_search_page` 的判据顺序，**已修**） | **一个真·无结果的窗口会同时给 `.card-no-result`（「抱歉，未找到相关结果」）和 5 张带作者的不相干帖子**（穆祉丞超话/凤凰传奇演唱会…，时间戳在窗口之外）。祖先链量过：结果卡与推荐卡**同构**（都挂在 `div#pl_feedlist_index.main-full` 下，`mark`/`card-type` 两边都是 None）→ **没有容器可用来区分**，而函数**先查卡片**才查 plate → 这 5 条会被当作关键词结果存进表（违反「不漏采、不重采、完全符合要求」的第三条） | 产品修复：plate 优先；断言用「空窗必须 0 行」 |
| U32 | `comments_weibo.py::parse_weibo_comments`（**已修**） | **四列在造假**（探针确认键名）：① 载荷里赞数键是 `like_counts`，代码读 `like_count` → **点赞数恒 0**（知乎 U23 同一形状）；② `楼层` 用 `enumerate(...,1)` 而 `crawl_weibo` **每页调一次解析** → 每页楼层都从 1 重数，站点自己印 `floor_number`；③ `评论时间` 原样塞 `"Sun Jul 26 09:49:46 +0800 2026"`，同文件作者路径的 `_normalise_weibo_time` 没用上 → 一列两种形状；④ `评论者主页` 填 `user.profile_image_url`（**头像图片地址**），同一 user 对象里就有 `profile_url='/u/<uid>'` | 产品修复（四列全改真读） |
| U33 | `comments.py::crawl_weibo`（**已修**） | **楼中楼拿不到，且差额从不可见**：`total_number=30` 的微博走游标只有 22 行，缺席楼层正好 8 个 = 子评论；五种形状全试错（`id=<父>`、`is_mix=1&sub=1&import_id`、`rootid=` 被忽略、`comment/hotFlowByIds` 是 HTML、带 `config=`/`rootid=` 直挂 → **400 Bad Request**），`m.weibo.cn/comments/hotflow?id&mid=<父>` 答 `{"ok":0}`。唯一在手里的是父行 `comments[]` 的**一条预览子评论**（749 条那帖第一页 3/22 行带）。另注：信封 `trendsText` 在只给 22/30 时仍写「**已加载全部评论**」→ **站点这句文案不可采信**，判据只能对 `total_number` 打 | 产品修复：收编行内预览子评论 + 新增 `父楼层` + 差额具名（`comment.weibo*`）；U19 微博那一格同时修（30 页预算 ≈600 行 < 分母 749/763，撞到即具名） |
| U34 | 第 0 步未收口项 | 本轮三个页面样本里**没有转发卡**（`nested=0`、`.feed-forward-wrap`=0），所以「转发卡的引用内容 + 嵌套 `.card-wrap` 会不会让同一条被数两次」**仍未测**——不是已排除。同理 `_get_full_text` 在转发卡上取到的是引用还是原文，只有真卡能答 | 第 0 步补测项：换一个必然出转发卡的时间窗，量一次「卡片数 vs 行数」漏斗（一次导航） |

| U35 | `weibo.py::_scrape_card` 的 转发数/评论数 选择器 | 一条批评意见（来自工作流的一路审查）说：热卡用另一套 woo 版式、计数是按钮的兄弟节点，于是**最有价值的行被存成 0**——依据是 pass 1 抓到的一张怪卡（`mid=5347502954124386`：卡内文本印着 714/1024/7274，而 `[action-type="feed_list_forward"]`/`..._comment"]` 读回裸词「转发」「评论」，只有 `.woo-like-count` 读对了 7274；`actionLabels` 顺序也不同）。**第 7 条探针按结构量完：这一版式假设未被支持**（整页 `.woo-count`/`.woo-forward-count`/`.woo-comment-count` = 0/0/0、`.woo-like-count` = 每卡一个；10 张卡的动作条全是旧 `menu s-fr`，有数的卡数就长在按钮自己的文本里）。零转发零评论的高赞帖本来就能长成那样，`714/1024` 更像那个视频号模块自己的数。**但也没有排除**：那次 `actionLabels` 顺序不同说明视频卡版式存在，只是这次没采到样本 → 结论：**没有样本就不改选择器** | 待测（换必然出视频卡的供给再量一次「动作条锚点文本 vs 卡内数字节点」；量到不一致才改）；测量出处 `backend/test_weibo_actionbar.py` → `scratchpad/weibo_actionbar.json` |

| U36 | `crawlers/weibo.py::_scrape_single_search` 的翻页判据（**已修 2026-09-28，写微博矩阵时从代码读出**） | **续跑把被停那一窗的深层页永久丢掉**：页循环用「`collected()` 没涨」当「这页之后没有了」（`if self.collected() == before: page_empty; break`）。而 继续 恰恰必然造出这个形状——游标把 `url_index` 留在被停的那一窗、`card_index/page_index` 归零，于是重进窗口后第 1、2 页的卡**全在台账里**（0 新增），循环在第一页就 break，**比 停止 更深的页再也没被请求过**。控制台还会打「第 2 页无有效卡片」——一句关于站点的话，说的是我们自己的台账。这正是 §11 第 0 步警告的「假设自洽」型缺陷：表、游标、总结行三方都同意一个短数 | 产品修复：`_harvest` 改回 `(kept, cards_seen)` 两个数，**停页只看站点空（cards==0）**，「整页都是旧行」只报数不收工。代价写进 docstring：一个每页都复读的坏 pager 现在会走完 `total_pages`（实测 1..10），有界；反向代价是一张贴着分母的短表没人报警。快层钉：`tests/integration/test_weibo_crawler.py::TestPagingWalk::test_a_page_with_nothing_new_on_it_is_not_a_page_with_nothing_on_it`（退回旧判据即红，并当场印出那句假「无有效卡片」）；真机判据：`test_live_weibo_workflow.py` E1/E2 断 继续 打开**更深的页**，不只同一个 URL |
| U37 | `crawlers/comments.py::crawl_weibo` 的 `ended='fetch'`（**已修**） | 评论游标三种收尾里**只有这一个不打字**：游标耗尽有 `comment.weiboShort`、站点复读有 `comment.weiboReplay`、用户上限刻意不打字（D5 钉住），而 `buildComments` 某页取数失败 → 直接 `break` 返回已有行，**控制台一个字没有** → 短表读起来像「这条微博就这么多评论」。审核微博矩阵时顺着「每种收尾都该留下一句话」查出来的 | 产品修复：新增 `comment.weiboFetchDied`（第几页失败 / 本次几条 / 站点标注几条 / 差额 / 游标停在失败页可继续）。快层钉：`tests/unit/test_comments.py::TestWeiboAdapter::test_a_failed_comment_page_names_itself_instead_of_looking_finished`（并钉住它**不得**同时打 `comment.weiboShort`——那句是替站点说话） |

**滚动节奏（fake driver 数出来的 scroll 命令，不是真机测量；读控制台 `scroll_round` 前先记住它）**：
`scroll_down(steps=3)` 一次发 **4** 条 scroll 命令（3 步 + 1 次底部跳转），所以搜索的一个 stalled round
= 2 次 `scroll_down`（轮首 + 轮内那次确认）= 8 条；连停 3 轮收工共 **20 条**，时间成本 ≈ 每轮 2×`CARD_WAIT`
(1.5 s) + 2×礼貌间隔(~1.1 s)。作者模式走 `walk_feed`，一个 round 只有 1 次 scroll 调用——**两条模式的分页
节奏不同，按行数换算滚动次数时不要混用**（`tests/integration/test_zhihu_crawler.py::test_stuck_pages_end_the_loop`
把这个 20 钉成等式，改了循环形状就会红）。

| U28 | `crawlers/comments.py` 知乎面板（**已修 2026-09-28，真机抓到**） | **八平台最大的一桩静默欠采**：面板**没有「更多」按钮**，列表由**容器内滚动**懒加载，而旧代码每轮找文本含「更多」的按钮、找不到就收工 → 每篇只拿首屏。实测（一条 261 条 / 一条 193 条）：开面板 12 / 10 → 滚容器 36 / 109 → 点子回复展开 41 / **138**；滚**窗口**无效。现按 `ZHIHU_PANEL_ROUNDS` 轮滚容器 + 点尽 `展开其中 N 条回复`，并逐轮打 `comment.zhihuRound`、走完仍不足页面自己的数字就 `comment.zhihuPanelShort`、耗尽预算 `comment.zhihuPanelCapped`；D4 新增「 unlimited 采集不得留下 short 行」这条硬判据 | 产品修复；证据 `backend/test_zhihu_comment_structure.py`、`docs/crawler_notes.md` 评论区一节 |
| U29 | 同上（**已修**） | 子评论（评论的评论）从不展开 = 一条都没采；现在行上多一列 `父楼层`（顶层为空），线程关系在导出里可读。实测另证两件事：展开**不换容器**（36→38 同一个盒子），但 `driver.back()` 会把面板弄没（→0 行），所以**永远不得**加返回动作；同时滚动目标必须选「含评论最多的盒子」而非第一个（子回复列表自己也符合可滚条件，选错就再也不前进） | 产品修复；同上两节为证 |

**流程**：每平台真机跑完 → 对 §8 审计表逐例归因（FULL/合法/NAMED 假行/静默）→ 上表对应项修复 →
单例复跑 → 平台层复跑 → 快层+lint 全绿 → 记 `crawler_notes.md`。

---

## 7. 全平台模板与专轴（轮到时按 §3-§6 展开）

| 平台 | 网络 | 专有点（除通用骨架外） |
|---|---|---|
| 知乎 | cn | （=§4 模板本体） |
| 微博 | cn | **serial_only**：并行组只测「强制排队+serialForced 行」；**双账号才允许真并行**（需第二个 cookie 文件 `weibo@<acct>`，没有该格则跳过并声明）；热搜 `needs_session=False`（无 cookie 可跑、无 account 字段）；时间窗 4 态（双无/单边/双有/非法）；mymblog 403 必须响亮拒；**窗口按 D9：副本取最近数天，验证 target 先满即收工且剩余窗口零付费**（原 Jan-1 大窗不跑） |
| 小红书 | cn | XH6 修复回归 + comment_preview 三档 + 过期 xsec_token 链接=具名失效非空表；profile_recommended：一次性 profile 路许可具名被墙 |
| 微信 | cn | 纯正文列集（无互动列/无 cookie 行）；无 target 语义（links 即预算；cookieExpired 分支对其不可达是**设计事实**）；粘贴/喂链两式；每行真导航（page_per_row）；正文 5000 字截断标记；链接取自 D7 |
| B站 | cn | page=1 零卡（裸 URL 请求首页）；评论纯 API 游标翻页；`board=ranking` 一次整表≤100 且**无 cap 行=修复项**；作者走空间页非 wbi API；UP主 续跑游标点名是谁的空间 |
| 抖音 | cn | sort×3 各自可验证性质 + sort 进游标；sticky 头几何（menu.hover 补 enter）；热榜反向语义（档案被验证码、一次性浏览器反通）；page_per_row 导航计数（列表是文档不是书签）；作者=每行一次详情导航、行内无播放数 |
| X | **os·待VPN** | 虚拟时间线：进度=保住的行；续跑身份=status-id 集（不许索引）；五计数同源 aria-label、浏览数唯一来源；一卡一次 execute_script；settle 预算回归（TX3/TX15） |
| YouTube | **os·待VPN** | innertube 页内 JSON（禁硬编码常量）；with_facts 2×2；游标选择按「是哪个列表的元素」；**国内网络下必须先测反向用例：不可达必须报 `unreachable` 而非假空/拒绝** |
| instagram | — | 不爬：双层拒绝（校验 + `run.notCrawlable`）+ 不掏浏览器，快层已钉 |

**每平台验收门（Gate）定义**：该平台所有模式 × 设置轴全值/双态 × {窗口,无头} × {串行,并行代表格} ×
D 组生命周期 × B 组对账 + E 组控制台审计零异常 + `测试：xxx.json` 原样通过 + 全组件副本通过。
任何一格 SILENT_SHORT、假行、对账不过 = 不过门，先修再跑。**规模心里有数**：设置轴差异用例全网 ≈48 条起步，
国内每平台一轮 2–3h 真机 + 修复轮。

---

## 8. 测试程序、捕获机制与实现状态

**落地文件**（已实现，路径即最终路径；闸门：`ruff check tests/` + 快层全绿）：

- [x] `tests/live_run_harness.py` —— 平台无关核心：
  - **全量控制台捕获**：`ConsoleRecorder` 以 2.0s 轮询 `GET /api/workflow/status`（`cadence=2.0`：一次
    状态读要付一次 Flask 请求 + JSON 解析，200 行尾窗在两拍之间被跑穿需要每秒 >100 行，所以这值是
    「够用且不干扰运行」而不是「越快越好」），用 `log_total` +
    200 行尾窗做**增量折叠**（每行恰好收一次），窗口被跑穿时置 `overflow`、换 run 时置 `resets`。
    **自证**：`recorder.complete()` 就是 `_log_total == len(captured)`（跨第二个 run 用 baseline 对齐），
    每条用例的 `assert_l3()` 先要它；所有权证明即 `run.started(rid=本 run)` / `run.resume_from` 必须在
    捕获里（status payload 永远不带 run_id）。**不改 `_push_log`、不提 `LOG_KEEP`**：产品自己那 5000
    行缓冲与浏览器读的同一扇窗，测试另开漏斗就会测一个用户看不到的通道。捕获写 `scratchpad/live_audit/`，
    **绝不写 logs/**（隔离守卫会整场红）。根 logger 另挂一个 mirror handler 只为审计留无过滤流水，`close()`
    必卸载；判据只读 console。
  - `canvas_for(platform, mode, **over)`：从 `capabilities.declared_defaults` + `MODE_KEY` 构造合法画布
    （先例 `tests/api/test_source_dispatch_matrix.py:236-256`）；`posts_then_comments_canvas` 两节点 feed 变体、
    `component_canvas` 多组件（并行/串行的输入形状）。`use_profile` 未说=不发（缺省是「跟着设置走」，不是 False）。
  - `classify_verdict(target, rows, console)`：FULL / NAMED_SHORT(理由=键名) / SILENT_SHORT 三判（白名单=§5），
    出口按 i18n 模板编译成正则匹配（槽位放宽），平台自己的出口由调用方并进来，不写死在这。
  - `audit_dump`：每例落 `.console.txt` + `verdicts.csv`（case,platform,mode,headless,use_profile,target,
    rows,verdict,reasons,wall_flags,cookie_expired,seconds）——**§6 归因的原料表**。
- [x] `tests/live_site/test_live_zhihu_workflow.py` —— §4 矩阵，标记 `[live_site, live_cn, enable_socket, serial]`；
  **零 pytest.skip**（跳过白名单是闭表，新文件不入表；爬出来的答案一律断言）。用例函数名即 case_id：
  `test_a1_windowed_serial_search_delivers_ten_rows_with_bodies` … `test_h3_the_whole_shipped_canvas_in_parallel_headless`；
  E1/E2 同一条（续跑要读同一次 run 的行与游标，`client` fixture 每例一套私有 store，跨例读不到）。
- [x] `tests/unit/test_live_run_harness.py` —— 捕获/分类/构造器的快层单测（假轮询器、不碰浏览器、审计只写 tmp）。
- [x] `tests/real_paths.py` —— 「真实 Cookie 目录在哪 + 有没有会话」的**唯一答案**（live conftest、harness、
  cookie_preflight 用例三处原先各写一遍，现统一从这里导入，并用产品自己的 `CookieManager` 判存在）。
- 状态（2026-09-27 合并轮落地后**本机重测**，非 agent 自报）：live 文件可收集 **31 例**（A1-A7 / B1-B2 / C1-C3 /
  D1-D4 / E1+E2 / E3-E7 / F1 / G1/G1b/G3 / H1-H3 / **S1-S2**）；快层 **4475 passed / 220 deselected**（隔离守卫静默）；
  `ruff check tests/` All checks passed，`ruff format --check tests/` 142 files already formatted；
  harness 单测 80 例。`scratchpad/live_audit/verdicts.csv` 尚未生成（真机一轮才写）。
- **合并轮（已定，勿再复议）**：捕获**不改 `_push_log`、不提 `LOG_KEEP`**——理由见本节第一条： recorder 读的就是
  浏览器读的那一扇窗，另开漏斗会测到用户看不到的通道，而「用户看不到」本身就是要报的缺陷。
  兜法已就位：`overflow`/`resets` 一旦被置起，`assert_l3()` 当场红并指名窗口被跑穿，那时再抬 `LOG_KEEP` 有据可循。
  同一轮已并入的审查修项：`abort_run`（用例中途死必须替产品按停止，否则漏一个还在占平台闸与 profile 锁的活 worker，
  还会把它的行折进下一例的流水里 = 假绿）、`ZHIHU_LIES` 谎言名单（`stuck/confirmed/emptyOrBlocked/authorTabEmpty`
  永不作出口）、按组件切片评分（一条诚实的「没有更多了」不得替另一个节点的沉默背书）、`numbers_from` 走目录取数
  （不再手写正则）、评论按真实 ask（`limit × 链接数`）判满、导出 CSV 作 L2 第三腿、游标只记位置的断言、
  `resets == 0`、run_id 所有权、en 语种一例（C3）、H 组 verdict 由组件推出、2× 叠加超时改为剩余预算。
- 已落地（合并轮收口，2026-09-27）：E3-E7（并行中途停并验「时段交还」/ 评论在文章之间停 / 改 keyword 续跑清游标 /
  cookie 死后续 / adopt 存量表入新图）与 C 组设置轴的 **S1 错峰 + S2 并发浏览器上限**两格；S1 的新助手
  `harness.stamped_second` 直接读产品自己的 `[HH:MM:SS]` 前缀，把「行里宣布的秒数真的过去了」变成可测事实。
  随后扩到其余平台。G1/G1b/G3/H3/S1/S2 已带设置开关的 finally 还原。

**已知硬约束（设计时踩过的坑，全平台通用）**：

- 真机层与 app 运行**不能同时持有同一平台**（crawl_gate + profile 锁双排队 900s）：跑运行级用例前先 `live_crawler.release`。
- **同一个 profile 不允许两个真机进程并存**（2026-09-28 自己踩的）：误开第二次 `pytest` 后，后启动的那个
  直接吃 `session not created: Chrome instance exited`，用例以「一条评论都没存」红掉——**这是环境冲突，
  不是产品缺陷**。开跑前查 `tasklist chromedriver.exe`，一次只留一个真机进程；日志文件也别共用同一个名字
  （两次运行写同一个 `.log` 会把先跑完那份的结论盖掉）。
- `live_site` 下 `crawl_gate.reset()` 不自愈（`tests/conftest.py:257-259`），排队冷却**跨用例真实存在**——排期时按它。
- run 级用例必须带 `serial` 标记（worker 会换 `sys.stdout` 为 `_LogTee`）。
- 评论节点**不受平台闸**（`app.py:3650-3654` 公开缺口）：source+comment 同平台真并发是可行的测试形状。
- 并行=一次 execute 里的多组件；**两次 POST 永远排队**（一 run 一名额）。
- 断言消息全走 `i18n.t()` 双语解析；`{platform}` 槽是词不是键。

---

## 9. data/workflows 盘点（2026-09-27 快照，验收原样跑这些）

| 文件 | 组件 | 现状与坑 |
|---|---|---|
| 测试：知乎 | 4（热榜/搜索/作者/评论） | 仅「关键词搜索」启用，其余 3 组件 `enabled:false`（H1 恰测跳过声明，H2/H3 副本全开）；每源节点 `recrawl:true` |
| 测试：哔哩哔哩 | 5（搜索/UP主/热门/评论/周排行） | 全启用；parallel+headless 存档；评论 `comment_limit:50`；`node-12` 输出**无时间戳**（重复跑覆盖同名文件） |
| 测试：抖音 | 6（3×sort/作者/热榜/评论） | 热榜+评论 `recrawl:false` → 热台账下**合法 0 行**（验收副本改 true）；page_per_row 成本大（每行一次导航） |
| 测试：微博 | 4（文章窗/作者/热搜/评论） | **时间窗 2026-01-01→09-26 = 6432 小时链接**——按 D9 验收副本改最近数天并断言「满额先收、剩余窗口零付费」，原窗不跑；评论 `recrawl:false`；serial_only |
| 测试：小红书 | 2（帖子/评论） | serial+窗口存档；评论链接带 xsec_token（时效！过期=具名失效用例原料）；`recrawl:false` |
| 测试：微信 | 1（推文正文） | **urls 为空 → 原样必被校验拒绝**；按 D7 从现有测试取真链接补副本 |
| 测试：图表可视化 | 2（世界杯/DeepSeek） | 含 legacy source（无 `collect`，回落 posts；params 里有野 `headless` 键进指纹）+ analysis rename_columns（**列不在场时静默改 0 列**——断言导出表头读「发帖人」）+ wordcloud；两节点扇出测 output 透传 |
| 测试：X（D10 新建） | 3（posts/author/comments 全覆盖） | parallel+headless 存档；author=@NASA、评论锚定 `x.com/jack/status/20`（长存推文）；`validate()` 零错误；VPN 阶段原样 H1 + 变体副本 |
| 测试：YouTube（D10 新建） | 3（posts/author/comments 全覆盖） | 同上；author=NASA 频道、评论锚定 `watch?v=jGwWNGJdvx8`（2005 年长存视频）；with_facts=true；`validate()` 零错误 |

配套事实：`data/cookies/` 七平台齐（wechat 无 cookie 行属设计；两 `.stale-20260924` profile 遗留目录可留意）；
`data/exports/` 当前为空（输出断言从 0 基线）；`data/settings.json` 是**用户全局**（`same_platform_queue:false`,
`stagger:2`, `use_browser_profile:true`, `cookie_preflight_before_run:false`）——测试进程读到的是 conftest
隔离后的**代码默认**（queue=true），两者不同是正常的。

---

## 10. 运行操作手册

**前置检查**（每平台开跑前）：
1. 端口 5000 无自己起着的服务器（`netstat -ano | findstr :5000`；有则先问用户，**绝不杀**）；
2. 网络：国内 6 平台关 VPN，X/YouTube 开 VPN（跑 `live_os` 前向用户确认）；
3. cookie 新鲜（用户 2026-09-27 已全平台重登+更新）。

```bash
# 知乎全矩阵（真·用户登录态；一次性约 1.5-2.5h，建议分批按组 -k 跑）
CIXI_LIVE_USE_USER_PROFILE=1 .venv/Scripts/python.exe -m pytest -q -m "live_site and live_cn" tests/live_site/test_live_zhihu_workflow.py -rA

# 单例（node id 带引号 + 必须重写 -m，否则整条被默认过滤器静默 deselected）
CIXI_LIVE_USE_USER_PROFILE=1 .venv/Scripts/python.exe -m pytest -q \
  "tests/live_site/test_live_zhihu_workflow.py::test_a3_forty_rows_prove_the_scroll_loop_and_nothing_else" \
  -m "live_site and live_cn"

# G 组（并行形态）——内部自管一次性 profile，无需 env 变量切换
... -m "live_site and live_cn" -k "test_g1 or test_g1b or test_g3"

# H 组（用户工作流终验）
... -m "live_site and live_cn" -k "test_h"

# 海外阶段
CIXI_LIVE_USE_USER_PROFILE=1 .venv/Scripts/python.exe -m pytest -q -m "live_site and live_os" -k "x or youtube" -rA
```

**产物**：`scratchpad/live_audit/<case>.console.txt` + `scratchpad/live_audit/verdicts.csv`——
每轮跑完先读这两样再读 pytest 结论（**用户点名要求：看过程不看绿灯**）。

**每平台第 0 步（先读页面，再读代码；本表全部流程的前提）**：动任何爬虫或断言之前，用一次性探针
（`backend/test_<平台>_<物件>.py`，产物进 `scratchpad/`）重测该平台的**页面结构**，结论写进
`docs/crawler_notes.md` 对应小节，至少要问清四件事：列表**靠什么分页**（按钮 / 窗口滚动 /
某个元素自己的滚动盒）、有没有**藏在展开器后面的嵌套内容**（子评论、合并卡）、**哪个容器真的装着行**、
页面到底显示哪些列。知乎的两条缺陷都是在代码复查全绿、快层全绿之后被一行控制台抓出来的
（`新增 12 条` 对上按钮上写的 `261 条评论`）：评论面板**根本没有「更多」**（靠覆盖层自身滚动懒加载，
实测 12 → 36 → 41），子评论又全在 `展开其中 N 条回复` 后面。**页面模型错了不会报错**——它只会让
控制台、汇总行、库里行数、导出预览**一起同意一张缺的表**（内部自洽 ≠ 采全）。因此每条判据都必须
带上**站点自己印出来的分母**（页面写着多少条），短了就按名报出（`comment.zhihuPanelShort` 那一类）。

**失败分诊流程**：红例 → 取其 `.console.txt` → 按 §5 白名单/§6 清单归因（FULL 假象? NAMED 假行? 静默? 排队超时?
cookie 死?）→ 产品 bug 修产品码（禁改断言就绿）→ 单例复跑 → 该平台组复跑 → 快层+lint 全绿 →
证据补 `docs/crawler_notes.md` 对应平台段 → 本文 §6 表销号。

**每平台完成定义**：§7 Gate 全绿 + §6 该平台相关嫌疑全部「修复并回归」或「真机证明为站点行为并入白名单」。

---

## 11. 进度板

- [x] 侦察两轮（11 路报告；digest 为易逝会话件，**结论已全部收进本文 §4-§9**）
- [x] 用户决策 D1-D10
- [x] 代建 `测试：X.json`、`测试：YouTube.json`（validate 零错误，2026-09-27）
- [x] 知乎测试程序：**31 例可收集**（A1-A7 / B1-B2 / C1-C3 / D1-D4 / E1+E2 / E3-E7 / F1 / G1/G1b/G3 / H1-H3 / S1-S2）
      + 设置轴两格已落地；**本机重测**快层 4475 passed / 220 deselected、ruff 两项干净
- [x] 知乎真机全矩阵：**31/31 绿**（2026-09-28，6 轮跑完），逐例控制台审计 → §6 已销号 U3、U19(知乎格)、
      U22-U24、U26-U29；H1/H2/H3 原样跑通用户 `测试：知乎.json`；已提交 `dcfb126`+`0b8b4bc`+`d7215d6`+`e1bc3b0`
- [ ] **微博**：按 §11「一个平台的完整复查流程」八步执行（**第 0-5 步已过、矩阵 20 格已落地，第 6-8 步真机**）
      - [x] **第 0 步 读页面**（2026-09-28，八条一次性探针 `backend/test_weibo_{structure,gaps,child,child2,child3,child4,actionbar,cardcount}.py`
            → `scratchpad/weibo_*.json`；结论写进 `docs/crawler_notes.md` 微博节，判决登记为 §6 **U31-U35**）。
            四条旧疑点的下场：**U12 成立且量化**（小时窗第 2 页真有 6 条、mid 交集 0 → `_may_page` 静默丢 40%，
            修法是**允许窗口翻页**而不是"声明上限"）；**U11 前提被否证**（本机首卡 0.42-0.85 s、稳定 2.47-2.92 s，
            9 s 够用），成立的是「裸 `driver.get` 绕开 `Crawler.open`」+「超时行说『可能无内容』」那两半；
            **U10 成立**（代码事实：搜索路径无收尾行，同文件 `author()` 有）；**U19 微博格成立**
            （每页 ~19-22 ⇒ 30 页 ≈600 < 分母 749/763，撞到只是 break）。
            **新发现三处**：空窗同时给 plate 与 5 张不相干卡且**容器同构**（U31，会污染结果表）；
            评论四列造假（`like_counts` 读成 `like_count` → 赞数恒 0、`楼层` 每页重数、时间未规范化、
            `评论者主页` 填头像，U32）；**楼中楼五种形状全拿不到**、行内只有一条预览子评论、
            而信封 `trendsText` 在 22/30 时仍写「已加载全部评论」（U33 → 判据只许吃 `total_number`）。
            否证一条：微博正文**不被截断**（带「展开」的卡 DOM 里就有 `feed_list_content_full`，153→759 字）
            → 知乎那病在微博不存在。未收口：转发卡这一轮无样本（U34）。
      - [x] **第 1-4 步 改码 + 快层同步**（提交 `01db2f4` 与其后的审计修复）：plate 优先、窗口允许翻页、
            导航走 `Crawler.open(url, judge=False)`（引擎新增该参数：留下 settled 与弹窗清理，把墙的判决交回
            按文档判定的调用方）、收尾行 `crawl.weibo.walk_done`（行数/目标/走到第几个窗口/原因）、
            评论四列改真读 + `父楼层` + 差额具名 `comment.weiboShort`。
            **`@code-auditor` 抓到我自己七处新错，全部回修**（提交 `6f46dcb`）：
            ① `walk_done` 把 `len(urls)` 说成「走完」——改成「窗口走到第 {walked}/{total} 个」；
            ② 差额行把**任何**短表都归因给楼中楼（评论上限、取数失败也算）——改为只有游标耗尽才报，
               且用**交给用户的那张表**的长度；③ 30 页常量与 README「后端无任何翻页上限」冲突，
               且新加的按 ID 去重会让 limit 永不触发、只剩常量能收工——删掉常量，改成
               「某页没交出新的一条」具名收工 `comment.weiboReplay`；
            ④ 子评论的 `楼层` 用了它在父行预览里的位置（正是同一提交谴责的"六行都叫 1"）——改为留空，
               并用站点自己的 `is_sub_cmt`/`rootid` 判父子；
            ⑤ 窗口循环只对 `login_wall` 收手：风控与「浏览器根本没取到页面」会一路走完 6432 个窗
               而收尾行说「已到列表末尾」——改为一律收手并分出三种原因（新增 `stopReason.risk`/`unreachable`）；
            ⑥ 窗口在**进入之前**就被游标记为已完成：一窗现在深至 10 页，中途停止会让续跑跳过没走的页
               ——游标改为只在窗口走完后推进（台账按 `微博ID` 去重，重入只花请求不重复存行）；
            ⑦ 等待挪用了共享 `wait_for_first_content` 是错的：它「见到墙就早退」，而 passport 帧正是墙形状
               ——退回本平台自己的轮询，但把共享助手承诺的三件事原样接过来（`PAGE_WAIT_TIMEOUT` 预算、
               每 tick 问 停止、两次未交付就不再花预算的 `pending_waits` 断路）。
      - [x] **第 5 步 `@code-auditor` 审**（只读、未跑真机）：2 Blocker + 5 Major + 9 Minor，
            其中影响判决/采满的七条已全部回修（见上），并新增 8 例快层针（4501 passed / 220 deselected 零跳过）
      - [x] **第 3 步（补）运行级矩阵落地 20 格**（`tests/live_site/test_live_weibo_workflow.py`：A1-A6 关键词/时间窗、
            B1-B3 作者、C1-C3 热搜、D1-D5 评论、E1+E2 停止续跑、G1-G2 `serial_only`；共用件抽进
            `tests/live_run_driver.py`，知乎那份 433 行的重复就此消掉）。**F 组（preflight 三态）与 S 组（错峰节奏）**
            在微博塌进 G1/G2 与 A2：这个平台 `serial_only`，错峰只能排在队列之内，测不出知乎那两条并行节奏；
            热搜匿名由 C3 承担。H 组欠一件公版件：知乎那套「按文件自身发现组件 + 逐组件判决 + 三一致」的接受夹具
            要先抽成共享模块，微博才不必抄第二份。
      - [x] **第 4-5 步（第二轮）矩阵自查 + 审核 14 条回修**（真机之前，全部对着代码核实，未凭审核报告照抄）：
            ① G1/G2 断的 `run.serialForced` 在默认开关下**根本打不出来**（`forced_serial = serial_only and not
            same_platform_queue`），且 `same_platform_stagger` 写在 canvas settings 里没人读 → 两格改成显式改全局
            开关 + `finally` 还原，两格这才不是同一个测试；② `楼层` 唯一性跨文章判（站点是**逐帖**编号，两帖各有
            1 楼）→ 按 `文章URL` 分组判；③ D1/D2 用发明出来的 ask 判满（链接只有 3 条评论却按 5×N 判）→ 选链
            下限抬到 ask、D2 的 ask 改由父表算，并要求「每个有评论的父链接都在评论表里出现或被具名」；
            ④ 白名单里放进了 `walk_done`/`authorDone` 与 `crawl.stopReason.end/no_new/no_cards/stuck/unreachable`
            —— 那是代码给自己循环写的总结，收进来等于每条 posts 用例的 `!= SILENT_SHORT` 不可证伪 → 全删，
            只留站点自己的 plate；⑤ A5/B2 的回归检查写在 `if rows>` / `if offered>` 里，**恰好在 bug 在场时跳过**
            → 改成无条件（A5 必 FULL 且必读到 >1 页、B2 非具名拒绝即必须 >28 行且游标 page>1）；
            ⑥ E1/E2 只断「重开同一个 URL」而游标把页深度抹平 → 加「继续必须打开比 停止 所在页**更深**的一页」，
            顺带在代码里查出并修掉 **U36**（见 §6）；⑦ C3 用 monkeypatch 假夺 cookie（app 不读那个函数），
            实为登录态下断「匿名」→ 新增 `harness.no_jar` 真空目录 + `use_profile=False` + 断 `run.profileOff`；
            ⑧ 文档里教人 `-k "A or C"` 分批，实际 pytest 是**子串**匹配 → 那一行选中全部 20 格，改成点名单元格；
            ⑨ 无头用例接受具名墙时不再接受 `about:blank` 上的墙（W1 仍开着，由真机判）；⑩ 会话中途死在微博
            是设计路径（间歇风控）→ `RunDriver.NAMED_DEATH_OK` 类属性，审计行照打 WARN，不静默；
            ⑪ G 组两组件只写一行审计 → `_audit_component` 逐组件一行；⑫ D3 丢掉分母、`正文` 非空要求会冤杀
            纯图卡、A6 断「还有窗没开」在供给刚好用完时假红 → 全部按可证说法改写。
            新针：`_harvest` 的「无新增 ≠ 无卡片」（U36）与 `comment.weiboFetchDied`（U37，评论第三种收尾此前
            一个字不打）各一枚快层钉，退回即红。
      - [ ] 第 6-8 步：真机分批（用户 2026-09-28 授权自走：设计完矩阵即开跑，不再逐次询问）→ 逐例读完整控制台销号
            → H 组跑 `data/workflows/测试：微博.json`（公版接受夹具抽出来之后）
- [ ] 抖音 → B站 → 小红书 → 微信（同一套八步）
- [ ] VPN 阶段：X → YouTube（先测反向用例：不可达必须报 `unreachable`，不许假空）
- [ ] 全平台门过 → §6 剩余嫌疑（U1 通用 under-target、U2 walk 计数器从不打印等）收口提交

### 交接状态（2026-09-28，**知乎已收口、微博第 0 步已读完页面**）

**已提交**（`git log` 可查，工作树只剩用户自己的 `.gitignore`，他已自行提交）：

- `dcfb126` 问题修复：知乎采集与评论引擎三处静默欠采（搜索一停即弃 / 评论靠容器滚动而非「更多」 / 固定深度取作者会挂邻座）+ 时间与赞数不再造假 + 新增 `父楼层` + 面板预算与差额具名 + `Crawler.page_height()`
- `0b8b4bc` 功能更新：知乎运行级真机验收矩阵 **31 格** + 平台无关 harness + `tests/real_paths.py`
- `d7215d6` 问题修复：cookie 面板版式审计改用它真正声称的视口（CDP 仿真 + 断言 CSS 量到的视口）
- `e1bc3b0` 修改：AGENTS 两条新规则（**读页面先于读代码**；**浏览器测量必须声明视口**）+ 两个 agent 定义

**闸门实测（提交后工作树）**：快层 **4483 passed / 220 deselected**、设备层 **127 passed**（两层都零跳过）、
`ruff check` + `format --check` 干净；知乎真机 **31/31 绿**（含用户 `测试：知乎.json` 的 H1 存盘 / H2 串行 / H3 并行无头）。

### 一个平台的完整复查流程（知乎走通的那一套，逐平台照抄，**不许跳步**）

1. **第 0 步：读页面**（AGENTS 首条）。一次性探针 `backend/test_<平台>_<物件>.py`，产物进 `scratchpad/`，
   回答四件事并把结论写进 `docs/crawler_notes.md` 对应小节：列表**靠什么分页**（按钮 / 窗口滚动 /
   某元素自己的滚动盒）、有没有**藏在展开器后面的嵌套内容**、**哪个容器真的装着行**、页面显示哪些列。
   知乎教训：这三处（评论无「更多」按钮、子回复在展开器后、作者祖先深度不定）都是代码复查+快层全绿也抓不到的，
   而**测试是照同一套错误假设写的，于是短表内部完全自洽**。
2. **判据必须带站点自己印出来的分母**（页面写着多少条/多少行），短了就按名报出；`FULL/NAMED_SHORT/SILENT_SHORT`
   三判照旧，且**谎言行永不入白名单**（§5 闭集，新增合法终局要先登记真机出处）。
3. **写运行级矩阵**：抄 `tests/live_site/test_live_zhihu_workflow.py` 的形状（A 供给×目标 / B 作者 / C 榜单 /
   D 评论 / E 停止→继续 / F 预检 / G 并行与排队 / H 用户画布 / **S 设置轴**），
   标记 `[live_site, live_cn|live_os, enable_socket, serial]`，**零 `pytest.skip`**；
   评论格按真实 ask（`limit × 链接数`）判满，多组件**按组件切片**评分，用例中途死靠 `harness.abort_run` 兜住。
4. **快层同步**：每条新判据都要有假驱动针，并**当场验一次"退回即红"**（把旧代码装回去跑一遍再装回来；
   知乎的 `test_a_page_that_grows_late_...` / `test_a_tall_page_is_not_read_as_the_end_of_the_list` 是样板）。
5. **`@code-auditor` 审**（只读、禁真机层）→ 修 Blocker/Major，欠账写进 §6 并说明为何暂不修。
6. **真机开跑**：先 `netstat` 确认 5000 空闲（**绝不杀 5000**）、`tasklist chromedriver.exe` 确认**只有一个真机进程**
   （同 profile 并存会假红，见 §8）；分批用 `-k`，命令见 §10；**绝不无人值守跑**。
7. **逐例读 `scratchpad/live_audit/*.console.txt` + `verdicts.csv`**（先于 pytest 结论），按 §6 归因销号，产品缺陷修产品码。
8. **H 组终验用户画布**，然后 `pytest -q` + `-m "integration or live_ollama"` + ruff 全绿 → 分类提交（产品 / 测试矩阵 / UI / 文档）。

知乎轮次踩到、其它平台**开工前直接规避**的错：`confirmed` 类"产品打不出来的行"被写进白名单；
"同一关键词两次必得同批条目"（真机否证：知乎搜索会轮换卡片 → 台账类判据要用**稳定供给**如热榜）；
短目标并行被 12 s 错峰默认串行化（G1/G3/S1 全因此红过：测并发要置 `same_platform_stagger=0`，测错峰要让目标活过间隔）；
硬预算（页数/轮数）走完不吭声；列写死常量冒充已读（`点赞数 0`）；浏览器测量不断言视口；
两个真机进程抢同一 profile；文档计数不随实测更新。

### 微博入口（下一步照此执行）

- 专轴见 §7 微博行（**`serial_only`**、热搜 `needs_session=False`、时间窗 4 态、mymblog 403 必须响亮拒、
  D9 窗口只验"先满即收工且剩余窗口零付费"）。
- 第 0 步要先回答的微博旧疑点（§6）：**U10** 全窗走完**没有任何总结行**（八平台最差控制台）、**U11** 每窗页面预算
  只有 9 s（慢网整窗丢还打「可能无内容」）、**U12** timescope 窗每窗 ~10 条上限从不声明、**U19** weibo 评论 30 页硬预算。
  这四条正是"页面模型/预算没测过"的产物，先用探针证实/证伪再动代码。
- 验收画布：`data/workflows/测试：微博.json`（原样跑，H 组三格）。

### 常驻事项

- **`ml_train/` 是用户自己的东西**，任何 agent 不得碰（我曾误判移走过，已还原核对）。
- 捕获机制**不改 `_push_log`、不提 `LOG_KEEP`**（理由见 §8），批评者不得复议。
- agent 定义改了要 `/agents reload` 或新会话才生效；`max_turns` 这类错拼会被**静默忽略**。
- 任务板：#6（跨平台采不满根因）与 #7（全平台终验）仍挂起；#9=微博第 0 步；#10 已闭环（本文件 U30）。

### `code-auditor` 首轮（开跑前）：修了什么、欠了什么

审的是这批未提交的测试程序（harness + 知乎 31 例 + `real_paths` + README 那句）。**1 Blocker + 4 Major + 8 Minor**；
开跑前修掉的（每条都会花真机钱或产假判决）：

- **Blocker**：H2/H3 的 `with LiveRun(...)` 体缺 `run.wait()`（H1 有）→ 一开跑就在空流水上 `assert_l3` 失败，
  再被 `__exit__` 的 `abort_run` **把刚付钱的 4 组件爬取停掉**。已补 `wait()`（旗舰终验此前从未真跑过，纯静态才看得见）。
- **Major**：`COMMENT_EXITS` 从 `ZHIHU_LEGIT_EXITS` 继承 → 搜索节点的「没有更多了/热榜封顶」能给**同一
  workflow 里**评论节点的沉默背书（feed 画布是一连通组件，`_slice` 拿到的是共享流水）。改成
  `harness.SHARED_EXITS + comment.*` 四键。
- **Major**：`assert_l3` 对整段流水按 key 计 `wf.node_failed`/`run.nodeStopped` ≤1 —— 4 组件挂两个是两条**事实**，
  会被定罪成一条根本不存在的控制台缺陷。改成按 `{nid}` 槽去重（同一节点不得双打），画布级键仍 ≤1。
- **Major**：校验被拒的 run 在 `app.py` **从不建行**，而 `wait()` 直奔 `read_record()` → 报成「no record for run …」，
  把产品的拒绝说成记录丢了。`wait()` 现先看 `outcome == 'rejected'`，按 `wf.validation_error`/`run.rejected` 原文失败。
- **Minor**：审计产物按 `{case}.{mode}` 命名会**互相覆盖**（终验画布有两个 帖子 组件）→ 改 `{case}.{mode}.{node}`；
  `real_paths` 在 import 期构造 `CookieManager` 会 `os.makedirs` 悄悄建出 `data/cookies/`（守卫只按文件指纹，看不见）
  → 改惰性；§8 的轮询秒数与单测例数改成实测（2.0s / 80）。

**明知欠账（不开跑阻塞项，轮到再修）**：① `LiveRun.verdict()` 缺省整段流水，G1/G1b/G3/S1 正这么用——今天无害
是因为它们同时用 `_assert_both_delivered` 把**两张表**都钉到目标，行数是严格的那一半；等哪天真要评多组件的
沉默，再把缺省改成「单组件才许整段」。② A3 对全量 `ZHIHU_LIES` 扫「搜索没提它」，其中 `authorTabEmpty` 只有
作者路径会打 → 那半恒真（严而不准，无害）。③ 存储路径唯一答案只做了一半：`data/workflows/`、`scratchpad/`、
`conftest` 仍各算一次 `REPO_ROOT`，`conftest.py` 还自拼 `{platform}_cookies.json` 文件名。④ `abort_run` 的
600s 是**兜底停止**的预算，与用例爬取预算不同目的（下一步是「下一例白等 900s 时段」），故不并入单一预算。
- [ ] 知乎 H1-H3 终验
- [ ] 微博 → 抖音 → B站 → 小红书 → 微信（每平台同流程）
- [ ] VPN 阶段：X → YouTube（含为两者补建验收工作流文件）
- [ ] 全部门过 → 收尾提交
