# 能力内核（capabilities_kernel）

> 状态：P1 骨架已落地；`tokenize` 是 pilot。目标契约见 [ADR-002](ADR-002-capability-manifest.md)。

`backend/capabilities_kernel/` 是“一个能力只声明一次”的落点。它替换的不是业务实现，而是**同一事实被复制到十几个表面**的做法：节点类型、默认参数、端口契约、验证、UI、AI 知识、测试和文档，都从同一份清单派生，或者由同一套门禁拒绝。

## 目录

```text
backend/capabilities_kernel/
  manifest.py              # 九段 dataclass + 结构校验 + manifest digest
  registry.py              # 发现/去重/排序/懒加载/版本检查
  nodes/
    <id>/manifest.py       # 一个能力一个目录（迁移目标）
    <id>.py                # 单文件形式（兼容期，同一 id 两边都有会被拒绝）
```

清单只声明契约，行为仍在 executor 里。清单**不得**导入 pandas/Selenium/Flask 或上层包：`nodes.catalog` 在解析 DAG 时会读它，启动路径必须保持轻。

## 九段

| 段 | dataclass | 回答的问题 |
|---|---|---|
| 身份 | `Identity` | id/kind/version/标题键/分组/目录位置/何时使用 |
| 参数 | `ParamSpec` | JSON Schema 子集（type/default/enum/min/max/required）+ 表单 widget |
| 端口 | `Ports` | 行形状、输入数、`emit_columns`/`read_columns` 的 `module:function` |
| 执行 | `Execution` | 懒加载的 `module:function`、控制台静默策略 |
| 验证 | `Rule` | 运行前的声明式拒绝（`required_param`/`enum_param`/`upstream_required`） |
| UI | `Ui` | 默认 schema 表单，或 `custom_renderer` 逃生口 |
| AI | `Ai` | 工具名、摘要、步骤、可解析的模板 JSON、失败模式 |
| 测试 | `Tests` | 证明该能力的契约测试路径 |
| 文档 | `Docs` | 说明页路径、生成的技能路径、文档哈希 |

`Manifest.problems()` 是完整性门禁的结构半部；`tools/doctor.py` 与 `tests/unit/gates/test_capability_completeness.py` 再补文件系统事实（执行器可导入、文档存在、生成物最新、双语键齐全）。

## 注册表

| 调用 | 行为 |
|---|---|
| `registry.manifests(kind)` | 发现整棵树，按 `identity.order` 再按 id 排序；每个模块只导入一次 |
| `registry.get(kind, id)` / `manifest_for_node(type)` | 只加载被问到的清单 |
| `registry.resolve('module:function')` | 解析执行器/端口钩子；缺模块或缺属性按名拒绝 |
| `registry.node_entries()` | `nodes.catalog` 的投影（type/label/category/rows/quiet/order） |
| `registry.node_defaults()` | `nodes.defaults` 的投影（参数默认值深拷贝） |
| `registry.register_node_executors()` | 把迁移节点的 handler 注册进 `nodes.registry` |

按名拒绝的情况：未知 kind、同一 id 同时有 `x.py` 与 `x/manifest.py`、`api_version` 不是当前版本、清单目录名与 `identity.id` 不一致、九段结构不完整、handler 不是 `module:function` 或不可调用。

## 今天已经派生的表面

- `nodes/catalog.py`：迁移类型从清单合并，按 `identity.order` 插回原槽位；字面表只剩未迁移类型。
- `nodes/defaults.py`：迁移类型的种子参数来自 `ParamSpec.default`。
- `services/validation/engine.py`：`Rule` 的唯一求值器；`engine/workflow.py` 不再为 tokenize 写 if 分支。
- `nodes/schema.py`（血缘）：清单声明的 `emit_columns`/`read_columns` 指向 executor 的同一个函数。
- `manifest.digest()`：声明内容的 SHA-256，供生成物 freshness 门禁使用。

## 还没迁移的表面（P2）

- 前端表单渲染、`canvas.js` 的类型/默认参数/摘要分支、`runs.js` 的验证 if 链。
- executor 文件仍在 `nodes/executors/<type>.py`；P2 把它们移进能力目录。
- 生成物（OpenAPI/工具 schema/技能索引/测试矩阵）与 `doctor` 在 P1 后续切片落地。

## Pilot：tokenize

`backend/capabilities_kernel/nodes/tokenize/manifest.py` 是唯一的声明点。它的四个旧落点已经改读清单：catalogue 槽位 8、默认参数、`engine.tokenize_no_column`、血缘钩子。`tests/unit/capabilities/test_tokenize_manifest.py` 逐项钉住“旧家不再有答案”。

新增一个节点的目标剧本：

```text
backend/capabilities_kernel/nodes/<id>/
  manifest.py
  executor.py
  knowledge/SKILL.md
  examples/*.json
```

然后 `python -m tools.doctor --capability node:<id>` 全绿即可；前端表单、验证、AI 工具、技能索引、测试矩阵、文档索引在 P2-P6 自动派生。
