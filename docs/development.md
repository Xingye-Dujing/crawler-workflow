# 开发与验证

> 本文是采析绘文档的一部分，返回总览见 [README.md](../README.md)。

项目结构（目录树）、如何训练传统 ML 模型、pytest 各测试层的运行命令与格式化钩子的坑。面向 agent 的测试不变量与改动流程见仓库根的 [AGENTS.md](../AGENTS.md)；逐条规则的真实证据（崩溃、实测数字）见 [agent_practices.md](agent_practices.md)，各平台实测契约见 [crawler_notes.md](crawler_notes.md)，真站验收矩阵与运行手册见 [live_test_plan.md](live_test_plan.md)。本文只保留人类可读的「每一层怎么跑」命令与说明。

## 项目结构

```
crawler_workflow/
├── backend/
│   ├── app.py                    # 引导（Flask 初始化 + 注册 25 个 Blueprint + 时钟接线 + 启动恢复）+ 1 条路由（页面）。执行/重跑在 api/workflow.py，运行编排在 engine/run.py
│   ├── core/                     # 地基包（只依赖 stdlib 与自身）
│   │   ├── config.py             # 配置与数据路径、保留/排队/预检常量
│   │   ├── refs.py               # 开关读取、名称解析、文件名、平台识别
│   │   ├── machine.py            # 按 OS 分支的机器事实（Chrome/驱动/xelatex/Node 位置）
│   │   └── procs.py              # 进程细节（创建标志、驱动进程树回收）
│   ├── i18n.py                   # zh/en 消息机制（t()/线程语言/audit + 合并按域词典）
│   ├── i18n_catalog/<domain>.py  # 服务端消息本体：一域一文件（crawl/collect/cookie/sched/run/analysis/biblio/charts/api/settings）
│   ├── runtime/                  # 进程级运行层（根只剩 app.py 与 i18n.py）
│   │   ├── state.py              # 进程内运行态与 console 缓冲（execution_state/_RUN_QUEUE/add_log…）
│   │   ├── stores.py             # run/dataset/housekeeper 单例与惰性 getter + 数据集缓存簇
│   │   ├── settings.py           # 运行时可改设置（data/settings.json，DEFAULTS/save_settings；原 settings_store.py）
│   │   ├── gate.py               # 同平台采集闸门（真排队/错峰；原 crawl_gate.py）
│   │   └── transport.py          # Ollama/OpenRouter 传输选择与「本机端口没人听」拒绝
│   ├── scheduling/               # 定时任务域：clock.py（进程内 daemon，到点走唯一启动路径）/ store.py（data/schedules.json）/ cron.py（五段解析 + IANA 时区）
│   ├── capabilities/             # 采集矩阵（一个平台一个文件）
│   │   ├── platforms/<id>.py     # 平台声明：模式/字段/建议；面板顺序由 platforms/__init__ 钉住
│   │   ├── fields.py             # 共享字段原子与四个模式工厂（posts/author/hot/comment）
│   │   ├── catbus.py             # 第二引擎的参数表单与 CatBus 独有平台/模式词
│   │   ├── model.py / requirements.py  # 已注册微调模型读取 / 「对机器的要求」判定
│   │   └── registry.py           # 查询面：校验、执行与前端面板的唯一口径
│   ├── sessions/                 # 登录态域：cookies.py（具名 Cookie 罐）/ flow.py / profiles.py（一账号一 user-data-dir）/ template.py（pristine 重建）/ preflight.py / routes.py（sessions Blueprint）
│   ├── api/                      # Flask Blueprint：按域拆出的路由簇（24 个已注册 + 2 个共享工具）
│   │   ├── http.py               # 共享请求工具（_json_body/_bad_body/_safe_int/_bad_param…）
│   │   ├── resolution.py         # 数据帧解析（_resolve_dataframe/NoRunDataError）
│   │   ├── analysis.py           # /api/analysis/{run,train}
│   │   ├── biblio.py             # /api/biblio/*（项目/快照/对比/表/来源）
│   │   ├── capabilities.py       # /api/capabilities（采集面板的字段口径）
│   │   ├── config.py             # /api/config + /api/models
│   │   ├── data.py               # /api/data/*（上传/粘贴/预览/合并/diff/重命名/删除）
│   │   ├── diagnostics.py        # /api/workflow/diagnostics（只读校验）
│   │   ├── exports.py            # /api/export/save + /api/exports/*（含 ledger/clear-*）
│   │   ├── history.py            # /api/history/*
│   │   ├── lexicon.py            # /api/lexicon GET/POST/DELETE
│   │   ├── llm.py                # /api/llm/*
│   │   ├── locks.py              # /api/locks（导出/运行/历史/工作流条目的钉住锁）
│   │   ├── node_types.py         # /api/node-types（服务端节点目录）
│   │   ├── project.py            # /api/project/{export,import}
│   │   ├── report.py             # /api/report/{generate,view,latex,studio-images}
│   │   ├── reusable.py           # /api/reusable*（含 rename）
│   │   ├── run_compare.py        # /api/runs/compare
│   │   ├── runs.py               # /api/runs/*（list/status/resumable/log/purge/...）
│   │   ├── schedules.py          # /api/schedules*
│   │   ├── settings.py           # /api/settings/*
│   │   ├── stats.py              # /api/stats/*
│   │   ├── studio.py             # /api/studio/*
│   │   ├── visualize.py          # /api/visualize/render
│   │   ├── workflow.py           # /api/workflow/*（execute/stop/status/rerun-node/queue/processes/...）
│   │   └── workflow_history.py   # /api/workflow/history*（含 rename/layout）
│   ├── crawlers/                 # 采集实现层
│   │   ├── __init__.py           # 平台注册表 + get_crawler/cookie_hosts/is_crawlable（工厂在此：Cookie 文件与 Profile 目录按账号拼）
│   │   ├── core/                 # 共用机械（不含站点事实）：crawler.py（基类：登录墙/Cookie 播种/流式落盘/游标/收尾）、browser.py、faults.py、video.py
│   │   ├── backends/catbus.py    # 第二采集后端（列、身份列、可采格都读适配器自己的清单）
│   │   ├── commenting/           # 评论引擎：session.py（活驱动 + 共享读取）、walks.py（平台→走路注册表）、protocol.py（无浏览器共用基件）
│   │   ├── platforms/<id>/       # 一个平台一个目录（目录名=全站平台 id）：zhihu/weibo/xiaohongshu/bilibili/douyin（含 overlay.py、rows.py）/youtube（innertube）/twitter/wechat（无登录态）/hongguo（player_ui/naming/trust——唯一 Windows 桌面能力）/cnki（检索+RefWorks 导出）/instagram（只捕 Cookie）
│   │   └── engine/               # 与站点无关的机械层（新抓取一律先走这里）：counters/wall/popup/feed/pager/pagefetch/jsonpath/times/pacing/innertube
│   ├── analyzers/                # 分析模块（LLM + ML 双模式）
│   │   ├── ml_base.py / llm_client.py  # TF-IDF+分类器底座 / Ollama·OpenRouter 客户端
│   │   ├── cleaner.py / keyword.py / ner.py / clustering.py / anomaly.py / correlation.py
│   │   ├── emotion.py / tendency.py / sentiment.py  # 情感/倾向/情感极性的 LLM+ML+BERT
│   │   └── aggression.py / bot.py / significance.py / stopwords.py  # 召回式攻击词表 / 水号 / 显著词 / 停用词
│   ├── nodes/                    # 节点插件：catalog.py（类型/形态/分组/quiet 唯一声明）、context.py（NodeCall）、registry.py（type→run，重复注册按名拒）、executors/（14 个插件：name/upload/resume/tokenize/accumulate/compile/biblio/fuse/output/visualize/analysis/process/comment/source，__init__ 触发注册）
│   ├── engine/                   # 工作流引擎
│   │   ├── workflow.py           # DAG 解析、调度、节点校验与指纹、node_label/effective_workflow
│   │   ├── plan.py               # 这次运行「是什么」：并行/串行、传输、要不要模型、重跑一个节点作废哪些
│   │   ├── run.py                # 运行本体：begin_run→_run_worker（零嵌套函数）、run_node_durable、execute_node、停止判定、队列排水、HEAVY_RESULT_ROWS/note_heavy_result
│   │   ├── run_logs.py           # 控制台两条写路径：抓 print() 的 LogTee 与按运行落库的 RunLogWriter
│   │   ├── run_schedule.py       # 定时触发的两扇门：scheduled_canvas（能不能无人值守跑）+ 这一次触发记账
│   │   ├── executor.py           # 线程池执行器
│   │   └── logger.py             # 日志管理
│   ├── services/                 # runs/（store：identity/base/ledger/progress/upkeep 五 mixin 组 RunStore/runs.db；files/windows/compare/history/history.db/housekeeping/queue/payload/settlement）、datasets/（store/merge/dedupe）、exports/（writer/browser）、analysis/（pipeline/params/process/llm/lexicon/lexicon_store/stats）、workflows/（manager/history/reusable/expand/bundle）、charts/（contracts/style/options/visualizer/tikz*/pdf/outputs）、reports/（html/paper）、ingest/（catbus/runtime/lifecycle/net/parts）、lock_store.py
│   └── static/
│       ├── index.html
│       ├── css/                  # 按 UI 域一样式表：base/menu/canvas/panels/controls/console/reusable/workspace/dialog/overlays/zenviz（2026-10-29 由 5,017 行 style.css 连续切片拆开）
│       └── js/
│           ├── app.js            # 入口（i18n fetch 注入、_mergeCatalogues、Settings/CloudMode、boot 序列）
│           ├── llm-settings.js / app-settings.js / floating-panels.js   # app.js 三段连续切片
│           ├── theme-boot.js / workflow-layout.js   # 主题引导 / 画布排布（独立切片）
│           ├── i18n/<domain>.js  # 浏览器词典（crawl/collect/cookie/sched/run/analysis/biblio/charts/api/settings/checks/misc/nodes/panels/chrome），页面在 app.js 之前加载
│           ├── canvas.js         # 画布与节点渲染（`canvas` 唯一绑定处）
│           ├── clipboard.js / canvas-view.js / canvas-snapshot.js / canvas-visuals.js / canvas-auto-layout.js   # canvas 对象的段（Object.assign 进同一个 canvas）
│           ├── workflow.js       # 执行、文件管理、全部对话框
│           ├── panels/           # 从 workflow.js 搬出的整块面板：data-views/shell/run-results/cookies/source-help/biblio/runlog/exports/runs/lexicon/datasets/files/diagnostics/settings/node-analysis/node-biblio/node-chart
│           ├── chart-preview.js / capabilities.js / reusable.js / node-types.js / menu.js / stats.js / custom-select.js / schedules.js
│           └── zenviz.js / zenviz-bridge.js / zenviz-page.js   # 内嵌 Chart Studio 图表库 / 与画布桥接 / 工作室页
├── data/                         # 运行时数据（gitignore；只有 workflows/ 例外）
│   ├── runs.db                   # 断点续跑状态（节点行/指纹/LLM 缓存/运行→文件台账 run_files/run_log）
│   ├── datasets.db               # 持久化上传数据集与引用 · history.db：执行历史与趋势 · lexicon.db：词表 · workflow_history.db：画布快照
│   ├── settings.json             # 运行时设置（DEFAULTS 见 runtime/settings.py）· schedules.json：定时任务台账
│   ├── model_registry.json       # 微调模型清单 · locks.json：面板条目钉住台账
│   ├── cookies/ · exports/ · models/ · checkpoints/ · chrome_profile/<平台>/<账号> · harvest/（红果收割产物）
│   └── workflows/                # 工作流配置（**进版本库**：作者写出的成果，引用数据集按 id）
├── build/make_lint_lists.py      # 生成三档 pylint 的目标清单（一次性脚本其余已删；结果由测试钉住）
├── .pylintrc · .pylintrc.tests · .pylintrc.probes
├── docs/                         # 本文所在，含 crawler_rules.md（采集端规则）/crawler_notes.md（实测）/agent_practices.md（证据）/live_test_plan.md
├── logs/
├── requirements.txt · requirements-optional.txt
└── README.md
```

