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
| **微博 hot 的另外两句** | `crawl.weibo.hotRefused`（接口给了答复但不是榜单）算合法；`crawl.weibo.hotNoHost`（**新增，U38**）**不算**——它说的是这个浏览器还停在 `passport.weibo.com/visitor/visitor`，同源请求根本发不出去，站点从没被问过。运行必须红，并把**它停的那个帧**打出来。热搜 `needs_session=False` 的声明经真机+探针复核为**真**（跳完访客引导后无 cookie 也回 `ok=1`），所以"匿名"这一格测的是时机，不是权限 | 端点答复 vs 本机没走到门口 |
| comments | `comment.status.blocked` 具名、`comment.zhihuNoPanels`、`comment.commentsClosed`、`comment.dyNone/dyNoPanel`、`comment.xNoList` | 关闭评论/真无评论/拒绝 |
| **微博 posts/author 登记（2026-09-28 写矩阵时）** | posts：`crawl.weibo.no_result`（站点自己印「抱歉，未找到相关结果」，实测它**与 5 张不相干推荐卡同屏**，故它是唯一判据 U31）、`crawl.weibo.page_empty`（某页**真的一张卡都没有**——U36 修复后这句话才成立：旧代码把「整页都是台账里的旧行」也报成空页）、`crawl.weibo.authorNoPosts`（200 + 空 list 是对一个账号的事实）。author 另加四条**raise 型拒绝**：`authorRefused`（mymblog edge 403，per-session 节流）、`authorWall`、`authorMirror`、`authorEmpty`（uid 读不出→开浏览器之前就拒，绝不猜一个人）。**明确不算合法**：`crawl.weibo.walk_done`/`authorDone` 与它们的 `{reason}` 槽（`crawl.stopReason.end`/`no_new`/`no_cards`/`stuck`）——那是**代码对自己循环的总结**，「窗走完」既可能是供给干涸也可能是 pager 少读一页，白名单收它=把每条 posts 用例的 `!= SILENT_SHORT` 变成不可证伪（知乎那表只收「站点自己的标记」，同一纪律）；`crawl.stopReason.unreachable` 也不收（AGENTS：浏览器没取到页面**不是**站点的拒绝）；`crawl.weibo.target_reached` 照旧不收（自己给自己发满分） | 站点 plate / 账号事实 / 具名拒绝；总结行不免责 |
| **微博 comments 登记** | `comment.weiboShowFailed`（statuses/show 取不回，带 URL）、`comment.status.dead`（逐文摘要里那格的 DEAD）、`comment.weiboReplay`（游标在动而整页复读）、`comment.weiboShort`（游标耗尽且 `total_number` 更高——差额是楼中楼 U33）、`comment.weiboFetchDied`（**新增**：某一页取数失败即收尾，带页数/本次条数/站点标注/差额，U37）。**不收** `comment.commentsClosed` 与 `comment.status.blocked`：`crawl_weibo` 没有墙判定，只可能返回 `OK`/`DEAD`，收进来就是 §5 末尾警告的那种「打死在名单里的行」（下一位读者会以为评论被墙是有判定的） | 具名拒绝/复读/分母差额；死链与墙分开说 |
| 跨切 | `run.wallRetry`、`run.platformQueued`/`platformStaggered`/`serialForced`、`crawl.profile_wait`、`run.pagePending`+`net.*` | 排队/重试/页面未到达 |
| **抖音 posts/author/hot 登记（2026-09-28 写矩阵时）** | posts/author/hot 共用：`crawl.dy.noCards`（那一屏到底是墙/502/没加载完，页面自己写着）、**`crawl.dy.noMore`**（列表底部印着「暂时没有更多了」，并把这次翻了几屏、最后一屏几张卡一起报出来——U48：`最新发布`/`最多点赞` 在「IU」上就是 14 张，`综合排序` 同一关键词能长到 107，所以「排序后的列表短」是站点的供给而不是滚动的失败，但这句话必须**由页面自己说**才算；没有这句标记就一句不说、真机继续红）、`authorNoWorks`（主页自报 0 作品）、`authorNoCards`（网格什么都没挂）、`hotCapped`（榜单大小由站点决定，带 `{board}`）、`hotRefused`（接口答了但不是榜）、`hotWall`（进门就被验证码中间页挡）、**加 `crawl.dy.wall`**（走路中途遇到的墙：抖音的墙在**标题**里，`check_intercept()` 在这种页面上会说 `ok`，而 `_record` 那条通用登录墙句**根本不打印**——审核第 3 条实测出来，不加它 A2 遇墙必红）。author 另加 **`crawl.dy.authorEmpty`**（raise 型：作者框是自由文本，粘一个昵称谁也不指向，`sec_uid` 才是地址；开浏览器之前就拒，绝不猜一个人）。**明确不算合法**：`crawl.dy.finished`/`processed`/`round`/`target_reached`/`authorDone`（代码对自己循环的总结，自己给自己发满分）；四条**逐行**拒绝 `detailEmpty`/`detailNoIdentity`/`detailWalled`/`detailSwapped` 也不进名单——它们在一次走路里几乎必然出现（实测 8 行问 12 次导航、39 次里 15 次是图文页），收进来等于给任何欠采发通行证，A1/E2 改成**按行计数**核账。**`crawl.dy.sortUnknown` 也被排除，并记原因**：`sort` 是 select，off-list 的值在 `engine.workflow.validate` 就被 `engine.source_bad_option` 拒了、`app.py` 在建 record 之前就 return（真机 A4 量到的就是这条路径），爬虫那句只是直接调用时的纵深防御 → 收进闭集就是 §5 末尾警告的「打死在名单里的行」 | 站点的答复 / 输入的事实；总结行与逐行句不免责 |
| **抖音 comments 登记** | `comment.dyNone`（页面挂着、计数也写着，列表就是没展开）、`comment.dyNoPanel`（面板始终不出现，带 URL）、**`comment.dyGone`**（**新增**：站点把这条链接换成**另一条视频**，替身 id 一起报出来——U47，按 DEAD 处理，不再是「拦截」）、**`comment.dyShort`**（**新增**：面板停止长大而站点自报的数仍更高，`declared/rows/nested/gap` 四个数一起报，U43；**并带上是哪个收尾**——`{reason}` 由走路自己记下的是「滚动不再出新行」还是「用户停止了运行」，否则一次 停止 会被念成站点的欠额，URL 也在句子里，一行多链接的控制台才知道差额属于哪条视频）、`comment.status.dead`/`comment.status.blocked`（逐链接摘要那格）。**不收** `comment.commentsClosed`：抖音这条路径没有任何判定会打印它（那是 B 站/X/YouTube 的句子），收进来=教读者以为「抖音评论被关闭」是有判定的 | 具名拒绝/差额/失效；关闭评论在抖音无判定 |


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
| U9 | `crawlers/bilibili.py:149-172`（BL2/BL7，**已修 2026-09-29**） | `fetch_json→{}`→`code is None`→**零行日志丢行**，最干净的一条静默欠采：`if code==0 / elif code is not None` 两道闸把 `None`（非 JSON/WAF 体）与 `-404`（稿件不存在）双双夹在中间，一条请求既不出行也不出一字 | 产品修复：`search()` 内层现补 `crawl.bili.fetchEmpty`(warning) 与 `crawl.bili.goneVideo`(info)；快层 `tests/integration/test_bilibili_crawler.py::TestSearch` 两枚具名针 |
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

