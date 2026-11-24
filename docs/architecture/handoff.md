# 交接与压缩检查点

## 工作方式（每次压缩都要带上，不许忘）

- **跑多少由这次改动能破坏什么决定，不由仪式决定。小改动只跑相关域，不要全量。**
  Lane A（文档/注释）= 文档门禁；Lane B（搬迁/改指测试缝）= 被搬模块 + 提到它的契约测试 + ruff；
  Lane C（一个域的行为）= 该域套件 + 契约/门禁，只有碰 UI/引擎/LLM/采集才加 device tier。
  全量 fast tier（约 14 分钟用户时间）只在**大改动、跨域改动、一批小改动收口或 closure gate** 跑一次，pylint 两个 tier 随批次跑；
  已经绿过的文件不为一行文档重跑。跳过全量时在提交说明里写明跑了哪些域，CI 是兜底。
  依据：`AGENTS.md` “Change workflow” 与 `docs/agent_practices.md` “测试怎么写”第一条（那里记着 2026-11-24 被用户
  当场纠正的那次：只改了算子下拉与相关测试，却准备跑全量）。
- 用户语言中文；歧义要问；后端/Python 改动只用 edit/write，禁止脚本重写仓库文件。

- 日期：2026-11-24
- 分支：`main`
- 最后提交：`d533e057 修改：收口批——去掉两份重复规则，修好 device tier 的陈旧测试并验通 CatBus`（已推 GitHub + Gitee，CI 触发）；框架仓库 `9e1e66a`（0.1.26）
- 工作区：W7 第 3 件（游标/账本值对象）的改动在本地未提交

## W7-2 算子级缓存：量过之后决定不做（2026-11-24）

计划自己要求“先有真实画布的命中率数字再上缓存”。数字由
`tests/unit/analysis/test_operator_cache_measure.py` 给出（真 `RunStore` + 真
`run_node_durable` 复用判定，只把 `execute_node` 换成真分析执行器、算子包一层计数）：

- 同一画布继续（没改任何东西）→ 节点 `restored`，**0 次**算子执行：缓存没有活干；
- 上游多一行（重新采集后继续）→ 节点重跑 **2 次**算子，键里的输入哈希全变，**0 命中**；
- 在管道末尾追加一步 → 节点重跑 **3 次**，其中 2 次是前缀步，**唯一能省的场景**；
- 代价：`node_rows` 只存最终表，缓存要按每个节点每次输入哈希多存 N−1 张中间表。

而贵的 LLM 步本来就有行级答案缓存（`llm_cache`），重算不付钱。所以 W7-2 以“量过的决定”收口：
**不建这一层**，理由与那张表写进 `docs/architecture/w7-incremental.md` 第 2 节。将来要重开，
先拿那张表量，不要先写缓存再找理由。

测出来的两个坑（写在这里省下次的时间）：

- 不记录父节点的资产行，`lineage_conflict` 答“未知”并保留复用——于是“上游变了”这一格会测成
  `restored`，数字全是假的。测量夹具必须像 source 节点那样先 `record_asset`。
- `run_node_durable` 的 `primary` 是**已合并的上游行**，不是 `[]`；传空会让分析执行器直接返回空表，
  看起来像“算子没跑”。

## W7 第 3 件：游标与账本值对象（2026-11-24）

`services/runs/store/values.py` 新增两个 frozen 值对象，`docs/architecture/w7-incremental.md`
记了验收与证据，这里只记“为什么这样做”和踩到的两处：

- `Cursor.position` 是爬虫自己的词表，`proven`/`total` 是评论引擎那条“已证明前缀”
  （`url_index`/`url_total`）——两者分开，`proven_prefix()` 拒绝负数/越界/无批次。
  store 的 `save_cursor` 写下的 JSON 与旧 dict **逐字节相同**，所以老 runs.db 直接能读。
- `get_cursor` 仍然在“没有游标”时返回 `None`（既有两条用例钉着这个区别），有游标时返回 `Cursor`；
  因此 `Crawler.resume_of` 从 `isinstance(cursor, dict)` 改成 `Mapping` 并 `dict(...)` 一份——
  不改这一处，9 个平台的 继续 会静默回到起点。
- `LedgerKey` 只装 `kind`+`parts`；站点字段表仍留在 `identity.py`（谁认识列名谁在那一层）。
  顺带把重复的 `_sha1` 收回成 `values.sha1_parts` 一份，`node_fingerprint`/`workflow_fingerprint`/
  `schema_digest`/`item_key` 共用；键值不变。
- 没做的：计划里“只有 position 的 Cursor 造不出来”做不到——行什么时候落地只有调用方知道，
  顺序仍由评论引擎保证；类型只管它能管的那半（这一点写进了 w7 文档，别在下次读到时以为是漏做）。

## W7 第 4 件：轮换规则纯函数化（2026-11-24）

`services/pool/policy.py` 是“能不能花下一个账号”的唯一住址：`Attempt` → `decide()` →
`Decision(ROTATE|SETTLE)`，无 I/O、无时钟。两个执行器现在只交事实：

- source 的两处 raise（wall / risk）把 `stored_rows = _proved_rows() - stored_before` 交给它；
  评论执行器的 `if status == BLOCKED and not rows ...` 变成把这一条 link 自己的行数交给 `_rotate`，
  由 `decide()` 回答。`pool.is_rotatable` 转发删掉了（唯一调用者已改用它）。
- 检查顺序是规则本身：停止 > 非池模式 > 未归因（network/未知）> 已有行 > 预算耗尽。
  两个调用点对“未说明原因的 BLOCKED”仍然各自不同（评论当作风控、source settle），
  这段差异留在调用方，`decide()` 只收已解析的 reason——统一它才是行为变更。
- 冻结体积：`nodes/executors/comment.py` 747→753、`nodes/executors/source.py` 881→883。
  涨的是“把事实交给规则”的调用与注释，没有新分支；预算表已同期改。
- 证据：`tests/unit/pool/test_pool_policy.py`（11 条）＋既有
  `tests/unit/executors/test_source_pool_rotation.py`、`tests/api/test_comment_pool_rotation.py`
  不改断言全绿。device tier 的一次真 `login_wall` 观测仍待（花账号，等用户）。

## 收口批的 device tier：两处测试缺陷（2026-11-24）

第一次真跑 device tier（`-m "integration or live_ollama"` + `CRAWLER_REQUIRE_BROWSER/OLLAMA=1`）发现两个
**只在真环境才暴露**的测试缺陷，都已修：

- `tests/integration/{test_ai_workspace_live,test_ui_layout}.py` 的服务夹具写 `deadline = time.time() + 40`
  却用 `while time.monotonic() < deadline`：Windows 的 `monotonic` 从开机算，远小于墙钟，于是 40 秒永不到期。
  服务器没起来时不是带日志失败，而是一直转到 900 秒全局 timeout（父进程空转、Chrome 与测试服务器泄漏，管道还被
  泄漏子进程攥着，后台命令的输出一直是空的）。两处都改成 `time.monotonic() + 40`。
- `test_ai_workspace_live.py` 的就绪探针指着 `/api/ai/bootstrap`；P4 之后 AI 的 HTTP 表面整体搬到
  `/api/ai/ws`（`api/ai_workspace.py` 的 `url_prefix`），所以它只会一直 404。改为 `/api/ai/ws/bootstrap`
  （手测：新端口 + 临时 `CRAWLER_DATA_ROOT`，200）。
- 同一批 2 个真浏览器用例红：`test_ui_layout.py` 的 `AI_BOOTSTRAP_STUB` 与 `@` 菜单桩还按 `/api/ai/...`
  匹配，于是 bootstrap 只回 `{ok:true}`（没有技能 → “no skill card rendered a context chip”）、`references`
  落到真服务器（“本用户没有可用的对象” → 2 行变 0 行）。两个桩改成 `AI_BASE + '…'`（`AI_BASE` 是
  `ai/kernel/http.js` 一处声明的页面拼写，桩不再持有第二份），两条都转绿。
- `tools/record_demo.py` 清 AI 会话也还在打 `/api/ai/conversations`，一并改到 `/api/ai/ws/conversations`
  （`test_frontend_workflow_deeplink.py` 的字面断言同步）。

规则已写进 `AGENTS.md`（“一个等待的两端读同一个钟”）与 `docs/agent_practices.md`（含两次实测的读法）。
**教训：移动一个端点要顺手跑一次 device tier**——这条 tier 在 P4 之后一直没人真跑过；“桩按产品自己的拼写
匹配”是同一条道理的另一面。

结果：**215 passed / 5 skipped / 6:12**；`CATBUS_HOME=F:\catbus-0.2.1` 下那 5 个跳过（CatBus 适配器）全部
变成 passed（适配器 0.3.0 + Node v24.21.0，入口 `dist/integrations/crawler-workflow/cli.js`，manifests 11 个
平台）。真实 CatBus 登录采集没跑：那要花用户账号，属于 live tier，得先问。

## W4：sessions 纯判定 + 弹窗接线（2026-11-24，`ee3cbfc2`）

- **三个纯模块**（无文件写、无读钟、无 Flask）：`sessions/naming.py`（`(平台, 账号)` 的折叠：
  `account_name`/`account_segment`/`cookie_filename`/`profile_path`/`account_order`/`next_free_label`）、
  `sessions/verdict.py`（状态词、`BLOCKING`、`classify_probe`、`cache_key`、`cacheable`、`is_fresh`，TTL 边界含端点）、
  `sessions/lanes.py`（profile 锁归属：`dir_key`/`acquire(…, clock=)`/`release_profile`/`is_busy`，等待的钟可注入）。
- `cookies.py` 的 `ACCOUNT_RE`/`DEFAULT_ACCOUNT` 变成 `naming` 的对象（一条规则一个家），其余方法委托；
  `profiles.py` 的 `_account_part`、锁块与路径拼接删掉，**889 → 776 行**；`preflight.py` 的分类/状态/
  阻塞/键/TTL/可缓存全部来自 `verdict`，**747 → 689 行**；预算表同步下调。
- **`instagram.dialogs` / `youtube.dialogs`：接入，不删。** 两条平台都真有弹窗路径：`Crawler.open()` 对任何带
  `prompts` 的类调用 `_dismiss_prompts()`，YouTube 的 `_boot()` 要从 EU 同意页底下读 `ytcfg`/`ytInitialData`
  （匿名采集必然遇到），Instagram 登录页由面板的验证探针经 `diagnose()→open()` 打开。于是
  `InstagramCrawler.prompts = (dialogs.NOTIFICATIONS,)`、`YouTubeCrawler.prompts = (dialogs.CONSENT,)`，
  两条 `ORPHAN_EXEMPTIONS` 删除，并新增 `tests/unit/crawlers/test_platform_prompts.py`：`dialogs.py` 里的
  每个 `Prompt` 都必须被其平台 crawler 类携带。
- **尾巴已收**：`crawlers/__init__.py` 的 `elif cookie_dir` 分支原来自行拼 `<platform>@<account>_cookies.json`
  （wechat 这类无会话平台），现在只调 `naming.cookie_filename`；`test_crawler_factory_account_path.py`
  对 `''`/`default`/`DEFAULT`/`work` 四种写法钉住“同一个命名者”。

## W5：AI 前端内核化（2026-11-24，`3df480fd`）

`ai-workspace.js` 4498 行 → 174 行的入口/接线，其余拆成 22 个模块（`index.html` 顺序即加载顺序，
`splits.json` 登记，`Object.assign` 保持一个全局）：

- `ai/kernel/`：`store.js`（唯一可观察状态 `AI_STATE` + `const AIWorkspace` + `AIStore`）、`dom.js`（安全渲染 +
  morph + 折叠记忆）、`http.js`（`AI_BASE` + 21 个请求→状态成员）、`sse.js`（SSE 解码 + `_onEvent` reducer +
  turn 时钟 + trace 流）。
- `ai/render/`：`markdown.js`（声明 `AIRender` 与转义/表格）、`question.js`、`artifact.js`、`toolcard.js`。
- `ai/features/`：`dock`/`chat`/`stored`/`composer`/`mentions`/`answers`/`sidebar`/`events`/`artifacts`/`monitors`/
  `folder`/`studio`/`editors`/`watch`。`ai/stream.js`、`ai/render.js`、`ai/studio.js`、`ai/watch.js` 删除（字节在新文件里）。
- **新门禁 `tests/js_budget.py` + `tests/unit/frontend/test_frontend_js_budget.py`**：单文件 ≤600 行，`SCOPE` 是
  唯一声明范围的地方（今天是 `ai-workspace.js` 的 splits 闭包），生成物 `zenviz-page.js`/`node-types-fallback.js`
  按名字豁免；带“超预算必须报出文件名/恰好在预算上通过/生成物豁免只有一处声明”的合成缺陷自测。
  页面级铺开会让 19 个既有文件变红（canvas.js 2637 等），那是后续片要显式改范围的事，不是现在的豁免。
- 一处必须修的行为：bootstrap 的模型清单答复在用户切走 provider 之后返回时，会把旧 provider 的模型写回去；
  `_loadBootstrap` 现在也拒绝一个页面已经离开的 provider 的答复（`test_the_local_daemons_real_models…` 仍绿）。
- 未做（已写在文件头，不假装做了）：`AIHttp` 还没有收养面板里约 30 处单次 `fetch`（studio 插件开关、文件夹、
  技能 CRUD、监控）。

## W3：ai/tools 拆包（2026-11-24）

`ai/tools.py`（1697 行、37 个工具、一份 `TOOLS` 字典）→ `ai/tools/` 包，一域一模块，各文件末尾一个
`TOOLS` 元组，`ai.tools.TOOLS` 是合并字典（与 `nodes/catalog.py` 同一手法）：

- `catalog.py`（覆盖率/能力技能/CatBus/图表/算子）、`datasets.py`（peek/profile/page/sample/query +
  封闭算子表）、`runs.py`（运行/控制台/确认编辑/`rerun_node` + `RERUN_REFUSAL_KEYS`）、
  `workflows.py`（保存的工作流 + 导出架）、`models.py`（本机模型 + infer/rerank）、`code.py`（源码只读）、
  `policy.py`（`UNIVERSAL_TOOLS`/`APPROVAL_TOOLS`/`ALWAYS_APPROVAL_TOOLS`）、`shared.py`（`_int_arg`）。
- `ai.tools.tool_x` 的历史地址用 PEP-562 `__getattr__` 转发到属主模块（**只转发调用**，patch 必须打在
  `ai.tools.datasets` 这类属主上——这条写在转发函数的 docstring 里）；测试里的 patch 目标随之改指属主
  （`_dataset_frame`/`_workflow_manager`/`_infer_text_classifier`/`get_setting`）。
- 顺手删掉四个死 schema（`ASK_USER_SCHEMA`/`UPDATE_PLAN_SCHEMA`/`PRESENT_SCHEMA`/`APPROVAL_SCHEMA`）：
  控制工具已由框架接管，这四个没有任何引用。
- 模块预算删掉 `ai/tools.py: 1697`（包内最大 `datasets.py` 454 行）。
- 新增 `docs/capabilities/tool-descriptions.md`（命名、参数 ≤8、读写分离、“什么时候不该用”，逐工具表）与
  门禁 `tests/unit/gates/test_tool_descriptions.py`（名字有域前缀、描述 ≥40 字、≤8 参数、无 `code`/`script`
  类自由参数、权限是已知动词、页面不漏列不多列）。
- 新增 `tools/eval_tool_routing.py`：26 条用户原话，用本地 Ollama 让模型只挑一个工具名，输出命中率；
  数字记在 `docs/testing/model-eval.md`。
- **删掉宿主 `ai.skills.route`（及 `test_catbus_skill.py` 里的那条用例）**：它是框架 `Skills.route` 的
  第二份关键词表，且两侧都没人调用；技能选择这件事只留框架一份。架构待办（R7）因此改写为“先把框架
  `Skills.route` 接进 `auto` 再评测”——`api/ai_workspace.py` 现在把 `auto` 当空串交给框架默认技能。

## W6：框架 0.1.26（2026-11-24）

框架侧两次提交（`aeeb11d`、`9e1e66a`），宿主侧换 wheel + 记文档：

- **`store.py`（1220 行、88 方法、16 聚合）→ `store/` 包**：`base`（连接 + `_db` 调用时解析 + schema）、
  `transcript`（会话/消息/轮次/事件/pending/命令/邮箱）、`steps`（步骤 + trace）、`usage`、`memory`（记忆 + 偏好）、
  `library`（产物/技能/文件/脚本）、`monitors`、`recipes`。`Store` 是它们的合成，公开方法一个不少。
- **`agent.py`（971 行）→ `agent/` 包**：`turn`（循环本体）、`dispatch`（**`CONTROL_TOOLS` 处理器表**，六个控制工具
  不再是一串 `if name ==`，处理器返回 content/answered/pause 三态）、`messages`（transcript→provider、孤立
  `tool_use` 修复、窗口裁剪）、`prompt`（系统提示词、用户行、引用、steering）、`resume`（回答暂停）、`limits`。
- **`service.py` → `turn_runner.py`**：`ask`/`_open_turn`/`_run_turn`/`subscribe`/`_record_event`/`_consume_commands`/
  `_handoff_unused_steer`/`_report_turn` 与 `_TurnOutcome` 搬出，`AgentWorkspace` 改为 `TurnRunner` 的合成；
  service 929 → 669 行，只剩装配与转发。
- **新增 `ports.py`**：一域一个 `Protocol`（store/tools/recipes/approvals/tracing/context/skills/costs/references/
  catalog/settings/host/artifact_registry）+ `AgentServices` 合成，替代无类型的 services 袋。
- **三个新门禁（框架自带）**：`tests/test_architecture_seams.py`（控制工具表 == tools 声明、处理器是 Agent 的方法、
  dispatch 不得再出现 `name == '…'`、ports 承诺的成员必须在真 workspace 上存在）；`tests/test_turn_without_workspace.py`
  （假 store/假 provider 跑完一轮：工具调用 → 产物 → 回答，另跑暂停路径，全程不构造 `AgentWorkspace`）；
  `tests/test_no_host_vocabulary.py`（`agent_workspace/` 出现宿主产品名或平台 id 即红——顺带把 config/host 里
  两处指向具体宿主的措辞改成通用说法）。框架 259 用例绿，ruff F/E9 绿。