## 训练传统 ML 模型

情感分析和倾向性分析支持传统 ML 模式（sklearn TF-IDF + 逻辑回归），需要先用 LLM 标注一批数据来训练：

1. 在工作流中配置 Process 节点 → Emotion 或 Tendency → 保持默认 LLM 模式
2. 连接上游数据源，执行工作流
3. 完成后，将 Process 节点的模式切换为 `ml`，点击「训练 ML 模型」
4. 系统自动从上游节点结果中提取文本列和标签列训练模型
5. 训练完成后，后续执行将使用 ML 模式批量推理（无需 Ollama / 不耗 token）

ML 模型保存在 `data/models/` 下，训练一次后持久可用；`ml_train/`（gitignored）训练情绪/倾向/情感的 sklearn+bert 模型并登记进 `data/model_registry.json`。

## 开发与验证

- 依赖安装、lint（ruff + pylint）、启动与测试均使用项目虚拟环境 `.venv/`（Python 3.11）
- 代码风格由 `ruff.toml` 约束（行宽 120、单引号），提交前必须通过 `ruff check` 与 `ruff format --check`，且只允许真正修复，禁止 `# noqa` 式忽略

### 自动化测试（pytest）

测试体系分六层，位于 `tests/`（约 **265** 个测试文件）。当前**收集数**：快速层 **8,249**（共 8,604 项中 355 项被
`pytest.ini` 排除）、设备层 **194**、`live_site` **161**、`live_quick` **11**。所有写入都落在临时目录（绝不触碰真实
`data/`）。每层的「证明了什么」一句话，详细 bug 故事见 [agent_practices.md](agent_practices.md) 与 [crawler_notes.md](crawler_notes.md)，
不在此复述：