| U38 | `crawlers/weibo.py::hot` 的请求时机（**已修 2026-09-28，真机 C3 第一次露出来**） | **一次问错门的请求，被说成接口拒绝**。热搜声明 `needs_session=False`，C3 拿「空 cookie 目录 + 不用 Profile」去验，4 秒就红：`微博热搜接口没有给出榜单（返回 empty）`。探针（`backend/test_weibo_hot_anon.py` → `scratchpad/weibo_hot_anon.json`）量到真相：一台站点从没见过的设备，`weibo.com/` 先答 `passport.weibo.com/visitor/visitor`（标题「Sina Visitor System」），**0.69 s 后自己跳回** `weibo.com/newlogin`，从那儿问 `ajax/side/hotSearch` 回 `ok=1` 带整张榜——**一个 cookie 都不需要，声明是对的**；旧代码在跳回之前就发同源请求，浏览器自己拒（`TypeError: Failed to fetch`），于是把账记到了从没被问过的接口头上 | 产品修复：`_await_home_frame()`（0.5 s tick、上限取本平台自己的 `PAGE_WAIT*3`=9 s、每 tick 问 停止），回到 weibo.com 才发请求；等不到就抛 `crawl.weibo.hotNoHost`，**只说自己看见的到场帧**，不替接口下结论。快层两枚针：`FakeVisitorDriver` 脚本化到场帧（`get` 不许写 URL，否则这个 bug 在假件里无法表达）。**这条不是合法收尾**：它说的是本机的门，不是站点的内容 |

| U40 | `crawlers/comments_weibo.py::_one_row` 的 评论内容（**已修 2026-09-28，真机 D1/D2 抓到**） | **纯表情评论被剥成空行**：这类行的 `text` 是一串 `<img alt="[可怜]" src="…png"/>`，适配器只读 `text` 再 `_strip_tags` → 剥完是 `''`，而行照留（有 `评论ID`/作者/楼层/时间）。**表行数、汇总、预览三方都同意**，分析节点拿到的是一条空白——这是「漏采」里最难看见的那一半：没丢行，丢了内容。实测同一对象里就带着 `text_raw='[可怜][鼓掌][黑线]'`；把 21 张「剥完全空」的卡挑出来数：**真评论 17/17 都有非空 `text_raw`**（另 4 张是探针存的 DOM 记录，不是评论）。同平台帖子行从一开始就是先 `text_raw` 再剥（`WeiboCrawler._author_row`），评论适配器没抄这条规矩 | 产品修复（评论内容先读 `text_raw`）；快层针 `tests/unit/test_comments.py::…::test_an_emoji_only_comment_keeps_its_text`；真机判据 `_assert_comment_rows` 里那条「每行必须有内容」——它就是抓到这件事的断言，**不许放宽** |

| U41 | `crawlers/comments.py::crawl_weibo` 的差额归因（**已修 2026-09-28，真机 D5 抓到**） | **把用户填的上限说成站点的缺额**：一条报 3 条评论的微博，首页一次给满 3 条且游标同时归零 → 循环在 `not max_id` 处 break，`ended` 还是 `'cursor'`（永远走不到 `'limit'` 那格），而差额比较用的是**被上限截过的表**（2 行）→ 打出「站点写着 3 条，本表只有 2 条（差 1 条）—— 差额是楼中楼」。这句话是替站点说话，起因却是用户自己填了个小的数，正上方那条分支要防的就是它 | 产品修复：差额只对**游标收到的行数**（`len(rows)`）判，收到的 == 站点报的数就一句不说；快层针 `test_a_limit_crossed_on_the_last_page_does_not_blame_the_thread`。同一段的 `comment.weiboFetchDied` 也一并改成按收到的行数报，免得同一类错位搬进新句子里 |

| U42 | `crawlers/douyin.py::_detail_row` 的 作者 / 粉丝数 / 获赞数（**已修 2026-09-28，抖音第 0 步探针抓到**） | **整列作者空白，而且没人说**：三个字段全靠 `_author_from_related` 从 `[data-e2e="related-video"]` 那块面板的文字里切（`泫九粉丝167.0万获赞1157.5万`）。实测这一版详情页**不渲染那块节点**（探针把页面上所有 `[data-e2e]` 遍历了一遍，没有；`backend/test_dy_author.py` → `scratchpad/dy_author.json`）**——这句当天 12 点被自己的第二次探针推翻**：同一条视频页 `related-video` 与 `user-info` 都在，里面就是 `白水鉴心 |  | 粉丝4399获赞341.9万`（`backend/test_dy_dead_video.py` → `scratchpad/dy_dead_video.json`）。早上那次「没有」是**在页面还没注水完时读的**（同一 id 相隔几分钟两次读数完全不同，见 U44），所以「整列为空」是真的、原因不是改版搬家，而是**作者读数取错了范围**（全文档第一个 `sec_uid` 锚点，会抓到推荐栏的别人）。下面这行按审计意见改写，别再拿旧结论当真。，于是每行 `作者=''`、`粉丝数=0`、`获赞数=0`；而守卫写的是 `if not author and not publish` —— 发布时间在，守卫永远不响。**真机闸门 `test_live_douyin.py:47` 那句「至少一行要有作者」今天本来就是红的**（说明这一格自站点改版后没再跑过——测试腐烂的教科书样子）。作者其实就在页面上：`a[href="https://www.douyin.com/user/MS4w…"]` 的链接文字（`白水鉴心`、`IU'ㅅ'`）；粉丝/获赞则**页面根本不发布**（满页只有那两个词的导航标签，没有数） | 产品修复：作者改读那条锚点（JS 里排除导航的 `/user/self` 与带 query 的推荐位，取「有文字的裸 sec_uid 链接」）；粉丝/获赞**留空不再填 0**（与不放 播放数 同一条规矩：没有一个可数的数，就不许有一列看起来在数），旧版若渲染那块面板仍照旧填。快层针 `tests/integration/test_douyin_crawler.py::test_a_page_that_names_its_author_by_link_still_fills_the_column`；真机验证：同一条探针改后 `作者='白水鉴心' / 'IU'ㅅ'`、两列为 `''`。**另记**：一次搜索 8 行实际开了 12 个详情页（2 张 `没有渲染出数据` + 2 张 `只渲染出计数条`，两种都具名、都不算行）——行预算≈1.5 倍导航，抖音的 target 就是这个价 |