- **宿主接入**：`vendor/agent_workspace-0.1.26-py3-none-any.whl`（重建于框架 checkout，
  `python -m pip wheel --no-deps -w dist .`），`requirements.txt` 与 `desktop/requirements-runtime.txt` 两处 pin
  同步；换 wheel 后宿主 `tests/unit/ai` + AI 表面 **177 passed**。

## W0/W1：清单校准 + 分层门禁（2026-11-24）

**读这两份**：[`improvement-plan.md`](improvement-plan.md)（W0–W7 与取舍）、
[`rewrite-plan.md`](rewrite-plan.md) 的“未完成清单（2026-11-24 校准）”。

- **W0 校准**：勾掉 7 项代码已完成但未勾的（RecipeFSM/H3b/H15/H21/工具覆盖门禁/完整性门禁/P9 版本与 CI）；
  把真正未完成的收成 R1–R10（契约未铺满、框架两层、评测三件、前端与变异测试）。
  `best_practices.md` §3 节点类型改回清单流程，依赖方向改成由门禁执行。
- **W1 四个门禁**（`tests/unit/gates/`）：
  - `test_import_graph.py`：只有 `api/` 与 `app.py` 可 import `api.*`；任何模块不得 import `app`；
    `core` 只依赖标准库与 `i18n`（`core.machine → services.components.manifest` 是一处登记过的例外，
    例外失效即红）；没有 import 者的模块必须进 `ORPHAN_EXEMPTIONS` 并写明理由，理由失效同样红。
  - `test_module_budget.py`：新模块 ≤600 行；34 个现存大模块冻结在当日行数；拆分后预算不降即红。
  - `test_http_surface.py`：路由只写在 `api/`；`app.py` 只有 `/` 一条。
  - 每个门禁都带“合成缺陷必须被抓”的用例。
- **同批修掉的耦合**：
  - 数值解析 `api/http.py` → `core/values.py`（9 个 engine/nodes/services 模块不再 import HTTP 层）。
  - `default_model_path_for`/`read_model_registry` → `services/models/catalog.py`（节点执行器与组件探针改依赖域层）。
  - `sessions/routes.py` → `api/sessions.py`；`services/pool/routes.py` → `api/pool.py`（`sessions/` 回到纯域）。
  - `runtime/settings.py` 不再 import `app`：上传上限由组合根 `on_saved` 钩子重读。
  - `core/refs.py` 的 pandas 依赖搬走：`df_to_csv_string`/`merge_results`/`json_safe_records` →
    `services/datasets/frames.py`（导入 `platform_for` 的爬虫不再付 pandas 启动成本）。
  - 删 16 个空的 `capabilities_kernel/nodes/<id>/__init__.py`（charts/operators/platforms 从来没有）。
- **验证**：`doctor.py --all` 全绿；`ruff check backend/ tests/` 全绿；
  `tests/unit/gates` 15 passed；`tests/api + tests/unit/foundation` 见当次输出。
- **W2 第一片（决策抽出）**：`engine/decide.py`（纯函数、无 store）：`record_has_component` /
  `record_belongs` / `split_records` / `choose_record`。采用仍由调用方 `pop` 返回的下标消耗候选
  （同一画布可有两个同名组件）。`engine/run.py` 删除四个私有助手（1984 → 1900 行，模块预算同步下调）。
  `tests/unit/runs/test_continue_record.py` 改为直接测 `decide`，保留全部旧用例并加一条随机性质
  （200 组行集，永不在指纹之间串台）。`tests/unit/gates/test_run_worker_module_scope.py` 仍绿。
- **下一步（W2 剩余）**：`engine/run/` 包（claim/worker/node/records/settle/stop）+
  `core/asset.py` 接入（节点结算写 asset 行，复用键含上游资产哈希）。验收见 improvement-plan W2。
- **全量 fast tier 实测（本批收口）**：`12234 passed / 7 skipped / 386 deselected`；同一份代码连测两次
  **12:37** 与 **10:36**（抖动 ±10%，最慢的全是“等满真实超时”的假驱动用例）。12 分钟线目前是**骑线**，
  不算有余量；归因与下一步（`crawlers/engine/` 的可注入就绪探针）写进 `docs/testing/performance.md`。

## W2：engine/run/ 包 + 节点资产（2026-11-24）

- `engine/run.py`（1900 行）拆成包，按**问题**而不是按行数：`decide`（纯决策）/ `node`（单节点持久结算）/
  `walk`（图遍历与并行池）/ `records`（记录开·关·采用·擦除）/ `settle`（结算 + 终局句 + 终局常量）/
  `worker`（线程全身）/ `claim`（`begin_run`）/ `stop`（停止与浏览器回收）。`engine.decide` 随之搬进
  `engine/run/decide.py`；`run/__init__.py` 重导出公开名，所以 `engine.run.begin_run`、`.stop_run`、
  `.start_next_queued`、`.run_node_durable` 等地址一个都没变（`api/workflow.py`、`queue`、`run_schedule`、
  `app.py` 都不需要改）。
- **两个 seam 要跟着属主走**：① 测试里 patch `engine.run.X` 的地方改成 patch 真正读它的子模块
  （`engine.run.claim.threading`、`engine.run.node.stop_requested`/`add_log`、`engine.run.worker.close_run`/
  `get_run_store`、`engine.run.walk._run_single_workflow`）；② `tests/api/conftest.py` 的 console 转发从
  1 条变成 4 条（node/walk/records/worker），普查门禁按 AST 自动要求，新增打印模块必须登记。
- `settle.py` 是把 `_run_worker` 里唯一一段“计数即判决”的代码提出来：`settle_attempt`（先 `settle_nodes`
  再数 broken）/ `finish_line`（skipped→stopped→failed 三个从句）/ `verdict`（停止压过失败、一个 broken
  压过 completed）。`tests/unit/runs/test_run_settle.py` 12 例逐条钉住（停止不算失败、画布删掉的节点不算、
  skipped 两头都不算）。
- 门禁同步：`test_run_worker_module_scope.py` 改成读包内每个 `.py`；`test_module_budget.py` 删掉
  `engine/run.py: 1900`（包内最大模块 ~480 行）；`test_console_buffer.py` 扫描包内全部模块；
  `test_reusable_expand.py` 的调用点改读 `run/claim.py`。
- 验证：gates + runs + accounts **1863**；api **2834**；workflows/executors/foundation/desktop/scheduling/
  ai/frontend **2713**；ruff 全绿。
- **节点资产接线（同一天）**：`core/asset.py` 终于有写方。`node_assets` 表（`(run_id, node_id)` 主键，
  sha256/size/uri/parents/input_sha）由 `services/runs/store/assets.py` 的 `AssetsMixin` 管；`engine/run/asset.py`
  负责把一次节点的产出填成 `DataAsset`（表按行、图表/compile 的 dict 按一份文档），再写行；`engine/run/node.py`
  在 applied-trace、PARTIAL、DONE 三处结算后写入，并在复用判定里加一条 `lineage_conflict`。**只知道不一致
  才拒绝**：没有资产行/没有 input_sha/上游本无资产都退回结构规则，老库不会被改判；改指纹、重跑节点、删除运行
  都会连带删资产（否则子节点会拿一张已不存在的表的哈希比较）。新测试 `tests/unit/runs/test_run_asset.py` 20 例，
  其中三例用真 `RunStore` 走 `run_node_durable`：首次运行写资产、同上游的 继续 恢复不重跑、上游内容变了就重跑。
  `core.asset` 从 `ORPHAN_EXEMPTIONS` 里删掉（门禁会拒绝过期豁免）。
- **下一步**：W6（框架 `Store`/`Agent` 拆分与 `ports.py`），然后 W3（`ai/tools` 拆片）、W4（sessions 纯判定）、
  W5、W7。

## P8 尾巴：消费者契约 + 性质测试（2026-11-24）
- **消费者契约** `tests/api/test_node_types_contract.py`：`/api/node-types` 的每个节点 defaults 键必须是
  已声明参数、`defaultsFrom` 类型不许有 defaults、未被运行期覆盖的种子值等于清单默认；图表 profile 等于
  `chart_profiles()` 且字段/默认名已声明；算子参数逐字段等于清单、面板盒子的 canonical 指向已声明参数。
- **性质测试** `tests/unit/foundation/test_properties.py`（固定种子伪随机）：`sanitize_filename` 的字节上限/
  UTF-8 合法/幂等/无路径分隔符；`normalize_step_params` 幂等与空 select 回退（`NO_DEFAULT` 保持空）；
  `value_key` 的 trim/url 幂等与空格/NA/NaN 不产生身份。
- **抓出并修掉两个真 bug**（`backend/core/refs.py`）：① “扩展名”自身超出预算时，结果 239 字节 > 200 上限；
  ② strip 顺序（空白→点→没有再空白）让“点+全角空格”开头的名字把空格留在开头，二次清洗又变。
- 验证：api/crawlers/workflows **2997 passed**；foundation+契约 473；gates+foundation+契约 **1745**；ruff 全绿；
  两份生成物已重渲染。

## P8 文档与技能收尾（2026-11-24）

- 旧路径逐条改指能力清单：`capabilities/platforms/<id>.py` → `capabilities_kernel/platforms/<id>/manifest.py`；
  `capabilities/model.py`/`fields.py` → `capabilities_kernel/platform.py`/`platforms/_fields.py`
  （agent_practices、crawler_rules×2、best_practices、`docs/capabilities/nodes/source.md`、
  `.opencode/skills/crawler-platform` 三处）。
- 流程类说法改对：`analysis-charts` 的“加算子”改为写清单（reads/writes/needs_llm/panel），分析层表与面板都是
  投影；`docs/analysis.md` 不再声称与 `ANALYSIS_OPS` 一一对应。
- `capabilities-kernel.md` 的生成物清单补上 `docs/capabilities/matrix.md` 与
  `docs/testing/value-inventory.md`（各自的工具与 freshness 门禁）。
- rewrite-plan：勾上“README/AGENTS/docs/skills 同步”，性能基线改 10:56。
- 验证：文档/引号/矩阵/清单门禁 + capabilities **444 passed**。
- **P8 剩余**：消费者契约测试、性质测试 + nightly mutation（计划内，未做）。

## P8 第四片：能力 × 测试矩阵（2026-11-24）

- `tools/gen_capability_matrix.py` → `docs/capabilities/matrix.md`：每个能力列出**声明的契约用例**与
  **以它命名的专属测试文件**（自己的目录下 `test_<id>.py` / `test_<id>_manifest.py` / `test_<id>_*.py`）。
  93 个能力中 **21 个有专属文件**（16 节点 + 5 平台），其余仅由共享门禁覆盖，页面把后者逐条列出。
- **刻意不猜覆盖率**：试过“裸 id / 技能地址出现即算”，`node.name` 会命中 Python 属性访问，把 4083 个
  无关用例记在一个能力名下——那样的数字会教人忽略这一页。只报可证事实。
- 门禁 `tests/unit/gates/test_capability_matrix.py`：陈旧即红；每个能力在页上；所列专属文件真实存在；
  扫描至少看到 15 个专属文件（空扫描不能永远通过）。
- 顺带：AGENTS 性能基线 11:36 → 10:56；rewrite-plan 勾上矩阵一项。
- 验证：gates + capabilities **1807 passed**；ruff 全绿；两份生成物已重渲染。

## P8 收口（2026-11-24）

- **全量 closure gate 记录下来**：`docs/testing/closure-2026-11-24.md`（提交 `002f9cc5` 时点）：
  fast tier **12172 passed / 7 skipped / 10:56**；ruff + product/tests pylint **10.00/10**；
  doctor 全绿；`PORT=5057` + 独立 `CRAWLER_DATA_ROOT` 冒烟：`/api/capabilities`（74 KB）、
  `/api/node-types`（118 KB）、`/api/settings/schema`、`/` 全部 200，随后关闭并释放端口。文档写明
  未纳入 device/live/CI/浏览器 AI 实机。
- **全量随机失败根因**：`tests/api/test_pool_api.py` 用 `accounts[0]` 取自己的行，而该列表来自共享
  cookie 目录，别的用例留下的登录把它挤走 → 改为按 `platform+account` 选行（`002f9cc5`）。
- **性能基线**：10:56（xhs 假驱动回答就绪探针后，两个慢例各减 5 s）；预算 ≤12 分钟达标，8 分钟
  目标仍待 `crawlers/engine/` 的可注入就绪探针（见 `docs/testing/performance.md`）。

## P8 第三片：快测预算（2026-11-24）

- 实测 `--durations=15`：**14:23 → 11:36**，省 2:47，全部来自修“陈旧测试缝”，没删用例：
  - `tests/api/test_collision_retry.py` 还在补丁 `Config.WALL_RETRY_BACKOFF`，产品早已改读设置
    `wall_retry_backoff` → 每例等满真实 45 s。补丁改到 `source.get_setting` 后 **94 s → 3.6 s**。
  - `test_hongguo_harvest` 的 `has_more=false` 用例仍向站点要下一页、每页等满 10 s×8。
    让假 UI 的 `scroll_drawer` 返回 `False`（断言不变）后 **78.7 s → 3.5 s**。
- 新增 `docs/testing/performance.md`：预算（fast ≤12 分钟达标；8 分钟未达，剩余热点与原因逐条列出，
  明确不用 xdist 掩盖，下一步是给假驱动加时钟接缝）、修复表、复测命令。
- AGENTS 测试节新增“预算 + 10 秒单例先查陈旧缝”；`docs/agent_practices.md` 记下这条教训。
- 验证：全量 fast tier **12172 passed / 7 skipped（11:36）**；ruff 全绿；文档/引号门禁 10 passed。

## P8 第二片：无断言用例 33 → 0（2026-11-24）

- 检测器先修准：除裸 `assert`/`pytest.raises` 外，也认“名字以 `assert` 开头（可带前导下划线）的调用”
  与显式 `raise AssertionError`。页面标记的 4 个私有 helper 因此改名（`_assert_no_duplicate_ids`、
  `_assert_markup_nests`、`_assert_no_dangling_idrefs`、`_assert_every_control_named`）——名字即断言。
- 真正无断言的 12 条逐条补断言：`close_login_browser`/`close_run`/`close_driver`/`release_profile`/
  `complain`/`_postcheck_node`/`verify_feed_signature` 断言返回 `None`；cookie delete 断言删后不存在；
  `json.dumps` 断言非空；文件名截断断言 UTF-8 字节上限且能原样解码。
- **门收紧**：`NO_ASSERT_ALLOWED` 清空，`NO_ASSERT_TOTAL` = **0**；AGENTS 对应句子改为“钉成 zero”。
- 验证：改写的 12 个文件 + 页面标记 + 计数器门禁 **393 + 23 passed**；inventory `--check` 通过；
  文档/引号/计数器门禁 14 passed；ruff 全绿。

## P8 第一片：测试价值清单与门禁（2026-11-24）

- `tools/test_inventory.py`：`ast` 扫描 `tests/**`（**434 文件 / 8555 用例定义**），逐文件统计
  用例数、无断言、skip/skipif、xfail，渲染 `docs/testing/value-inventory.md`；`--check` 比字节。
- 门禁 `tests/unit/gates/test_test_inventory.py`：页面陈旧即红；“无断言又没写理由”即红；**无断言总数
  钉成 33**（新增一处就失败，逼作者补断言或写理由并改数字）；skip 只允许 OS/环境事实。
- 现状：**10 个 skip 全部是 OS/环境事实**（POSIX 可执行位、macOS `ps`、Windows `MessageBoxW`、
  Node 未装、POSIX mode bits）；**33 条无断言**逐文件写明理由（“不得抛异常”“与副本比较”“由 helper
  断言”），P8 下一步把它们改写成显式断言并缩小这个数。
- 顺带修掉一个检测 bug：`parametrize` 里的 `'st-skipped'` 曾被当成 skip 标记（skip 数从 11 修正为 10）。
- 验证：门禁 4 passed；`--check` 通过；ruff 全绿；文档/引号门禁 14 passed。

## P7 收口：分析面板 37/37（2026-11-24）

- `PanelField` 增加两个虚拟控件：`control='note'`（只渲染 hint_key 的提示行）与 `control='roles'`
  （双表步骤的“过滤表/基准表”实时角色行，`role_keys` + `toggle_param`）。二者不写参数，`problems()`
  不要求 canonical；`hide_when` 的引用改为校验“另一个已声明的盒子”。
- `anti_join` 迁完：roles / keep_mode / left_on / right_on / match_mode（选项由 enum 派生）/
  ignore_case / max_distance（`hide_when`：match_mode 为空或非 similar 时隐藏）/ swap_tables。
  `node-analysis.js` 不再有任何按算子的手写块——只剩算子下拉与预览按钮。
- 测试：面板块解析器允许“没有按算子的块”；api 契约跳过虚拟控件。验证（全量收口）：**12168 passed /
  7 skipped**；ruff 全绿；product 与 tests pylint **10.00/10**；doctor 全绿。
- **P7 七项全部完成**：算子 37、图表 30、平台 10 清单化；九表面门禁；MCP + CLI；面板（下拉 + 37/37 表单）。

## 分析面板收口（36/37，2026-11-24）

- 第三批剩余 16 个算子迁完（cluster_label / cluster_review / cooccur / reply_graph / compare_platform /
  filter_rows / rename_columns / convert_type / sort_rows / sample_rows / groupby_agg / join_tables /
  column_calc / bin_column / select_columns / strip_whitespace）；`node-analysis.js` 只剩算子下拉、
  预览按钮与 **anti_join** 的块。
