# 架构改进计划（W0–W7）

> 这份文件回答两个问题：**还剩哪些结构债**，以及**每一笔怎么还、用哪个门禁证明还完了**。
> 它不是今天的代码地图（那份是 [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md)），也不是能力契约
> （那份是 [`ADRs`](README.md)）。清单的勾选规则同 [`rewrite-plan.md`](rewrite-plan.md)：代码 + 测试 + 文档 + 门禁 + 收口。

## 结论先行

两个仓库都不需要重写。采析绘的“一个事实一处声明”已经由能力清单 + 生成物 + doctor 钉住
（2026-11-24 复核 `doctor.py --all` 全绿，93 个能力）。真正剩下的只有三类：

1. **契约没铺满**：三个产出表的节点没有 `emit_columns`；`core/asset.py` 没有使用方。
2. **层没拆**：`engine/run.py`、`ai/tools.py`、`api/sessions.py`、`sessions/profiles.py` 是大模块；
   框架的 `store.py` / `agent.py` 是两个上帝对象。
3. **规则只写在文档里**：导入方向、模块预算、HTTP 表面、死模块，过去靠人记；现在由
   `tests/unit/gates/` 执行。

明确不做的：拆微服务、上消息队列、全量事件溯源重写运行记录、引入 ORM/DI 容器、为单一实现造端口。
依据与现实约束见本文末“取舍”。

## W0 校准（已完成 2026-11-24）

- `rewrite-plan.md` 勾掉 7 项已完成但未勾的（RecipeFSM、H3b、H15、H21、工具覆盖门禁、
  完整性门禁、P9 的版本/CI），并把真正未完成的收进该文件的“未完成清单（2026-11-24 校准）”。
- `best_practices.md` §3 的节点类型一行改回清单流程；依赖方向一段改成由门禁执行的规则。
- `core/asset.py` 保留（P2/R2 会接上），并由死模块门禁登记为“有计划的例外”，不是沉默的遗留。

## W1 分层与门禁（已完成 2026-11-24）

四个门禁，每个都能证明自己会红：

| 门禁 | 拒绝什么 |
|---|---|
| `tests/unit/gates/test_import_graph.py` | `api.*` 被 `api/` 与 `app.py` 之外导入；任何模块 import `app`；`core` 依赖其它后端层；无 import 者且未登记的模块 |
| `tests/unit/gates/test_module_budget.py` | 新模块超过 600 行；已冻结模块变大；拆分后预算没跟着降 |
| `tests/unit/gates/test_http_surface.py` | `@*.route/get/post/...` 出现在 `api/` 之外（`app.py` 只有 `/` 一条） |
| `tests/unit/gates/test_capability_completeness.py`（已有） | 清单与生成物、执行器、文档不一致 |

同批修掉的真实耦合：

- **数值解析搬进 `core/values.py`**：`_safe_int`/`_safe_float`/`_optional_*`/`_float_with_default`
  曾住在 `api/http.py`，被 `engine/run.py`、7 个节点执行器、2 个分析模块导入——服务层为了读一个数字而依赖
  Flask。现在只有 `api/http.py` 拿 Flask。
- **模型默认值搬进 `services/models/catalog.py`**：`default_model_path_for` / `read_model_registry`
  曾是 API 层函数，被 `nodes/executors/process.py` 与 `services/components/probe.py` 反向导入。
- **`sessions/routes.py` → `api/sessions.py`，`services/pool/routes.py` → `api/pool.py`**：
  HTTP 表面只剩 `api/` 一处；`sessions/` 与 `services/pool/` 回到“只回答问题”。
- **`runtime/settings.py` 不再 import `app`**：上传上限的 Flask 配置由组合根注册 `on_saved` 钩子重读，
  保存路径（路由 / 预设 / 测试）都走同一个钩子。
- **`core/refs.py` 不再 import pandas**：三个 DataFrame→传输函数搬到 `services/datasets/frames.py`，
  于是每个只想要 `platform_for`/`as_bool` 的导入者不再付 pandas 的启动成本。
- **删掉 16 个空的 `capabilities_kernel/nodes/<id>/__init__.py`**：charts/operators/platforms 都没有，
  这些是迁移脚手架；`doctor.py --all` 仍全绿。

## W2 运行引擎拆分（进行中：决策已抽出，Asset 与拆包未做）

`engine/run.py` 1900 行、`_run_worker` 465 行、`begin_run` 305 行，是全仓最贵的知识。做法是
**函数核 / 命令壳**，不是重写：

- [x] 四个记录决策搬进 `engine/decide.py`，纯函数、无 store：`record_has_component` /
  `record_belongs` / `split_records` / `choose_record`。采用仍然“消耗候选”（调用方 pop 返回的
  下标），因为同一画布可以有两个同名组件。`tests/unit/runs/test_continue_record.py` 覆盖全部
  旧用例 + 一条随机性质（100 组行集，永不在指纹之间串台）。
- [ ] `engine/run/` 包：`claim.py` / `worker.py` / `node.py` / `records.py` / `settle.py` / `stop.py`
- [ ] `core/asset.py` 接上：节点结算写 asset 行，复用键含上游资产哈希

