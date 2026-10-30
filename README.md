# 采析绘（数据的采集、分析与可视化）

一个基于 **Flask + Selenium + LLM (Ollama / OpenRouter) + scikit-learn** 的多平台社交媒体数据采集、清洗、
分析与可视化工作流系统：拖拽式画布把「采集 → 清洗 → 分析 → 可视化」串成一条可运行的工作流，内置
**断点续跑**——任务中断后可从检查点继续，已花费的采集与 LLM 成本不会重复支付。

> 本文是**预览**。分平台采集细节、分析/可视化、引擎、API、配置、开发验证的完整文档都在 [`docs/`](docs/)
> 下（见文末**文档索引**）；面向 AI agent 的规则在 [`AGENTS.md`](AGENTS.md)。

## 快速开始

> 所有运行与安装一律在项目虚拟环境 `.venv/`（Python 3.11）中进行，勿使用系统 Python。

**1. 环境要求**

本项目按 **Windows / Linux / macOS 三套系统**开发，源码版三者都能跑（云端部署目标是 Linux）。只有两处
系统专属：`desktop/` 打包目录（PyInstaller + UPX + Inno，只出 Windows exe），以及「红果短剧评论收割」
（要驱动本机播放器进程 + 装系统证书，只有 Windows 桌面做得到）——后者在 Linux/macOS 与 cloud 模式下
**按名拒绝**，面板也不再给出那个选项。

- Python 3.11+（代码使用 `zip(..., strict=True)`）
- Chrome（Selenium 驱动）。Linux 装 `chromium` + `chromium-driver`（或 `google-chrome-stable`），macOS
  装 Chrome 的 `.app`；程序按当前系统查找，也认 `CHROME_PATH` / `CHROME_BIN`。**chromedriver 不随项目
  分发**（驱动与 Chrome 大版本一对一绑定），Selenium 首次采集时自动取匹配版本（需联网）。