| 层 | 证明什么 | 外部依赖 |
|----|----------|----------|
| `tests/unit` | 纯逻辑：断点续跑存储（被硬杀后按已落库行回填「已存行数」与完成数；`node_done` 只数真完成、restored 算完成；改工作流名/标签不进节点指纹、续跑改写记录描述字段、保留策略交回认领）、数据集存储、DAG 引擎（悬空连线不报"环"、空画布拒绝）、执行器（一层任务等自己启动的线程全退才交回槽）、清洗算子/图表/导出/分析器/i18n、浏览器启动参数（图片偏好须明确答复）、日志轮转、保留策略时间闸、Cookie 白名单、微信能力边界；**前端 JS 行为层**用 node 真加载 canvas/workflow/app（validate 预检门、键盘归属、撤销历史、Cookie 闸门、控制台游标与标签页历史、面板转义、目录双语对齐、每个被服务的 JS 文件都过 `node --check`）；**多处三向对齐门**（Cookie 面板 HTML↔白名单↔词典、`settings.DEFAULTS`↔`AppSettings._inputMap`↔index.html↔接线、共享登录墙判定、Cookie 归属过滤、Profile 的 JS 层） | 无（JS 层需 node，缺 node 自动跳过） |
| `tests/api` | Flask test_client 覆盖 50+ 端点：「上传→清洗→导出」全链路、Cookie 状态机与三种验证结论、运行前预检逐平台与缓存、节点执行与节点×算子×参数矩阵、`recrawl` 释放台账、队列交棒四种结局、被停止的并行不留线程、25 个「平台×采集内容」派发矩阵（含「无头仍无头建浏览器」）、保留策略对活运行的豁免、续跑用「标题 #id」、并行/串行×同平台×profile 的运行矩阵（真锁非假桩）、撞墙重试四种形状、控制台噪声分界、拒绝必须让节点失败、一次失败只播一遍、`test_console_buffer.py` 的控制台基线不变量、串行标签页归属、导出三端点路径规则、停止路径整条契约、每条带体 POST 路由点名加固（矩阵由 app.py 现算） | 无（外部调用全 mock） |
| `tests/integration` | LLM 传输边界（OpenRouter 一律 mock）、行运行器、真 Chrome 解析 `file://` 夹具、Profile 记住图片封锁、登录墙判定与"路过型闪现不钉死判墙"、各平台假驱动契约（小红书/知乎展开/B 站翻页/抖音"列表是一份文档"/X 进度只认保住的行）、矩阵每字段都被爬虫读到、真浏览器 UI 回归（逐容器 × 双语测溢出）、并行记录/历史删除/控制台切换/stopping 记录在真浏览器里的样子（**fetch 全程打桩，本层不写服务器**） | 夹具层需 Chrome |
| `live_ollama`（marker） | 真调本地 Ollama 的活模型用例（服务不可达自动跳过） | Ollama |
| `live_site`（marker） | **全平台真实爬取 × 双浏览器模式**：各平台搜索/正文/评论真跑真断言，断言按站点给的数（卡片评论数/页面自身计数/榜单规模）派生且双向；运行级知乎矩阵像用户那样 `POST /api/workflow/execute` 再读运行记录+控制台（停止→继续七格 E1–E7、并行/真排队、原样跑用户画布）；判据 FULL/NAMED_SHORT/SILENT_SHORT，整段控制台与结论落到 `scratchpad/live_audit/`（绝不写 `logs/`） | Chrome + 已存 Cookie |
| `live_quick`（marker） | **`live_site` 的子集：每个可爬平台恰好一条真采集**（**11** 条，每条只取 3~5 行），改动前后的日常闸门；`test_test_tiers.py` 钉住它必须是 `live_site` 子集、矩阵每平台都被触及、总数不超预算、禁止整模块打此标记 | Chrome + 已存 Cookie |

