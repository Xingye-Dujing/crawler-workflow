# P0 基线

- 记录日期：2026-11-22
- 用途：重构前的能力清单、测试基线、lint 基线；每个阶段对照它判断“有没有变慢/变少”。

## 已知基线（来自 `AGENTS.md` 与本机）

| 项 | 值 |
|---|---|
| 节点类型 | 16（`nodes/catalog.py`） |
| 分析算子 | 38（`services/analysis/ops/`） |
| 图表类型 | 30（`services/charts/registry.py`） |
| 采集平台 | 11 个模块（9 个社交平台 + CNKI + 红果；instagram 仅 cookie-capture） |
| AI 工具 | 47（`ai/tools.py`） |
| AI 技能 | 18 个内置大领域（`ai/skills.py`） |
| 快速测试 | 约 10.6k 条（`python -m pytest -q`） |
| 全层（fast+device+live） | 约 18 分钟（AGENTS 估算） |

## 本次全量快测

命令：

```bash
.venv/Scripts/python.exe -m pytest -q
```

结果（2026-11-22，热修批次开始前启动，运行中又有少量热修落盘；只作起点，收口时重跑）：

```text
10578 passed, 7 skipped, 384 deselected, 1 warning in 870.83s (0:14:30)
```

- [x] 收集/通过/跳过/失败数：10578 / 7 / 384 deselected / 0 failed
- [x] 墙钟耗时：14 分 30 秒
- [ ] `ruff check` / `ruff format --check`（每个 commit 单独跑，收口再全量）
- [ ] `python tools/ci_lint_tiers.py product`
- [ ] `python tools/ci_lint_tiers.py tests`
- [ ] `/smoke-verify`（孤立 data root）

## H11-H16 热修批次收口（2026-11-22）

在 H11-H16（附件抽取、数据授权、工作流管理、覆盖矩阵、stack_pct 验证）以及 H1-H10 的回归修正之后重跑：

```text
10646 passed, 7 skipped, 384 deselected, 1 warning in 846.06s (0:14:06)
```

- 快测：10646 passed / 7 skipped / 0 failed，14 分 06 秒（比旧基线 +68 条测试，时间 -24 秒）。
- 设备层：`-m "integration or live_ollama"` → `213 passed, 5 skipped, 10820 deselected`，5 分 54 秒；
  浏览器/Node 都真实跑了（H4/H5 的 pointer capture 回归就是这一层发现的）。
- lint：`ruff check` / `ruff format --check` 全绿；`ci_lint_tiers.py product` 10.00/10；
  `ci_lint_tiers.py tests` 10.00/10。
- 冒烟：隔离 `CRAWLER_DATA_ROOT` 在 5057 启动，`/`、`/api/config`、`/api/settings`、`/api/workflow/list`、
  `/api/data/datasets`、`/api/runs/list`、`/api/stats/summary`、`/api/capabilities`、`/api/cookies/flow`、
  `/api/ai/bootstrap`、`/api/ai/conversations`、`/api/ai/references`、`/api/ai/memories`、
  `/api/workflow/status` 全部 200；进程已停，5057 已释放。
- **未跑**：`live_quick` / `live_site`（会花用户账号，需用户指定 `live_cn`/`live_os` 网络并明确同意）；
  打包桌面 GUI、真实云端启动、真实登录爬取也不在本机冒烟范围内。

## 这条基线保护什么

- 任何“重构让测试变少/变慢”的改动都要对照本文件解释。
- P8 的测试瘦身目标（fast ≤8 分钟）以本文件的实测值为起点，不以感觉为准。
- 一个阶段的 DoD 必须能回答：这条基线里的哪一项被证明没有退化？