- 新通用能力：`PanelField.options_param` + `option_label_prefix`——select 选项从已声明参数的 enum 派生
  （`filter_rows` 的 12 种比较不再抄第二份）；`problems()` 拒绝 options 与 options_param 并存。
  `filter_rows` 的值框用 `hide_when=('op', ('is_null','not_null'))` 隐藏。
- **保留手写 anti_join（1/37）**：`twoTableRoleLine` 按 `swap_tables` 实时显示“过滤表/基准表”，
  通用渲染表达不了；条件出现的 `max_distance` 本可用 hide_when，但角色行不行。
- **自伤记录**：给 sentiment_evolution 加 panel 时把 `reads=`/`writes=` 整段替换掉，契约变空、写入模式
  退化为 passthrough；被“未配置表单不得毁行”用例抓到并修复。教训：向 `operator_manifest(...)` 追加参数时，
  编辑锚点必须包含被保留的行。
- 验证（全量收口）：**12168 passed / 7 skipped**；ruff check+format 全绿；product 与 tests pylint
  **10.00/10**；doctor 全绿。

## 分析面板：第三批（时间/事件，2026-11-24）

- 迁移 extract_time / bin_time / suggest_stages / sentiment_evolution / forecast / alert（累计 **20/37**）。
- **操作事故与修复**：为补 import 用了 PowerShell `Get-Content -Raw` + `Set-Content`（按 ANSI 读入），
  中文串被二次编码、BOM 注入、6 个文件语法错误；`git checkout` 还原后改用 edit 重做。**清单只能 edit/write。**
- 验证：operator/panel 契约 297 passed；frontend contract 107 passed；ruff 全绿；生成物重生成。
  该批未跑 product/tests pylint（下一批收口时补）。

## 分析面板：第二批（topic 家族，2026-11-24）

- 迁移 topic_model / topic_by_stage / topic_label / topic_map / topic_salience / topic_timeline /
  topic_flow / topic_coherence（累计 14/37）。共享盒子在 `operators/_panel.py`：`N_TOPICS`、
  `TOPIC_METHOD`、`EMBEDDING_MODEL`、`TOPIC_MAX_FEATURES`；每步自己的 topp 标签与提示用
  `dataclasses.replace(..., hint_key=...)` 挂在各自的盒子上。
- `tests/api/test_analysis_api.py` 的面板契约改为**清单优先**：`_panel_fields` 先读
  `operator_entries()['panel']`，没有才解析 JS；块覆盖测试要求 `rendered | declared == 全部算子`
  且两者不相交。
- 验证：capabilities/analysis/frontend/api/表面门禁 **6338 passed**（约 7.5 分钟，未跑全量）；
  ruff 全绿；两个 pylint tier 10.00/10。
- **剩余**：23 个算子的面板块（时间 4、统计/关联/事件 12、图与文本 7）。

## 分析面板：首批算子表单清单化（2026-11-24）

- `OperatorManifest` 新增 `panel`（`PanelField`：面板键/规范参数/标签键/控件/默认/选项/提示/占位/hide_when），
  `operator_entries()` 投影给 `/api/node-types`；`node-types.js` 新增 `operator(key)`。
- `node-analysis.js` 新增 `renderOperatorPanel`：有 `panel` 就按清单渲染，否则回落手写块——**缩小的清单**。
  首批迁移 6 个（drop_null/fill_null/drop_duplicates/dedupe_similar/semantic_dedupe/similar_to），
  共享 `columns` 块只剩 select_columns/strip_whitespace；`normalize_analysis_params` 未动。
- 三例门禁：迁移后的面板值只产出已声明参数；已迁移算子不得留手写块；未迁移算子必须在 JS 仍有表单。
- 验证：capabilities/analysis/frontend/api/表面门禁 **3558 passed**（约 3 分钟，未跑全量）；ruff 全绿；
  两个 pylint tier 10.00/10。
- **剩余**：31 个算子的面板块（topic/时间/统计/关联类），下一批继续。

## 面板清单化（第一半，2026-11-24）

- `registry.operator_entries()` 成为浏览器的算子投影（id/词/分组/槽位/是否用模型/写形状/读列/声明参数），
  `/api/node-types` 同时返回 `types`/`charts`/`operators`，冷页的 `node-types-fallback.js` 与
  `capability-schema.json` 带同一份；`node-analysis.js` 删除手写 `ANALYSIS_OPS`，步骤下拉渲染
  `NodeTypes.operators()`。
- 门禁：算子新增 `api:operators`、`generated:frontend-schema` 两条表面断言；“第二份算子名单”扫描阈值
  4→10（整份下拉才算拷贝）。
- **剩下的一半**：37 个算子的**字段块**仍手写；搬它要同时把面板字段名与 `normalize_analysis_params`
  的映射放进清单，否则旧画布的面板会显示空框。
- 验证：analysis/frontend/capabilities/api/gates **5557 passed**；表面+capabilities 514 passed；ruff
  全绿；product 与 tests pylint 10.00/10（按“小改动只跑相关域”的口径，未跑全量）。

## P7 多表面：MCP server 与能力 CLI（2026-11-24）

- **`services.mcp`**：传输无关的 JSON-RPC（`initialize`/`ping`/`tools/list`/`tools/call`），工具
  `capabilities_list`、`capabilities_show`、`workflow_validate`；转调 `ai.knowledge` 与
  `engine.workflow`，所以编辑器/终端看到的能力不会比产品多一个。通知不回包、未知方法与未知工具按名
  拒绝、工具级拒绝是 `isError` 结果（不是传输层错误），`serve()` 是逐行 JSON 的 stdio 传输。
  `tools/mcp_server.py` 是入口。
- **`services.capability_cli`**：`list [--kind] [--query]` / `show <skill_id>` / `validate <file>`，
  退出码区分“未知 id”（2）与“校验不通过”（1）；入口 `tools/capability_cli.py`。两个列表都取
  `MAX_LIMIT`，避免默认短页静默截断。
- **门禁扩展**：七表面门禁新增 `mcp:capabilities` 与 `cli:capabilities` 两条双向断言（现 87 例）。
- **验证**：mcp/cli 14 passed；capabilities+表面+文档+引号 520 passed；全量 fast tier **12160 passed**
  （唯一失败是自己文档里用了角括号，已改并复跑）；ruff 全绿；product 与 tests pylint 10.00/10。
- **未做**：UI 表单的清单化（随“面板/停靠/设置清单化”）；MCP 资源（当前只暴露工具，不暴露 resources）。

## P7 七表面一致性门禁（2026-11-24）

- **一个表面表**：`tests/unit/gates/test_capability_surfaces.py` 的 `SURFACES` 按 kind 声明该能力必须
  出现的表面（`runtime:node-types`/`runtime:ops`/`runtime:charts`/`runtime:platforms`、
  `api:chart-profiles`、`generated:catalog`/`ai-tools`/`frontend-schema`/`openapi`、
  `ai:skill-catalog`/`ai:vocabulary`、`docs:page`/`docs:skill`），每个 (kind, surface) 双向断言：
  清单里的 id 一个不漏，表面上的 id 一个不多。
- **它抓到的三处真实漂移**：node 与 operator 共用 `NodeParams.` 前缀（现为 `OperatorParams.`）；
  前端目录的 key 被写成 `types` 而实际是 `nodes`；AI 词汇表里的 CatBus-only 平台
  （京东/淘宝/快手/TikTok/闲鱼）不属于本树——门禁显式排除，而不是假装不存在。
- **生成物补齐**：OpenAPI 现在为图表（`ChartFields.<id>`）与平台（`PlatformModes.<id>`）生成 schema，
  四类能力在机器可读接口上一致。
- **验证**：表面门禁 71 passed；capabilities/gates/ai 1931 passed；ruff 全绿；文档门禁通过。
- **未做**：MCP server 与 CLI 两个表面；面板/停靠/设置清单化。

## P7 第三类：10 个采集平台清单化（2026-11-24）

- **新增能力种类 `platform`**：`capabilities_kernel/platforms/<id>/manifest.py`（`PlatformManifest`，见
  `capabilities_kernel/platform.py`）。声明的还是那些站点事实（模式、字段、产出、屏幕行为、是否需登录、
  机器要求、实测运行建议），只是现在带上了 identity/七段技能/文档/契约测试；工作区里 `skill_load` 能读到
  “这个平台有哪几种采集、各自要什么、什么时候别用”。
- **值类型搬进 kernel**：`Capability`/`Mode`/`Field` 与共享原子/模式工厂（`platforms/_fields.py`）离开
  `capabilities/`；`capabilities/fields.py` 与 `capabilities/model.py` 删除。`Field.value_from` 的
  `core.refs` 导入延迟到方法内（core.refs 拉 pandas，而清单在解析画布时就要加载）。
- **投影**：`capabilities.platforms.CAPABILITIES = registry.manifests('platform')`（面板顺序 = `identity.order`），
  `capabilities.registry`/`catbus` 改读 kernel；爬虫类 `crawlers.platforms.<id>.crawler:<Class>` 成为清单
  handler，doctor 因此逐个核对“这个平台的爬虫还在”。
- **生成物**：每个平台生成 `docs/capabilities/platforms/<id>.md`（模式/必填字段/建议/机器要求）与七段技能页。
- **验证**：api/crawlers/foundation/ai/capabilities **4891 passed**；全量 fast tier **12059 passed**（唯一失败
  是文档仍引用已删除的 `capabilities/fields.py`/`model.py`，已改指 kernel 并复跑）；ruff check/format 全绿；
  product 与 tests pylint **10.00/10**；doctor 全绿。
- **未做**：面板/停靠/设置清单化；多表面生成（MCP server / CLI）；七表面一致性门禁；平台级 `preflight`。

## P7 第二类：30 个图表类型清单化（2026-11-24）

- **新增能力种类 `chart`**：`capabilities_kernel/charts/<id>/manifest.py`（`ChartManifest`，见
  `capabilities_kernel/chart.py`）。字段词汇集中到 `charts/_fields.py`：同一个 x/value 框只声明一次。
  清单声明字段/角色/必填/默认/控件、`any_of` 组、`echarts_only`/`latex_buildable`、文献视图必读列、
  面板槽位与七段技能；`chart_manifest()` 从字段契约推导技能其余五段与模板（填必填框与 `any_of` 组）。
- **`services.charts.registry` 改为投影**：`SPECS = registry.manifests('chart')`，`ChartSpec`/`FieldSpec`/
  `FAMILY_*`/`FIELD_ROLES`/`NUMERIC_ROLES` 从 kernel 复用；派生元组与 `spec_for`/`chart_profiles`/
  `chart_problems`/`chart_preflight` 未变。16 个控制台绘图函数改名为公开 `build_<id>` 并成为清单 handler，
  文献图 handler 指向 `services.biblio.charts.*`。
- **技能与生成物**：每个图表生成 `docs/capabilities/charts/<id>.md`（字段表/引擎/文献列）与七段技能页；
  `knowledge.render/l2` 为图表增加 Fields 段；`@` 候选列表不再截断（框架负责筛选），三类能力技能都出现。
- **验证**：全量 fast tier **11920 passed**（唯一失败是候选被 40 条截断，已修并复跑）；charts/ai/capabilities
  子集 1648 + 1060 passed；ruff check/format 全绿；product 与 tests pylint **10.00/10**；doctor 全绿。
- **未做**：`panels/node-chart.js` 仍按控件名注册小部件（声明与控件已由测试钉住，但表单仍是手写渲染）；
  平台（第三类）清单化；图表级 `preflight` 仍由 `chart_preflight` 承担（未搬进清单）。

## P7 第一类：37 个分析算子清单化（2026-11-24）

- **新增能力种类 `operator`**：`backend/capabilities_kernel/operators/<id>/manifest.py`，用
  `capabilities_kernel/operator.py` 的 `OperatorManifest` 声明：读（`one`/`some`/`nonblank`/`mapping`/
  `two_table_keys`）、写（`replace`/`add`/`select`/`passthrough`/`dynamic`/`unknown` + 固定列/追加列/`bin_column`
  的 `<列>_bin`）、策略（`needs_llm`/`empty_by_design`/`checks`）、参数与选项、徽章字段名、七段技能。
- **一套投影，删掉五张手写表**：`contracts.STEP_PARAMS`、`LLM_OPS`；`params` 的七个写表；
  `matching.STEP_TWO_TABLE`/`MATCH_MODES`/`KEEP_MODES`；`kernels` 六个选项表；`step_checks.TWO_TABLE_KEYS`
  与 `_OP_PARAM_LABELS`；`ops.OPS`。全部由 `registry.manifests('operator')` 生成，`NO_DEFAULT` 移到 kernel。
- **七段技能自动生成**：`operator_manifest()` 从必填框推导模板与前置/步骤/失败/验收；人工只写“何时用/别用”。
  生成 `docs/capabilities/operators/<id>.md`（契约说明）与 `docs/capabilities/skills/operators/<id>.md`（七段正文），
  `skill_catalog`/`skill_load` 直接可检索；`knowledge.prompt_lines` 只放节点 L1（算子已在合法词汇表逐条列出）。
- **形状检查不再写死在共享模块**：`bin_time` 的边界/名称数量检查由清单 `checks=` 引用，`step_checks` 只负责调用。
- **验证**：`analysis`/`ai`/`capabilities`/`gates`/`frontend contract`/`api analysis` **3332 passed**；ruff
  check/format 全绿；product 与 tests pylint **10.00/10**；`tools/doctor.py` 全绿（含 artifacts）。
- **未做**：把算子参数的中文标签搬进清单（面板表单仍是 `panels/node-analysis.js` 的 `if op == …`）；
  图表与平台两类清单化；算子级 `preflight`（数据样本检查）。

## 已完成（每个一类改动一个 commit）

