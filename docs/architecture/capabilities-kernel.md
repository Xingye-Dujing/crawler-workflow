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
| 验证 | `Rule` | 运行前的声明式拒绝（`required_param`/`enum_param`/`upstream_required`/`no_input`/`requires_output`），以及 `validators` 指向的节点专属检查 |
| UI | `Ui` | 默认 schema 表单，或 `custom_renderer` 逃生口 |
| AI | `Ai` | 工具名、摘要、步骤、可解析的模板 JSON、失败模式 |
| 测试 | `Tests` | 证明该能力的契约测试路径 |
| 文档 | `Docs` | 说明页路径、生成的技能路径、文档哈希 |

`Manifest.problems()` 是完整性门禁的结构半部；`tests/unit/gates/test_capability_completeness.py` 再补文件系统事实（执行器可导入、端口钩子可解析、文档/契约测试存在、双语词齐全、生成物最新）。`python tools/doctor.py --all` 从同一组事实逐项打印勾选。

## 生成物（freshness gate）

`python tools/gen_capabilities.py` 从清单渲染五个产物；`--check` 只比较字节：

| 产物 | 用途 |
|---|---|
| `backend/capabilities_kernel/generated/catalog.json` | 机器目录 + 能力 × 检查项测试矩阵（含每个清单的 digest） |
| `backend/capabilities_kernel/generated/openapi.json` | `/api/node-types` 的 OpenAPI 3.1 描述与每个节点的参数 schema |
| `backend/capabilities_kernel/generated/ai_tools.json` | AI 可读的摘要/步骤/示例/失败模式（P4/P6 生成技能与工具） |
| `backend/capabilities_kernel/generated/capability-schema.json` | 浏览器 schema 表单目录（P2 渲染器读取；当前页面仍走 `/api/node-types`，所以它是数据而非已加载的 JS 模块） |
| `docs/capabilities/index.md` | 人类可读的能力索引 |

`tests/unit/gates/test_capability_completeness.py` 调用同一个 `generate.check()`：改了清单却忘记重新生成，CI 直接红，并打印 `run python tools/gen_capabilities.py`。渲染是确定性的（registry 顺序、dataclass 字段顺序、跨平台 LF），所以 Windows 与 Linux 比较的是同一串字节。

## 注册表

| 调用 | 行为 |
|---|---|
| `registry.manifests(kind)` | 发现整棵树，按 `identity.order` 再按 id 排序；每个模块只导入一次 |
| `registry.get(kind, id)` / `manifest_for_node(type)` | 只加载被问到的清单 |
| `registry.resolve('module:function')` | 解析执行器/端口钩子；缺模块或缺属性按名拒绝 |
| `registry.node_entries()` | `nodes.catalog` 的投影（type/label/category/rows/quiet/order） |
| `registry.node_defaults()` | `nodes.defaults` 的投影（参数默认值深拷贝） |
| `registry.register_node_executors()` | 把迁移节点的 handler 注册进 `nodes.registry` |

按名拒绝的情况：未知 kind、同一 id 同时有 `x.py` 与 `x/manifest.py`、`api_version` 不是当前版本、清单目录名与 `identity.id` 不一致、九段结构不完整、handler/validator 不是 `module:function` 或不可调用。

## 今天已经派生的表面

- `nodes/catalog.py`：迁移类型从清单合并，按 `identity.order` 插回原槽位；字面表只剩未迁移类型。
- `nodes/defaults.py`：迁移类型的种子参数来自 `ParamSpec.default`。
- `services/validation/engine.py`：`Rule` 与 `validators` 的唯一求值器；`engine/workflow.py` 不再为 name/upload/tokenize/compile/output 写 if 分支。
- `nodes/schema.py`（血缘）：清单声明的 `emit_columns`/`read_columns` 指向 executor 的同一个函数。
- `manifest.digest()`：声明内容的 SHA-256，供生成物 freshness 门禁使用。
- 五个生成物（`catalog.json`/`openapi.json`/`ai_tools.json`/`capability-schema.json`/`docs/capabilities/index.md`）由 `tools/gen_capabilities.py` 渲染；`tests/unit/gates/test_capability_completeness.py` 的 `generate.check()` 拒绝陈旧字节。
- `tools/doctor.py`：同一组事实的逐项勾选（含 validator 可解析），`--capability node:<id>` 只看一个能力。

## 已迁移 / 还没迁移

已迁移（P2 前六批）：除 `source` 外的全部节点类型——`name`、`upload`、`resume`、`comment`、`process`、
`python`、`analysis`、`tokenize`、`biblio`、`verify`、`fuse`、`accumulate`、`visualize`、`compile`、`output`。
`biblio` 的 56 个参数与选项表就声明在它的清单里，`services/biblio/schema.py` 的 `DEFAULTS`/选项元组由清单派生
（不再保留第二份）。
还没迁移：`source`；前端表单与 `canvas.js`/`runs.js` 的第二套规则也在 P2 后续切片删除。

## 已迁移的例子

`backend/capabilities_kernel/nodes/tokenize/manifest.py` 是最初的 pilot：catalogue 槽位 8、默认参数、
`engine.tokenize_no_column`、血缘钩子四处旧落点都已改读清单，`tests/unit/capabilities/test_tokenize_manifest.py`
逐项钉住“旧家不再有答案”。

P2 第一批按同一模板迁移了 `name`、`upload`、`compile`、`output`：
- `name` 用声明的 `no_input`/`requires_output` 规则表达“必须在头部、必须有下游”；
- `compile`/`output` 用 `validators` 指向 executor 自己的 `validate_node`，把父节点形状检查留在能力目录，
  共享引擎只负责求值和按名报告；
- `upload` 的 `emit_columns` 仍从数据集存储读真实列，清单只声明这个钩子属于它。

新增一个节点的目标剧本：

```text
backend/capabilities_kernel/nodes/<id>/
  manifest.py
  executor.py
  knowledge/SKILL.md
  examples/*.json
```

然后 `python -m tools.doctor --capability node:<id>` 全绿即可；前端表单、验证、AI 工具、技能索引、测试矩阵、文档索引在 P2-P6 自动派生。