```text
engine/run/decide.py    纯函数：should_reuse / adopt_record / rerun_invalidates / stop_verdict / split_records
engine/run/claim.py     begin_run 的认领与队列（drop:true 语义）
engine/run/worker.py    循环体：取一个节点 → 决策 → 执行 → 结算 → 推进游标
engine/run/node.py      run_node_durable + preflight/postcheck 调用点
engine/run/records.py   _continue_record / _component_run / _close_component_record
engine/run/settle.py    结算；stop.py：停止
```

验收：

- 决策函数的性质测试（幂等、顺序无关、failed 永不当 done）；
- 同一画布第二次运行 0 次浏览器启动、0 次模型调用（Asset 内容寻址）；
- `tests/unit/gates/test_run_worker_module_scope.py` 仍绿；
- 模块预算表里 `engine/run.py` 的数字被删掉或降到 600 以下。

## W3 AI 领域切片

`ai/tools.py`（1697 行、50 个函数、47 个 `ToolSpec`）按域拆成
`ai/tools/{datasets,runs,workflows,models,code}.py`，每个文件末尾一个 `TOOLS` 元组，`ai/tools.py` 只做聚合——
与 `nodes/catalog.py` 同一个手法。同片补两件 P6 的欠账：

- `docs/capabilities/tool-descriptions.md`：命名 `<域>_<名词>_<动词>`、≤8 参数、读写分离、每个工具写“什么时候不该用”；
- qwen3.5:4b/9b 的 20–30 任务评测集与技能选择评测（`docs/testing/model-eval.md`）。

## W4 会话/账号切片

`sessions/profiles.py`（889 行）与 `sessions/preflight.py`（747 行）里，纯判定（路径折叠、锁定、
verdict 缓存键）抽成函数，路由只做序列化。`instagram.dialogs` / `youtube.dialogs` 两个死模块在这里
决定“接入还是删除”，并删掉死模块门禁里对应的例外。

## W5 AI 前端内核化

`ai-workspace.js` 4446 行，承担 SSE 解析、渲染、侧栏、设置、工作室五种职责。拆成：

```text
ai/kernel/   store.js（单一可观察状态） sse.js  http.js  dom.js（安全渲染 + morph）
ai/features/ chat.js  composer.js  sidebar.js  studio.js  watch.js
ai/render/   markdown.js  question.js  artifact.js  toolcard.js
```

零构建、`index.html` 顺序、`splits.json` 登记全部不变；新增“单文件 ≤600 行”的前端门禁
（`zenviz-page.js`、`node-types-fallback.js` 是生成物，豁免）。

## W6 框架收口（agent-workspace）

对齐 [`framework-parity.md`](framework-parity.md) 已写下的目标，用绞杀式迁移，公开 API 一个不改：

| 现在 | 目标 |
|---|---|
| `store.py` 1093 行 / 90+ 方法 / 16 个聚合 | `store/` 每聚合一文件 + `base.py`（连接/迁移）+ `uow.py`；`Store` 变薄门面 |
| `agent.py` 925 行；`run()` 380 行生成器；6 个控制工具 `if name ==` | `agent/` 包；`CONTROL_TOOLS` 处理器表；`messages.py` 三个纯函数 |
| `service.py` 889 行，组合根 + 门面 + 运行时状态 | `turn_runner.py` 拆出；`service.py` 只装配与转发 |
| `Agent(self)` 拿整个门面 | `ports.py` 五个 Protocol（`TurnStore`/`EventSink`/`Provider`/`ToolRunner`/`PolicyEngine`） |

验收不是“文件变小”，而是**用假 store + 假 provider 跑完一轮含提问/审批/产物的 turn，不构造
`AgentWorkspace`**；框架 224 用例与宿主 parity 全绿；新增“框架不出现宿主领域词”的门禁。

## W7 算法与增量

1. **内容寻址执行**：`(节点指纹, 上游资产哈希)` → 结果，复用从启发式变成可证明。
2. **算子级缓存**：`(op, params, input_hash)`，缓存键必须含列名（`正文` 与 `cleaned_text` 是两条曲线）。
3. **游标/账本值对象**：`Cursor(proven_prefix, position)`、`LedgerKey(platform, comment_id)`，把规则变成类型不变量。
4. **采集节流/风控纯函数化**：`Attempt`/`Outcome`/`RetryPolicy`，性质测试钉住“网络故障永不轮换账号”。
5. **工具检索式路由**：BM25 + embedding + RRF 取代“按用户原话排序”。

## 取舍与边界

- **不拆进程**：单运行槽、单数据根、`MAX(seq)+1` 是产品语义；模块化单体的收益在边界与门禁，不在网络。
- **不给数据表做减重**：`runtime/settings_schema.py`（94 条 `Setting`）、`i18n_catalog/*`、清单文件是声明；
  行长门禁按名字豁免它们，否则会逼出更糟的设计。
- **不为单一实现造端口**：采析绘的采集后端（selenium/catbus）与框架的 provider/store 是真实接缝；
  其它地方加接口只是多一层间接。
- **一个门禁只在它能红的时候才保留**：每个新门禁都带一个“合成缺陷必须被抓住”的用例
  （`test_the_gate_can_fail`），否则它只是打印了一行绿色的字。