| 提交 | 内容 |
|---|---|
| `6d368ebd` | P6 第一片：16 个节点能力技能七段内容、L1/L2 目录、`skill_catalog`/`skill_load`、生成页面与门禁 |
| `adc60e3e` | P6 第二片：`@` 引用接缝（技能/工作流/导出/回答引用、候选交错合并），框架 0.1.23 |
| `d8104301` | P6 第三片：RecipeFSM（证据步骤、工具遮罩、用户跳步）、两条产品配方与 `/recipes` API，框架 0.1.24 |
| `f661b4a8` | P6 第四片：配方进度条与跳过（输入框上方，状态只来自服务端） |
| `d46b8a1b` | P6 第五片：严格模式工具预算（本地供应商 12 个工具，控制/核心/配方步骤必留），框架 0.1.25 |
| `50ca1505` | P7 第一类：37 个分析算子清单化（契约/读写形状/策略/七段技能；analysis 旧表全部改为投影） |
| `f272770a` | P7 第二类：30 个图表类型清单化（字段/引擎/文献列/七段技能；registry 改为投影，绘图函数公开为 handler） |
| `6a8c4025` | P7 第三类：10 个采集平台清单化（模式/字段/登录与机器要求/七段技能；值类型搬进 kernel，爬虫类成为 handler） |
| `a36c997a` | P7 七表面一致性门禁（每类能力 × 每个表面双向断言）+ OpenAPI 图表/平台 schema |
| `9c8fddf2` | P7 多表面：MCP server（stdio，3 个工具）与能力 CLI（list/show/validate），门禁新增两条表面 |
| `7e1652a4` | 面板清单化（第一半）：算子下拉改由 `NodeTypes.operators()` 渲染，删掉 `ANALYSIS_OPS` |
| `6e5fd4c` | 待答问题按 `question_id` 恢复；服务端派生 `message_id`；多选答案写入状态 |
| `28d9820` | 本地 Ollama 全局强制 `think:false`；过滤残留 thinking/think 标签；UI 开关禁用 |
| `1b69457` | 架构 ADR、问题台账、实施计划、5 个架构技能 |
| `f5b0c91` | 新消息不再取消待答问题；有待答问题时按名拒绝（邮箱在 P4） |
| `84b1a0c` | 侧栏按实测宽度布局；列宽随 dock 夹紧；12px grip + pointer capture；流式重绘恢复 scrollTop |
| `d8a7d55` | Python 节点显示脚本/参数；补全 `python`/`fuse` 标题 |
| `ab1285d` | 放宽 AI 输出/工具结果/回合/表格读取限制；0=不限；表格单页 2000 |
| `0c965b8` | LLM 行任务可配置并发；API 并行；Ollama 串行 |
| `279ed41` | agent-workspace parity 矩阵 |
| `5e038bd` | 附件文本抽取（pdf/docx/pptx/xlsx/csv/txt/html，缓存）；`files`/`vision`/`inline_images` 三能力拆分；图片内联；本地/无 key 供应商可上传；`pypdf` 依赖 |
| `438723e` | 数据集行读取授权：`request_dataset_access` 走暂停/恢复问题通道；会话+数据集+行数 grant；`dataset_page`/`sample`/筛选查询累计；`peek` 免费；侧栏列出/撤销 |
| `702705e` | 工作流/导出管理工具：list/read/update/rename/delete/export/run/stop + export_list/delete；删除强制审批+审计；停止与 HTTP 共用 `engine.run.stop_run` |
| `a00e89b` | `ai.coverage` 能力→AI 入口矩阵（节点/平台模式/算子/图表/工具）+ `ai_coverage` 工具 + 门禁（可反向失败） |
| `b3dbfb3` | `ChartSpec.required_params` 声明 `stack_fields`；`WorkflowEngine.validate_detailed` 在运行前按名报告，默认值先填充 |
| `33b738a` | 覆盖矩阵只统计内置工具，插件工具不算产品能力 |
| `0361be1` | 回归测试对齐：新消息在待答问题期间按名拒绝；stack_pct 在 validate 阶段拒绝 |
| `b54c5a0` | 测试复用已导入的 `store`，修 pylint 重复导入 |
| `44dcb01` | `setPointerCapture` 抛错不再中断侧栏拖拽；真实 Chrome 层验证 |
| `1c52910` | H11-H16 收口基线（10646/14:06、device 213/5:54、lint、冒烟） |
| `dad5d55` | H17/H18：`#ai-chat` 拆成 `#ai-transcript` + `#ai-panel`；转录按 `turn_id`/消息 id 复用；流式气泡跨重绘与 A→B→A 复用；`harness_dom.appendChild` 改为浏览器语义（移动而非复制） |
| `a8420a1` | P1 第一片：`capabilities_kernel` 九段清单 + registry 投影；`tokenize` pilot；声明式验证改由 `services/validation/engine.py` 求值 |
| `55329a7` | P1 第二片：`tools/gen_capabilities.py` 五类产物、`tools/doctor.py`、生成物 freshness gate |
| `ef5b789` | P1 第三片：`runtime/fsm.py` 四张状态机表 + recipe 工厂；`runtime/events.py` 字段契约 + AST 调用点 census |
| `afc7d34` | P1 第四片：`runtime/flags.py` 迁移开关与到期门禁；`core/asset.py` 的 `DataAsset` 骨架 |
| `7a5f660` | 生成的前端目录从 `static/js` 移到 `generated/capability-schema.json`（全量快测的前端门禁拒绝无人加载的模块） |
| `0086cca` | P2 第一批：manifest 增加 `validators` 与 `no_input`/`requires_output`；name/upload/compile/output 迁移，engine 删除对应 if 分支 |
| `77731f2` | P2 第二批：resume/process/python 迁移；process 的 operation/tokenize 检查移到 validator |
| `68b8f49` | P2 第三批：analysis/accumulate/verify 迁移；engine 不再导入行形状集合 |
| `d59d65b` | P2 第四批：visualize/fuse 迁移；fuse 参数错误改为 code/message_key 数据 |
| `45dd0be` | P2 第五批：comment 迁移；账号会话检查从 engine 移到 `sessions/preflight.py` |
| `14938f8` | P2 第六批：biblio 迁移；56 参数与 10 组选项表由清单派生，`schema.py` 不再保留第二份 |
| `6ce014e` | 第二轮死代码清理：移除 15 个 executor 的 `NODE_TYPE`、无调用函数/方法/常量/helper（AST 扫描逐项确认） |
| `cd6cdc2` | P2 第七批：source 迁移；`_source_errors`/watermark 检查搬入 executor，`session_errors` 删除 |
| `109cb3d` | P2 前端第一片：`/api/node-types` 与生成的 `node-types-fallback.js` 同源；canvas 删除类型/标签/默认值字面表 |
| `d72b0a62` | P2 前端第二片：`/api/workflow/validate` 成为唯一运行门；删除 `runs.js` 校验 if 链与 `sourceNodeErrors` |
| `2f6e21cf` | P2 前端第三片：process/biblio 选项表改读清单枚举；`node-types.js` 幂等加载 |
| `64dede4e` | P2 前端第四片：清单 `ui` 选择表单；`openSettings` 删除逐类型分支；通用 schema 渲染器 + 注册表；设备层禁用节点用例等待服务端诊断 |
| `1be81060` | P3 第一片：`ChartSpec.fields` 成为面板/校验/血缘/AI 目录的单一来源；验证条目带 `param`/`severity`/`fix`；设置面板一键修复与字段描红 |
| `429b5cfd` | P3 第二片：`Manifest.preflight` + 同指纹上游样本（≤200 行、30 秒缓存）；图表缺列/非数值列在 validate 阶段命名；诊断/validate/运行门接线 |
| `43caa638` | P3 第三片：`node_schema` 记录生产者真实列集合 + `schema_hash`；`contracts.columns_for` 记录优先、声明兜底；引擎按 `read_columns` 报 `engine.missing_column`（warning）；前端删除差集，诊断不再返回 `reads` |
| `ec8faf20` | P3 第四片：`Manifest.postcheck`（`postcheck(node, rows, inputs)`）；运行循环在节点 DONE 后打一行控制台，不改状态；analysis 非空输入产出 0 行报 `engine.empty_output` |
| `8b6cc478` | P4 依赖：`vendor/agent_workspace-0.1.0-py3-none-any.whl` 钉版；`requirements.txt` 以仓库根相对路径引用；`deploy/Dockerfile` 复制 `vendor/` 并从 `/app` 安装；requirements 门禁校验 wheel 名/METADATA/唯一声明 |
| `31b3c9ba` | 框架升到 0.1.1：`HostAdapter.turn_finished(summary)` 轮次完成通知（桌面弹窗/提示音的宿主接缝）；wheel 替换并更新 sha256；P4.0 增加 F17 |
| `47496d0` | 框架 0.1.2（ADR-003 第一片）：`fsm.py` TurnFSM；`turns`/`turn_events`/`pending_calls`；answer 按 `call_id` 幂等并复用原 turn；重启保留待答问题、收尾半途 turn |
| `e99a6d8` | 框架 0.1.3（ADR-003 第二片）：后台 `TurnRunner` + `subscribe(after)`；关流不停轮；`EVENT_PROTOCOL=1`；`turn_commands` 持久 stop；`bind_account`；`/turns/<id>` 与 `/turns/<id>/events` 重连路由 |
| `30d1d5d` | 框架 0.1.4（ADR-003 第三片）：`turn_inbox` 邮箱——待答期间的新消息排队、`notice(turn.queued)`、带 `mailbox_id` 再发才执行 |
| `4c506e0` | 框架 0.1.5（ADR-003 第四片）：`steer` 安全边界插入指引；最后边界之后的指引进邮箱；`/steer` 路由 |
| `57dd1c9` | 框架 0.1.6（F6）：`policy.PolicyEngine` + `ToolSpec.always_ask`；删除/覆盖/资源授权永远人批且不接受 session 授权 |
| `82a4a081` | wheel 0.1.6；rewrite-plan 勾选 F6；handoff/README 记录第五片，下一步 F12 |
| `f0283b8` | 框架 0.1.7（F12）：`agent_steps` 工具步骤 + 幂等重放；崩溃遗留 `running` 标 `interrupted` 且不再执行；`/turns/<id>/steps` |
| `f21b5e8` | 框架 0.1.8（F13）：`HostAdapter.tools()` 构造时注册；重名按 `tool.builtinConflict` 拒绝 |
| `61d8952` | 框架 0.1.9（F8）：多问题卡 `questions[]`（1–5），一张卡一次答复，答案按 `call_id` 对齐 |
| `cd7eda6` | 框架 0.1.10（F9）：`agent_mode=plan` 遮罩写入工具（schema + 允许列表 + 执行处），meta 带 mode |
| `1df4f91` | 框架 0.1.11（F3）：`retry` 从 user 行所属 turn 恢复 provider/model/skill，复用已存上下文块，不新增 user 行 |
| `2511b09` | 框架 0.1.12（F10）：附件接缝（宿主抽取文本/内联图片，框架按能力路由）；修复用户消息在每次 provider 请求中被重复追加 |
| `e2a60b3` | 框架 0.1.13（F11）：`ArtifactRegistry` + HostAdapter 校验/预览声明；提案与 apply 各校验一次，未声明 kind 标 `unvalidated` |
| `5f99f6a` | 框架 0.1.14（F14）：`agent_traces` OTel GenAI span + trace 树；best-effort、无正文 |
| `13d9937` | 框架 0.1.15（F15）：`structured_output` 能力 + `output_schema`；OpenAI 兼容映射 `response_format`，未声明按名拒绝 |
| `8ed62f4` | 框架 0.1.16（F16）：`chat_once` 按供应商限流（`max_parallel`/设置/本地串行） |
| `cc589d3` | 框架 0.1.17（F18）：`CommandRegistry` + `/status` `/skills` `/mode` `/compact`；host 可注册 `/init`，重名拒绝 |
| `aef340c` | 修复 trace 顺序：按 rowid 插入顺序，避免同一微秒的 span 排序漂移 |
| `22f9ef51` | wheel 0.1.17；rewrite-plan 勾选 F18，P4.0 全部完成；handoff/README 记录第十五片与 P4 接入 |
| `c8a1278f` | P4 接入第一片：`backend/ai_host` 的 `CaiXiHuiHost`（facts/tools/skills 委托旧注册表）；门禁加入 ai_host；运行库带 vendored wheel |
| `809fe5c9` | P4 接入第二片：`CaiXiHuiHost.artifact_validators()` 委托 `ai.validators`（memory/workflow/workflow_draft） |
| `6c894ccb` | wheel 0.1.16；rewrite-plan 勾选 F16；handoff/README 记录第十四片，P4.0 只剩 F18 |
| `fa7d965d` | wheel 0.1.15；rewrite-plan 勾选 F15；handoff/README 记录第十三片，下一步 F16 |
| `c6d392d7` | wheel 0.1.14；rewrite-plan 勾选 F14；handoff/README 记录第十二片，下一步 F15 |
| `3708da31` | wheel 0.1.13；rewrite-plan 勾选 F11；handoff/README 记录第十一片，下一步 F14 |
| `aa8bb1af` | wheel 0.1.12；rewrite-plan 勾选 F10；handoff/README 记录第十片，下一步 F11 |
| `6fdb5712` | wheel 0.1.11；rewrite-plan 勾选 F3；handoff/README 记录第九片，下一步 F10 |
| `c23175bf` | wheel 0.1.9；rewrite-plan 勾选 F8；handoff/README 记录第七片，下一步 F9 |
| `06aa5735` | wheel 0.1.8（含 F12/F13）；rewrite-plan 勾选 F12/F13；handoff/README 记录第六片 |
| `6f49c40e` | wheel 0.1.4；rewrite-plan 勾选邮箱、留出 steer；handoff/README 记录第三片 |
| `5b2281ff` | wheel 0.1.2；AGENTS/architecture README 增加“每次先读架构文档”；补 ADR-002 的 custom_renderer 门禁与文档哈希说明；rewrite-plan 勾选 TurnFSM/重启恢复，补 R10 与双路径开关 |
| `860e6e85` | 删除 `nodes/catalog.py` 空置的旧字面表 `_DECLARED` 与 `_with_kernel_nodes`；16 个节点全部由清单投影 |

## P1 第一片：能力内核 + tokenize pilot（2026-11-22）

- `backend/capabilities_kernel/`：九段 `Manifest`（identity/params/ports/execution/rules/ui/ai/tests/docs）、
  结构校验 `problems()`、SHA-256 `digest()`；`ROW_SHAPES` 等词汇在这里，`nodes/catalog.py` 不再保留第二份。
- `registry`：`<kind>/<id>.py` 或 `<id>/manifest.py` 两种家，目录名即 id；重复 id、未知 kind、api_version 不符、
  kind/id 不一致、不完整清单都在读取时**按名拒绝**；`node_entries()` / `node_defaults()` 是目录投影，
  `register_node_executors()` 把 handler 注册进 `nodes.registry`（所以 `registered_types() == NODE_TYPES` 仍成立）。
- 旧表面改读：`nodes/catalog.py` 按 `identity.order` 插回原槽位（tokenize 仍在 index 8）；`nodes/defaults.py`
  取 `ParamSpec.default`；`engine/workflow.py` 的 tokenize if 分支换成 `services/validation/engine.py`
  的声明式规则；血缘钩子由 `ports.emit_columns/read_columns` 解析到 executor 自己的函数。
- pilot：`backend/capabilities_kernel/nodes/tokenize/manifest.py`；`tests/unit/capabilities/test_tokenize_manifest.py`
  逐项钉住“旧家不再有答案”（catalogue/defaults/validate/hooks）。
- 门禁：`tests/unit/gates/test_capability_completeness.py`（结构/执行器/端口/文档/契约测试/双语词/清单轻导入/生成物 fresh）；
  `test_doc_paths` 与 `test_requirements_pinned` 的包清单已加 `capabilities_kernel`。
- 生成物：`tools/gen_capabilities.py` 渲染 `catalog.json`（目录 + 测试矩阵）、`openapi.json`、
  `ai_tools.json`、`capability-schema.json`、`docs/capabilities/index.md`；`--check` 与门禁共用
  `generate.check()`。`tools/doctor.py --all` 逐项打印 `[x]`，未知 `--capability` 也是失败行。
  前端表单目录先放在 `capabilities_kernel/generated/`：全量快测的 `test_frontend_page_scripts_js` 拒绝
  “没有页面加载的 static/js 模块”，P2 真正接页面时再移入 `static/js` 并注册到 `index.html`。
- `runtime/fsm.py`：`RUN`/`NODE`/`TURN`/`VIEW` 四张表 + `recipe_machine(steps)`；构造时拒绝不连贯表，
  `require()` 对非法移动按名拒绝；`tests/unit/foundation/test_fsm.py` 穷举全部状态对。
- `runtime/events.py`：四个运行事件的字段类型契约；`publish()` 校验后交给 `run_events` 总线；
  `tests/unit/gates/test_event_contract.py` 用 AST 检查现有调用点与 `ai/monitors.py` 的订阅词汇。
- `runtime/flags.py`：`Flag(name/owner/remove_by/description/default)`；`active()` 读 `CIXI_FLAG_*`（空值取默认，
  非布尔按名拒绝），`problems()` 把过期/无 owner/非法日期变成门禁失败；`tests/unit/gates/test_flags.py` 用合成开关
  证明门禁能红。当前 `FLAGS` 为空——P1 的两个 pilot 都是单路径切换。
- `core/asset.py`：`DataAsset`（id/kind/owner/origin/sha256/size/uri/parents/meta/schema）与 `from_dict`/`to_dict`；
  只导入标准库，供 P2 的运行库、节点、API、AI 共用。`services/components` 的 `Asset` 是可下载组件载荷，不是同一种。
- 文档：`docs/architecture/capabilities-kernel.md`、`docs/capabilities/nodes/tokenize.md`、ADR-001/ADR-003 的 P1 落点。
- 本片验证：相关模块 `2048 passed`（analysis/gates/runs/executors/capabilities + node-types/workflow API）；
  全量快测 `10789 passed, 7 skipped, 386 deselected, 1 failed`（14:16），失败项是“前端目录是无人加载的
  static/js 模块”，已改为 `generated/capability-schema.json` 并单跑通过；ruff 全绿；product pylint 10.00/10、
  tests pylint 10.00/10；`test_boot_import_budget` 9 passed。
- P1 清单已全部落地；下一步进入 P2（15 个节点迁移 + schema 表单 + 删除前端第二套规则）。

## P2 第一批：name / upload / tokenize / compile / output（2026-11-22）

- manifest 验证段扩展：`Rule` 新增 `no_input`/`requires_output`；`Manifest.validators` 指向能力目录自己的
  `module:function`。`services/validation/engine.py` 新增 `ValidationContext`（父节点、连线、标签、数据输入），
  并同时求值声明规则与 validators。
- 迁移：`name`（头部/命名/下游三条规则）、`upload`（dataset_id 必填 + 数据集列钩子）、`compile`/`output`
  （父节点形状检查移到 executor 的 `validate_node`）、`tokenize` 保持。`engine/workflow.py` 删掉这五个节点的
  验证 if 分支；`nodes/catalog.py` / `nodes/defaults.py` 的字面表只剩 11 个未迁移节点（顺序与槽位不变）。
- 失败语义：validator 抛错、返回非 list、缺 code/message_key、非法 severity/context 都变成
  `engine.validator_failed` 并有 zh/en 文案；`/api/workflow/diagnostics` 不 500，其他徽章仍显示。
- 门禁：completeness gate/doctor 增加 validators 可解析；生成物矩阵增加 `validators` 检查项。
- 测试：`tests/unit/capabilities/test_{name,upload,compile,output}_manifest.py`、
  `test_validation_engine.py`；`tests/unit/analysis/test_node_plugins.py` 不再把 `PDF_SOURCE_NODE_TYPES`
  钉在 engine 上（它已随保存/编译的校验移入能力目录）。
- 本片验证：相关用例 `245 passed`（capabilities + node plugins/schema + workflow/node-types API）、
  `1262 passed`（workflow API + runs/charts/biblio/frontend node-types + capabilities）；ruff 全绿；
  product pylint 10.00/10、tests pylint 10.00/10；生成物 `--check` 通过、doctor 全绿。
- 未做（P2 后续）：`source`/`resume`/`comment`/`process`/`python`/`analysis`/`biblio`/`verify`/`fuse`/
  `accumulate`/`visualize` 的清单；schema 表单渲染器；删除 `canvas.js`/`runs.js` 的第二套规则；executor 搬进能力目录。

## P2 第二批：resume / process / python（2026-11-22）

- `process` 用 `validators=('nodes.executors.process:validate_node',)` 保留 `process_no_op` 与
  `tokenize_no_column`；节点对象上的 `operation` 与 params 里的都接受。`engine/workflow.py` 删除这两条 if。
- `python` 只声明脚本 id/args/timeout/max_rows 与“本地可运行”的契约；云模式/空脚本/坏 args 仍由 executor 按名拒绝。
- `resume` 刻意没有必填规则：空 run/node 是“自动选择最新可恢复运行/最满节点”的合法路径。
- 三个节点的 catalogue 槽位（3/5/6）与默认参数不变；`nodes/catalog.py` 剩 8 个未迁移类型。
- 本片验证：`156 passed`（capabilities + node plugins/schema + executors）、`585 passed`
  （workflow/node-types API + runs + capabilities）；ruff 全绿；product/tests pylint 10.00/10；生成物 --check 通过。

## P2 第三批：analysis / accumulate / verify（2026-11-22）

- `analysis`：`steps` 或 operation 之一存在即可；`analysis_no_op` 移到 `validate_node`，emit/read 钩子继续由执行器回答。
- `accumulate`：名字/identity/键列/恰好一个表父节点全部移进 validator；`emit_columns` 仍返回上游合并列。
- `verify`：两个数据父节点（命名节点不计）与两个键列移进 validator；`read_columns` 继续回答血缘。
- `engine/workflow.py` 删除这三段 if；`TABLE_NODE_TYPES` 从此不再被 engine 导入（行形状检查已随
  accumulate/compile/output 的 validator 走），契约测试改为只钉 `NODE_TYPES`。
- 本片验证：`181 passed`（capabilities + node plugins/schema + executors）、`1770 passed`
  （analysis + workflow/node-types API + runs）；ruff 全绿；product/tests pylint 10.00/10；生成物 --check 通过。