- [Ollama](https://ollama.ai/) 本地大模型，或 OpenRouter API Key（二选一）；云端 `CRAWLER_CLOUD=1` 只留 OpenRouter
- `xelatex`：仅「编译 PDF / 论文成稿」需要（Windows MiKTeX，Linux `texlive-xetex texlive-lang-chinese`，
  macOS MacTeX）。没有它 LaTeX 源照出、PDF 按名拒绝。
- Matplotlib 渲染中文图需系统中文字体（Linux `fonts-noto-cjk`）；缺失时控制台点名该系统该怎么补，而非静默画方框。
- 前端资源已随仓库分发：ECharts 及其 GL / 词云扩展、界面字体在 `backend/static/vendor/`，中国与世界底图在
  `backend/static/geo/`——离线机器也画得出图，缺失文件时每个画图位置都指名是哪个文件没加载。

**2. 建虚拟环境、装依赖**

```bash
cd crawler_workflow
python -m venv .venv
source .venv/Scripts/activate        # Windows（cmd 用 .venv\Scripts\activate）；Linux/macOS 用 .venv/bin/activate
pip install -r requirements.txt
ollama pull qwen3.5:9b               # 可选；用 OpenRouter 可跳过
cd backend && python app.py          # 访问 http://127.0.0.1:5000（端口 PORT、地址 HOST 用环境变量改）
```

`backend/` 是 `sys.path` 根，必须从这里启动。默认只监听本机、不自动开浏览器；开发时 `FLASK_DEBUG=1` 开热重载。

**一次只能运行一个 `app.py` 服务**：本项目按「本机单人使用」设计，所有状态存在同一份 `data/`
（`runs.db`/`datasets.db`/`cookies/`/`exports/`）。同时开两个实例会把正在写入的运行判为中断、两边互改同一
节点的行与游标——要换端口先停掉旧实例。确需第二个实例（验证脚本、测试自启）时，用
`CRAWLER_DATA_ROOT=<目录>` 给它一份自己的 `data/`+`logs/`，两边互不干涉。

**云端 / 桌面版**：放服务器给别人访问用 `python app.py cloud`（或 `CRAWLER_CLOUD=1`）——关掉本地模型界面、
强制无头抓取、拒绝浏览器生成（开关、隐私边界、profile 模板规则见 [`docs/config.md`](docs/config.md)）。
给不装 Python 的人（仅 Windows）：`desktop/` 用 PyInstaller onedir 打包出 `CaiXiHui.exe`（`-Installer` 再出
Inno 安装包），双击即启本地服务并开浏览器；数据默认在 `%APPDATA%\CaiXiHui`，exe 旁放空文件 `portable.txt`
切便携模式。构建命令、体积边界、首启依赖自检与「为什么排除 onefile」见 [`desktop/README.md`](desktop/README.md)。
微调 BERT 的四个模型不在应用包里，是单独的模型包 zip，解压到与 exe 同级即可自动登记；不放则相关节点降级并打印实际模式。

## 功能一览

每项细节都在 `docs/`，此处一行一个能力 + 去处。

- **多平台数据采集**：知乎 / 微博 / 小红书 / 微信公众号 / 哔哩哔哩 / 抖音 / 红果短剧 / 中国知网 / YouTube / X（Instagram
  已可存 Cookie，采集待接入）；关键词 / 作者作品 / 热榜 / 评论多模式，支持分批流式落库、上游喂链接、多账号与持久
  Profile。红果评论由带代理的桌面播放器旁听收割（**仅 Windows**，其他平台按名拒绝且置灰写明原因）。→ [`docs/collection.md`](docs/collection.md)
- **第二采集引擎（CatBus）**：数据源/评论节点按 **平台 × 引擎 × 功能** 组织；哪些可采、输出哪些列、哪列是身份，
  全部读自适配器自己的 `capabilities` 清单（本项目不抄表）；不可运行组合列着、置灰、写明原因，运行时按名拒绝，绝不
  静默换后端或降级成空采。两条与浏览器后端的真实差异都打印出来（无偏移量、用 CatBus 自己的账号文件、登录门键分开）。
  快手 / TikTok / 京东 / 淘宝 / 闲鱼目前只有 CatBus 引擎。→ [`docs/collection.md`](docs/collection.md)
- **AI 分析**：Ollama / OpenRouter 双提供方；情感 / 倾向 / 情绪（LLM · sklearn ML · 微调 BERT 三模式，默认微调
  BERT，跑不动自动降级并打印实际模式；BERT 有 torch 与 onnxruntime 两个运行时）、情感极性、NER、关键词、聚类、异常、
  相关性、显著性检验（Welch t / ANOVA / Mann-Whitney / Kruskal-Wallis，p 值走 scipy 真实分布）、网暴言论识别。→ [`docs/analysis.md`](docs/analysis.md)、[`docs/why_finetuned_bert.md`](docs/why_finetuned_bert.md)
- **数据处理**：确定性清洗算子、去重（含 SimHash 近重复）、分组聚合、**事件研究套件**（阶段划分 / 分阶段 LDA / 主题
  流向 / 情感演化 / 二次爆发预警 / 曲线外推），主题步骤默认 `auto`（装了编码器用 embedding+KMeans，否则 LDA，都如实写明）；
  通用导出（CSV/JSON/Excel/TXT/HTML/Markdown，Parquet 需可选 pyarrow）、一键运行报告与「智能清除」。→ [`docs/analysis.md`](docs/analysis.md)
- **文献计量 / 知识图谱**：Upload 自动识别真实导出件（CNKI/CSSCI/WoS/Scopus/Dimensions/Lens/PubMed/RIS/BibTeX/
  EndNote…，见 `services/biblio/formats/`）；Bibliometrics 节点按时间切片构建关键词/作者/机构/国家/学科/共被引等网络，
  支持 TopN/g-index/TC 过滤/Pathfinder/MST/多种中心性/谱聚类与标签/Kleinberg 突现，输出 GraphML/GML/JSON/CSV/Pajek 及
  节点/边/聚类/突现/结构变异/双图叠加/情感·话题叠加分层；列映射可把爬取数据接进网络。顶栏**文献计量工作区**停靠面板
  读持久台账，可快照存项目并与基准对比。→ [`docs/analysis.md`](docs/analysis.md#文献计量)
- **LLM 簇综述·研究前沿**：Analysis 的 `cluster_review` 喂本地模型的不是簇内文本而是这一簇已有的度量（缺哪列就少一行，
  不写「未知」诱使编造）；付费纪律与其他模型步骤一致（没起模型先按名拒绝、Stop 标未处理并结算 PARTIAL、按 prompt 缓存续跑不重付）。
- **可视化**：论文印刷风格图表（ECharts / Matplotlib 双引擎）、主题距离图 / 显著词图 / 关系图 / 桑基 / 占比堆叠 / 知识
  图谱 / 环形 / 时间线 / 突现词 / 时区 / 三维 / 结构变异 / 双图叠加 / 情感叠加 / 话题叠加 / 国家地理图 / 同心环布局，
  LaTeX 图与三线表、MiKTeX 编译 PDF、Chart Studio 工作台；「存为图片 (PNG@2×)」与「存为 SVG」两个一键导出；
  「论文成稿（LaTeX）」只交 `run_id` 就把台账登记过的图与三线表合成 `article`+`ctex` 文档并本机编译。→ [`docs/analysis.md`](docs/analysis.md)
- **跨源融合（`fuse`）**：把任意多张上游表按**候选列顺序**折叠成一份规范记录表（来源随行保留，绝不猜），下游 `biblio`
  节点因输入带 `来源` 而多出 `来源`/`跨源` 两列，可读「哪些词只在一个语料、哪些两边都在谈」。
- **跨 run 监测（超越点）**：`biblio` 填 `watch_project` 就把每次网络存成项目快照并与上次捕获对比（增减节点/连边/簇/
  突现、改过的参数逐条打印），交给定时任务按周期跑同一画布即成领域监测流水线。
- **工作流引擎**：拖拽画布、fan-in/fan-out、禁用即不存在、撤销/重做、视角持久化、大纲定位、自动排布、运行队列、
  停止与并行/串行。节点类型 14 个：Name / Data Source / Upload / Process / Analysis / Bibliometrics / Fuse /
  Accumulate / Visualize / Compile / Tokenize / Output / Resume / Comment，类型与行形态由 `nodes/catalog.py` 单点声明，
  执行器全在 `nodes/executors/`、注册表在 `nodes/registry.py`。→ [`docs/workflow.md`](docs/workflow.md)
- **画布历史 / 可复用节点 / 布局基准**：把画布存成命名快照（`data/workflow_history.db`，恢复前列差异、恢复是一步撤销、
  上限 100 份满了按名拒绝）；选中一组节点可「创建可复用节点」收成一个模板（`data/reusable_nodes/`，折叠时只占一个节点、
  运行态为内部汇总、展开时接输入槽），可拖拽柄拖到画布插入、预览/重命名/删除模板。自动排布有「算法排布」与「按历史基准恢复」两策略。→ [`docs/workflow.md`](docs/workflow.md)
- **断点续跑与运行记录**：节点级检查点、LLM 答案缓存、增量采集台账、Cookie 中途过期续跑、Resume 节点、保留策略；
  控制台文本按运行号持久化（`run_log`，事后可按级别/工作流过滤搜索下载 `.txt`，实时控制台与刷新重连不变）；每个节点每次
  运行的表格输出按运行号持久化（`node_rows`/`node_runs`）；进入画布默认载入本工作流最近一次运行结果，节点角标绿勾=完成/复用、
  黄转圈=运行中、红叉=未成功，未知绝不画成成功；「从此节点重跑」只重算该节点及下游、复用上游已存行。→ [`docs/workflow.md`](docs/workflow.md)
- **累积数据集 / 数据集合并 / 跨运行水位**：Accumulate 节点把新增行追加到带版本长期数据集（去重方式显式选，列变化按名拒绝）；
  数据集面板可多源合并同构数据集（缺/多列按名拒绝，默认加「来源」列）、行级对比；哔哩哔哩作者投稿模式可「停在上一次运行边界」的水位续跑。→ [`docs/workflow.md`](docs/workflow.md)
- **定时任务（为云服务器准备）**：应用内常驻调度时钟，到点执行已存画布（预设或 cron 五段、每任务可指定 IANA 时区，留空=服务器本地）；
  **定时任务不碰模型**（含模型节点的画布在选择时就标明「不能定时」并写原因）；停机错过的时刻只记一条「已错过」不补跑；到点走与
  手动 Run 同一条启动路径、服务忙则排队；下次/最近时刻、任务句子、可跑性判定全部服务端算好送来。台账在 `data/schedules.json`。→ [`docs/workflow.md`](docs/workflow.md#定时任务)
- **界面**：中英双语、亮/暗主题（`自动`跟随系统，图表配色与 PNG 同步）、搜索过滤、复制粘贴/框选/方向键微移/`WASD` 选择/`Enter` 开合面板/
  `L` 连线/缩略总览图/剪贴板抽屉、连线拒绝成环、运行前诊断（每个节点常驻校验角标、设置面板顶部显示会输出哪些列、状态栏给预计行数与 LLM
  调用数）；后端运行队列镜像到 `runs.db` 重启不丢。→ [`docs/workflow.md`](docs/workflow.md)
- **词库 / 停用词**：底栏「词库」面板增删停用词与领域词库（`data/lexicon.db`，`/api/lexicon`），管线经唯一入口读取按版本缓存，
  领域词启动时写入并全局加载 jieba 用户词典；改词从下一次运行起生效。
- **HTTP API / 配置**：全部端点见 [`docs/api.md`](docs/api.md)；环境变量、运行时设置、常量、云端部署见 [`docs/config.md`](docs/config.md)。

## 项目结构

```
crawler_workflow/
├── backend/
│   ├── app.py                    # Flask 组合根：注册 Blueprint、请求钩子、时钟接线、启动恢复；唯一路由是页面 /
│   ├── core/                     # 地基包（config/refs/machine/procs）：只依赖 stdlib，谁都可以 import
│   ├── i18n.py + i18n_catalog/   # zh/en 机器 + 按域数据（10 个域文件）
│   ├── runtime/                  # 进程级运行层：state / stores（测试接缝）/ settings / gate / transport
│   ├── api/                      # 全部 HTTP 端点：24 个 Blueprint 模块 + http.py（请求强转）+ resolution.py
│   ├── scheduling/               # 定时任务域：clock / store（data/schedules.json）/ cron
│   ├── capabilities/             # 采集矩阵：platforms/<id>.py + fields/catbus/registry
│   ├── nodes/                    # 节点插件：catalog + registry + executors/（14 类型）+ schema
│   ├── engine/                   # 工作流引擎：DAG/计划/run.py（无嵌套函数）/run_logs/run_schedule
│   ├── services/                 # charts/reports/ingest/runs/analysis/biblio/workflows/datasets/exports + lock_store
│   ├── analyzers/                # LLM + sklearn + BERT 分析
│   ├── crawlers/                 # 各平台爬虫 + 无站点依赖的 engine/ + backends/catbus
│   ├── sessions/                 # 登录态域：具名 Cookie、各账号 Chrome profile、模板、预检、路由
│   └── static/                   # 前端：index.html、css/（10 张分域表）、js/（canvas/workflow/app…）、geo/、vendor/
├── data/                         # 运行时数据（gitignore；仅 workflows/ 进版本库）
├── docs/                         # 文档（采集/分析/工作流/API/配置/开发 + 实测记录 + 重构方案）
├── tests/                        # unit / api / integration / frontend / 真站各层
├── ml_train/                     # 训练脚本与模型（gitignored）
├── logs/                         # 运行日志（自动轮转）
├── desktop/                      # Windows 打包（PyInstaller/UPX/Inno，唯一故意写死系统的目录）
└── requirements.txt              # 依赖声明（可选 torch/transformers 在 requirements-optional.txt）
```

完整逐模块目录树见 [`docs/development.md`](docs/development.md)。

## 使用示例

**从画布跑一条完整工作流**：拖入 Data Source 选平台+关键词 → Process 选清洗/情感/倾向并在 AI 面板选提供方与模型
→ 可选 Analysis 做确定性清洗、Tokenize 出词频 → 加 Visualize 看分布、Output 选导出格式 → 连线、加 Name 命名 → 菜单 Execute。

**只处理已有数据（不采集）**：直接拖一个 Visualize（或 Analysis / Bibliometrics）节点，把数据源切成 Upload File
上传 CSV/TSV/JSON/TXT/Excel/NBIB/RIS/BibTeX/EndNote/NoteExpress，配好字段后 Preview Chart 即可；文献导出件会自动解析成
文献记录表，其它普通文本/CSV 仍按原有方式导入。Excel 一次只导一张表（多非空工作表会按名拒绝并列表名）；Upload 面板的
「从已保存数据集选择」可挂载库里已存文件，支持搜索、显来源/列数/行数、详情与被引用、「应用到其他上传节点」、断链红标。

**中断后续跑**：执行中 Stop、关服务或中途失败都没关系——已完成的节点与已处理的行都在 `data/runs.db`。重开工作流后顶部出现
"检测到中断的运行"横幅，点「继续」只重跑缺失部分（LLM 走缓存不重付费），点「重新开始」全量重跑；原平台已登出/已花成本时，
拖一个 Resume 节点直接收养历史运行的输出行。

## 文档索引

| 文件 | 里面是什么 |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | **代码结构地图**：后端/前端各模块、大文件的耦合约束、接缝规则 |
| [`docs/refactor_plan.md`](docs/refactor_plan.md) | **全项目结构审计与重构总纲**（缺陷分类、目标目录树、分层规则、阶段与完成定义） |
| [`docs/frontend_modules.md`](docs/frontend_modules.md) | `workflow.js` 的**逐模块拆分方案** |
| [`docs/collection.md`](docs/collection.md) | 各平台采集的内容、字段、模式、选项与上限 |
| [`docs/analysis.md`](docs/analysis.md) | AI 分析 · 数据处理 · 可视化 的完整细节 |
| [`docs/workflow.md`](docs/workflow.md) | 工作流引擎 · 断点续跑 · 界面 · 节点类型 |
| [`docs/api.md`](docs/api.md) | Flask 后端全部 HTTP 端点 |
| [`docs/config.md`](docs/config.md) | 环境变量 · 运行时设置 · 常量 · 云端部署 |
| [`docs/development.md`](docs/development.md) | 完整项目结构 · 训练模型 · pytest 各层 · 格式化钩子的坑 |
| [`docs/crawler_notes.md`](docs/crawler_notes.md) | 逐平台**真机实测记录**（改爬虫前先看） |
| [`docs/crawler_rules.md`](docs/crawler_rules.md) | 采集端工程**规则** |
| [`docs/live_test_plan.md`](docs/live_test_plan.md) | 全平台真机验收的用例矩阵与运行手册 |
| [`docs/tendency_model_comparison.md`](docs/tendency_model_comparison.md) | 倾向性模型对比研究 |
| [`docs/why_finetuned_bert.md`](docs/why_finetuned_bert.md) | 为何这三类分析主推**微调 BERT**（含实测 accuracy/F1 与吞吐） |
| [`AGENTS.md`](AGENTS.md) | 面向 AI agent 的项目规则与改动流程（测试不变量在此） |

---

本项目依赖由 `.venv/` 承载，代码风格由 `ruff.toml` 约束（行宽 120、单引号）。开发与验证流程、各测试层命令见
[`docs/development.md`](docs/development.md) 与 [`AGENTS.md`](AGENTS.md)。