**真站层的会话形状必须和你自己抓取时一样**（实测教训，详见 crawler_notes）：它用 `scratchpad/live_profiles/<平台>`
这个跨运行保留的 profile，Cookie 只在第一次使用时种进去、之后由站点自己更新那份 jar；微博每轮只问一次。
**但"另一个 profile"本身就还是第二台设备**——要真验"登录态抓取"这条路，得让测试用你自己的 profile：加
`CIXI_LIVE_USE_USER_PROFILE=1`（明确授权）就落在 `data/chrome_profile/<平台>`，隔离看门狗只为此时放行这一棵子树。
**这一层不要无人值守跑**——它每轮都在消耗真实账号。

```bash
# 快速套件（默认，约 7~8 分钟、8.2k 用例；上面三层未打 marker 的部分）
.venv/Scripts/python.exe -m pytest -q

# 设备套件（真 Chrome + 真 Ollama）
.venv/Scripts/python.exe -m pytest -q -m "integration or live_ollama"

# 设备套件「要么真跑，要么报错」：默认下浏览器/守护进程起不来只是 skip，
# 而一整档 skip 在 -q 下读起来和通过没区别。要一个能当证据的绿色就带上开关：
CRAWLER_REQUIRE_BROWSER=1 CRAWLER_REQUIRE_OLLAMA=1 .venv/Scripts/python.exe -m pytest -q -m "integration or live_ollama"

# 真站层按网络分两组：先国内（关 VPN），再海外（开 VPN）
.venv/Scripts/python.exe -m pytest -q -m "live_quick and live_cn"     # 国内：抖音/微博/知乎/小红书/B站/微信
.venv/Scripts/python.exe -m pytest -q -m "live_quick and live_os"     # 海外：X、YouTube

# 想让真站层用你自己的登录态（否则它用自己的测试 profile，微博会把你当第二台设备拒掉）：
CIXI_LIVE_USE_USER_PROFILE=1 .venv/Scripts/python.exe -m pytest -q -m "live_quick and live_cn"
.venv/Scripts/python.exe -m pytest -q -m "live_site and live_cn"      # 全量同理，只在最终验收跑

# 覆盖率
.venv/Scripts/python.exe -m pytest -q --cov=backend --cov-report=term
```