## P2 第四批：visualize / fuse（2026-11-22）

- `visualize`：chart_type/x_field/ChartSpec.required_params 移进 `nodes.executors.visualize:validate_node`；
  engine 删除整段图表校验与 `NO_X_TYPES` 导入。`read_columns` 继续回答图表字段与文献固定列。
- `fuse`：输入要求变成声明规则 `upstream_required`；参数错误由 `services.biblio.fuse.collect_problems` 返回
  `{code,message_key}`，validator 求值；`collect_errors` 仍是给直接调用者的已本地化句子。
- `nodes/catalog.py` / `nodes/defaults.py` 只剩 `source`/`comment`/`biblio` 三个未迁移类型。
- 本片验证：`196 passed`（capabilities + node plugins/schema + executors）、`1293 passed`
  （charts/biblio + workflow API + runs + capabilities）；ruff 全绿；product/tests pylint 10.00/10；生成物 --check 通过。

## P2 第五批：comment（2026-11-22）

- 账号会话检查从 `engine/workflow.py::_account_session_errors` 移到 `sessions/preflight.py`：
  `session_problems()` 返回 `{code, message_key, context}`，`session_errors()` 是给 source 节点（尚未迁移）
  用的已本地化句子版本。source 的 `_source_errors` 改调后者，engine 里不再有这段逻辑。
- `comment` 清单：`urls` 必填规则 + `validate_node`（对链接涉及的每个平台问一次账号会话，@pool 问池，
  CatBus 不问 Cookie）。表单声明为 `ui.form='custom'` / `custom_renderer='comment'`，因为它的账号/楼中楼/
  时间过滤表单本来就是自定义面板。
- `engine/workflow.py` 删除 comment 的 if 分支；`nodes/catalog.py` / `nodes/defaults.py` 只剩
  `source`/`biblio` 两个未迁移类型。
- 本片验证：`229 passed`（capabilities + pool + node plugins/schema）、`850 passed`
  （node-types/workflow API + runs/workflows/sessions + 前端 node-types + completeness）、
  `1334 passed, 4 skipped`（crawlers + executors + node matrix）；ruff 全绿；生成物 --check 通过。

## P2 第六批：biblio（2026-11-22）

- `biblio` 的 56 个参数、10 组选项表与默认值搬进 `capabilities_kernel/nodes/biblio/manifest.py`；
  `services/biblio/schema.py` 的 `DEFAULTS`/`ENTITY_TYPES`/`OUTPUT_SHAPES`/… 全部由清单派生，不再有第二份。
- 参数校验改成 `collect_problems()`（`{code, message_key, context}`）+ `collect_errors()`（同一份数据的句子版，
  供 `normalize_params` 直接调用者）；数值范围集中在 `RANGE_CHECKS`，选项集中在 `OPTION_CHECKS`。
  `biblio` 的“无上游/多上游”检查移到 executor 的 `validate_node`，`engine/workflow.py` 删除整段 biblio 分支与
  `biblio_param_errors` 导入。
- 清理随迁移失效的代码：`nodes.catalog`/`nodes.defaults` 只剩 `source`；`services.biblio.fuse.collect_errors`
  与 `name.execute_name_node` 删除（前者由 `collect_problems` 取代，后者是只被 `run` 调用一行的转发）。
- 本片验证：`704 passed`（capabilities + biblio + node plugins + frontend contract + biblio/node-types API）、
  `622 passed`（frontend js + 门禁 + runs）；ruff 全绿；product/tests pylint 10.00/10；生成物 --check、doctor 全绿。

### P2 最后一个节点：source

- `source` 的清单不声明参数：字段是平台 × 后端 × 模式的矩阵答案，清单用 `ui.defaults_from='capabilities'`
  让客户端问矩阵；`nodes/defaults.py` 的 `DYNAMIC_DEFAULTS` 字面表随之删除，改由 `NodePlugin.defaults_from` 传播。
- `engine/workflow.py::_source_errors`（约 100 行）、watermark 分支整段删除；同一套判断搬进
  `nodes/executors/source.py::validate_node`，返回 `code/message_key/context` 数据，`engine.workflow` 只保留
  唯一的清单校验循环。
- `sessions/preflight.session_errors()` 删除（迁移后无调用者），`tests/unit/pool/test_pool_contracts.py`
  改问 `session_problems()` 的数据。
- 契约测试：`tests/unit/capabilities/test_source_manifest.py`；文档：`docs/capabilities/nodes/source.md`。

## P3 第二片：样本 preflight（2026-11-23）

- `Manifest` 第九段之外新增可选 `preflight='module:function'`（ADR-002 的 `preflight(node, sample)`）；`problems()`
  拒绝不是 `module:function` 的引用，`doctor.py` 增一行 `preflight`，`generate.MATRIX_CHECKS` 与完整性门禁同步枚举。
- `services/validation/samples.py`：`samples_for(workflow)` 只给声明了 preflight 的节点取样本——
  - 上游是它的**数据父节点**（name 节点是元数据，不算数据），
  - 取“当前节点指纹”下最近一次已结算运行（`done`/`partial`/`restored`/`failed`）的 ≤200 行，
    由新 `run_store.sample_rows(node_id, fingerprint, limit)` 的 SQL `LIMIT` 读取（不物化整张表）；
  - 任一上游没有同指纹的存储运行 = 没有样本，不猜；多个上游按引擎 fan-in 顺序拼接；
  - 缓存键 `(该账号 runs.db, 节点 id, 指纹)`，TTL 30 秒、上限 32 项；命中返回浅拷贝行。
- `WorkflowEngine.validate_detailed(samples=None)` / `validate(samples=None)`：引擎不读数据库，调用方给样本；
  没有样本的节点不调用 preflight。`/api/workflow/diagnostics`、`/api/workflow/validate` 与运行门
  （`engine.run._preflight_samples`）都传入；读样本失败只记一条 `run.preflightSamplesFailed`，当作没有样本。
- `nodes.executors.visualize:preflight` → `chart_preflight()`：同一 `ChartSpec.fields` 的 role。只报能证明的事实：
  - 点名的列不在样本里 → `engine.chart_column_missing`（多半是改名）；
  - 数值/坐标/堆叠列有非空值却一个数字都没有 → `engine.chart_column_not_numeric`（与 builder 的 `chart.y_not_numeric` 同规则）；
  - 空样本、全空列、饼图负值、热力图最终格数都不下结论（builder 仍在运行期拒绝），写在函数 docstring 里。
  - 钩子抛错/返回畸形 → `engine.preflight_failed`（不 500，其它节点继续）。
- 测试：`tests/unit/charts/test_chart_preflight.py`（30 图型 × 合格样本；每个数值角色 × 文本列；改名/空样本/未知图型/
  默认列）；`tests/unit/runs/test_validation_samples.py`（数据父节点、多上游拼接、name 不取、指纹/账号缓存键）；
  `test_run_store.py::TestPreflightSampleRows`（最新已结算运行、指纹不匹配、running/skipped 不取、LIMIT）；
  `test_visualize_manifest.py` 与 `test_diagnostics.py` 钉端到端（引擎纯函数 + 路由接线 + 样本读取失败仍 200）；
  `engine.run._preflight_samples` 的通过/失败两例。
- 本片验证：全量快测 `11118 passed, 7 skipped, 386 deselected`；设备层 `215 passed, 5 skipped`；ruff 全绿；
  product/tests pylint `10.00/10`；`gen_capabilities.py --check`、`doctor.py --all` 全绿；隔离 data root 冒烟：
  种入一条同指纹的上游运行后，`POST /api/workflow/validate` 返回 `engine.chart_column_missing`（`param=x_field`），
  列存在时无条目。
- 第三片把缺列判定移到数据契约（`engine.missing_column`），`engine.chart_column_missing` 已删除；样本只保留
  “数值列没有数字”的值检查。

## P3 第四片：运行后数据质量断言（2026-11-23）

- `Manifest.postcheck='module:function'`（可选）：节点结算为 DONE 后调用 `postcheck(node, rows, inputs)`——
  本次真正产出的行 + 真正收到的上游表。`problems()` 拒绝非 `module:function` 引用；`doctor.py` 增一行
  `postcheck`，`generate.MATRIX_CHECKS` 与完整性门禁同步枚举。
- `services.validation.engine.postcheck_problems` 复用 validator 的归一化与坏钩子处理；钩子抛错报
  `engine.postcheck_failed`。运行循环在“节点完成”之后调用 `engine.run._postcheck_node`，每条 finding 走
  `add_log(t(message_key, nid, **context))`，随运行日志持久化。
- **只上控制台，不改状态**：行已经产出并存好，质量结论不能让完成节点变失败；下游该跳过仍跳过。
- 第一个使用者 `analysis`：非空输入产出 **0 行**报 `engine.empty_output`（warning）；含
  `filter_rows`/`join_tables`/`anti_join` 的流水线豁免（0 行是用户要的答案），输入为空由运行循环按“跳过”处理。
- 测试：`tests/unit/analysis/test_analysis_postcheck.py`（0 行/扁平与 steps 形状/豁免/非空/空输入）；
  `tests/unit/runs/test_run_postcheck.py`（每个 finding 一行、无钩子不打印、未知类型、dict 结果按无行）；
  `tests/unit/capabilities/test_validation_engine.py::TestThePostcheck`（归一化/坏钩子/畸形结果）；
  `test_analysis_manifest.py` 钉钩子身份；`tests/api/test_nodes_execution.py::TestTheAfterRunDataCheck`
  端到端：`drop_null` 把全空列清成 0 行，节点仍 done、控制台出现 `drop_null` 的警告行。
- 本片验证：全量快测 `11173 passed, 7 skipped, 386 deselected`；设备层 `215 passed, 5 skipped`；ruff 全绿；
  product/tests pylint `10.00/10`；`gen_capabilities.py --check`、`doctor.py --all` 全绿；端到端 API 用例
  （`drop_null` 清空全空列）证明节点仍 done、控制台出现警告行。

## P3 第三片：数据契约（2026-11-23）

- 生产者结算时记录真实输出形状：`run_store.finish_node(..., schema=rows)` 把列并集写进新表 `node_schema`
  （排序后的 `columns_json` + `schema_hash`）；读取按 `node_fingerprint` 匹配，指纹变化时 `begin_node` 删除、
  `invalidate_nodes`/`delete_run` 一并释放；空表不写形状（空输出不是“没有列”的证据）。
- `services.validation.contracts.columns_for(workflow)`：在有效图上取“记录优先、声明兜底”的 `{节点: 列|None}`；
  store 读失败只丢记录的一半并记 `run.schemaReadFailed`，`compute_columns` 的插件错误仍由诊断路由按原有 `ok:false` 处理。
- `WorkflowEngine.validate_detailed(samples=, columns=)`：每个声明了 `ports.read_columns` 的消费者，把所有数据父节点
  （name 不算数据）的列取并集，读列表里不在并集里的列按名报 `engine.missing_column`（warning：上徽章，不拒绝运行；
  节点仍在运行期按名失败）；任一父节点未知就沉默；读钩子抛错报 `engine.read_columns_failed`。诊断、
  `/api/workflow/validate` 与运行门接线，引擎仍不读数据库。`validate()` 只保留 error，`validate_detailed()` 含 warning。
- 图表缺列从样本 preflight 移到数据契约：同一缺列不再出现两条徽章；样本只保留数值角色检查。旧运行没有
  `node_schema` 时，爬虫→图表这一段要等下一次运行才裁决（声明已知的生产者不受影响）。
- 前端：`Diagnostics` 删除 `_reads`/`inputColumns`/`missingColumnProblems`，只渲染 `validation.perNode` 与
  `problems`；`/api/workflow/diagnostics` 不再返回 `reads`；`nodes.schema.referenced_columns` 删除（读取声明归清单）。
- 测试：`test_run_store.py::TestNodeSchema`（排序/摘要/指纹/最新/空形状/stale/invalidate/delete）；
  `test_validation_contracts.py`（记录优先、声明兜底、有效图、store 失败）；`test_validation_engine.py::TestTheColumnContract`
  （缺列/未知上游/name 父节点/无父节点/坏钩子）；`test_workflow_engine.py`（运行门 helper 与引擎接线）；
  `test_diagnostics.py`（不再有 reads、契约与样本各自接线）；前端 harness 场景改为“服务端条目才产生徽章”。
- 本片验证：全量快测 `11140 passed, 7 skipped, 386 deselected`；设备层 `215 passed, 5 skipped`；ruff 全绿；
  product/tests pylint `10.00/10`；`gen_capabilities.py --check`、`doctor.py --all` 全绿；隔离 data root 冒烟：
  种入一条同指纹运行（`schema=['X']`）后，`x_field=不存在的列` 返回 `engine.missing_column`（warning，`messages` 为空），
  `x_field=X` 无条目，`/api/workflow/diagnostics` 的 `columns.p=['X']` 且不再返回 `reads`。

## P3 第一片：图表契约与一键修复（2026-11-23）

- `services/charts/registry.py` 的 `ChartSpec` 新增 `fields`（`FieldSpec`：参数名、角色、是否必填、表单标签/占位/提示键、
  挂在其下的聚合控件）、`any_of`（箱线图 x 或 y 至少一个）、`controls`（字段之外的控件）、`hint_key`、
  `tokenize_compatible`；`no_x` 改为从 `fields` 派生，`required_params`（H16 的临时规则）删除。
- 30 种图型全部声明字段：柱/折线的 x+y、双轴的 y2、占比堆叠的 `stack_fields`、主题图的 pc1/pc2、散点/直方图的数值列、
  热力图的双分类、桑基/关系图的来源目标、词云的文本列、地图的地区列、模型一致率的三列、文献计量的固定 reads。
- 同一张表派生三个表面：
  - `chart_profiles()` → `/api/node-types` 的 `charts` + 冷启动 `node-types-fallback.js` + `capability-schema.json`；
    `node-types.js` 新增 `charts()`/`chart(key)`（深拷贝）。`panels/node-chart.js` 删除 `CHART_TYPES`/`BIBLIO_CHARTS`/
    `CHARTS_NO_Y`/`CHARTS_WITH_Y2`/`CHART_X_LABEL_KEY` 等 11 个手写数组与标签映射，按 profile 画框、控件与提示。
  - `chart_problems()` → `nodes.executors.visualize:validate_node` 只调用它；未知图型 `engine.chart_unknown`（声明默认
    值作为 fix）、缺字段 `engine.chart_field_missing`（带 `param`）、至少一个 `engine.chart_field_group_missing`；
    `engine.visualize_no_chart`/`engine.visualize_no_x` 删除（空白图型就是清单默认的 `bar`，执行器一直如此）。
  - `read_columns()` 从同一 `fields` 派生（模型一致率的三列现在也参与缺列检查）。
- 验证条目新增 `severity`/`param`/`fix`；`fix` 形如 `{'set': {参数: 值}}`，只允许顶级参数。首个真实修复：
  `engine.chart_unknown` → 声明默认图型、`engine.output_needs_pdf` → `format=pdf`；清单 `enum_param` 越界且有默认值时也
  自动带 fix。设置面板在节点问题列表里为带 fix 的条目画“一键修复”按钮（`applyValidationFix` 走 `updateParam` 再重问服务端），
  并把被点名的字段框描红。
- 测试：`TestRequiredFieldsReachValidation` 遍历 30 种图型（填满契约→无问题；逐个清空必填→按名报告；有默认值→不报；
  未知图型→带 fix）；面板场景新增 scatter/heatmap/stack/dual/未知图型/文献图/一键修复；冷启动目录带图表 profile 且深拷贝；
  `engine.visualize_no_*` 从后端目录与测试清单删除。
- 本片验证：全量快测 `11066 passed, 7 skipped, 386 deselected`；设备层 `215 passed, 5 skipped`；ruff 全绿；
  product/tests pylint `10.00/10`；`gen_capabilities.py --check`、`doctor.py --all` 全绿；隔离 data root 冒烟
  10 个 GET 全 200，`/api/node-types` 30 个图表 profile，`POST /api/workflow/validate` 对 heatmap 缺列与未知图型
  返回带 `param`/`severity`/`fix` 的条目。

## P2 前端第四片：表单由清单选择（2026-11-23）

- `Ui` 新增 `hint_key`；`ParamSpec` 新增 `label_key`/`placeholder_key`，并把 `description_key` 接到通用表单。
  `form='schema'` 的清单必须为每个参数声明 `label_key`（`problems()` 按名拒绝），`ui.hint_key` 是表头说明。
- 13 个有手写面板的节点在清单里声明 `ui.form='custom'` + `custom_renderer`：`source`/`comment`/`upload`/
  `resume`/`process`/`analysis`/`tokenize`/`biblio`/`verify`/`fuse`/`accumulate`/`visualize`/`output`。
  `name`/`compile` 留在 `schema`，由通用渲染器按清单画。
- `panels/settings.js::openSettings` 删除整条 `node.type === …` 分支链，只做一次
  `settingsRenderer(node.type)` 分派；各模块用 `registerSettingsRenderer('<id>', {html, mounted})` 注册自己的表单：
  settings.js（source/comment/accumulate/tokenize/output/resume/upload/process）、
  `panels/node-*.js`（analysis/biblio/fuse/visualize/verify/python）、`reusable.js`（reusable）。
- `mounted` 收拢了原先三个按类型执行的挂载动作：resume 填运行列表、upload 拉数据集、process 拉 Ollama 标签。
- 通用渲染器支持 `text`/`textarea`/`number`/`select`/`switch`/`column`/`dataset`/`json`；标签、占位、说明全部来自清单键，
  选项表仍是清单 enum。
- 失败按名：目录未加载 `settings.noCatalogue`、类型不在目录 `settings.unknownType`、清单点名了未注册渲染器
  `settings.noRenderer`；面板不画空表单。`reusable` 不是能力，按类型名注册，保持原来的模板边界表单。