| U43 | `crawlers/comments.py::crawl_douyin` 的轮次上限（**已修 2026-09-28，抖音 D 组第 0 步探针抓到**） | **评论面板带着 40 轮预算，而它自己报 OK**：`for _round in range(40)` 决定了「一条 thread 有多大」。探针（`backend/test_dy_comment_denominator.py` → `scratchpad/dy_comment_denominator.json`）在用户自己粘的那条视频上量到：站点写着 **3388** 条评论，走满 40 轮停在 **406 行**（第 40 屏照常返回），状态 `ok`，一句「还差多少」都不说。这正是 AGENTS「没有哪条走路带轮次预算」那条红线在这里的形状：用户问「怎么采不满」，答案是一行代码里的常数 | 产品修复：`while True` + 只有三件事能让它收工（这一屏没有新行、滚动盒子不再长大、用户的 停止/评论条数）。同段补 `comment.dyShort`（`declared/rows/nested/gap` 四个数一起报）——**分母是站点自己写的数**，且按 `declared - Σ子回复数` 判（实测 406 行 + 1062 条子回复 ≠ 3388，所以差额确实还没采到，而不是「楼中楼不算」）。快层三枚针：`test_a_thread_is_walked_to_its_end_not_to_a_round_count`（45 屏必须 45 行；把 `range(40)` 放回去立刻红在 `40 != 45`）、`…_names_the_gap`、`test_an_ask_that_is_met_does_not_complain_about_the_thread` |

| U44 | `crawlers/douyin.py::_detail_row` 的行身份 + `_driver_facts` 的作者读数（**已修 2026-09-28，真机 A1 抓到**） | **空行被当有效数据，而且作者还是别人的**：A1 把 `7687166416143123826` 存成 `标题='' 正文='' 发布时间='' 四个计数=0`，控制台却念「已收录…当前有效数据: 7 条」。探针连打同一地址（`backend/test_dy_dead_video.py` → `scratchpad/dy_dead_video.json`）：稍后再访问同一 id 是**完整的一行**（`吻#邓恩熙…`、`2026-09-19 16:51`、作者 `白水鉴心`）——所以那次是**详情页还没注水完就被读**；而 `作者` 那格填进来的是**推荐栏里另一个人的名字**（`青小鲜三门青蟹 海鲜礼包`、上一次是另一家商铺），因为 U42 的读法是「全文档第一个裸 sec_uid 锚点」，页面头部还没挂载时先出现的是推荐位。两条错叠加：旧守卫 `if not author and not publish` 永远不响（author 有值），守卫的「身份」用错了列 | 产品修复：①身份=**文案或发布时间**，作者不算身份（`if not text and not publish` → 具名 `detailNoIdentity`）；②等待只认页面自己的 `发布时间`（旧写法把导航文字 `评论` 也算到场，正是它让读数的时机提前了）；③作者改在 `[data-e2e="user-info"]` 里读，读不到就留空，`related-video` 那块的开头仍是同一作者块（实测两次都一样）。快层三枚针：`test_a_name_is_not_identity_when_the_page_published_nothing`（把守卫换回旧写法立刻红）、`tests/integration/test_douyin_detail_dom.py` 两枚**真 Chrome + 本地页**的选择器范围针（头部必须赢过 DOM 里更早出现的推荐锚点；没有头部就一句不填）|

| U45 | 抖音结果列表里藏着的**图文页**（`/video/<id>` → `/note/<id>`）（**已定性 2026-09-28，真机 E2 抓到**） | 同一格「旅行攻略」两轮真机（每行在控制台与镜像里各出现一次，下面按**页数**计）：**09:56 那轮开 39 次详情页、21 次报「详情页没有渲染出数据」、只交 18 行**；改完具名句后的 **10:08 那轮同样 18 行、13 次改成报「验证码中间页」**——不是解析坏了：那些 id 打开后被站点重定向到 `/note/<id>`（图文帖），而这台设备访问 note 页拿到的标题就是 **「验证码中间页」**，整页没有 `[data-e2e]`（探针 `backend/test_dy_note_card.py` → `scratchpad/dy_note_card.json`，两次三访全是这个结果；定向复测 `backend/test_dy_dead_video.py`、`scratchpad/dy_wall_cause.out`：被拒的 6 个 id 慢速重开 **6/6 仍是 note + 墙**，同期成功的 6 个视频 id **6/6 正常**）。**顺带否掉了 2026-09-26 那条记录**：它说「图文卡没找到」，因为它只看卡片 `href` 的直方图（16/16 都是 `/video/`）——锚点确实是 `/video/`，是**服务端按 id 重定向**，不打开就看不见。这是「页面模型读错了不会报错，只会让所有账一起同意一张缺的表」的抖音版本 | 记账，不改读法：这类行**站点侧确实拿不到**（视频页照常），但话要说对——新增 `crawl.dy.detailWalled` 逐行报名「这一条被站点挡在验证码中间页（图文页）」，并且**不 latch `login_wall`**（一次会话级判定会把整个节点判成「COOKIE 可能过期」，而同一轮下一条视频爬得好好的，D2 那次的误责就是这类）。它是**逐行**句，因此既不进合法收尾也不进说谎名单，A1/E2 按行计数 |

| U46 | `crawlers/comments.py::crawl_douyin` 的 楼层 编号（**已修 2026-09-28，`code-auditor` 报出、探针证实**） | **楼层每滚一屏就从 1 重数**：`parse_douyin_comments` 在**它拿到的那一批**里 `enumerate(…, 1)`，而走路是「每一轮解析一次再 extend」→ 40 屏的 thread 存下 40 个「1 楼」。§3-B 那条「评论列集含楼层连续性」在抖音一直是破的，且三方（表、汇总、预览）自洽看不见 | 产品修复：先把元组收完（`collected`），走完再统一解析编号——**列表是一份文档，不是一叠书签**（AGENTS 同条）。快层两枚针：`test_the_floor_number_runs_across_the_panel_not_down_one_screen_at_a_time`、`test_a_thread_is_walked_to_its_end_not_to_a_round_count`（顺带断言 1..45）；真机 D1 把 ask 从 15 提到 **40**：一屏 ~16 条，15 行的问法永远走不出第一轮，那句断言就没有牙齿（审核第 17 条点名过这件事） |

