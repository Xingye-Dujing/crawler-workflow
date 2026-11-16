# 开发与验证

> 本文是采析绘文档的一部分，返回总览见 [README.md](../README.md)。面向 agent 的规则见
> [AGENTS.md](../AGENTS.md)；规则背后的证据见 [agent_practices.md](agent_practices.md)，采集端实测见
> [crawler_notes.md](crawler_notes.md)，真站验收矩阵见 [live_test_plan.md](live_test_plan.md)，包职责见
> [ARCHITECTURE.md](ARCHITECTURE.md)。

## 项目结构
- `backend/` 从 `app.py` 起步，包划分（`core`/`runtime`/`capabilities`/`scheduling`/`sessions`/`api`/`crawlers`/
  `analyzers`/`nodes`/`engine`/`services`/`static`）见 [ARCHITECTURE.md](ARCHITECTURE.md)。
- `data/`（gitignore，只有 `workflows/` 入库）：`runs.db`（节点行/指纹/LLM 缓存/运行→文件台账 `run_files`/`run_log`）、
  `datasets.db`（上传数据集与谱系）、`history.db`（趋势）、`lexicon.db`（词表）、`workflow_history.db`（画布快照）、
  `settings.json`、`schedules.json`、`model_registry.json`、`locks.json`、`pool.db`（账号/出口池冷却）；
  目录 `cookies/`、`exports/`、`models/`、`checkpoints/`、`chrome_profile/<平台>/<账号>/`、`harvest/`；
  账号级状态在 `data/users/<id>/`，系统级文件（`accounts.db`、`settings.json`、`lexicon.db`、`models/`、`logs/`）留在根上。
- `tools/`：构建/迁移/备份/CI 辅助；`.pylintrc`、`.pylintrc.tests`、`.pylintrc.probes` 是三档 lint 的配置；
  `ml_train/`（gitignore）训练 sklearn + bert 模型并登记进 `data/model_registry.json`。

## 训练传统 ML 模型
情感/倾向/情感极性支持传统 ML（sklearn TF-IDF + 逻辑回归），先用 LLM 标注一批数据：
1. 画布上 Process 节点选 Emotion 或 Tendency，保持 `llm` 模式，接上游数据源并执行。
2. 把模式切到 `ml`，点“训练 ML 模型”；系统从上游结果取文本列与标签列拟合并存 `data/models/`。
3. 之后的运行直接用 ML 批量推理，无需 Ollama、不耗 token；`bert` 模式的模型由 `ml_train/` 训练并登记。

## 测试分层
`tests/` 六层；默认只收快速层。每层证明什么：

| 层 | 证明什么 | 外部依赖 |
|---|---|---|
| `tests/unit` | 纯逻辑：断点续跑存储、数据集存储、DAG 引擎、执行器、清洗/图表/导出/分析器/i18n、浏览器启动参数、日志轮转、保留策略、Cookie 白名单；前端 JS 用 node 真加载；多组三向对齐门 | 无（JS 需 node，缺则 skip） |
| `tests/api` | Flask `test_client` 覆盖 50+ 端点：上传→清洗→导出、Cookie 状态机与三种验证结论、运行前预检、节点×算子×参数矩阵、队列四种结局、串行/并行×同平台×profile、停止契约、控制台不变量 | 无（外部调用全 mock） |
| `tests/integration` | LLM 传输边界、行运行器、真 Chrome 解析夹具、登录墙判定、各平台假驱动契约、真浏览器 UI 回归（fetch 全程打桩，不写服务器） | Chrome |
| `live_ollama` | 真调本地 Ollama 的活模型用例 | Ollama |
| `live_site` | 全平台真爬取 × 双浏览器模式，断言按站点自己的数派生且双向；判据 FULL/NAMED_SHORT/SILENT_SHORT，产物落 `scratchpad/live_audit/` | Chrome + 已存 Cookie |
| `live_quick` | `live_site` 的子集：每个可爬平台一条真采集；`test_test_tiers.py` 钉住子集关系与预算 | Chrome + 已存 Cookie |

真站层用 `scratchpad/live_profiles/<平台>` 这份跨运行保留的 profile，Cookie 只在首次种入、之后由站点更新；
`CIXI_LIVE_USE_USER_PROFILE=1`（用户明确授权）才改用 `data/chrome_profile/<平台>`，隔离看门狗只此时放行这一棵子树。
**真站层绝不无人值守跑**——每轮都在消耗真实账号；微博每轮只问一次。

