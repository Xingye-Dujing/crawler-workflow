# 全平台真机验收（live test plan）

本文只讲**要测什么、怎么判、怎么跑、修谁**：红线在 `AGENTS.md`，实测证据在 `docs/crawler_notes.md`。
按符号名找代码，不按行号。采集分派入口是 `backend/nodes/executors/source.py::execute_source_node`，
评论分派是 `backend/nodes/executors/comment.py::execute_comment_node`；评论走路从
`crawlers/commenting/session.py` 经 `crawlers/commenting/walks.py` 注册表分派到各平台。

## 前置与同意

1. 端口 5000 没有自己起着的服务器（`netstat -ano | findstr :5000`）；有则先问用户，**绝不杀**。
2. **先问用户在哪个网络**：国内平台关 VPN 跑 `live_cn`，X / YouTube 开 VPN 跑 `live_os`；一次只跑当前这一侧。
3. `tasklist chromedriver.exe` 只有一个真机进程（同一 profile 一浏览器锁，并存即假红）。
4. Cookie 新鲜；平台登录态属于用户，**绝不无人值守跑** `live_quick` / `live_site`——花的是用户账号。
   `CIXI_LIVE_USE_USER_PROFILE=1`（用他本人的 profile）只在他明确同意时使用。
5. 单例必须重写 `-m` 过滤，否则被默认过滤器静默 deselected。

## 命令

`.venv/Scripts/` 是 Windows 的路径；Linux/macOS 用 `.venv/bin/`。前置检查里的 `netstat`/`tasklist` 同样是 Windows 写法。

```bash
# 知乎全矩阵（真用户登录态，约 1.5–2.5h，建议按组分批）
CIXI_LIVE_USE_USER_PROFILE=1 .venv/Scripts/python.exe -m pytest -q \
  -m "live_site and live_cn" tests/live_site/test_live_zhihu_workflow.py -rA

# 单例
CIXI_LIVE_USE_USER_PROFILE=1 .venv/Scripts/python.exe -m pytest -q \
  "tests/live_site/test_live_zhihu_workflow.py::test_a3_forty_rows_prove_the_scroll_loop_and_nothing_else" \
  -m "live_site and live_cn"

# 海外阶段（先问用户在 VPN 侧）
CIXI_LIVE_USE_USER_PROFILE=1 .venv/Scripts/python.exe -m pytest -q -m "live_site and live_os" -k "x or youtube" -rA
```

- `CRAWLER_REQUIRE_BROWSER=1` / `CRAWLER_REQUIRE_OLLAMA=1` / `CRAWLER_REQUIRE_NODE=1`：缺浏览器/Ollama/Node 时默认跳过，
  会让一档绿得像没跑过；设 1 把跳过变失败。
- `CRAWLER_DATA_ROOT`：给测试进程自己的 `data/` 与 `logs/`；不带它时不要同时开第二个服务器。
- 产物只写 `scratchpad/live_audit/`：`<case>.console.txt` 与 `verdicts.csv`
  （case,platform,mode,headless,use_profile,target,rows,verdict,reasons,wall_flags,cookie_expired,seconds）。
  **先读这两样，再读 pytest 结论。**
- 捕获用 `tests/live_run_harness.py::ConsoleRecorder`：2.0s 轮询 `GET /api/workflow/status`，用 `log_total` + 200 行尾窗
  做增量折叠，自证 `recorder.complete()`。**不改 `_push_log`、不提 `LOG_KEEP`**——产品读的就是浏览器读的那扇窗。
  共享件：`tests/live_acceptance.py`（H 组公版判决与 CSV）、`tests/live_run_driver.py`、`tests/real_paths.py`
  （真实 cookie 目录的唯一答案）。

## 三层判据

