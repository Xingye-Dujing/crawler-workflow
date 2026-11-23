# 架构重构（工作文档）

本目录是采析绘“内核替换 + 逐域迁移”的实施文档。它不描述今天的代码，而描述**目标契约**与**验收门禁**；今天的形状仍以 [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) 为准。

## 先读什么

**每次会话第一步**（与读压缩交接文档同等义务）：本目录的 README → ADR-001/002/003 → handoff →
rewrite-plan 的未勾选项。代码可能有意落后于契约；与 ADR 冲突的改动必须先写成决策，不能默默绕过。

1. [ADR-001：内核替换，而不是推倒重来](ADR-001-kernel-replacement.md)
2. [ADR-002：能力清单（Manifest）与完整性门禁](ADR-002-capability-manifest.md)
3. [ADR-003：持久状态机与中断恢复](ADR-003-durable-state.md)
4. [能力内核（P1 骨架）](capabilities-kernel.md) —— 清单、注册表、pilot 落点
5. [问题台账](problem-ledger.md) —— 每个用户问题属于“直接修 / 重构 / 已决策”
6. [实施计划](rewrite-plan.md) —— Workbuddy 式勾选，未过验收不打勾

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

- 当前阶段：**P4.0 框架完善**（P1 内核骨架、P2 全量节点迁移、P3 验证完整化已完成）
- P4.0 已落地七片（框架 0.1.9）：turn 生命周期（FSM/事件/runner/命令/邮箱/restart）；通知；审批策略；步骤幂等；
  宿主工具注册；多问题卡。F9–F11、F14–F16、F18、F3 仍开放（顺序见 rewrite-plan）
- 已确认的 10 个方向决策见 [rewrite-plan.md](rewrite-plan.md#已确认的决策)
- 一个勾选项只有在“代码 + 测试 + 文档/技能 + 门禁 + 收口”全部通过后才能打勾