| U47 | `crawlers/comments.py::crawl_douyin` 把**换页**读成**拦截**（**已修 2026-09-28，真机 D2 抓到**） | 粘一条不可能存在的视频 id：站点把它换成**另一条视频**（`/jingxuan?modal_id=…`，每次换的还不一样；实测某次还先印了一瞬「你要观看的视频不存在」再跳走）。面板自然挂不起来，旧读法报 BLOCKED 并念出「该视频计有 **1214** 条评论」——**那个数是替身视频的**；BLOCKED 再被节点判成「登录态疑似失效：COOKIE 可能过期」，而**同一次运行下一行刚从那篇真链接采到 8 条评论**。一句替站点说谎的话，附带把用户的好 cookie 定了罪 | 产品修复：面板挂不起来时先比 `current_url` 里的 id 与要的那个（地址是这三次测量里稳定的一半），不同即 `comment.dyGone`（报出替身 id）+ **DEAD**；`looks_blocked` 的判定与「无面板」的 `dyNoPanel`/`dyNone` 原样保留。快层两枚针对着假件补了 `redirects` 映射（不给这个能力，这条产品分支在假件里根本无法表达）：`test_a_video_the_site_swaps_for_another_one_is_dead_not_walled`（并断言替身没被当成自己的链接再访问一次）、`test_a_real_page_that_mounts_no_panel_is_still_the_blocked_shape`（反向对照，防新分支吞掉旧分支）；真机 D2 现在断言 `not run.cookieExpired` |

| U48 | 抖音「排序之后的列表到底有多长」被走成了「滚动没生效」（**已修 2026-09-28，真机 H1 抓到**） | **14 行对 50 行的缺口，没有任何一句解释它**：H1 那次六个组件里，`最新发布` 与 `最多点赞` 两条搜索都只交了 **14 行**（目标 50），而 `综合排序` 交满 50 行。两条不同排序给出**一模一样的 14** 不可能是巧合，所以这个数字是这次走路对页面的读法，而不是站点的供给——第一版判断因此指向「排序后的列表换了滚动盒子」。三条探针把这件事量清（`backend/test_dy_sorted_length.py`、`test_dy_sorted_scroller.py`、以及逐轮比 id 的 turnover 测量 → `scratchpad/dy_sorted_*.json`）：`综合排序` 连滚 8 轮 16→25→34→62→107 照常长大；两个排序视图**停在 14 张、八次滚动后连 id 都不换一个**，而且列表底部写着 **`暂时没有更多了`**——所以 14 就是这张榜给的东西，**错的是我们没把这句话读出来**。旧写法只把「这次滚动没让卡片变多」当成 `drained=True` 就收尾，控制台最后一句是 `搜索完成，共获取 14 条（目标 50 条，翻了 2 屏）`：说数字、不说原因，按 §5 那条「给自己发满分的总结行不算合法收尾」，这就是 SILENT_SHORT | 产品修复：`_harvest_pool` 在「滚动不再长大」的那一刻去读页面自己的收尾句（`LIST_END_MARKS=('暂时没有更多了','没有更多了')`，从可见正文里读，不认 class 名），读到才打 `crawl.dy.noMore`（带上这次走了几屏、最后一屏几张卡）；**没读到就一句不说**——那仍然归因到本机的读法，真机层该红。它因此是**合法收尾**（站点自己的标记，与知乎 `crawl.zhihu.no_more` 同族），也是这次真机能区分「站点给这么多」与「我们少读一页」的那句话。**同日 12:28 复测把话说回来一半**：同一关键词同一排序再跑，页面**这一次没印**那句话（`A6` 14/40 → SILENT_SHORT，`body_len≈800` 里 marker 不在），而 hook 住 `fetch`/`XHR` 之后**一个搜索请求都没抓到**（列表随文档一次性给到，滚动不再触发翻页），所以「14 就是这张榜给的东西」这句**当时写过头了**——正确说法是「本站点对本会话给到这么多，且它的收尾句不是每次都印」；用户随后自己复测判定**抖音搜索本身就是浅的**（换号也一样），故搜索线暂停，不再拿它的行数当采集缺陷追。快层两枚针互为对照：`test_a_short_sorted_list_is_reported_as_the_site_s_end_not_as_a_stalled_scroll` / `test_a_scroll_that_grows_nothing_without_the_marker_stays_unnamed`；真机新增 **A6**（`IU` + 最新发布、问 40）：实测 13 行 + `列表自己写了「暂时没有更多了」：翻了 2 屏，最后一屏 13 张…` → NAMED_SHORT/WARN。**另一件事顺带记下**：同一天用 `宠物` 跑 A6 时，结果页五分钟一张卡都没挂载，最后由 `crawl.dy.noCards` 具名收场（页面自报 `502 Bad Gateway`）——那条路径的判词本来就是对的，这里只记下它发生过 |


