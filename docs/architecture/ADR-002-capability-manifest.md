# ADR-002：能力清单（Manifest）与完整性门禁

- 状态：已接受（2026-11-22）
- 相关：[ADR-001](ADR-001-kernel-replacement.md)

## 背景

今天新增一个普通节点，至少要 14 处手改、涉及 12 个文件；另有约 20 处会静默退化或漏报。典型漏点：`canvas.js` 的默认标题 map（`python`/`fuse` 已缺）、节点卡片摘要（`python` 已空白）、`panels/settings.js` 的设置分派、`panels/runs.js` 的前端验证 if 链、三份不一致的“表类型”名单、`reports/paper.py` 的方法段、`api/workflow.py` 的 dataset 引用、`runs/store/identity.py` 的指纹、`engine/plan.py` 的 LLM 门控。它们没有测试枚举，所以“漏了也能绿”。

## 决策

每个能力一个清单，声明九段；注册表自动发现；其它表面派生或生成；完整性门禁枚举每个清单。

### 九段

1. **身份**：`id`、`kind`、`version`、`title`、`category`（L1/L2）、`description`、`when_to_use`。
2. **参数**：JSON Schema 子集（type/default/enum/min/max/required）+ UI 元数据（widget/options/columnRef/placeholder）。
3. **端口**：输入数量、行形状（table/pdf/none）、输出列契约（`emit_columns`/`read_columns`）。
4. **执行**：executor 模块路径或 handler id；懒加载。
5. **验证**：声明式规则 + 可选 `preflight(node, sample)`；问题带 `code`/`severity`/`fix`。
6. **UI**：默认 schema 表单 + 可选 `custom_renderer` id（逃生口）。
7. **AI**：暴露的工具名、用法、步骤、示例、模板 JSON、失败模式。
8. **测试**：fixture/golden case；每个能力至少一条契约测试。
9. **文档**：技能目录路径、版本哈希；与清单同步。

### 一个清单，七个表面

同一份 manifest 派生：

- HTTP API 的 OpenAPI schema
- AI 工具 schema
- MCP server 的 tools/resources/prompts
- CLI 命令
- 前端表单
- 文档/技能目录
- 测试矩阵

### 注册表

- 扫描 `backend/capabilities_kernel/<kind>/<id>.py`，也接受现有目录的适配器。
- 去重、确定性排序、懒加载执行器（不把 pandas/torch 拖进每次 DAG 解析）。
- 重复 id、未知类型、缺执行器都按名拒绝。

### 完整性门禁

`tests/unit/gates/test_capability_completeness.py` 枚举每个清单，检查：

- 九段是否齐全
- 执行器是否注册
- 验证规则是否存在
- UI renderer 是否存在
- 双语键是否齐全
- 技能七段是否齐全
- 示例 JSON 是否可解析
- 工具 schema 是否有效
- 生成物是否最新（`gen_capabilities.py --check`）
- 文档哈希是否匹配

`python -m tools.doctor --all` 用同一套逻辑逐项打印勾选；不绿就不算完成。

## 扩展剧本

新增一个节点：

```text
backend/capabilities_kernel/nodes/<id>/
  manifest.py        # 九段
  executor.py        # run(node, call) + emit/read/preflight
  knowledge/
    SKILL.md         # 何时用/步骤/示例/失败模式
    examples/*.json  # 节点模板
```

然后 `python -m tools.doctor --capability node:<id>`。前端表单、验证规则、AI 工具、技能索引、测试矩阵、文档索引全部自动派生；不再需要改 `canvas.js`/`runs.js`/`index.html`/`splits.json`。

## 后果

- 迁移期新旧清单并存：旧 `nodes/catalog.py` 仍是运行期事实，新 kernel 通过适配器读它；迁移完成后再删旧表。
- 生成物必须有 freshness 门禁，否则“自动生成”会变成“生成一次就过期”。
- 清单不是代码生成器：行为仍在 executor 里，清单只声明契约。

## 被否决的替代方案

- **继续在 `canvas.js`/`runs.js` 加分支**：每加一个节点就多一处漏配。
- **只写一个“节点矩阵测试”**：测试能发现漏，但不能让新增节点只改一处。
- **用运行时反射猜 UI/验证**：会生成“看起来能用”的错误表单；契约必须显式。
