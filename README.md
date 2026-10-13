# 采析绘（数据的采集、分析与可视化）

一个基于 **Flask + Selenium + LLM (Ollama / OpenRouter) + scikit-learn** 的多平台社交媒体数据采集、清洗、
分析与可视化工作流系统：拖拽式画布把「采集 → 清洗 → 分析 → 可视化」串成一条可运行的工作流，内置
**断点续跑**——任务中断后可从检查点继续，已花费的采集与 LLM 成本不会重复支付。

> **TL;DR** — 采集中外文社媒八平台的数据，用本地大模型与 sklearn 清洗分析，在画布上出图出报告。
> 跑起来：`cd backend && python app.py`（先在 `.venv/` 里 `pip install -r requirements.txt`）。
> 本文只是**预览**，分平台采集细节、分析/可视化、引擎、API、配置、开发验证的完整文档在 [`docs/`](docs/) 下，见文末**文档索引**。

## 快速开始

> 所有运行与安装一律在项目虚拟环境 `.venv/`（Python 3.11）中进行，勿使用系统 Python。

**1. 环境要求**
- Python 3.11+（代码使用 `zip(..., strict=True)`）
- Chrome 浏览器（Selenium 驱动，驱动路径可在设置面板修改）
- [Ollama](https://ollama.ai/) 本地大模型，或 OpenRouter API Key（二选一即可）
- 若用 Matplotlib 引擎渲染中文图表，服务器需安装中文字体（`fonts-wqy-microhei` / SimHei / Microsoft YaHei 任一；Linux 下 `apt install fonts-wqy-microhei`）

**2. 建虚拟环境、装依赖**

```bash
cd crawler_workflow
python -m venv .venv
source .venv/Scripts/activate        # Windows Git Bash；cmd 下用 .venv\Scripts\activate
pip install -r requirements.txt
```

**3. 下载 Ollama 模型（可选，用 OpenRouter 可跳过）**

```bash
ollama pull qwen3.5:9b
```

**4. 启动应用**

```bash
cd backend
python app.py
```

访问 http://127.0.0.1:5000（端口 `PORT`、监听地址 `HOST` 均可用环境变量改，默认只监听本机、不自动开浏览器；
开发时 `FLASK_DEBUG=1` 打开热重载）。`backend/` 是 `sys.path` 根，必须从这里启动。

**一次只能运行一个 `app.py` 服务**：本项目按"本机单人使用"设计，所有状态存在同一份 `data/`
（`runs.db`/`datasets.db`/`cookies/`/`exports/`），服务启动会把遗留的"运行中"记录判为**已中断**（续跑横幅的来源），
同时开两个实例（比如端口 5000 与 5057 各一个）时，后启动的会立刻把前一个正在写入的运行标成中断，两边还会互相改写同一节点的行与游标——要换端口就先停掉旧实例，别并行开着。确需第二个实例（跑验证脚本、测试里自启的那台），用
`CRAWLER_DATA_ROOT=<目录>` 给它一份自己的 `data/`+`logs/`，两边互不干涉。

**5. 可选：OpenRouter / 云端部署** — 不设任何旗标就是本机形状。要放到服务器上给别人访问，用
`python app.py cloud`（或 `CRAWLER_CLOUD=1`）：同时关掉本地模型界面、强制无头抓取、拒绝浏览器生成。
云端开关、隐私边界与 profile 模板规则的完整说明见 [`docs/config.md`](docs/config.md)。

## 功能一览

- **多平台数据采集**：知乎 / 微博 / 小红书 / 微信公众号 / 哔哩哔哩 / 抖音 / YouTube / X（推特）
  （Instagram 已可存 Cookie，采集待接入），关键词 / 某作者的作品 / 热榜 / 评论多种模式，
  采集量只由你填的目标数决定，支持分批输出、上游喂链接、多账号与持久 Profile。→ [`docs/collection.md`](docs/collection.md)
- **AI 分析**：Ollama / OpenRouter 双提供方，情感 / 倾向 / 情绪（LLM · sklearn ML · 微调 BERT 三模式，**默认微调 BERT**，跑不动自动降级到 ml/snownlp 并打印实际模式；BERT 截断长度可调）、
  情感极性、NER、关键词、聚类、异常、相关性、显著性检验（按分组列比较数值列：Welch t / ANOVA / Mann-Whitney / Kruskal-Wallis，p 值走 scipy 真实分布、非 Student 的 Welch 会如实标注）、网暴言论识别。→ [`docs/analysis.md`](docs/analysis.md)、为何主推微调 BERT → [`docs/why_finetuned_bert.md`](docs/why_finetuned_bert.md)
- **数据处理**：确定性清洗算子、去重（含 SimHash 近重复）、分组聚合（多指标）、**事件研究套件**（阶段划分 / 分阶段 LDA /
  主题流向 / 情感演化 / 二次爆发预警 / 曲线外推（移动平均 · Holt · 季节 Holt-Winters/朴素）），主题步骤（主题模型 / 分阶段 / 距离图 / 显著词）默认
`auto`（装了编码器用 embedding+KMeans，没装自动走 LDA，控制台都如实写明用了哪种；可选装 `requirements-optional.txt`，也可显式选 `embedding`/`lda`），输出列三种方法一致，通用导出（CSV/JSON/Excel/TXT/HTML/Markdown，Parquet 需可选引擎 pyarrow）、一键运行报告与「智能清除」（按运行、按节点分片）。→ [`docs/analysis.md`](docs/analysis.md)
- **可视化**：论文印刷风格图表（ECharts / Matplotlib 双引擎）、主题距离图 / 显著词图 / 关系图 / 桑基 /
  占比堆叠 / 模型一致率、LaTeX 图与三线表、MiKTeX 编译成 PDF、Chart Studio 工作台。→ [`docs/analysis.md`](docs/analysis.md)
- **工作流引擎**：拖拽画布、连线 fan-in/fan-out 语义、禁用即等同于不存在、撤销/重做、视角持久化、
  右侧大纲侧栏一键定位节点、自动排布上下顺序可指定、运行队列、停止与并行/串行执行。→ [`docs/workflow.md`](docs/workflow.md)
- **断点续跑与运行记录**：节点级检查点、LLM 答案缓存、增量采集台账、Cookie 中途过期续跑、Resume 节点、
  保留策略与运行时长；控制台文本另按运行号**持久化**（`run_log`，每条物理行都存），事后在运行记录里「查看运行日志」——按级别 / 工作流标签过滤、搜索、加载更早、下载 `.txt`（实时控制台与刷新重连一律不变）。→ [`docs/workflow.md`](docs/workflow.md)
- **界面**：中英双语、亮/暗主题（`自动`跟随系统或手动切换，图表配色与 PNG 导出同步跟随）、节点库与右侧大纲支持按名称/类型/缩写搜索过滤、节点库条目为 `role=button` 且 Tab 可达（`Enter`/空格或直接点击即在画布添加该类型节点）、`Ctrl`/`Cmd`+`F` 唤起大纲查找、选中节点 `Ctrl`/`Cmd`+`C`/`V` 复制粘贴（副本错位叠开）与方向键微移（`Shift` 精调 1px）在输入框外生效、框内不劫持、`W`/`A`/`S`/`D` 键把选中跳到该方向最近的节点（纯选择、不挪位置，与方向键微调互不抢键）、选中节点按 `Enter` 打开其设置（焦点在按钮上时不劫持 `Enter`）、右键「复制节点为 JSON / 从 JSON 导入节点」可跨画布分享单个节点、对话框为模态且键盘可达（Tab 焦点锁在框内、Esc 关闭、role/aria-modal 语义）、启动步骤各自兜异常、离线不拖垮整页；画布支持触控板双指滚动平移 / 捏合缩放与平板双指手势；状态栏一个 `●` 表示画布有未保存改动（只跟踪节点/连线模型，平移视角不算改动，保存/打开即清除），打开另一份工作流仅在确有未保存改动时才二次确认；已打开的文件在每次改动后**静默自动保存**（几秒去抖、绝不新建未命名文件、无提示音），刷新/关闭页面前若有未保存改动则浏览器原生提醒；`L` 键连线（选中一个节点按 `L` 定起点、选中第二个再按 `L` 完成，`Esc` 取消）；`Shift` 点选 + 空白处**框选**可多选，批量删除/方向键微移一次生效（选择是视图态，不进撤销历史）；右下角**缩略总览图**按当前缩放画出所有节点与视口框、点击即把画布居中到该处；**剪贴板抽屉**（顶栏「视图」组或 `toggleClipboardDrawer()` 开合）把每次复制（单/多选节点、复制为 JSON、手动「添加文本」）累积成一份持久化清单，存于独立的 `crawler_clipboard` 键（与草稿 `crawler_canvas` 分离、刷新/重开仍在），可对任意一条**粘贴 / 重命名 / 置顶 / 删除 / 全部清空**，支持搜索过滤、上限 50 条且**置顶条目不被容量淘汰**；文本条目若是节点 JSON 还能「作为节点插入」。抽屉是视图态，绝不进 `getState()`/撤销历史，粘贴一律复用画布同一 `_pasteAt` 通道，且**跨标签页实时同步**（另一处窗口改了剪贴板，本窗口经 `storage` 事件自动刷新）；状态栏新增缩放控件 `[−] 百分比 [+]`（点数字即「适应」，另可 `+`/`-`/`0` 键位），`?`/`F1` 打开**快捷键一览浮层**（逐条对应实际绑定）；多选后右键可**对齐 / 分布**（左右上下、水平/垂直居中、水平/垂直等距，一次操作=一步撤销）；拖线**拒绝成环**（在唯一提交点 `connectNodes` 前置有向可达性检测，指针与 `L` 键两路同规则，避免跑出无解的环）；「视图」菜单另有**剪贴板抽屉**与快捷键入口。后端：运行**队列重启不再丢失**（待运行请求镜像到 `runs.db`，开机自动回填，仍严格一次跑一个）；运行详情的每张节点卡片可对已完成节点**「从此节点重跑」**（只重算该节点及其全部下游，未变的上游已存行原样复用、绝不重采/重付费）；数据集面板可勾选两份**行级对比**（`POST /api/data/diff`，报出新增/删除行与增删列，仅在显式指定唯一键列时才判定「变更行」，绝不臆测主键）。**运行前诊断**：每个节点常驻校验角标（缺配置 / 断线 / 引用了上游没有的列，悬浮看原因、点击选中并滚到该节点），设置面板顶部显示该节点**会输出哪些列**（爬虫 / 续跑等运行前不可知者如实标注、绝不臆造），状态栏给出**预计行数与 LLM 调用数**（按采集矩阵默认值估，无界情形标「不封顶」）——把「跑完才发现列名 / 配置错」提前到编辑期。→ [`docs/workflow.md`](docs/workflow.md)
- **节点类型**：Name / Data Source / Upload / Process / Analysis / Visualize / Compile / Tokenize / Output / Resume / Comment。→ [`docs/workflow.md`](docs/workflow.md#节点类型)
- **HTTP API**：工作流、运行记录、数据集、分析/可视化/导出、Chart Studio、统计/历史、AI/Cookie/系统全部端点。→ [`docs/api.md`](docs/api.md)
- **配置**：环境变量、运行时设置（`data/settings.json`）、保留策略 / 内存 / 排队-错峰-预检常量、云端部署。→ [`docs/config.md`](docs/config.md)

## 项目结构

```
crawler_workflow/
├── backend/
│   ├── app.py                    # Flask 主入口（路由 + 执行编排）
│   ├── config.py                 # 配置与数据路径
│   ├── i18n.py                   # zh/en 消息目录
│   ├── settings_store.py         # 运行时可改设置（data/settings.json）
│   ├── crawl_capabilities.py     # 采集矩阵：平台 × 模式 × 字段 × handler（唯一口径）
│   ├── crawlers/                 # 各平台爬虫 + 无站点依赖的机械层 engine/
│   ├── analyzers/                # 分析模块（LLM + ML + BERT）
│   ├── engine/                   # 工作流引擎：DAG 解析、执行器、日志
│   ├── services/                 # 续跑存储 / 数据集 / 导出 / 报告 / 可视化 / LaTeX 等
│   ├── utils/                    # 工具函数
│   └── static/                   # 前端：index.html、css、js（canvas/workflow/app…）
├── data/                         # 运行时数据（gitignore；仅 workflows/ 进版本库）
├── docs/                         # 文档：采集/分析/工作流/API/配置/开发 + 实测记录
├── tests/                        # 单元 / API / 集成 / 前端 JS / 真站各测试层
├── ml_train/                     # 训练脚本与模型（gitignored）
├── logs/                         # 运行日志（自动轮转）
├── requirements.txt              # 依赖声明（可选 torch/transformers 在 requirements-optional.txt）
└── README.md
```

完整的逐模块目录树见 [`docs/development.md`](docs/development.md)。

## 使用示例

**从画布跑一条完整工作流**：拖入 Data Source 选平台+关键词 → Process 选清洗/情感/倾向并在 AI 面板选提供方与模型
→ 可选 Analysis 做确定性清洗、Tokenize 出词频 → 加 Visualize 看分布、Output 选导出格式 → 连线、加 Name 命名
→ 菜单 Execute 运行。

**只处理已有数据（不采集）**：直接拖一个 Visualize（或 Analysis）节点，把数据源切成 Upload File 上传
CSV/TSV/JSON/TXT/Excel，配好字段后点 Preview Chart 即可，不必跑整条工作流。Upload 节点还能在面板的
「从已保存数据集选择」下拉里直接挂载数据库里已存的文件（此前上传、粘贴或分析产出的），无需重复上传。
该下拉可**搜索过滤**、每行显示**来源/列数/行数**、按**最近使用**排序，库为空时给出**直达数据集管理**的引导；
「详情」展开可见列、被本画布哪些节点引用、被哪些工作流引用；「应用到其他上传节点」一键把同一份数据分发给画布上
其余 Upload 节点；被删掉的文件会以**红色断链**标出（清空失效 id 以免运行读到死指针，同时说明原因）。

**中断后续跑**：执行中 Stop、关服务或中途失败都没关系——已完成的节点与已处理的行都在 `data/runs.db`。
重开工作流后顶部出现"检测到中断的运行"横幅，点「继续」只重跑缺失部分（LLM 走缓存不重付费），点「重新开始」
则忽略检查点全量重跑。原平台已登出/已花过成本时，拖一个 Resume 节点直接收养历史运行的输出行。

## 文档索引

| 文件 | 里面是什么 |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | **代码结构地图**：后端/前端各模块、两个大文件的耦合约束、以及分步（每步过测试）的重构路线 |
| [`docs/collection.md`](docs/collection.md) | 各平台采集的内容、字段、模式、选项与上限（面向使用者） |
| [`docs/analysis.md`](docs/analysis.md) | AI 分析 · 数据处理 · 可视化 的完整细节 |
| [`docs/workflow.md`](docs/workflow.md) | 工作流引擎 · 断点续跑 · 界面 · 节点类型 |
| [`docs/api.md`](docs/api.md) | Flask 后端全部 HTTP 端点 |
| [`docs/config.md`](docs/config.md) | 环境变量 · 运行时设置 · 常量 · 云端部署 |
| [`docs/development.md`](docs/development.md) | 完整项目结构 · 训练 ML 模型 · pytest 各层怎么跑 · 格式化钩子的坑 |
| [`docs/crawler_notes.md`](docs/crawler_notes.md) | 逐平台**真机实测记录**（登录墙 / 翻页契约 / 字段来源）——改爬虫前先看 |
| [`docs/crawler_rules.md`](docs/crawler_rules.md) | 采集端工程**规则** |
| [`docs/live_test_plan.md`](docs/live_test_plan.md) | 全平台真机验收的用例矩阵与运行手册 |
| [`docs/tendency_model_comparison.md`](docs/tendency_model_comparison.md) | 倾向性模型对比研究 |
| [`docs/why_finetuned_bert.md`](docs/why_finetuned_bert.md) | 为何这三类分析主推**微调 BERT** 而非通用大模型：质量/速度/成本对比（含实测 accuracy/F1 与本机 GPU 吞吐 rows/s） |
| [`AGENTS.md`](AGENTS.md) | 面向 AI agent 的项目规则与改动流程（测试不变量在此，不在文档里重复） |

---

本项目依赖由 `.venv/` 承载，代码风格由 `ruff.toml` 约束（行宽 120、单引号）。开发与验证流程、
各测试层命令见 [`docs/development.md`](docs/development.md) 与 [`AGENTS.md`](AGENTS.md)。