| U49 | 我在**今天的修复里**引入的两个新缺陷（`code-auditor` 二轮抓出，均已修） | ① **共享走路借用了搜索页的耐心等待**：`_harvest_pool` 的「空屏先等列表重挂」分支调了 `_wait_for_page()`，那是搜索路由的挂载等待（轮询搜索锚点、上限 `Config.PAGE_WAIT_TIMEOUT`=300 s），从作者网格走进去就是**在一张永远答不上来的页面上等五分钟**，而且等完还要用 `read_ids` 重读一遍——等等本身没有收益。② **换链接的守卫只在「面板没挂载」分支里**：若站点先挂好自己那条面板再把地址换走，旧位置就漏判，替身视频的整批评论会以用户粘的那个 URL 入库（与 `crawl.dy.detailSwapped` 同一条红线，注释里我自己写的原则被代码漏了一半） | ①改成只等**这条列表自己**（`feed.wait_for(lambda: len(read_ids()), 1, …SCROLL_WAIT)`）；快层针 `TestAuthorProfile::test_the_harvest_loop_waits_on_its_own_list_not_on_the_search_route`（把 `_wait_for_page` 换成 `pytest.fail`，走进去就红；并断言那次空读不占屏数）。②守卫**提到分支之前**（挂没挂都先比地址），并补**走完再比一次**（走路中途被换掉就整批丢弃 + `comment.dyGone`/DEAD）；快层两枚针 `test_a_substitution_is_refused_before_the_panel_is_walked`（断言一次滚动都没发生）与 `test_a_panel_that_moves_halfway_through_loses_its_rows`（假件新增 `moves_on_scroll`，没这个旋钮这条分支在假件里无法表达）。 |
| U50 | 去掉评论面板 40 轮上限后，走路变成 **O(n²)** 且没人说（同一轮审计抓出） | 每轮都重新 `find_elements` 并把**所有已挂载节点**逐条 `_safe_text` 读一遍（每次一个 JS 往返）。3388 条的 thread 就是 ~1M 次读数、按小时计——**修掉「采不满」的同时把「采得完」变成了跑不完**，而且慢下来时没有任何一句提示 | 只读**新增的尾巴**（面板是追加式的，实测 16→56）；但**追加不是可以从数量推出来的**：虚拟化列表可以「同样多、头一个变了」，所以哨兵用**头节点的文字**而不是计数，头一变就回到 0 重读。快层两枚针：`test_a_growing_panel_is_read_by_its_new_tail_not_from_the_top`（数 `_safe_text` 次数 < 挂载总量）、`test_a_recycled_panel_is_re_read_from_the_top`（同数量换头 → 新条仍要被读到）；把哨兵换回「按数量判断」立刻红（已实测：`'第8条内容'` 被跳过）。 |
| U51 | `crawlers/comments.py::crawl_douyin` 的差额句替站点说话（**已修 2026-09-28，同日二轮复查抓出**） | 让走路收工的四件事里，「你按了 停止」与「滚动不再出新行」是**两种相反的事实**，而 `comment.dyShort` 那句把后者写死在模板里（「面板滚到不再出新行即收尾」）——于是一次 停止 中断的走路被念成「站点就给了这么多」，正是 §5 拒的自证形状（同一件事在运行级已有对照：`run.finished.stopped` 报「1 个被停止」而不是「1 个失败」）。这句还漏了 `{url}`：调用一直传、模板里没有，一行多链接的控制台不知道差额属于哪条视频。修：走路自己记下出口（`no_new`/`target`/`stopped`/`stuck`），差额句按既有词表 `crawl.stopReason.*` 说出是哪一个，URL 回到句首。快层两枚针互为对照：`test_a_panel_that_ends_short_of_the_counters_number_names_the_gap`（`stuck`）、`test_a_walk_cut_short_by_the_stop_button_blames_the_stop_not_the_site`（`stopped`，并断言停止之后**一次都没再滚**） |
| U52 | `crawlers/comments_douyin.py::douyin_comment_fields` 按位置取正文（**已修 2026-09-28，同日二轮复查抓出**） | 正文写死 `lines[1]`，两件事随之而来：① 评论换行时第二行之后**整段丢掉**（这张表的目的就是「不漏采」），而正文里自成一行的纯数字会被下面 `line.isdigit()` 那条读成 点赞数——一个挂在看起来对的列名下的错数；② 作者名渲染为空而塌行时（本模块 docstring 自己承认的形状）每个字段整体前移一格，「1天前·北京」被写进 评论内容，楼层与行号照样好看。修：把面板自己的「时间·地区」那行当锚点——锚点之前全是正文（多行按换行拼接），点赞数只认锚点之后的裸数字；锚点之前没有正文就是没有正文，这行由调用方丢掉，**宁可少一行也不存一句时间戳**。快层 `test_a_wrapped_comment_keeps_every_line_and_its_own_numbers`、`test_a_timestamp_is_never_filed_as_the_comment_text`；退回即红实测：把 `head` 改回 `lines[1:2]` → 两枚同时红（`'1天前·北京' == ''`） |


