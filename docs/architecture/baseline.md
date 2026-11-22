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

结果：**运行中，完成后回填**（`docs/architecture/baseline.md` 的这次编辑只记录起点，不伪造数字）。

回填项：

- [ ] 收集/通过/跳过/失败数
- [ ] 墙钟耗时
- [ ] `ruff check` / `ruff format --check`
- [ ] `python tools/ci_lint_tiers.py product`
- [ ] `python tools/ci_lint_tiers.py tests`
- [ ] `/smoke-verify`（孤立 data root）

## 这条基线保护什么

- 任何“重构让测试变少/变慢”的改动都要对照本文件解释。
- P8 的测试瘦身目标（fast ≤8 分钟）以本文件的实测值为起点，不以感觉为准。
- 一个阶段的 DoD 必须能回答：这条基线里的哪一项被证明没有退化？