- 测试：`TestSettingsPanel` 新增 `name`/`compile`/未知类型场景；`TestSettingsRenderers` 让每个 custom 清单 id 与注册项
  一一对应，并断言 `openSettings` 不再有类型链；完整性门禁检查 `hint_key`/`label_key`/`placeholder_key`/
  `description_key` 的双语词。
- 设备层回归：`test_a_disabled_node_goes_grey_and_its_downstream_says_so` 原先直接调 `Diagnostics.recompute()`；P2 第二片后
  编辑期判定来自 `/api/workflow/diagnostics`，用例改为 `await Diagnostics.refresh()` 后再测量（禁用/启用各等一次应答）。
- 本片验证：全量快测 `11034 passed, 7 skipped, 386 deselected`；设备层 `215 passed, 5 skipped`；ruff 全绿；
  product/tests pylint 10.00/10；`gen_capabilities.py --check`、`doctor.py --all` 全绿；隔离 data root 冒烟 10 个
  GET 全 200、`POST /api/workflow/validate` 200。

## P2 前端第三片：选项表来自清单（2026-11-23）

- `process` 清单的 `operation` 声明 16 个 enum 值；`panels/settings.js` 的 `PROCESS_OPS` 数组删除，
  面板在渲染时读 `NodeTypes.params('process')`。
- `panels/node-biblio.js` 的 10 个手写选项数组（实体、选择、连线、计数、剪枝、寻径、标签、输出形态）删除，
  统一由 `biblioEnum(name)` 读 `NodeTypes.params('biblio')` 的 enum；工作区 `panels/biblio.js` 也读同一处。
- `node-types.js` 改为幂等全局（`var NodeTypes = window.NodeTypes || {...}`）：一个 harness 可能通过两条
  companion 路径读到同一模块，重复求值不再触发 `Identifier 'NodeTypes' has already been declared`。
- `splits.json` 让 workflow/settings 侧也能拿到目录；测试改为断言面板读清单，而不是逐字比较两份数组。
- 本片验证：全量快测 `11012 passed`；ruff、两档 pylint、生成物 freshness、doctor 全绿。

## P2 前端第二片：校验单一来源（2026-11-23）

- `/api/workflow/validate` 返回 `engine.workflow.validate_detailed()` 的 `messages`/`perNode`/`entries`；
  `/api/workflow/diagnostics` 的同一份 payload 也带上 `validation`，编辑期徽章与运行门读同一套规则。
- `panels/runs.js` 删除整段本地校验 if 链（约 290 行）与 `workflow.js::sourceNodeErrors`（约 120 行）；
  `workflow.validate()` / `validateDetailed()` 改为一次服务端调用，网络失败按名报“无法校验”，不伪装成干净画布。
- `panels/diagnostics.js::recompute()` 读服务端 `validation.perNode`；分析算子的参数徽章仍由浏览器措辞。
- `i18n/checks.js` 只保留仍在前端渲染的词（analysis 参数 + `validate.unavailable`），60 余个只服务于旧 if 链的键删除。
- 测试：删除 `TestValidateGate`/compile/PDF/model_agreement 的 JS 规则用例（Python `WorkflowEngine` 用例已覆盖），
  harness 不再断言本地规则；运行管理/画像/Cookie 门/面板场景改为提供 `/api/workflow/validate` 的应答。
- 新增 API 用例：诊断 payload 的 `validation`、独立 validate 端点、干净画布通过。

## P2 前端第一片：目录单一来源（2026-11-23）

- `/api/node-types` 与生成物 `backend/static/js/node-types-fallback.js` 现在读同一个投影
  `capabilities_kernel.registry.node_schema_entries()`：每个节点带 `params`/`rules`/`ports`/`ui`，
  前端不再有第二份类型表或默认值表。
- `canvas.js` 删除 `_VALID_NODE_TYPES`、`_META_ONLY_TYPES`、`addNode` 的标签表和
  `getDefaultParams` 的全部字面分支；只剩 `source`（矩阵）与 `reusable`（前端模板）两个真实例外。
- `node-types.js` 从生成的 `window.NODE_TYPE_CATALOGUE` 冷启动（懒读，顺序无关），失败时保留它并报出原因；
  `index.html` 在 `node-types.js` 之前加载该脚本。
- `splits.json` 声明 `canvas.js → node-types.js → node-types-fallback.js`，所有 canvas harness 自动获得
  与页面一致的目录。
- 测试改钉生成物：`test_node_plugins.py` 解析 fallback 并对比 `NODE_TYPES`/rows/seeds；
  `test_frontend_node_types_js.py` 驱动真实画布验证冷启动、失败保留与深拷贝。
- 当时未做：schema 表单渲染器；已在“P2 前端第四片”完成（`openSettings` 只做一次 `ui` 分派）。

## 测试基线（H11-H16 收口，2026-11-22）

- 全量快测：`10646 passed, 7 skipped, 384 deselected, 1 warning in 846.06s (14:06)`。
- 设备层：`-m "integration or live_ollama"` → `213 passed, 5 skipped, 10820 deselected`，5 分 54 秒；
  H4/H5 的 pointer capture 回归就是这一层发现的，已修。
- lint：`ruff check` / `format --check` 全绿；`ci_lint_tiers.py product` 10.00/10；
  `ci_lint_tiers.py tests` 10.00/10。
- 冒烟：隔离 data root 在 5057 启动，9 个基础 GET + 5 个 AI GET 全部 200；进程已停、端口已释放。
- **未跑**：`live_quick`/`live_site`（花用户账号；需要用户指定网络并同意）。
- H17/H18 之后又全量跑过一次：`10651 passed, 7 skipped, 386 deselected, 1 warning in 836.93s (13:56)`；
  两个新增的 device 用例（面板面 / 切会话单消息区）单跑通过。之后按用户要求改为按改动范围测试。

## 测试策略（用户 2026-11-22 明确要求）

- **小改动只跑改动到的地方**：相关模块的 pytest 用例 + 前端 harness + 受影响的 device 用例；不再每次都全量。
- **攒一批或做大改动后才跑全量**：`python -m pytest -q`、全量 device、两档 pylint、冒烟。
- **不要为仪式感测试**：能用一条针对性用例证明的行为，不重复铺三层。
- 本次 H17/H18 已做过一次全量（10651 passed / 7 skipped / 386 deselected / 13:56）；之后的 P1 切片先按需测试。

## 硬性约束：不留残骸

重构/迁移完成后旧实现必须删除，不留“兼容层”：一个事实只允许一处声明（默认值、选项表、验证分支、句子都是），
迁移完成即删旧函数/旧分支/转发别名/只为旧路径存在的测试/没人 import 的模块。每片收口包含一次“本片是否新增了重复”
的检查；发现历史死代码顺手删除。详见 `docs/architecture/rewrite-plan.md` 开头与 `docs/agent_practices.md`。

2026-11-22 已删（随 P2 迁移失效）：`name.execute_name_node`、`fuse.collect_errors`、
`registry.register_many`、`nodes/executors/__init__.py` 里 15 个迁移类型的第二条注册表（现在由清单注册，
该文件只剩尚未迁移的 `source`）；AI 重写留下的无调用函数 `_current_thinking`、`_abandon_pending`、
`ensure_dirs`、`attachments_payload`、`abandon_questions`、`list_steps`、`thinking_block`/
`tool_use_block`/`tool_result_block`、`ProviderReply`、`context_section`。

2026-11-22 第二轮死代码清理（AST 全仓库扫描，逐项人工确认）：
- 迁移残骸：15 个已迁移 executor 的 `NODE_TYPE`（清单已声明类型；`source` 迁移后最后一个也删掉）、
  `nodes/catalog.py` 的 `plugin_for`/`types_in` 与 `nodes/__init__.py` 的再导出（无人按名字使用）、
  `nodes/defaults.py` 的空 `_DECLARED` 与合并函数（直接投影清单）。
- 无调用取名字/兼容读：`core/machine.py` 的 `driver_executable_name`/`node_executable_name`/`_installer_export`
  与 `DRIVER_FILE_NAMES`；`crawlers/engine/pacing.py` 的 `pace_scale`/`page_scale`/`gentle_crawl_on`
  与 `_PAUSE_DIMENSIONS`（`page_nap` 仍读 `crawl_page_scale`，所以设置项保留；`crawler_rules.md` 已改指 `nap`）。
- 无人引用的 helper：`services/biblio/formats/common.py` 的 `split_affiliations`/`refs_payload`/`has_columns`/
  `header_has`/`parse_ref`；`services/components/install.py::verify_component`；
  `services/models/manifest.py::is_legacy_manifest`；`ai/plugins.py::manifest_json`。
- 无引用方法：`EmotionAnalyzer._train_ml`、`Crawler.scroll_to_bottom`、`PlayerUI.wait_window`、
  `XiaohongshuCrawler._extract_count`、`FilesMixin.forget_run_files`。
- 无引用常量：`GRAPH_KEYS`、`SCORE_MODES`、`doctor.CHECKS`、bilibili `REPLY_API`、cnki `ROW_PAUSE`、
  xhs comments `OPENER_RE`、`RESTART_KEYS`/`CRAWL_KEYS`、`DIVERGING_CMAP`/`SEQUENTIAL_CMAP`、`STATE_CANCELLED`。
- 保留（扫到但确认在用）：`services/charts/options/relations.py` 的 `_model_agreement`/`_sankey`（`@builder`
  装饰器注册，名字不在调用点出现）；`services/biblio/formats/*` 与 `i18n_catalog/sched.py`（按注册表/列表加载）。
- 本片验证：2324 passed（capabilities/analysis/biblio/crawlers/charts/update/ai/node-types API），
  208 passed（node plugins + node-types API + capabilities），ruff 全绿。


## P6 第五片：严格模式与工具预算（框架 0.1.25，2026-11-24）

- **问题**：37 个领域/通用工具平铺给任何模型，本地 4B/9B 一次要看全部 schema，选择准确率下降、
  提示词也变贵。
- **做法**：`ToolSpec` 目录新增 `HostAdapter.core_tools()`；`ToolRegistry.schemas()` 接受
  `query`/`limit`/`required`，预算生效时**控制工具 + 核心工具 + 当前配方步骤工具**必留，其余按用户原话
  与工具名/描述的关键词重合排序（中文二元组），截到 12 个。`tools.strict_local`（默认开）让
  **本地供应商（`local_only`）自动严格**，强模型仍是完整列表——这是决策 9，不新增 UI 开关。
- **产品**：`CaiXiHuiHost.core_tools()` 返回 `UNIVERSAL_TOOLS`（项目/工作流/文件夹/数据集授权/产物等
  每轮都可能用到）；配方步骤工具通过 `required` 保证不被裁掉。
- **测试**：框架 `tests/test_tool_budget.py`（默认设置、控制/核心/命中工具保留、无关工具被裁、
  配方步骤保留、0=全量）；产品 `TestStrictMode`（核心工具集合与默认设置）。
- **验证**：框架全量 + ruff 绿；产品 AI/API/requirements 子集 **177 passed**；ruff 绿。
- **未做**：可调预算的设置项与 UI（当前固定 12）；每轮工具使用情况的可见面板（H23）。

## P6 第四片：配方进度条与跳过（前端，2026-11-24）

- 输入框上方新增 `#ai-recipe` 步骤条：标题、`第 n/N 步`、每步记号（✓ 完成 / ● 当前 / ↷ 跳过 / 失败色）；
  状态**只来自服务端**——`recipe` 事件实时更新，切换会话时 `GET /recipes?conversation_id=` 重读，完成即隐藏。
- “跳过此步”只调 `POST /recipes/skip`，不推进本地状态；服务端把用户选择记为 `skipped`，工具证据不会被伪造。
- 双语键 `ai.recipe.progress`/`ai.recipe.skip`；CSS 用现有 token，无新主题；`node --check` 通过。
- 测试：真实 `ai-workspace.js` + DOM stub 新场景（可见/3 步/当前 1/完成 1/进度 2/3/跳过按钮与调用；
  完成状态隐藏），前端用例 **82 passed**。
- **未做**：从面板**开始**新配方（当前由模型 `recipe_start` 或 API 开始）；每节点配方随 P7。

## P6 第三片：配方 FSM 与工具遮罩（框架 0.1.24，2026-11-24）

- **框架 `agent_workspace/recipes.py`**：宿主声明有序步骤（每步一个工具 + 前序 `requires` + `produces`），
  框架持久化 `recipe_runs`/`recipe_evidence`；`mask()` 在运行中只下发**当前步骤工具 + 只读工具 +
  永远要人批的工具**；步骤完成只认服务端拿到的工具结果，失败留步，`recipe_skip` 把用户主动跳步记为
  `skipped`（最终报告可见）；未知配方/未知工具/前向依赖/重复 id 都在注册或开始时按名拒绝。
- **回合接线**：`ChatRequest.recipe_id` 开始或续用配方；每轮按当前步重新计算工具集；越步调用返回
  `recipe.stepTool`（带步骤名与应有工具）；工具成功即写证据并推进，事件 `recipe` 让前端重画进度；
  `recipe_start`/`recipe_skip` 是控制工具（任何技能可用，没配方时按名拒绝）。
- **产品配方**：`ai/recipes.py` 声明 `workflow_build`（读词汇 → 提交工作流产物卡 → 同一引擎校验）与
  `dataset_answer`（列/类型 → 样本 → 精确聚合）；项目事实新增“配方”段，模型知道何时 `recipe_start`。
  API：`GET /api/ai/ws/recipes`、`POST /recipes/start`、`POST /recipes/skip`。
- **顺带修掉的回归**：上一轮删除“框架同名工具”时 `apply_workflow` 其实没有框架实现，导致提示词让模型调用
  一个不存在的工具、`UNIVERSAL_TOOLS` 里留有悬空名字。现改回 `present_artifact(kind="workflow")`（卡片
  Apply 保存并载入），提示词、配方、门禁同步；真正的 `apply_workflow` 工具要等产物应用端点统一后再恢复。
- **测试**：框架新增 `tests/test_recipes.py`（目录/首步/遮罩/证据/失败留步/跳步/结束/未知/冲突/跨回合）；
  产品 `tests/unit/ai/test_recipes.py` 与 `GET /recipes` API 用例；requirements 钉版随 0.1.24 更新。
- **验证**：框架全量 + ruff 绿；产品 AI/API/i18n/requirements 子集 **298 passed**；产品 ruff 绿；本批全量 fast
  **11019 passed / 1 failed**——唯一失败是新增的两个 POST 路由没有登记进 body 拒绝矩阵，已补 `recipes/start|skip`
  并单跑 hardening **449 passed**（按新策略修复后只重跑受影响面）。
- **未做（明确声明）**：配方前端面板（进度条/跳过按钮）与每节点配方（随 P7 清单化）；`apply_workflow`
  作为独立产物应用端点恢复；工具分层路由（每轮 ≤12）与严格模式仍待做。

## P6 第二片：@ 引用接缝（框架 0.1.23，2026-11-24）

- **修复两个静默断裂**：`/api/ai/ws/references` 曾返回 `candidates` 而浏览器读 `references`（`@` 菜单始终为空）；
  composer 挑中的 chips 只进 payload，框架只解析正文 token（挑中的引用从未到达模型）。现在路由用 `references` 键；
  框架 `References.resolve_rows()` 展开 chips，`/chat` 把 chips 与正文 `@kind:id` 合并进同一预算（去重，不重复展开）。
- **回答框的引用也成立**：`answer(references=…)` 把展开文本作为该次工具结果的 `reference_text` 交回同一回合；
  空正文 + 只有引用的消息可发送（H21 已修）。
- **宿主种类**：框架 0.1.23 增加 `HostAdapter.reference_candidates()` / `resolve_reference()`；`CaiXiHuiHost` 提供
  能力技能 / 工作流 / 导出，并补上此前从未接的 `resolve_dataset()` / `resolve_run()`（旧 `@dataset`/`@run` 一直解析为空）。
  `ai/reference_text.py` 负责每种对象的有界文本：数据集形状 + 3 行、运行 20 行控制台尾、工作流节点图与连线、
  导出前 4000 字、技能正文与 `skill_load` 同一渲染。
- **前端**：`ai.ref.skill`/`artifact`/`conversation` 双语标签；菜单仍按 kind 显示。
- **框架**：wheel 0.1.23；新增 `tests/test_references.py`（候选合并/过滤、token 与 chips、重复不展开、未知项、
  只有引用、回答引用）。**候选交错合并**：宿主返回很多技能/工作流时不再把用户自己的文件挤出 20 条上限（全量跑里
  唯一的失败项，已用复现用例钉住）。
- **产品测试**：`test_reference_text.py`、host 引用接缝、`/references` 路由形状、requirements 钉版。
- **验证**：框架全量绿 + ruff 绿；产品 AI/API/i18n/frontend/requirements 子集 **371 passed**；本批全量 fast
  **11012 passed / 1 failed**（即上面的排序缺陷），修复后仅重跑受影响子集（按新测试策略，不再重复全量）。
- **未做（明确声明）**：算子/图表/平台技能要等 P7 清单化；配方 FSM、工具分层路由与严格模式仍是 P6 待办。

## P6 第一片：能力技能目录（L1/L2）与七段内容（2026-11-24）

- **清单第七段成为技能的唯一家**：`Ai` 新增 `when_not_to_use`/`prerequisites`/`template`/`acceptance`；
  16 个节点清单全部补齐七段（何时用/何时不用含最近可混淆能力、前置、步骤、示例、模板、失败、验收）。
  `Manifest.problems()` 对 `node` 拒绝缺段、模板 `type` 不符、模板参数超出枚举。
- **派生而不是复制**：`capabilities_kernel/knowledge.py` 投影 **L1**（id/分组/一句话/何时用/何时不用/文档）
  并渲染 **L2** 正文（七段 + 参数表 + 可达工具）；参数表在渲染时从 `manifest.params` 重读（测试改默认值
  验证正文随之变化）。`ai/knowledge.py` 只加本地化标题与 `AIError` 具名拒绝。
