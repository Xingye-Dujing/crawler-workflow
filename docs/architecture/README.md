# 架构重构（工作文档）

本目录是采析绘“内核替换 + 逐域迁移”的实施文档。它不描述今天的代码，而描述**目标契约**与**验收门禁**；今天的形状仍以 [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) 为准。

## 先读什么

**每次会话第一步**（与读压缩交接文档同等义务）：本目录的 README → ADR-001/002/003/004 → handoff →
rewrite-plan 的未勾选项。代码可能有意落后于契约；与 ADR 冲突的改动必须先写成决策，不能默默绕过。

1. [ADR-001：内核替换，而不是推倒重来](ADR-001-kernel-replacement.md)
2. [ADR-002：能力清单（Manifest）与完整性门禁](ADR-002-capability-manifest.md)
3. [ADR-003：持久状态机与中断恢复](ADR-003-durable-state.md)
4. [ADR-004：AI 上下文、产物分组与会话执行](ADR-004-ai-context-artifacts-sessions.md)
5. [AI 工作区四模块实施规划](ai-workspace-modules-plan.md) —— Skills 多选/自检索、产物分组、会话工作夹与执行恢复
6. [能力内核（P1 骨架）](capabilities-kernel.md) —— 清单、注册表、pilot 落点
7. [问题台账](problem-ledger.md) —— 每个用户问题属于“直接修 / 重构 / 已决策”
8. [实施计划](rewrite-plan.md) —— Workbuddy 式勾选，未过验收不打勾
9. [架构改进计划](improvement-plan.md) —— W0–W7：还剩哪些结构债、每笔怎么还、用哪个门禁证明

## 十条长期原则

1. **Contract-first，不是 code-first**：先声明能力、参数、端口、权限、版本。
2. **Generate，不是 duplicate**：同一事实只写一次；生成物有 freshness 门禁。
3. **Durable，不是 in-memory**：运行、回合、中断、配方都有持久状态与恢复路径。
4. **Asset-centric，不是 task-centric**：节点输出是有身份的资产，支持血缘、增量、缓存、契约。
5. **Capability-based security**：每个工具/插件声明权限，策略引擎按账号/会话/模式授权。
6. **Progressive disclosure**：技能/工具/文档分层加载，每轮有预算。
7. **Version everything**：manifest/API/数据 schema 都有版本和弃用窗口。
8. **Observe everything**：trace/metrics/audit 默认开启，内容默认脱敏。
9. **Zero-build UI**：custom elements + design tokens + 渐进增强，不锁定框架。
10. **Local-first，cloud-refusable by name**：本地能力默认可用；云端按名拒绝并隐藏入口。

## 状态

- 当前阶段：**P6 技能/工具/小模型**（P1 内核骨架、P2 全量节点迁移、P3 验证完整化、P4/P5 AI 框架与接入已完成）
- **P4.0 已全部完成（框架 0.1.17，F1–F18）**；P4 接入与 P5 前端切换已收口（`/api/ai/ws` 是唯一 AI 表面）。
  P6 第一片已完成：16 个节点能力技能的 L1/L2 目录、`skill_catalog`/`skill_load`、生成页面与门禁
- **W0/W1 已完成（2026-11-24）**：清单与代码校准；导入方向 / 模块预算 / HTTP 表面 / 死模块四个门禁上线，
  `core/values.py`、`services/datasets/frames.py`、`api/sessions.py`、`api/pool.py` 落位。见
  [improvement-plan.md](improvement-plan.md)
- **P10 已完成（2026-11-25）**：框架 0.2.0 的多技能/渐进披露/产物分组/会话工作目录已接入；
  验收与证据见 [ai-workspace-modules-plan.md](ai-workspace-modules-plan.md)。
- 已确认的 10 个方向决策见 [rewrite-plan.md](rewrite-plan.md#已确认的决策)
- 一个勾选项只有在“代码 + 测试 + 文档/技能 + 门禁 + 收口”全部通过后才能打勾