| U53 | `crawlers/bilibili.py::author` 的分页假设（**已修 2026-09-29，B站第 0 步抓到**） | **投稿页把「换页」当成「滚动加载」**：第 0 步在生产同款托管 Profile 上量到——高产 UP 首屏 40 卡，**窗口滚动与元素滚动一个都不加**，而 `下一页` 一点整屏换成另外 40 张（交集 0、URL 不变）。旧 `author()` 走 `feed.walk_feed(scroll=window-scroll)` 且用默认**卡片数**哨兵，滚动不加 → `stuck` → 收工，于是**任何投稿过百的 UP 都被采到首屏就停，还替站点打 `已到列表末尾`**。与 §6 反复警告的「页面模型错了不会报错，只会让表/游标/总结三方同意一张缺的表」同形状 | 产品修复：`scroll=self._click_next_page`（点 `下一页`）+ `window=self._on_screen_key`（当前屏 BV 集合当哨兵，换页计数仍是 40，故不能用卡片数）；快层 `SpaceDriver` 重写为「只在点 `下一页` 脚本时换屏」，新增 `test_a_second_page_that_keeps_the_card_count_is_not_read_as_the_end`（把 `window=` 撤掉或 scroll 换回 `scroll_down` 当场红）；测量出处 `backend/test_bili_{step0,author_dom,author_pager}.py` → `scratchpad/bili_*.json`。**排行榜 `target>100` 无 cap 行（§7）同轮补 `crawl.bili.rankingCapped`** |


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
  - **`tests/live_acceptance.py`（H 组公版件，2026-09-28 抽出来）**：读用户自己的 `测试：<平台>.json`
    （只读）、按连接分量发现组件、`comment_ask`（评论 ask = 上限×链接数，0=每篇一条）、按**节点身份**找回
    各组件的 run 记录、逐组件判决 + 逐组件审计行、由组件结论派生用例索引行、导出 CSV 行数对账。
    平台特有部分留作回调传入（哪些行算「具名死亡」、评论格怎么按本站逐篇数字判、行形状）。
    **欠账（明确记着，不是漏了）**：知乎的 H 组仍用它自己那一份同名函数（当初落地时先写在其文件里）。
    搬动一份**已经真机跑过**的判决代码，代价是要重跑知乎 H1-H3（四组件真爬，且知乎 cookie 会老），
    所以这一步留到知乎下一次真机触碰时一起做；新平台一律 `import live_acceptance`，**不再抄第三份**。
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
- [x] **微博**：按 §11「一个平台的完整复查流程」八步执行完毕（2026-09-28，第 0-8 步全过；
      真机 **22 格全绿**：A1-A6 / B1-B2 / C1-C3 / D1-D5 / E1+E2 / G1-G2 / H1-H2，
      逐例控制台读进下面的「真机第一轮进度」；这一轮从真机与代码里新增并修掉 **U36-U41**）
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
      - [x] **第 6-8 步真机跑完**（国内网络，`CIXI_LIVE_USE_USER_PROFILE=1`，产物 `scratchpad/live_audit/<pass>/`；
            每例都读了完整控制台，不只看结论；H1/H2 见下面的验收记录）
      - [ ] **真机第一轮进度**（国内网络，`CIXI_LIVE_USE_USER_PROFILE=1`，产物 `scratchpad/live_audit/<pass>/`；
            每例都读了完整控制台，不只看结论）：
            * **B3 ✅**（`不是微博作者地址` 具名拒付，零导航零行）；**C1 ✅ FULL**（40 条、5 列、热度是精确整数）；
              **C2 ✅ NAMED_SHORT**（`hotCapped` 报出站点榜大小 **51**，表也正好 51 行——分母与表一致）。
            * **C3 第一轮 ❌ → 修好后 ✅**：红成 `hotRefused`，探针量清是 U38（访客引导未走完就在
              passport 帧发同源请求，被浏览器自己拒），修完这一轮匿名取到 10 条真榜单（0 cookie）。
            * **A1 ✅ FULL 6 秒**：单链接搜索，`本页共发现 10 个卡片` → `获取 10 条` →
              收尾行 `10 条（目标 10，窗口走到第 1/1 个，原因：达到目标条数）`，节点完成/运行结束齐全。
              注意：这一格**没测到翻页**（首屏就满 10），翻页由 A5 承担——记下来免得以后误以为 A1 覆盖它。
            * **A3 ✅**：`窗口走到第 2/24 个，原因：达到目标条数`，付费窗数与控制台说的 2 个**逐行对齐**
              （D9「剩余窗口零付费」第一次真机成立）；第 2 窗 `本页共发现 8 个卡片` 后靠累计满 10 收工。
            * **A4 ✅ NAMED_SHORT（36 秒 / 178 行）**：24 个空窗**一个都没存**（0 行），每窗四句
              （URL / 访问 / 等待 / 「该时间段无搜索结果，跳过」）逐窗对齐，收尾
              `0 条（目标 10，窗口走到第 24/24 个，原因：已到列表末尾）`——U31 的「plate 优先」在真机成立，
              那 5 张同构推荐卡没有污染结果表。
            * **A6 ✅ FULL**：目标 25 恰好在**第一个小时窗**内取满（第 1 页 10 张、第 2 页 9 张、第 3 页 6 张即停），
              收尾 `25 条（目标 25，窗口走到第 1/24 个，原因：达到目标条数）`，且 `stated target == 25`——
              「采得够」与「不多采」同一张表里同时被钉住；顺带证明站点这一小时有 50 页供给。
            * **D1-D4 ✅（一轮修断言、一轮修产品之后）**：共享那一次搜索给 12 行，评论数都是个位数——
              于是 D 组的 ask 一律**由选中链接自己的 评论数 算出来**（`sum(min(limit, 评论数))`），
              不再写死 5×N 或「≥12 才算数」；写死的那两版各红了一次，规矩记进 AGENTS。
              D2（连线喂 4 条链接）逐链接核对归属，D4 变成双向断言（短了必须报差、齐了必须闭嘴）。
            * **D5 抓到 U41**：3 条评论的微博、上限填 2，控制台打出「站点写着 3 条…差额是楼中楼」——
              首页一次给满 3 条**同时**游标归零，`ended` 停在 'cursor'，而差额拿**截断后的表**比，
              于是把用户填的数说成站点的缺额。已修（只对游标收到的行数判）并钉快层针。
            * **D1 另抓到 U40**：只发表情符号的评论被 `_strip_tags` 剥成**空白行**（行还在、id/作者/时间都在，
              内容没了）；同一对象里就有 `text_raw='[可怜][鼓掌]'`（21 张空文本卡里真评论 17/17 都有），
              同平台帖子行一直先读 `text_raw`，评论适配器没抄。已修 + 快层针 + 真机断言「每行必须有内容」保留不放。
            * **A2 ✅ FULL（无头 6 秒，10/10）**：这一轮无头没有撞墙，`page_timeout` 一类假行也没出现；
              **A5 ✅ FULL**：`最大页码: 50 → 检测到总页数: 50 → 正在爬取第 2/50 页`，首屏 10 张、第 2 页 9 张，
              14 条只能来自翻页——U12 那 40% 的静默丢失在真机上确认已经关上。
            * **B1 ✅ FULL 8 条 / B2 ✅ FULL 40 条**（mymblog 这一轮答的是 200 而不是 edge 403）：
              40 条必须跨页，游标 `page>1` 与 `微博ID` 全不重复两条都过；作者行的 用户链接 全为所请求 uid，
              图片链接 保持空（不拿 CDN 规律造 URL）。
            * **H1 ✅ / H2 ✅（他自己的 `data/workflows/测试：微博.json`，四组件）**：按 D9 只把 6432 小时窗
              换成最近两天，其余原样。逐组件行：posts 50/50、author 50/50、hot 50/50、comments 1/90
              （`comment_limit:0` 无行数预算，按「每篇一条」判，表里真给 90 条），用例行由四格派生
              （`4 components, 240 rows` FULL）。H1 还钉住 D9 的正断言：收尾行说 `窗口走到第 3/24 个`，
              而 `访问搜索链接` 也是 3 条——**剩余窗口零付费**；H2（串行）另断每组件各开自己那条记录、
              名字就是它的 label、`wf_count==1`、状态不是 completed 时它自己那段控制台必须点名理由。
              L2 三一致在这里逐组件走了一遍（导出 CSV 行数 == 库内行数），并且第一次跑到「按标签找文件」
              会被逐篇导出文件骗到：并行记录名是四个 label 用 ' + ' 串的，宽松 substring 匹配于是把
              评论文件当成了文章文件——改成匹配节点写下的文件名前缀，并顺手把 §3-C 的
              「per_article_file 文件数==文章数」也钉上。
            * **H3 明确不做**（写在文件末尾，理由是可替他省四遍真爬）：知乎那一格测「浏览器池收窄到一条」，
              而微博 `serial_only` 本来就一条，G1/G2 已经测过——同样的钱买不到新的判据。
            * 知乎的 H 组仍用它自己那份同名函数：搬运已经真机跑过的判决代码，代价是要再跑一次知乎四组件
              真爬，所以 §8 记成明确欠账，知乎下次真机触碰时一并折叠；**新平台一律 `import live_acceptance`**。