- **两个常备工具**：`skill_catalog`（`kind`/`query`/`limit`）与 `skill_load`（正文 + 模板 + 工具名）进入
  `UNIVERSAL_TOOLS`，任何技能都能用；未知 kind 报 `ai.skillKindBad`，未知技能报 `ai.skillUnknown`。
- **项目事实只放 L1**：`project_facts()` 增加“能力技能”一节（每技能一行摘要），正文按需展开，不占系统提示。
- **生成物**：`gen_capabilities.py` 额外生成 `docs/capabilities/skills/index.md` 与每能力一页；页面与
  `skill_load` 共用 `knowledge.render`，`docs/capabilities/` 也加入 `docs_search` 的文档根。
- **门禁/测试**：完整性门禁要求七段并证明模板可被引擎接受（不得产生参数/矩阵拒绝）；生成物 freshness 覆盖
  新页面；新增 `tests/unit/capabilities/test_skill_catalog.py`、`tests/unit/ai/test_knowledge_tools.py`；
  `test_generate.py` 的固定产物集合改为“六个固定产物 + `docs/capabilities/skills/` 下的能力页”。
- **验证**：按 2026-11-24 用户要求，小改动只跑相关域、不再每次全量——AI/能力/门禁/i18n **937 passed**，
  同一批更早的 api+frontend+i18n **4638 passed**；`gen_capabilities.py --check` 通过；ruff 全绿；
  product/tests 两档 pylint **10.00/10**。本片按新策略没有跑全量 fast（留给下一批收口）。
- **测试策略（同时写入 AGENTS/practices/testing-lanes）**：小改动只跑它碰到的域 + 命名它的门禁；全量 fast 只在
  大改动、跨域改动或一批（约 4 刀）收口时跑一次；已经证明过的文件不为文档换行重跑。
- **未做（明确声明）**：算子/图表/平台技能要等 P7 把这三类清单化；配方 FSM、工具分层路由与严格模式仍是 P6 待办
  （`@` 引用已在下一片完成）。

## P4/P5 收口：旧 AI 引擎与蓝图已删除（2026-11-23）

- **删除**：`backend/api/ai.py`；`backend/ai/agent.py`、`store.py`、`costs.py`、`approvals.py`、
  `approval_preview.py`、`references.py`、`plugins.py`；`runtime/flags.py::ai_workspace`（已无在途开关）；
  `api/ai.py` 的 `_workspace_conversation` 过渡桥。对应的 `tests/api/test_ai_*.py` 旧引擎用例随模块删除，
  有价值的覆盖改写为直接单测/新表面用例。
- **`backend/ai` 只留领域事实**：providers、context（项目事实+文档搜索）、skills（BUILTIN）、tools（领域工具）、
  validators/previews、vocabulary/workflow_draft、workspace（文件夹选择器+表格导入）、monitors（事件词汇）、
  file_text、dataset_access、files（搜索/抓取）、errors/types/scopes/environment。
- **宿主编排补齐（0.1.22）**：`CaiXiHuiHost` 现在提供 `environment()`（cloud/desktop/local）、`bind_account`
  （账号树 + 线程语言）、`search/fetch`（浏览器密钥随请求到工具上下文）、`import_table`、`script_library`、
  `python_runtime`（画布与 AI 共用一个脚本库/解释器）、`universal_tools`、`event_bus`（把
  `runtime.run_events` 映射为框架监视事件）、工具权限门（cloud/python/机器管理员）。
- **修复的真实缺陷**：
  - 新表面 `account()` 曾把 `Account` 对象的 repr 当账号 id（登录账号的路径全错），已改为 `user_id`。
  - 监视器 POST 旧前端发 `spec`，新路由只读 `conditions`（手动建监视器从不生效）；现在在 host 边缘把
    `spec` 规范化成框架 conditions，并把 armed/active、交付行映射回前端形状。
  - 数据集读取授权（`request_dataset_access`）改为“永远询问”的审批工具：用户批准后落 grant，行数仍按
    `dataset_access` 预算扣减；不再存在模型自行授权。
  - 工作文件夹只有一个根：`/workspace` GET/POST 与工具都用框架 workspace；browse/pick 只做机器选择器，
    非管理员按名拒绝。
  - `/stop` 与删除会话会同时结束该会话 scope 的子进程（进程面板 parity）。
  - POST 体规则统一：非对象 JSON 一律 400（`api/ai/ws/*` 全部纳入 body 矩阵）。
- **前端**：保持不变，只把请求切到 `/api/ai/ws`（`AI_BASE` + 47 处调用及 studio/watch/llm-settings/
  node-python/workflow）。实机浏览器用例（本地模型真实回答 + 实时行 + 停止）通过。
- **验证**：全量 fast **10964 passed**（7 skipped）；`ruff check`/`format --check` 全绿；product/tests 两档 pylint
  **10.00/10**；隔离数据根启动服务器（端口 5057）后 `/api/config`、`/api/ai/ws/health`、`/api/ai/ws/bootstrap`、
  `/api/node-types`、`/api/workflow/list` 均 200；本地 Ollama 经 `/api/ai/ws/chat` 一轮真实回答 37s（text/usage/done）。
  浏览器版 AI 实机用例本轮未能重跑：Selenium 启动在当前机器上挂起（无失败断言），此前同一前端切换已 2 passed。
- **仍未做（明确声明，不静默）**：
  1. 旧 `data/users/<id>/ai.db` 的历史会话/记忆/技能**不迁移**；新表面从空工作区开始。需要历史时用旧版
     本导出，本版本没有导入器。
  2. 框架的 `apply_artifact` 宿主钩子未实现写入；前端产物卡片走各自的类型端点（workflow/记忆/监控/图表），
     `/artifacts/<id>/apply` 直接调用时按名拒绝。


## P4 接入第五片：node trace 迁到框架 store（2026-11-23）

- `services/llm_trace.py` 不再写旧 `ai.db`：会话、intro、追问、流式行、样本、结果全部进 `AgentWorkspace`
  store；会话标题仍是 `run | node | op #n`，`traces_for_run` 按 run 前缀检索，`meta.skill=node_trace`。
- 工作区目录按账号解析：`ai_host.manager` 用 `paths.active()`（本地所有者）或 `paths.for_user(id)`，
  不再把 `default` 当账号 id。
- `/api/ai/ws` 增加 `GET /traces/<run_id>`、`POST /traces/<id>/apply`；会话详情返回 `skill` 供 trace 面板识别。
- 旧 `api/ai.py` 的 trace 列表已读新 store（同一 `services.llm_trace`），但打开会话仍走旧 store——前端切换时一并解决。
- 测试：框架 store 的 trace 用例（prompt/answer 行、run 检索、结果 provenance、传统模型样本）替换旧 sweep 用例；
  AI/analysis/API **1584 passed**。
- 下一步：前端切 `/api/ai/ws` → 删旧 `api/ai.py`/`backend/ai`/开关 → 旧 ai.db 历史。

## P4 接入第四片：host 端点补齐（2026-11-23）

- `/api/ai/ws` 补齐旧前端在用的 host 端点：workspace（GET/POST/browse/pick）、artifacts/preview、chart/preview、
  workflow/validate、rerun、monitors/catalog、python/install、plugins/install、codebooks、multipart 上传（文本/图片
  存入框架文件行 `meta`，chat 的 attachments 接受文件 id）。
- 框架 0.1.20：`add_file(..., meta=)`；0.1.19：`test_provider` 返回 model/latency/reply。
- 测试：上传→按 id 附件进模型、预览/图表/校验/重跑拒绝、codebooks/插件冒烟；蓝图用例 13 passed。
- **仍剩**：node trace（`services/llm_trace` 仍写旧 store，需迁到框架 store/turns）；前端切到 `/api/ai/ws`；
  删旧引擎与开关；旧 ai.db 历史。

## P4 接入第三片：新表面补齐通用路由（2026-11-23）

- `/api/ai/ws` 现有约 40 条路由：chat/turns/events/steps/trace、answer/stop/steer/retry/command、pending/inbox、
  bootstrap/providers、会话 CRUD+导出、记忆、产物+apply、技能/插件、监控+投递、文件、Python、设置、用量、上下文、
  引用、健康检查。账号来自 `account_context`，附件在 host 侧用 `ai.file_text` 抽取，`/init` 由 host 注册。
- 测试：聊天→turn→重放、关流后续跑、命令/停止/steer、附件进模型、会话/记忆/产物/设置/用量、通用路由冒烟；
  282 个 AI 相关用例通过。
- **仍未完成（P4 DoD 不勾）**：领域路由（traces/harness/workflow draft/codebooks）仍在旧 `api/ai.py`；旧引擎未删；
  旧 `ai.db` 历史未迁移；parity 矩阵未逐行补齐。

## P4 接入第二片：/api/ai/ws 新表面（2026-11-23）

- `backend/ai_host/manager.py`：每账号一个 `AgentWorkspace`，目录 `users/<id>/ai_workspace`（**不复用旧 ai.db**）；
  `close()` 先结束 runner 再关库。
- `backend/api/ai_workspace.py`：`/api/ai/ws` 的 `/chat`（SSE/非流式）、`/turns/<id>`、`/turns/<id>/events`
  （`after`/`Last-Event-ID`）、`/turns/<id>/steps|trace`、`/pending`、`/inbox`、`/answer` `/stop` `/steer` `/command`。
- `app.py` 在 `runtime/flags.py` 的 `ai_workspace` 开关（默认开，owner=P4 AI 接入，remove_by=2027-03-01）下注册；
  旧 `/api/ai` 原样保留。
- 测试：裸 Flask + 临时账号根跑通 chat → turn → 重放 → command / stop / steer / pending；旧 app 启动用例不受影响。
- 仍待：附件抽取、设置映射、`/init`、parity 矩阵、旧引擎删除。

## P4 接入第一片：ai_host 宿主适配器（2026-11-23）

- `backend/ai_host/`：`CaiXiHuiHost(DefaultHostAdapter)` 把领域事实/工具/技能以**委托**方式交给框架：
  `facts()` ← `ai.context.project_facts()`；`tools()` 逐条转换 `ai.tools.TOOLS`（handler 原样保留，`mutating`/
  `always_ask` 复用 `APPROVAL_TOOLS`/`ALWAYS_APPROVAL_TOOLS`）；`skills()` 转换 `ai.skills.BUILTIN`。
- 框架自带的同名工具（`project_facts` 等）不重复声明——框架的版本读同一份宿主事实；`FRAMEWORK_TOOLS` 明确列出。
- 门禁同步：`test_doc_paths._PROJECT_DIRS` 与本地包清单加入 `ai_host`；`desktop/requirements-runtime.txt` 声明
  vendored wheel，requirements 门禁从 wheel METADATA 取发行版名。
- 测试：全量工具/技能与旧注册表一一对应、审批标志来源、`AgentWorkspace(CaiXiHuiHost)` 能启动。
- **仍待**：路由迁移到 `AgentWorkspace`（`/chat` 返回 turn_id、`/turns/<id>/events`）、本地附件抽取、设置映射、
  `/init`、parity 矩阵、`runtime/flags.py` 双路径开关、薄门面与删旧引擎。

## P4.0 第十五片：命令与压缩（2026-11-23，框架 0.1.17 —— P4.0 收口）

- `CommandRegistry`：框架 `/status`（会话/最近 turn/pending/inbox/usage/mode）、`/skills`、`/mode`
  （写会话偏好，下一轮默认遵守）、`/compact`（清旧 user 行的 `context_text`，不改写转录）；宿主用
  `HostAdapter.commands()` 注册 `/init` 等，重名按 `command.duplicate` 拒绝。
- Flask 增加 `POST /command`（name/args/conversation_id）。
- 同一轮的两个 provider span 可能共享 `started_at` 的微秒，trace 树曾因此漂移；改为 rowid 插入顺序（`aef340c`），
  测试连跑 10 次稳定。
- **P4.0 至此全部完成（F1–F18）**。框架 0.1.17，220 条测试全绿。
- 下一步：P4 接入（`backend/ai_host`）——HostAdapter 领域实现、领域技能/工具、本地附件抽取、设置映射、`/init`、
  parity、双路径开关、薄门面。

## P4.0 第十四片：行任务并发（2026-11-23，框架 0.1.16）

- `chat_once` 走每供应商信号量：`ProviderSpec.max_parallel` → 设置 `providers.max_parallel`（默认 4）；`local_only`
  固定 1（一个守护进程、一次模型加载）。轮次内的工具调用仍在轮次线程上按序执行。
- 测试：设置上限、供应商上限覆盖设置、本地串行；213 条全绿。
- **P4.0 只剩 F18**：命令注册表 + `/status` `/skills` `/mode` `/compact`（`/init` 留 host）。

## P4.0 第十三片：结构化输出能力（2026-11-23，框架 0.1.15）

- `ChatRequest.output_schema`：只有声明 `structured_output` 的供应商会收到；OpenAI 兼容传输映射为
  `response_format={'type':'json_schema', …}`，未声明的按 `capability.refused` 拒绝（不拿散文冒充结构化结果）。
- `thinking` 继续同一规则；Ollama 不声明 `structured_output`，其 `think:false` 行为保持不变。
- 测试：声明者收到 schema、未声明者按名拒绝、OpenAI 传输映射、thinking 拒绝、Ollama 不声明；210 条全绿。
- 下一片：F16 并发 → F18 命令/压缩。

## P4.0 第十二片：OTel GenAI trace（2026-11-23，框架 0.1.14）

- `agent_traces`：每次 provider 调用与每次工具调用一行；属性用 `gen_ai.system`/`gen_ai.request.model`/
  `gen_ai.usage.*`/`gen_ai.tool.name`/`gen_ai.operation.name`，只含 id、状态、token 与耗时，**不含正文**。
- 工具 span 的 `parent` 是发起它的 provider span；`trace_tree()` 返回嵌套结构。`Tracing` 全部 best-effort：
  写失败只丢观测，不影响已经付费的轮次。
- 读接口：`traces(turn_id)`、`trace_tree(turn_id)`、`GET /turns/<id>/trace`。测试覆盖树形、无正文、崩溃 span 的
  `error`、trace 写入失败仍完成轮次；205 条全绿。
- 下一片：F15 供应商能力 → F16 并发 → F18 命令/压缩。

## P4.0 第十一片：产物校验与预览（2026-11-23，框架 0.1.13）

- `ArtifactRegistry`：`HostAdapter.artifact_validators()`（kind → `payload -> list[str]`）与
  `artifact_previews()`（kind → `payload -> dict`）在构造时注册。
- `present_artifact` 先校验：有问题 → 错误 tool_result `artifact.invalid`，**不落库**；通过后存库，事件带
  `preview` 与 `unvalidated`（未声明的 kind 如实标为未校验，交给宿主按纯文本渲染）。
- `apply_artifact` **再次**校验（payload 现在是什么就是什么），失败按名拒绝，宿主永远拿不到坏 payload；
  预览构建失败不影响卡片呈现。
- 测试：有效/无效/未声明 kind、apply 前复检、有效产物只交给宿主一次；201 条全绿。
- 下一片：F14 trace → F15 供应商能力 → F16 并发 → F18 命令/压缩。

## P4.0 第十片：附件接缝（2026-11-23，框架 0.1.12）

- `attachments.prepare()`：宿主通过 `context_payload['attachments']` 交来 `{name, text, image, file_id}`；文本有界并
  随 user 行持久化（块 + `meta.attachments`）；图片只在供应商同时声明 `vision` 与 `inline_images` 时以 OpenAI
  兼容的 image part 送入，否则按 `attachment.visionRequired` / `attachment.inlineRequired` 拒绝（超限另报
  `attachment.imageTooLarge`）。框架**不读文件、不解析文档**——抽取是 host 的事。
- `provider_messages` 会把 user 行的图片块还原成 content parts；`replay_context` 不再把多模态 content 字符串化。
- **顺带修掉一个真 bug**：user 消息在每次 provider 请求里被重复追加（存好的 user 行之后又拼了一遍）。现在只有
  `retry` 需要补一次（历史以旧回答结尾），新 turn 与 resume 都不补；附件测试断言一个 turn 只有一条 user 消息。
- 测试：文本附件、内联图片 + 重放、纯文本模型拒绝图片、有 vision 无 inline_images 拒绝、单一 user 消息；196 条全绿。
- 下一片：F11 产物 validator/preview → F14 → F15 → F16 → F18。

## P4.0 第九片：retry 还原原轮（2026-11-23，框架 0.1.11）

- `retry()` 用 user 行所属 turn 的 provider/model/skill 构造请求，而不是今天的默认值。
- 重试分支不再重建上下文：provider 历史由 `replay_context()` 把该 user 行自己的 `meta.context_text` 放回，
  重读实时 sources 会描述“现在”而不是被复现的那次运行；`meta.context.context_restored` 记录这一点。
- 不新增 user 行；测试断言三件套（provider/model/skill）与单一 user 行。框架 192 条全绿。
- 下一片：F10 attachment 接缝 → F11 → F14 → F15 → F16 → F18。

## P4.0 第八片：plan/build 模式（2026-11-23，框架 0.1.10）

- `context_payload['agent_mode']` = `plan` / `build` / 空；未知词按 `mode.unknown` 拒绝，meta 事件带 `mode`。
- plan 模式把 `mutating`/`always_ask` 工具从 **schema 与 allowed 列表**一起移除；`_dispatch` 的“未提供即拒绝”
  再挡一次，回放的历史也绕不过去。
- 测试：plan 隐藏/拒绝写入、build 默认、未知模式；框架 191 条全绿。
- 下一片：F3（retry 还原原轮），随后 F10 → F11 → F14 → F15 → F16 → F18。

## P4.0 第七片：多问题卡（2026-11-23，框架 0.1.9）

- `ask_user_question` 接受 `questions[]`（1–5）；单问题仍走旧的 `question`/`options` 形状。
- 多问题事件只带 `questions`（不伪装成单问题）；答案以与问题对齐的列表按同一 `call_id` 回填；长度不符报
  `question.answersExpected`。