## 运行命令
```bash
# 快速套件（默认；约 7~8 分钟）
.venv/Scripts/python.exe -m pytest -q

# 设备套件（真 Chrome + 真 Ollama）
.venv/Scripts/python.exe -m pytest -q -m "integration or live_ollama"

# 设备套件“要么真跑、要么失败”（缺浏览器/守护进程时默认 skip，会伪装成通过）
CRAWLER_REQUIRE_BROWSER=1 CRAWLER_REQUIRE_OLLAMA=1 .venv/Scripts/python.exe -m pytest -q -m "integration or live_ollama"

# 真站层按网络分组：国内关 VPN，海外开 VPN
.venv/Scripts/python.exe -m pytest -q -m "live_quick and live_cn"
.venv/Scripts/python.exe -m pytest -q -m "live_quick and live_os"
CIXI_LIVE_USE_USER_PROFILE=1 .venv/Scripts/python.exe -m pytest -q -m "live_quick and live_cn"
.venv/Scripts/python.exe -m pytest -q -m "live_site and live_cn"      # 全量，只在最终验收跑

# 覆盖率
.venv/Scripts/python.exe -m pytest -q --cov=backend --cov-report=term
```
POSIX 用 `.venv/bin/python`。跑单个设备/live 用例时**也要覆盖 marker 过滤**（只给文件名会报 `N deselected`）。

## Lint：三档标准，都要干净
`tools/ci_lint_tiers.py` 枚举每档目标（嵌套配置读不到，所以每档是一次独立的 `--rcfile` 调用；空列表按名失败）。

```bash
.venv/Scripts/python.exe -m ruff check backend/ tests/ desktop/ tools/
.venv/Scripts/python.exe -m ruff format --check backend/ tests/ desktop/ tools/
.venv/Scripts/python.exe tools/ci_lint_tiers.py product   # backend 去掉 test_*.py + desktop/tools/ml_train/scripts
.venv/Scripts/python.exe tools/ci_lint_tiers.py tests     # tests/
# 本地探针档（backend/test_*.py），CI 不跑；pylint 不做通配，先展开文件列表：
.venv/Scripts/pylint.exe --rcfile=.pylintrc.probes (Get-ChildItem backend -Filter test_*.py)
```
绝不写 `# pylint: disable`/`# noqa`，也绝不为消一条告警放宽 `.pylintrc*`：修根因。

## 格式化与 CI
- `ruff format`/`--fix` 用“写临时文件→改名”落盘，在受限工作区会 `os error 5` 且钩子静默失败；提交前手跑上面的命令。
- `.github/workflows/ci.yml` 是兜底门禁：Linux / macOS / Windows 三系统各跑 `ruff check`、`ruff format --check`、
  两档 pylint 与 fast 全量；`browser` job 用真 Chrome 跑 `-m integration` 并保留 `CRAWLER_REQUIRE_*`，设备缺失即失败。
- `workflow_dispatch` 的 `probe` 开关只让 Ubuntu/macOS 的失败不红整次运行（用于首次排查）；push/PR 始终阻塞。
- CI 能证明三系统的 fast 层与真 Chrome 设备层；**只能在本地做**：真实云服务器启动/采集、`live_site`/`live_quick`、
  Ollama 活模型、CatBus 适配器、打包后的桌面窗口。CI 绿不等于所有层都跑过。
- 某一步 CI 是否覆盖，只能查运行历史：`curl -s https://api.github.com/repos/Xingye-Dujing/crawler-workflow/actions/runs/<id>/jobs`
  的 `steps[].name` 才是实际步骤。可选依赖（`bert` 的 torch/transformers）见 `requirements-optional.txt`。

## 备份与恢复
`data/` 不在 git（`data/workflows/` 例外），push 保护不了运行记录、数据集与登录态。
- **远端**：每次提交后同时 push `crawler-github` 与 `gitee`（`git remote -v` 核对）；两者都不含 `data/`。
- **还原点**：`tools/backup.py` 在 `backups/<时间>/` 写 `repo.bundle`（全部 ref，`git clone` 即恢复）、`data.zip`、
  `manifest.json`（时间、HEAD、工作区是否脏、远端、成员清单）。`data.zip` 收系统树与每个账号树的
  `workflows/`、`reusable_nodes/`、`*.db`，加 `settings.json`、`model_registry.json`；每个库先 `wal_checkpoint`，
  被服务占住时连 `-wal` 一起存。
  - 默认**不含**任何 `cookies/`（明文凭据）；要含加 `--with-cookies`，并把 zip 当密码保管。
  - 不含 `chrome_profile/`、`exports/`、`logs/`、`data/users/.trash/`。`backups/` 已 gitignore。
  - 命令：`.venv/Scripts/python.exe tools/backup.py [--out <目录>] [--with-cookies]`（POSIX 用 `.venv/bin/python`）。
  - `runs.db` 会随运行增长；备份前先按保留策略清理，或把 `--data` 指向精简副本。清单的 `data_bytes` 报出归档大小。
- **恢复**：停服务 → `git clone backups/<ts>/repo.bundle crawler_workflow` → 把 `data.zip` 解到该**检出根目录**
  （包内已带 `data/` 前缀）→ 建 `.venv`、`pip install -r requirements.txt` → 从 `backend/` 启动。

## 第三方警告
快速套件恰好打印一条 `DeprecationWarning`：`jieba/_compat.py` 的 `import pkg_resources`（setuptools ≥74 触发）。
出处不在本仓库，jieba 0.42.1 已停更；替换分词器会让 tokenize/关键词/词云/聚类/LDA 的全部派生量与列契约重推，
钉低 setuptools 属于消音。因此**保留可见、不写 `filterwarnings`**；`pytest.ini` 里没有过滤，也不为它改产品行为。