- [ ] **抖音（2026-09-28，第 1–7 步过、第 8 步未过）** —— 逐例读数与判据同微博；**H1 两次都红**，所以这一格没勾：

            * **第 0 步（先读页面）**：四枚探针 —— `test_dy_page_model.py`（列表挂载比注释写的更快、
              窗口就是分页器）、`test_dy_funnel.py`（8 行付 12 次导航，两种拒绝都具名）、
              `test_dy_author.py` + `test_dy_dead_video.py`（作者块的位置与「没注水完就读」的空行）、
              `test_dy_comment_denominator.py`（面板 406 行 / 站点写 3388 / Σ子回复 1062）、
              `test_dy_note_card.py`（`/video/` 锚点里藏着 `/note/`，本机一律验证码中间页）。
              结论都写进了 `docs/crawler_notes.md` 抖音一节，并**否掉**了 2026-09-26 那条「图文卡没找到」。
            * **真机 17 格**（`tests/live_site/test_live_douyin_workflow.py`）：**A1-A6、B1-B2、C1-C2、D1-D2、
              E1/E2、G1 共 14 格跑过并逐行读过控制台**；**A7/A8 还没跑过真机**（补写于当日审计之后；A7 的
              三条排序性质今天改成**两侧都有话**：行数不足 3 时必须由站点自己的收尾句免责，
              否则红——旧写法 `or len(likes) < 3` 会让只回来 2 行的 最新发布 空过。这两格不再补跑，因为它们的
              搜索腿属于用户已判定暂停的抖音搜索线，所以这里只记「写好了、没跑过」，不记成通过），
              H1 跑过三轮、三轮都没过（见下）。每格判据以其台账行为准：
              A1 ✅ FULL 10/10（11:42 那一轮；早前一轮 12 开 1 拒，U44 修复前是 10 行里混 1 张空行）；
              A2 ✅ FULL（伪装无头 10 行，`crawl.dy.wall` 因此进了白名单：抖音的墙在标题里，通用那句不打印）；
              A3 ✅ FULL（`已选 最新发布（列表是否换血：True)`，随后 `第 1 屏：0 张`→`第 2 屏：28 张`，
              正是刚点完在换血的那一瞬；审核第 7 条要求这句只核**菜单**那三条 liar）；
              A4 ✅ **REFUSED**（off-list 的 `sort` 由 `engine.source_bad_option` 点名「节点 采集 #node-1：
              「排序方式」没有「最热」这个选项」，2 行控制台、2 秒、**没有 record**、没有 `crawl.dy.start`
              ——所以 `crawl.dy.sortUnknown` 是打不出来的，白名单里不收它并记了原因）；
              A5 ✅ FULL（问 5 存 5，`翻了 1 屏`）；
              B1 ✅ FULL 12/12（`主页自报 145 条`；审核第 8 条：先断 `works >= asked` 再断 FULL，
              供给侧哪天变了这格会说出是供给没了，而不是判走路有罪）；
              B2 ✅ NAMED_SHORT（`[抖音作者] 没有给出作者…：泫九`，4 秒，浏览器根本没指过去）；
              C1 ✅ FULL 40 条、C2 ✅ NAMED_SHORT `榜单本次只有 51 条`（`{board}=51` == 表行数）；
              **C 组第一次跑是红的，报的是 `hotWall`**：用户自己的 profile 在 `/hot` 上被答验证码中间页，
              这正是本文件 §7 记了两天的**反向语义**那一格——热榜要用一次性浏览器（`use_profile=False`），
              矩阵与 `docs/crawler_notes.md` 的说法被真机复核为**仍然成立**，用例因此显式要求该形状；
              D1 ✅ FULL 40 条（问 15 时那格没有牙：一屏 ~16 条，永远走不出第一轮，故提到 40；
              **楼层现在实测 1..40 连续**，且封顶的问法**不该**抱怨差额）；
              D2 ✅ NAMED_SHORT/WARN（`comment.dyGone` + `comment.status.dead`，替身 id 印在句子里，
              **`run.cookieExpired` 断言为不存在** —— 修之前这里打的是「登录态疑似失效」，
              而同一次运行下一行刚采到 8 条）；
              E1 ✅ NAMED_SHORT（2 行即停，`1 个被停止` 而不是 `1 个失败`）+ E2 ✅ FULL（续跑 20/20：
              按行核账 `filed + refused`，`run.dedupe_skipped` 必须不出现——去重台账会把重付的导航
              悄悄抹平成「行不重复」，所以行不重复**不是**省钱的证据，这一格改成了它原本该有的形状）；
              G1 ✅（两组件并行，`lane_switches(queue=False, stagger=0)` 显式改全局开关再还原；
              审核第 6 条：默认 `same_platform_queue=True` 时这格测的是排队而不是重叠）。
            * **修掉的产品缺陷 9 项**（§6 的 U43–U52：评论面板 40 轮预算 / 空行冒充有效数据 + 作者张冠李戴 /
              图文页被说成「没渲染数据」 / 楼层每屏重数 / 死链接被说成登录墙 / 我的修复自己引入的两个新坑
              U49——走路借了搜索页的 300 秒等待、替换检查挂在面板分支之后 / U50——去掉轮次上限把走路做成
              O(n²) / U51——差额句把「用户按了停止」说成站点欠额、URL 还在调用里传着却没进模板 /
              U52——评论拆行器按位置取正文，换行评论丢掉第二行、正文里的纯数字被读成点赞数、塌掉的作者行
              把「1天前·北京」当成评论），每枚都有快层针并做过**「退回即红」**实测：把 `range(40)` 放回去 →
              `40 != 45` 红；把旧守卫放回去 → 空行被存下来红；把 `_wait_for_page` 放回去 → 作者腿红在等待上；
              把 `head` 放回 `lines[1:2]` → U52 那两枚同时红。
              作者读数那处的范围只能在浏览器里证，故新增设备层 `tests/integration/test_douyin_detail_dom.py`
              （真 Chrome + 本地页，推荐锚点故意排在作者块之前）。
            * **共享件按审核意见收口**：`harness.lane_switches()`（微博文件里那份搬进 harness，两边共用）、
              `RunDriver.wait_refused()`（为「运行前就被校验拒绝、根本不建 record」这类格子准备的路径——
              它连 `run.started` 都不该有，所以 `assert_l3` 那四句在这里不是欠账而是无关）。
              `comment.dyShort` / `comment.dyGone` / `crawl.dy.detailWalled` 三个新键双语齐。
            * **H 组（用户画布 `data/workflows/测试：抖音.json`）：三轮全红，没收口**。逐轮读控制台后的账：
              ① 10:31 那轮根本没跑起来（`records_by_node` 找不到组件行，原因是我先把「按标签找记录」写错了）；
              ② 11:27 那轮六格跑完但三格 SILENT：作者 2/50 的真相是 `invalid session id`——**我在验收跑没结束时
              另开了一个探针进程，用的是同一个 profile 目录，Chrome 一个目录只容一个进程，是我抢死了它**；
              评论 27/50 是同一件事的连带（浏览器死了，站点那 3388 的计数也读不到）；综合排序 46/50 则抓到
              一个真 bug（见下 U49）；③ 12:09 按用户要求**全串行**复跑，车道开 `same_platform_queue=True`、
              全程只有它一个浏览器：**作者 50/50、评论 50/50、综合排序 50/50 三格补满**（用户的并行判断
              在这一点上成立），两个排序腿却因为我自己写的 `self.nap`（爬虫上没有这个方法）直接崩成 0 行；
              修好后单独复测排序腿 = 14/40 且这次页面没印收尾句 → 仍然红（搜索线按用户判定暂停）。
              **所以第 8 步没过的原因有三类，已各自归因**：并发抢 profile（操作纪律）、`nap` 崩溃（已修+已针）、
              抖音搜索供给浅（用户判定，不追）。