- 畸形/超过 5 个返回 `badArgs`，并把错误结果写进转录——此前不写，会留下孤立 `tool_use`，现在由同一修复覆盖。
- 测试：schema、单卡两问、成组回答、长度不符、六个问题；框架 187 条全绿。
- 下一片：F9 plan/build → F10 → F11 → F14 → F15 → F16 → F18 → F3。

## P4.0 第六片：步骤幂等与注册收口（2026-11-23，框架 0.1.7/0.1.8）

- **F12**：`agent_steps` 每次工具调用一行（`running` → `done`/`error` + 结果），覆盖普通工具与审批后的执行；
  同一 `(turn_id, call_id)` 再次出现时重放记录，**不再执行**；启动把遗留 `running` 标为 `interrupted`
  （`{'error': 'step.interrupted'}`），下一次同样不重跑。`steps(turn_id)` 与 `/turns/<id>/steps` 可读。
  说明：框架的“run”就是 `turns` 行（一个生命周期对象，不新增第二张 run 表）；工作流 Run 仍是 host 域。
- **F13**：`HostAdapter.tools()` 在 `AgentWorkspace` 构造时注册一次；与内置/控制工具或另一个宿主工具重名按
  `tool.builtinConflict` 拒绝；技能白名单仍过滤工具。
- 测试：步骤记录/重放/崩溃恢复、宿主工具注册/重名拒绝；框架 182 条全绿。
- 下一片：F8 多问题卡 → F9 → F10 → F11 → F14 → F15 → F16 → F18 → F3。

## P4.0 第五片：审批策略（2026-11-23，框架 0.1.6）

- `agent_workspace/policy.py` 的 `PolicyEngine.decide(spec, auto=)` 是唯一判断点：读工具不询问；`mutating`
  在 auto-approve 关闭时询问；`always_ask`（删除/覆盖/资源授权）**永远**询问，`session_allowed=False`。
- `ToolSpec.always_ask` 由 host 在注册工具时声明；审批卡只提供“允许一次/拒绝”，`Approvals.consume(once_only=True)`
  拒绝 session 授权，`settle` 对未提供的 scope 不授予任何东西。
- 测试覆盖三类决策、伪造 session 答案、同一参数的一次授权、以及“下一轮再问一次”。
- 下一步：F12（`agent_runs`/`agent_steps` + 幂等恢复）→ F13（注册收口）→ F8…。

## P4.0 第四片：steer（2026-11-23，框架 0.1.5）

- `steer(conversation_id, text)` 写 `turn_commands`；runner 在**两轮之间**把指引作为一条 `user` 行加入本轮
  （`meta.steer`）并发 `steer` 事件——这是唯一不会把 tool_call 和它的 result 拆开的位置。
- 最后一个安全边界之后才到的指引进 `turn_inbox` 成为下一轮，不会被静默丢弃；没有活动 runner 时 `steer()` 返回
  `False`。
- Flask 增加 `POST /steer`；测试覆盖注入、事件、用户行与“无活动轮次”。框架 168 条全绿。
- ADR-003 的 turn 部分至此全部落地（TurnFSM、事件、runner、answer/stop/steer、邮箱、重启恢复）。

## P4 归属复核（2026-11-23）

rewrite-plan 的 P4 清单原先混着“框架通用能力”和“采析绘接入”。按“换一个宿主是否也需要”重新归类：

- **移到 P4.0（框架）**：SSE 续传/后台 turn、限制语义 0=不限 + usage meter、`/status` `/skills` `/mode` `/compact`
  （新增 F18；`/init` 仍留 host）、provider 结构化输出/thinking 能力声明、并发与限流、run/turn 记录与幂等恢复、
  权限策略引擎、OTel trace、多问题卡、plan/build、attachment 接缝、产物 validator/preview、retry 还原原轮。
- **留在 P4 接入（host）**：ai_host、领域技能/工具、工作流/产物/源码工具、本地附件抽取、设置项到框架语义的映射、
  `/init` 注册、旧前端事件名映射、parity 矩阵、双路径开关、薄门面。
- **共享但一侧一半**：`answer` 用框架 `call_id`，旧前端 `question_id`/`message_id` 的派生属 host 的 HTTP 层；
  附件由 host 抽取文本，框架只收结果。

## P4.0 第三片：邮箱（2026-11-23，框架 0.1.4）

- 待答期间发来的普通消息不再取消问题、也不再静默 settle：`ask()` 入 `turn_inbox`，返回
  `notice(key=turn.queued, mailbox_id)` + `done(stop_reason=queued)`，问题原样保留。
- `inbox(conversation_id)` 列出排队消息；客户端在问题答完后带 `context_payload={'mailbox_id': …}`（和自己的 Key）
  再发一次，服务端 `take_inbox` 取走一次后执行——排队不替用户花钱，Key 永不入队。
- 未知/已取走的 mailbox id 按 `turn.unknownMailbox` 拒绝；`delete_conversation` 一并清理。
- 仍开放：`steer`（安全边界插入指引）与 F6–F16。

## P4.0 第二片：轮次脱离请求线程（2026-11-23，框架 0.1.3）

- `ask()` 建 turn 后起后台 `TurnRunner`，自身只 `subscribe(after)`：关流、刷新、切会话都只结束订阅，答案仍落盘。
- 事件带 `seq` 与 `v=EVENT_PROTOCOL`；`subscribe(turn_id, after)` 与 Flask 路由 `/turns/<id>`、
  `/turns/<id>/events`（`after` / `Last-Event-ID` / `?stream=0`）提供重连与重放。
- `stop` 先写 `turn_commands`，runner 在轮次边界取走并置取消位；没有活动 runner 返回 `False`。`answer` 复用原
  `turn_id`，重复答案按 `question.unknown` 拒绝。
- `HostAdapter.bind_account(account)`：runner 线程启动先绑定账号数据根（线程继承不到宿主上下文）。
- `close()` 先停活动轮次并 join 再关 store——否则后台写会撞上临时目录清理（本片实测到一次 access violation）。
- 待答期间的新消息改为按名 `turn.awaitingUser` 拒绝，不再静默 settle 成 skipped；排队邮箱是下一片。
- 测试：163 条全绿（新增 runner/订阅/stop/bind_account/重连路由/关流不停轮）。

## P4.0 第一片：TurnFSM + 持久事件 + 中断恢复（2026-11-23）

按 ADR-003 先落数据模型，不先写 runner（避免“先做界面再改表”）：

- 框架 `agent_workspace/fsm.py`：`TURN` 表 `new→context→streaming→tool→awaiting_user→streaming→settled|interrupted`；
  `require()` 对非法移动按“机器名 + 两端状态”拒绝；测试逐对穷举合法/非法。
- `store.py` 新增 `turns`（状态/停止原因/解析后的 provider/model/skill）、`turn_events`（`seq = MAX(seq)+1`）、
  `pending_calls`（call_id/conversation/account/turn/kind/tool/args/provider/model/skill）。删会话时一并清理。
- `service.ask()`：每轮建行、逐事件落盘并推进状态；`answer()` 复用 pending 行的 `turn_id`，`_resume` 在同一把锁里
  `claim` 一次 → 重复答案按 `question.unknown` 拒绝；重启时 `settle_interrupted_turns()` 只收尾真正半途的 turn，
  `awaiting_user` 保留。新增公开读：`turn()`/`turn_events(after)`/`pending()`。
- 待答期间的普通新消息仍按旧行为 settle 为 skipped（邮箱是下一片）；`answer` 对已结算的 call 现在按名拒绝，不再
  静默开新轮。
- 同时补 ADR-002 的一个门禁缺口：`test_capability_completeness.py` 现在拒绝“清单指向浏览器未注册的
  `custom_renderer`”；`capabilities-kernel.md` 说明文档哈希由生成物 digest 承载（写回清单会让文档与清单互相绑架）。
- 仍开放：runner（脱离请求线程）、`turn_commands`（stop/steer）、邮箱、事件 `v`/`Last-Event-ID`、R10 Asset、
  `ai_host` 双路径开关。

### 对照 ADR-001/002/003 的复核（2026-11-23）

- **ADR-001**：P1–P3 都是逐域迁移，旧节点表已删除（`nodes/catalog.py` 现在只是清单投影）；P4 的“双路径开关”此前
  只写在 parity 文档的流程里，现已变成 rewrite-plan 的未勾选项，接入时必须在 `runtime/flags.py` 声明。
- **ADR-002**：九段、注册表、六类生成物与 freshness 门禁都在；**缺的两个门禁已处理**——自定义表单 renderer 现在
  会被门禁核对（浏览器里没有人 `registerSettingsRenderer` 的 id 直接红）；“文档哈希”按“生成物携带清单 digest”
  解释并写进 `capabilities-kernel.md`（写回清单是反向依赖）。技能七段属于 P6，保持未勾选。另删掉了
  `nodes/catalog.py` 里空置的旧字面表与合并函数——16 个节点全在清单里，旧表是残骸。
- **ADR-003**：TurnFSM、事件 seq、pending 持久化、重启恢复已落地；runner、命令表、邮箱、事件版本号仍未勾选，
  顺序写在 rewrite-plan。
- **R10**：`DataAsset` 仍只有骨架；`node_schema` 是形状半部，物化列入 P4 未勾选项，不能算 P3 已完成。

## P4.0 决策：框架先完善，再接入（2026-11-23）

用户追加约束：**AI 框架可能还不完善；先按通用标准把框架补到能承载采析绘的全部 AI 功能，再做接入。框架必须保持
宿主无关、可扩展、架构合理，不为采析绘加领域分支；允许重构，必要时重写单层。**

- 顺序：P4.0 框架完善（F1–F16，见 `framework-parity.md`）→ `backend/ai_host/` → `/api/ai` 薄门面 → 前端。
- 架构基准：保留 `AgentWorkspace` 门面与分层；把 `store.py`/`agent.py`/`tools.py` 的持久化、策略与循环拆成
  “端口 + 适配器 + `TurnFSM`”；某一层无法承载所需通用能力时重写该层、保留公开入口并升版本。
- 通用性门禁：框架仓库里不得出现节点/数据集/工作流/图表/平台等领域词；宿主只经 `HostAdapter` 注入。
- 依赖节奏：框架改动 → 框架测试全绿 → 重建 wheel（替换同一文件、更新 sha256）→ 本仓库 AI 测试 → 提交流程不变。
- 已完成：`8b6cc478` 把 wheel 钉版、`vendor/README.md`、requirements 门禁与 Docker 安装路径落好。
- 已完成 F17：框架仓库 `7323f2e` 新增 `HostAdapter.turn_finished(summary)`——每次 `ask()` 结束后一次，
  `completed`/`paused`/`cancelled`/`error`/`aborted` + ≤240 字预览；宿主据此做桌面右下角通知与提示音，框架不知道
  窗口焦点，钩子异常也不打断轮次。框架升到 0.1.1（139 个测试全绿），`vendor/` 已替换新 wheel。
  **采析绘接入时**：`ai_host` 覆写该方法，只在窗口不在前台或用户开了提醒时弹窗/响铃；不要在钩子里做网络或长任务。

## 下一步（按顺序）

1. **P3 第二片已完成**：`Manifest.preflight` + `samples_for`（≤200 行、指纹匹配、30 秒缓存）+ visualize 数据检查；
   验证条目带 `param`/`severity`/`fix`，设置面板有一键修复。见“P3 第二片”。
2. **P3 第三片已完成**：`node_schema` 记录生产者真实列集合 + `schema_hash`；`contracts.columns_for` 记录优先、
   声明兜底；引擎按 `read_columns` 报 `engine.missing_column`，前端删除差集。见“P3 第三片”。
3. **P3 第四片已完成**：`Manifest.postcheck` + 运行循环的控制台告警；analysis 0 行检查。P3 清单全部勾选。
   见“P3 第四片”。
4. **P4 依赖已完成**：wheel 钉版 + 门禁 + 镜像安装路径（`8b6cc478`）。
5. **P4.0 第一片已完成**：框架 `turn_finished` 通知（`7323f2e`，0.1.1）；ADR-003 的 TurnFSM + `turns`/`turn_events`/
   `pending_calls` + 幂等 answer + 重启恢复（框架 `47496d0`，0.1.2）。
6. **P4.0 第二片已完成**：后台 runner + 订阅续传 + 持久 stop + `bind_account` + 重连路由（框架 `e99a6d8`，0.1.3）。
7. **P4.0 第三片已完成**：邮箱（待答期间的新消息排队，带 `mailbox_id` 再发才执行）（框架 `30d1d5d`，0.1.4）。
8. **P4.0 已完成（框架 0.1.17，F1–F18 全勾）**。下一步进入 **P4 接入**：`backend/ai_host`（HostAdapter 的 facts/
   sources/tools/skills/resolvers/artifacts/UI）→ 领域技能/工具迁移 → 本地附件抽取 → 设置映射 → `/init` →
   parity → `runtime/flags.py` 双路径开关 → 删旧引擎/薄门面。R10 Asset 物化可以并行。


## H11 的关键落点（避免重复调查）

- `backend/ai/file_text.py`：`extract(name, data)`、`extract_attachment(row)`（缓存 `<local>.text.json`）、`image_payload(row)`（>8 MB 用 Pillow 缩到 4096px）。
- `backend/ai/agent.py::_attachment_plan`：有 `files` + `file_id` → 原生；否则本地抽取；图片只问 `vision`，无 `file_id` 时要求 `inline_images`，否则 `ai.imageNeedsUpload`。
- 新增设置 `ai_attachment_text_chars`（0=不限）；浏览器 `settings.js` 与后端 `settings_schema.py` 同步；`pypdf==6.1.1` 已进 `requirements.txt` 与 `desktop/requirements-runtime.txt`。
- 本地/无 key 供应商上传：`files.save_attachment` + 服务端上传后立即抽取；`.doc/.ppt` 按名拒绝，提示转 `.docx/.pptx`/PDF。

## H12-H16 的关键落点（避免重复调查）

- **H12 授权**：`backend/ai/dataset_access.py`（进程内 grant，键 `(会话, 数据集)`，`max_rows=0` 表示不限）；
  `request_dataset_access` 是 control 工具，走 `_dataset_access_event` → `_attach_question`；
  `answer()` 里先 `approvals.settle` 再 `dataset_access.settle`；`tools._dataset_rows` 是唯一的行消费口。
  API：`GET /api/ai/conversations/<id>` 带 `dataset_grants`；`DELETE …/dataset-grants/<dataset_id>`。
- **H13 管理**：`workflow_list/read/update/rename/delete/export/run/stop` + `export_list/delete` 在 `ai/tools.py`；
  `APPROVAL_TOOLS` 覆盖写操作，`ALWAYS_APPROVAL_TOOLS={'workflow_delete','export_delete'}` 绕过 auto-approve 强制审批；
  `engine.run.stop_run` 是 HTTP 与工具共用的停止实现（旧的 route 主体已移走）。
- **H14 覆盖**：`backend/ai/coverage.py`；入口集合是 `agent.UNIVERSAL_TOOLS` + `agent.FILE_TOOLS` + 技能 `tools`；
  插件工具 `ToolSpec.builtin=False`，不计入；门禁 `tests/unit/gates/test_ai_coverage.py` 可反向失败。
- **H16 图表**：`ChartSpec.fields` 是唯一声明（P3 起含字段角色/必填/表单标签）；`WorkflowEngine.validate_detailed`
  经 `chart_problems` 读它，先 `with_chart_defaults`；stack_pct 缺失时整张画布在运行前被 rejected，控制台按名给出 `stack_fields`。

## H17/H18 的关键落点（避免重复调查）

- `index.html` 的 `#ai-chat` 下有两个同级面：`#ai-transcript`（对话）与 `#ai-panel`（设置/工作室），CSS 里两者 `grid-area: 1/1`。
- `ai-workspace.js`：`_showPanel()` 只隐藏转录、`_showChat(refresh)` 拿回并可选重读会话；设置/工作室的所有 `innerHTML` 与
  面板内查询都走 `_dom.panel`（grep 找不到 `_dom.chat` 的面板写入即正确）。
- `_renderMessages` 协调 key：`message:<id>` / `turn:<turn_id>` / `row:<id>`；流式气泡在 `meta` 时打同一 key；
  `_streamTurnId` + `_streamConversation` 让“回到仍在流式的会话”接管存储的轮次元素。
- `_appendQuestion(question, turn)` 把卡片挂回提问那一轮，`blocks` 用该轮存储内容播种，回答后续写不会丢前文。
- `tests/frontend/harness_dom.mjs::appendChild` 现在是浏览器语义（已在树内的节点移动、不复制）；改协调逻辑前先看它。

## 压缩后必须保留的规则

1. **10 个已确认决策**（见 `docs/architecture/rewrite-plan.md#已确认的决策`）不得重新讨论，除非用户明确复议。
2. **一类改动一个 commit**；每个勾选项只在“代码 + 测试 + 文档/技能 + 门禁 + 收口”全过后打勾。
3. **自动压缩时机**：当预计剩余上下文不足以完成一个“代码 + 测试 + commit”的完整切片时，先收口当前切片、提交、更新本文件，再请求用户压缩；**不要在半成品上压缩**。压缩后从“下一步”继续。
4. **不要靠提示词保证行为**：能用服务端校验/工具遮罩/状态机/门禁的，必须用机制。
5. **不要在全量重写上打转**：内核替换 + 逐域迁移；旧路径只在数据丢失/安全级别热修。
6. **歧义必须问**，不要猜；用户语言是中文。
7. **关键路径**：`docs/architecture/`、`backend/ai/`、`backend/static/js/ai-workspace.js`、`backend/static/js/canvas.js`、`backend/runtime/settings_schema.py`、`tests/api/test_ai_workflow.py`、`tests/unit/frontend/test_frontend_ai_js.py`。
8. **测试按改动范围跑（用户 2026-11-22 要求）**：小改动只跑相关用例；攒一批/大改动再全量 fast + device + 两档 pylint + 冒烟。

## 给压缩后的第一句话

> 从 `docs/architecture/handoff.md` 的“下一步”继续；当前工作区干净，最后提交 `dad5d55`。先做 P1 内核骨架。