运行单个设备/live 用例时**也要覆盖 marker 过滤**（只给文件名会报 `N deselected`）。

### Lint：三档标准，三次运行，都要干净

`build/make_lint_lists.py` 生成每档的目标清单（嵌套配置不会被 pylint 读到，所以每档是独立一次带 `--rcfile` 的调用）：

```bash
.venv/Scripts/ruff.exe   check backend/ tests/
.venv/Scripts/ruff.exe   format --check backend/ tests/
.venv/Scripts/pylint.exe --rcfile=.pylintrc        <product targets>   # backend 去掉其 test_*.py + desktop/tools/ml_train/scripts
.venv/Scripts/pylint.exe --rcfile=.pylintrc.tests  tests/
.venv/Scripts/pylint.exe --rcfile=.pylintrc.probes backend/test_*.py   # 一次性探针脚本的本地档（CI 不跑）
```

**绝不写 `# pylint: disable` 或 `# noqa`，也绝不为消掉一条告警而放宽 `.pylintrc*`**：修根因；真正无意义的消息，
例外连同理由写在该树自己的 config 里。

### 关于格式化：不要只依赖编辑器钩子

`ruff format` 与 `ruff --fix` 用「写临时文件 → 改名覆盖」落盘。在限制写入的工作区（含本项目沙箱会话）这一步
会直接失败（`os error 5`），钩子静默什么都没做而编辑看起来成功——格式债就这样积累。所以格式与 lint 由
`.github/workflows/ci.yml` 兜底：它跑 `ruff check`、`ruff format --check`、两档 pylint（产品 / tests，各一次 `--rcfile`）、
fast 全量，以及一个用真 Chrome 跑 `-m integration` 的 `browser` job（`.pylintrc.probes` 是本地档，CI 不跑）。本地提交前请显式跑一遍上面的命令。