- [ ] **B站（2026-09-29 第 0 步过，产品修复已落地，运行级矩阵与真机未跑）** —— 三条一次性探针
      （`test_bili_step0.py` / `test_bili_author_dom.py` / `test_bili_author_pager.py` → `scratchpad/bili_*.json`）
      在生产同款托管 Profile 上重读页面，结论进 `docs/crawler_notes.md` B站节，判决登记为 §6 **U9（已修）/ U53**：
      * **搜索契约复核为真**（`page=1` 0 卡、7 屏 211 唯一、非互斥靠 `seen`、`cm.bilibili.com` 广告卡被
        `CARDS_JS` 正确排除——不是漏采）；20 张卡 `view` 全 `code=0`，**U9 本轮未触发但确为潜伏**，已补
        `crawl.bili.fetchEmpty` / `crawl.bili.goneVideo` 把静默丢行变具名。
      * **抓到一处静默漏采 U53**：投稿页靠 **`下一页` 换页**（整屏替换、交集 0、URL 不变），窗口/元素滚动一个不加；
        旧 `author()` 按滚动+卡片数 → 首屏就停还谎报 `已到列表末尾`。修：点 `下一页` + BV 集合当哨兵；
        `SpaceDriver` 重写为换屏模型 + `test_a_second_page_that_keeps_the_card_count_is_not_read_as_the_end`（退回即红）。
      * **排行榜 `target>100` 补 `crawl.bili.rankingCapped`**（§7「无 cap 行=修复项」）。
      * 闸门：快层 **4696 passed / 0 skipped**、设备层 `-m integration` **131 passed / 0 skipped**、ruff 两项干净。
      * **未做（需你与浏览器在场）**：`tests/live_site/test_live_bilibili_workflow.py` 运行级矩阵（抄知乎 §4 模板）
        + §10 真机八步 + H 组用户画布 `测试：哔哩哔哩.json` 终验。
- [ ] 小红书 → 微信（同一套八步）
- [ ] VPN 阶段：X → YouTube（先测反向用例：不可达必须报 `unreachable`，不许假空）
- [ ] 全平台门过 → §6 剩余嫌疑（U1 通用 under-target、U2 walk 计数器从不打印等）收口提交

### 交接状态（2026-09-28 晚，**Cookie 多账号 / 微信 / i18n / 云端部署**；抖音第 8 步仍未收口）

**工作树干净**，闸门：**快层 4552 passed / 261 deselected、设备层 129 passed（exit 0 复核过）、
`ruff check` + `format --check` 干净**。今天这七笔（`git log` 可查，未 push）：

- `05ee245` 问题修复：抖音采集与评论九处静默欠采/误责（每枚针做过「退回即红」）
- `a7475f8` 功能更新：抖音运行级真机矩阵 17 格 + 验收共享件（`lane_switches` / `wait_refused` / `cursor_of` / `component_verdict`）
- `d35921d` 问题修复：**微信根本不让爬**的真凶是 `execute()` 里第二段弱闸门——它读 `/api/cookies/status`
  的 `cookies[platform]`，而那张表按平台只对**默认账号**求值且不含 wechat（不在 `CookieManager.PLATFORMS`），
  于是「选了账号仍说没 Cookie」与「微信永远起不动」同源；该段整删，矩阵改 `wechat/posts needs_session=False`
- `0639298` 问题修复：`dialog.cookieDelete` 模板有**两处** `{platform}` 而 `.replace` 只填第一处（屏幕上露原文，
  且贴的是裸键）→ `I18n.t(key, vars)` 全量填 + 新增 **JS 守护** `tests/unit/test_frontend_i18n_js.py`
  （占位符出现次数必须由调用点覆盖、`{platform}` 不许填裸键、zh/en 占位符计数须相等）；守护顺手抓出两处没被报告的：
  `settings.liveExportHint` 的 `{node}` 从未填过、`dialog.serialWarn` 英文重复占位符。同笔删掉
  「把 Cookie 更新进 Profile」按钮 + `/api/cookies/refresh-profile` + 四句拒绝文案，保存即种进 Profile
- `019a274` 功能更新：多账号后端——状态按 `(platform, account)` 回答、候选与校验按**创建顺序**
  （`accounts_in_order`，空白只在默认文件真存在时出现）、留空第二次保存自动 `default2`（显示 **默认账号2**）、
  保存的日志/回复报出是哪个账号
- `3d19ab7` 功能更新：保存时该账号**还没有 Profile 就当场建好并种进去**（没启用 profile 时不买浏览器也不谎报；
  被占用则明说，靠 `needs_refresh` 下次抓取自动带上）；`has_session_to_test` 改公开名
- `828b838` 功能更新：云端旗标 `CRAWLER_CLOUD=1` / `python app.py cloud`（`--cloud` 同），`/api/config` 回 `cloud_mode`

**明确没做/主动回退的（下一次从这里接）**：
1. 任务 **#28**：「节点选的账号没有 Cookie → 按名字拒绝执行」代码与双语键已写好，但跑出 84 格红后**在提交前
   回退**。真因是测试夹具顺序，不是规则：新增的 `seeded_cookies`（tests/conftest.py）只依赖 `app_module`，
   `client` 夹具随后重建 tmp 数据根，种下的 Cookie 被换掉 → 表现为"运行根本没起来"（`get_run` 返回 None、
   `logs == []`、`total_nodes == 0`）。修法：让 `seeded_cookies` 依赖 `data_root`（或 `client`）再写文件，
   写完自证一次 `exists()`；只对 9 个真起爬取的模块 `usefixtures`，**不要全局 autouse**
   （`test_cookie_preflight` / `test_config_api` 要靠"没有 Cookie"说话）。
2. 任务 **#25/#26/#27**：云端隐藏 Ollama 与「无头」设置项（隐藏后一律无头跑）、隐私审查 + 首次隐私声明弹窗、
   **pristine Profile 模板**。这里我先前写了一条错误的告诫（"知乎评论区/内容页拒绝无头，云端要按名字拒绝"）——
   那是从 `comments.py` 一段**过期 docstring** 读来的：`NEVER_HEADLESS` 早在 #148 就随"无头带桌面指纹"一起删了
   （README 记着实测：知乎评论区伪装无头 5/5 == 可见窗口 5/5），代码里除了那句注释再无此物。该注释今天已改正，
   平台该无头就无头、该开窗口就开窗口，**云端不需要为任何模式加拒绝**。教训同下一条：结论要从代码取，
   文档也会过期。
3. **不复制用户日常 Chrome 目录**做模板：`data/` 是 gitignore 而仓库有 remote，手工剥离 `Login Data`/`History`/
   `Local Storage`/`Preferences` 极易漏；且 `browser_profiles.py` 记着实测（目录独占、Cookie 应用绑定加密、
   Chrome 136 起默认禁远程调试）。云端模板由**程序自启一次空白 Chrome** 生成，天生不含登录。
4. 抖音：第 0-7 步已逐例读控制台收口；**第 8 步 H1 不能按原样收口**（两条排序腿在用户判定暂停的搜索线上），
   A7/A8 是"写好了、没跑过"，§11 记的就是这个状态。

**给下一段的提醒（本轮真实发生过）**：一次子代理审计给出的多条 Python 结论（`reached()`/`logged()`、
`comment.gapFound`、重名测试、"已提交的 deploy 外壳"）在仓库里**并不存在**，我也曾把没发生的提交当成已完成汇报过。
凡是准备据此动手的结论，先自己读一遍文件/`git log`；闸门数字要带退出码取，别凭记忆。


#### 上一阶段的交接（2026-09-28 早，**知乎已收口、微博第 0 步已读完页面**）

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