- **L1 状态**：run 必须 `completed`；cookie 死亡只许走设计路径（node `partial` + run `failed` + `继续` 横幅 + `run.cookieExpired`）。
- **L2 数量**：`FULL`（rows≥target）绿；`NAMED_SHORT`（控制台打出闭集具名行）看平台策略；`SILENT_SHORT` 一律红并归因。
- **L3 过程**：该有的行都在（`run.started→executing_node→结论行→node_completed→run.finished`），没有 `{placeholder}`、
  没有一句话双打、没有 Traceback、没有虚报行；行数/目标/原因与库内 `node_runs.row_count`、`cursor_json` 互证。

**合法收尾是闭集**：`Crawler.end_reason` 只认 `LICENSED_ENDS = {'site_end','capped','empty'}`（`crawlers/core/crawler.py`），
即站点自己说了才算；`UNDER_TARGET` 是被定罪的短收；`None`（未迁移 handler）维持宽松。
`Crawler.note_end` 拒绝把“翻了几轮/已到末尾”这类循环自述登记成许可。合法具名行包括各模式 `crawl.*.target_reached`、
`crawl.zhihu.no_more`、`run.dedupe_skipped`/`run.dedupe_all_skipped`、`run.nodeStopped`、`run.cookieExpired`、
`crawl.riskBlocked`/`crawl.loginWall`、榜单 `crawl.*.hotCapped`/`crawl.bili.rankingCapped`、评论 `comment.status.blocked`/
`comment.zhihuNoPanels`/`comment.commentsClosed`/`comment.dyNone`/`comment.dyNoPanel`/`comment.xNoList`、平台具名短收
`comment.weiboShort`/`comment.biliShort`/`comment.dyShort`/`comment.xhsShort`、墙的别名 `crawl.bili.blocked`/`crawl.dy.wall`、
跨切 `run.wallRetry`/`run.platformQueued`/`platformStaggered`/`serialForced`/`crawl.profile_wait`/`run.pagePending`。
明确**不算**合法：`crawl.*.finished`/`processed`/`round`/`authorDone`/`walk_done`/`crawl.stopReason.end`/`no_new`/`no_cards`/
`stuck`/`unreachable`、`crawl.dy.sortUnknown`、`crawl.weibo.hotNoHost`。一条行能否被看到取决于开关：
`run.serialForced` 只在 `same_platform_queue=False` 时打，排队开着时打 `run.platformQueued`。

**通用 under-target 判决**在 `execute_source_node` 收尾三段：墙短 → `run.cookieExpired`（保行、run failed、出 `继续`）；
风控短 → `run.riskControlled`；无墙无风控且 `end_reason==UNDER_TARGET` → `run.underTargetShort`（带 have/want）。
每平台仍需一个正向“确实没采完”信号才上判，未迁移 handler 传 `None` 维持宽松。

**续跑 / 游标 / 去重**：游标只记位置（`scanned`/`done`/`url_index`/`keyword`），掺入 id 或链接列表即红；
source 与 comment 都用 `row_sink` 账本按 `item_key` 去重，重跑命中不落库并打 `run.dedupe_skipped(n)`（全空补
`run.dedupe_all_skipped`，续跑不打、墙不打）。针：`tests/api/test_source_dispatch_matrix.py::test_a_repeated_comment_run_names_the_ledger_skip`。
两次 POST 永远排队（一 run 一名额）；source + comment 同平台可真并发。

**重试与拒绝**：`live_site` 一轮只当爬虫自己报了 `login_wall` 才重试一次，断言必须**点名**墙/风控；无名空表保持红。
一切“选数据、选成本、选名字”的入参按名拒绝、绝不猜；`raise` 不返回 `[]`。任何 live 数字算自站点，绝不预先选死。

**会话并发**：同一 profile 一浏览器锁（`sessions/profiles.py::acquire_profile` + `runtime/gate.py::hold`）；
`runtime/gate.py::reset()` 在 `live_site` 下不自愈（`tests/conftest.py` 只在非 live_site 用例复位平台闸），
排队冷却跨用例真实存在，排期要按它算。真 profile 与 cookie 一一对应，`sessions/profiles.py::needs_refresh`
决定是否带登录态重取；断言文案走 `i18n.t()`。