**"CI 有没有覆盖某一步"只能查运行历史，不能读本地 yaml**（读文件会把"计划要做"说成"已经在做"）：

```bash
curl -s https://api.github.com/repos/Xingye-Dujing/crawler-workflow/actions/runs | head
curl -s https://api.github.com/repos/Xingye-Dujing/crawler-workflow/actions/runs/<id>/jobs
```

第二条给出每个 job 的 `steps[].name`，那就是 CI 实际执行的步骤清单。可选依赖（`bert` 模式需要的
torch/transformers，几个 GB，不装也能正常用其它功能）见 `requirements-optional.txt`。修改代码后的完整验证流程见
`AGENTS.md` 的 "Change workflow"。全平台真机验收的用例矩阵与运行手册见 [live_test_plan.md](live_test_plan.md)。

## 备份与恢复

`data/` 不在 git 里（只有 `data/workflows/` 是版本化的例外），所以一次 push 保护不了运行记录、数据集与登录态；
仓库的 git 历史也曾被工具误删过一次。两条互补的备份路径：

- **远端**：每次提交后同时 push `crawler-github` 与 `gitee`（`git remote -v` 核对）；两个远端都不含 `data/`。
- **还原点**：`tools/backup.py` 在 `backups/<时间>/` 下写三样东西——`repo.bundle`（全部 ref，
  `git clone repo.bundle` 即可恢复代码与历史）、`data.zip`（`workflows/`、`reusable_nodes/`、`*.db`、
  `settings.json`、`model_registry.json`）、`manifest.json`（时间、HEAD、工作区是否脏、远端、成员清单）。
  - 默认**不含** `data/cookies/`：那是明文账号凭据，备份文件常被拷来拷去。确需时加 `--with-cookies`，
    并把那份 zip 当作密码保管。
  - 不含 `chrome_profile/`、`exports/`、`logs/`：浏览器数据与可再生文件，不值得进归档。
  - 命令：`.venv/Scripts/python.exe tools/backup.py [--out <目录>] [--with-cookies]`（Linux/macOS 用
    `.venv/bin/python`）。`backups/` 已在 `.gitignore` 内。
  - **`runs.db` 会随运行增长**（本机实测 5.8 GB）：备份前先按保留策略清一次，或把 `--data` 指向一份精简副本；
    清单里的 `data_bytes` 与命令输出都会报出这次归档了多大。
- **恢复**：停服务 → `git clone backups/<ts>/repo.bundle crawler_workflow` → 把 `data.zip` 解到该**检出根目录**
  （包内已带 `data/` 前缀）→ 建 `.venv`、`pip install -r requirements.txt` → 从 `backend/` 启动。

## 已知的一个第三方警告（保持可见，绝不过滤）

快速套件始终恰好打印**一个** `DeprecationWarning`：

```
.venv/.../jieba/_compat.py:18: DeprecationWarning: pkg_resources is deprecated as an API
```

- **出处不在本仓库代码**：`jieba/__init__ → _compat → import pkg_resources`，而 setuptools ≥74 一 `import pkg_resources` 就发这条警告。本仓库自身代码零警告（8,249 用例只此一条，且全属外部）。
- **无法靠升级消除**：jieba 最新版即 0.42.1（已停更，PyPI 无更新版本），其 import 改不掉。
- **实测「换 jieba_fast」不成立**：jieba_fast 0.53 的 `_compat.py:6` 同样 `import pkg_resources` 照发此警告，且 `cut_for_search` 结果与 jieba 不同（非等价替身）。
- **清零只剩两条都不划算的路**：①换掉整个分词器（分词结果会变，tokenize/关键词/词云/聚类/LDA 一切派生数字与列契约都要重推）；②把 setuptools 钉到 <74（本质是把一条正当的前瞻性弃用警告压下去，属「消音」，违反仓库规则）。

结论：按「报告、不过滤」处理，保留可见，仅在此记明来历——既不写 `filterwarnings`，也不为此改产品行为。
`pytest.ini` 里没有 `filterwarnings`。将来若真替换分词器，须连同所有分词派生量一并重验，再删本节。
