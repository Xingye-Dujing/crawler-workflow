# 交接与压缩检查点

- 日期：2026-11-22
- 分支：`main`
- 最后提交：`279ed41 修改：记录 agent-workspace 迁移 parity 矩阵`
- 工作区：干净（`git status --short` 无输出）

## 已完成（每个一类改动一个 commit）

| 提交 | 内容 |
|---|---|
| `6e5fd4c` | 待答问题按 `question_id` 恢复；服务端派生 `message_id`；多选答案写入状态 |
| `28d9820` | 本地 Ollama 全局强制 `think:false`；过滤残留 thinking/think 标签；UI 开关禁用 |
| `1b69457` | 架构 ADR、问题台账、实施计划、5 个架构技能 |
| `f5b0c91` | 新消息不再取消待答问题；有待答问题时按名拒绝（邮箱在 P4） |
| `84b1a0c` | 侧栏按实测宽度布局；列宽随 dock 夹紧；12px grip + pointer capture；流式重绘恢复 scrollTop |
| `d8a7d55` | Python 节点显示脚本/参数；补全 `python`/`fuse` 标题 |
| `ab1285d` | 放宽 AI 输出/工具结果/回合/表格读取限制；0=不限；表格单页 2000 |
| `0c965b8` | LLM 行任务可配置并发；API 并行；Ollama 串行 |
| `279ed41` | agent-workspace parity 矩阵 |

## 测试基线

- 全量快测（热修批次开始前启动，运行中又有少量热修落盘）：
  `10578 passed, 7 skipped, 384 deselected, 1 warning in 870.83s (14:30)`。
- 每个提交都有针对性的测试；尚未做这一批的最终全量 closure gate。
- 收口时必须重跑：`python -m pytest -q`、ruff、两档 pylint、`/smoke-verify`。

## 下一步（按顺序）

1. **H11 附件文本抽取**：pdf/docx/xlsx/csv/txt/html → text；无 `files` 能力的模型也能用；`files` 与 `vision` 解耦。
2. **H12 数据读取授权**：`request_dataset_access` + 会话/数据集/行数 grant + revoke；`dataset_page` 遵守 grant。
3. **H13 工作流/产物管理工具**：list/read/create/update/delete/rename/export/run/stop；走域服务，不走裸文件系统；删除需审批 + 审计。
4. **H14 工具覆盖审计**：能力→工具/技能覆盖门禁。
5. **H16 占比堆叠图验证**：`stack_fields` 在 validate 阶段命名；P3 迁移到 ChartSpec preflight。
6. **H17/H18 视图单实例**：设置/工作室不覆盖 `#ai-chat`；切会话不重复消息区（可与 P5 框架 UI 合并）。
7. **P1 内核骨架**：manifest/registry/generator/doctor/FSM/events；pilot `tokenize`。

## 压缩后必须保留的规则

1. **10 个已确认决策**（见 `docs/architecture/rewrite-plan.md#已确认的决策`）不得重新讨论，除非用户明确复议。
2. **一类改动一个 commit**；每个勾选项只在“代码 + 测试 + 文档/技能 + 门禁 + 收口”全过后打勾。
3. **自动压缩时机**：当预计剩余上下文不足以完成一个“代码 + 测试 + commit”的完整切片时，先收口当前切片、提交、更新本文件，再请求用户压缩；**不要在半成品上压缩**。压缩后从“下一步”继续。
4. **不要靠提示词保证行为**：能用服务端校验/工具遮罩/状态机/门禁的，必须用机制。
5. **不要在全量重写上打转**：内核替换 + 逐域迁移；旧路径只在数据丢失/安全级别热修。
6. **歧义必须问**，不要猜；用户语言是中文。
7. **关键路径**：`docs/architecture/`、`backend/ai/`、`backend/static/js/ai-workspace.js`、`backend/static/js/canvas.js`、`backend/runtime/settings_schema.py`、`tests/api/test_ai_workflow.py`、`tests/unit/frontend/test_frontend_ai_js.py`。
8. **收口命令**：见 `AGENTS.md`；最终必须 fast + ruff + 两档 pylint + device + smoke，无文件待改。

## 给压缩后的第一句话

> 从 `docs/architecture/handoff.md` 的“下一步”继续；当前工作区干净，最后提交 `279ed41`。先做 H11。