## 当前矩阵

| 平台 | 网络 | 覆盖 | 判定 |
|---|---|---|---|
| 知乎 | cn | 搜索/作者/榜单/评论/停止→继续/并行/用户画布 | 全绿 |
| 微博 | cn | 时间窗（serial_only）/热搜/作者/评论 | 全绿 |
| 抖音 | cn | 作者/热榜/评论（关键词搜索模式已移除） | 三条腿已收口；A7/A8 未跑 |
| B站 | cn | posts/author/hot/评论 | 主腿绿；评论腿 NAMED_SHORT |
| 微信 | cn | 正文型，`needs_session=False` | 全绿 |
| 小红书 | cn | 搜索 posts / 评论 | 旗舰绿；全矩阵待有人盯的窗口 |
| 红果短剧 | cn | 四个榜单（匿名）/评论（`tests/live_site/test_live_hongguo_comments.py`） | 榜单绿；评论需播放器 + mitmdump + 用户在场 |
| CNKI | cn | 两页选择 + 一次导出（必须可见窗口） | 无 cookie 则跳过 |
| X | os | 搜索/作者/评论/画布 | **未测**；先重新登录，先测反向 `unreachable` |
| YouTube | os | 搜索/作者/评论/画布 | 运行级全绿 |
| instagram | — | 不爬：校验 + `run.notCrawlable`，不掏浏览器 | 快层已钉 |

## 每平台复查流程（不许跳步）

1. **先读页面**：一次性探针 `backend/test_<平台>_<物件>.py`（产物进 `scratchpad/`，结论进 `docs/crawler_notes.md`），
   问清四件事：列表靠什么分页、有没有藏在展开器后面的嵌套内容、哪个容器真装着行、页面显示哪些列。
   页面模型错了不会报错，只会让控制台、汇总、库内行数、导出预览一起同意一张缺的表。
2. 判据必须带**站点自己印出来的分母**；谎言行永不入白名单。
3. 写运行级矩阵（A 供给×目标 / B 作者 / C 榜单 / D 评论 / E 停止→继续 / F 预检 / G 并行与排队 / H 用户画布 / S 设置轴），
   标记 `[live_site, live_cn|live_os, enable_socket, serial]`，零 `pytest.skip`；多组件按组件切片评分，用例中途死靠
   `harness.abort_run` 兜住。
4. 快层同步：每条新判据配假驱动针，并当场验一次“退回即红”。
5. 只读审：`@code-auditor` 审完修 Blocker/Major，欠账写明为何暂不修。
6. 真机开跑（命令见上），绝不无人值守。
7. 逐例读 `console.txt` + `verdicts.csv` 归因销号；产品缺陷修产品码。
8. H 组终验用户画布，然后快层 + 设备层 + ruff 全绿再提交。

## 已拍板的决定

D1 先 `live_cn` 再 `live_os`；D2 单浏览器用例用用户 profile，D3 并行用例改用一次性 profile（cookie 快照照常注入）；
D4 无头从严（风控 40362 采不满按 bug 追修，不长期豁免）；D5 原文件只读（`测试：<平台>.json` 永不改写，变体在内存副本上改 payload）；
D6 数量硬判据（充足供给下 `rows==target`，无声少交一律红）；D7 微信链接取自现有测试的 `mp.weixin.qq.com/s/…`；
D8 续跑不重不漏；D9 微博不开长测专项，取最近数天并断言“target 先满即收工且剩余窗口零付费”；
D10 X/YouTube 的 3 组件工作流已建、`validate()` 零错误。

**常驻**：`ml_train/` 未经明确授权不得动；准备据以动手的结论先自己读文件/`git log`；闸门数字带退出码取。

**完成定义**：通用形状全绿 + 该平台嫌疑“修复并回归”或“真机证明为站点行为并入白名单” + `测试：<平台>.json`
原样通过 + 全组件副本通过。任何一格 SILENT_SHORT、假行、对账不过 = 不过门。
