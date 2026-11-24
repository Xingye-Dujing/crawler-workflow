# ADR-004：AI 上下文、产物分组与会话执行

- 状态：已接受（2026-11-25）
- 相关：[ADR-001](ADR-001-kernel-replacement.md)、[ADR-002](ADR-002-capability-manifest.md)、
  [ADR-003](ADR-003-durable-state.md)、[四模块实施规划](ai-workspace-modules-plan.md)
- 影响：AI 框架 `agent-workspace`（0.2.0）、采析绘 `backend/ai_host/`、`api/ai_workspace.py`、
  `services/exports/`、`services/runs/store/`、`backend/static/js/ai/`、`backend/static/js/panels/exports.js`

## 背景

今天的 AI 工作区已经有可靠的地基：回合在后台线程运行，事件写入持久日志，断线后可以按 `seq`
续传（ADR-003，框架 0.1.30）。但四个用户可见的能力仍停在“单值、平铺、会话级之外”：

1. **技能是一轮一个字符串。** `ChatRequest.skill` 是一个 id，回合只把该技能的 `prompt` 放进系统提示；
   技能的 `context` 声明没有被 `ContextBuilder` 消费。`@skill:id` 目前走的是“能力技能正文”的文本展开，
   和专家模式是两套东西。
2. **技能正文没有渐进披露。** 自动路由只返回一个 id；没有被选中的技能连元信息都不进上下文，AI 也
   没有“先看目录、再读正文、最后读资源”的通用入口。
3. **产物是平铺文件。** `run_files` 已经知道一次运行写了哪些文件，但 `export_dir` 的读写、下载、删除
   都假设“没有子目录”，前端也只能画一张平表。运行记录与产物之间没有可浏览的文件夹边界。
4. **工作目录是账号级、模型是请求级。** `Workspace.root()` 读账号 `prefs`，同一账号的所有会话共用
   一个目录；`conversations` 表没有 `workspace_dir`，也没有 `provider/model`。前端
   `_rememberConversationModel()` 已经在 PATCH `provider/model`，但 `patch_conversation` 只接受
   `title/pinned/archived`，所以这次写入一直被静默丢弃。
5. **断线恢复没有接到界面。** 框架的 `subscribe(after)` 已经能续传，`selectConversation()` 却只
   GET 一次消息；切走再回来时，正在跑的回合仍在服务端继续，界面不知道它还在跑。
6. **并发没有调度边界。** 每个 `ask()` 直接起一个线程，没有全局上限，也没有“同一会话只允许一个
   活动回合”的约束；两个标签页可以在同一会话里同时开两轮。

这些事实各自都有明确的归属：技能、提及、工作目录、产物分组、回合调度都是**框架级通用能力**；
节点、工作流、运行记录、导出目录才是采析绘的领域事实。把它们继续写进宿主或前端，会形成第二份
规则，下一次改动就会分叉。

## 决策

### D1. 提及（mention）是一种通用原语，分“内容”和“指令”两类

`@` 解析仍是唯一的入口，但解析结果分成两类：

- **内容引用**（`dataset`、`run`、`workflow`、`export`、`capability`、`file`、`artifact`、
  `conversation`、`group`）：展开为有界文本，追加到该轮 user 行，和今天的行为一致。
- **指令引用**（`skill`）：不展开正文，而是把该 id 加入本轮的技能集合；它改变的是本轮的系统提示与
  工具白名单，不是用户消息的文本。

两类共享同一个解析器、同一份安全校验：路径 root allowlist、单文件字节上限、文本类型白名单、
单项/整轮字符预算、脱敏计数。框架只认识 `MentionKind` 的声明，具体对象由宿主通过
`HostAdapter.reference_candidates()` / `resolve_reference()` 提供。

### D2. 技能是“轮次级集合”，会话只保存默认值

- `conversations.skills`（JSON 数组）保存该会话下一轮的默认显式技能；空数组表示 `auto`。
- `ChatRequest.skills`（字符串数组）是本轮的显式集合；空数组表示 `auto`。请求值覆盖会话默认值。
- `auto` 路由返回**有序的多个候选**（默认最多 3 个，分数为 0 的不入选；只有显式集合为空时才运行）。
- 解析结果 = 显式集合（若有）+ 自动候选（若显式为空）+ 本轮 `skill_load` 工具加载的技能。
- 任一显式技能在本机/本供应商不可用时，按名字拒绝整轮，不静默丢弃；自动候选不可用时才回落
  `general`（用户没有选它）。
- 一条 `@skill:id` 提及把本轮切到显式集合；它不改变会话默认值。用户在输入框里多选技能才会写回
  `conversations.skills`。

### D3. 技能采用三层渐进披露

- **L0 元信息**：每个可用技能一行 `id — name/description`，作为系统提示的“技能索引”常驻。只有元信息，
  没有正文。
- **L1 指令体**：显式/自动选中的技能，其 `prompt` 作为独立段落进入系统提示；AI 通过
  `skill_catalog(query)` 检索元信息、再用 `skill_load(skill_id)` 加载正文；工具加载的正文作为该次工具
  结果进入上下文，并在后续轮次把它加入工具白名单。
- **L2 资源/脚本**：`skill_load(skill_id, resource=...)` 读取该技能声明的一项资源；资源索引由
  `HostAdapter.skill_resources(skill_id)` 提供，正文由 `HostAdapter.skill_resource(skill_id, name)`
  读取，统一 12k 字符上限。没有资源的技能只返回空索引。能力（节点/算子/图表/平台）文档改用
  `capability_catalog` / `capability_load`，与专家技能的 `skill_*` 词汇分开。

`ContextBuilder` 在这一层同时补上一个既有缺口：只组装**活动技能声明的 context 来源**（并集），而不是
把所有来源无条件塞进每一轮。`turns.skills` 与 `meta.context.skills` 记录本轮实际生效的集合及来源
（`explicit` / `auto` / `tool`），刷新后仍可追溯。

### D4. 产物分组是运行记录拥有的物理文件夹

- 一次运行在 `export_dir` 下拥有一个文件夹，名字为 `{工作流文件名}_{YYYY-MM-DD_HH-MM-SS}`，冲突时追加
  `-2`、`-3`；文件夹名经过 `sanitize_filename` 并按 UTF-8 字节截断，避免 Windows 路径超限。
- 分组身份是 `run_id`；`runs.export_group` 保存最终文件夹名（续跑复用，不重新起名），
  `run_files.group` 保存文件所属分组。它们与 `run_files.name`（basename）一起构成“运行 → 分组 → 文件”
  的唯一答案。
- 运行上下文携带 `export_dir`（该分组目录）；source/comment/analysis 的 `PartWriter`、`SnapshotWriter`、
  output、report 都从上下文取目录，不再各自读账号级 `EXPORT_DIR`。手动导出/工作室图表进入
  `_手动导出` 分组。
- `list_exports` 从“平铺扫描”改为“分组树”；下载、删除、清空、分片批量删除都接受
  `(group, name)`，解析器同时校验两段，任何 `..`、绝对路径或符号链接逃逸按名拒绝。
- 存量平铺文件由一次性迁移工具按 `run_files` 移入对应分组；没有账本的文件进入 `_历史产物`。
  迁移先 `--dry-run`，写 `migration_manifest.json`，支持反向移动；运行时只有一条新布局，不保留双读路径。

框架不解释 `run`、`workflow` 或 `export_dir`。它只提供通用值对象与宿主钩子：

```text
ArtifactGroup(id, label, root, kind, metadata, created_at)
HostAdapter.artifact_groups(account) -> list[ArtifactGroup]
HostAdapter.artifact_group_entries(account, group_id) -> list[dict]
HostAdapter.artifact_group_guidance(group) -> str
```

采析绘把 `run_id` 映射为 `ArtifactGroup`，把 `run_files` 映射为 entries；框架只做校验、合并与呈现。

### D5. 工作目录绑定到会话，产物分组可一键挂载

- `conversations.workspace_dir` 保存该会话的根路径；`workspace_group` 保存它来自哪个产物分组（空表示
  会话自己的目录）；`workspace_label` 是侧栏显示名（不向前端暴露绝对路径）。
- 新会话默认创建独立目录 `<host.data_dir()>/workspaces/<conversation_id>`；用户也可以挂载一个
  `ArtifactGroup`，此时 `workspace_dir` 指向该分组的真实根，多个会话可以共享同一个分组。
- `Workspace.root()` / `resolve()` 接受 `conversation_id`：会话根优先，账号 `prefs` 只作为未绑定会话的
  默认值。工具通过 `ctx.conversation_id` 取到同一个根。
- 挂载分组时不把文件内容注入上下文，只注入“目录存在 + 顶层条目名 + 该分组类型的提示词扩展”。
  提示词扩展由 `HostAdapter.artifact_group_guidance(group)` 返回，框架按 `group.kind/metadata` 匹配，
  采析绘配置“这是一次工作流运行的导出，目录约定/典型任务”等内容。
- 目录读取仍走已有的 `workspace_list` / `workspace_read`；AI 自己决定读哪些文件、何时读。
- 云端没有用户本地文件系统：分组仍可在产物面板浏览/下载，但“挂载为工作目录”按名拒绝。

### D6. 模型选择是“会话默认 + 轮次覆盖”两级

- `conversations.provider` / `conversations.model` 是该会话的默认模型；`PATCH /conversations/<id>` 原子
  更新一行，不重建会话。
- 每轮请求的 `provider/model` 覆盖会话默认值；解析后的值写入 `turns.provider/model`，`meta` 事件携带，
  该轮的 assistant 行只按 `turn_id` 关联，不复制第二份模型字段。
- 切换前由框架做历史兼容检查：历史里已有 `tool_use/tool_result` 时，新供应商必须声明 `tools`；已有内联
  图片时必须声明 `vision`/`inline_images`。不兼容按名拒绝（`model.historyIncompatible`），不静默发送。
- 会话详情返回 `turns` 摘要（id、state、provider、model、skills），前端据此在每一轮标注实际模型；
  侧栏的会话摘要继续显示会话默认值。

### D7. 回合与连接解耦，执行有界且按会话隔离

- 保留 ADR-003 的持久事件日志与 `subscribe(after)`；新增“会话详情包含活动回合”和前端重连，
  连接断开不取消回合，重连用同一份事件日志重建画面。
- 新增 `TurnScheduler`：每会话最多一个活动回合；全局并发上限 `turns.max_parallel`（默认 4，0=不限）。
  同一会话的新消息在已有活动回合时进入邮箱，不并行开第二轮；不同会话各自持有线程、账号上下文和工作目录。
- 进程重启后仍在跑的回合按 ADR-003 收敛为 `interrupted`，不假装续跑；界面明确显示“中断”，重试复用
  原回合的 provider/model/skills/context。只有连接断开才走重连续传。
- 每一步的可恢复检查点仍是“先落库再推进”：助手行在首字节前以 `streaming` 落盘，工具步骤先写
  `running`，事件先写 `turn_events` 再广播。调度器只决定何时开始，不改变这些写入顺序。

## 契约（框架 ↔ 宿主）

| 目的 | 框架侧 | 采析绘侧 |
|---|---|---|
| 技能集合 | `ChatRequest.skills`、`turns.skills`、`meta.context.skills` | `api/ai_workspace.py` 映射请求；`ai_host/adapter.py` 把 `ai.skills.BUILTIN` 转成 `SkillSpec` |
| 技能路由 | `Skills.route_many(text, account, limit)` | 每个技能声明中英 `keywords`；评测表给多标签期望 |
| 渐进披露 | `ContextBuilder` 的 L0 索引、`skill_catalog`/`skill_load`（含 `resource=`） | `HostAdapter.skill_resources()/skill_resource()` 读文档、脚本、源码；能力文档走 `capability_*` |
| 提及 | `References` 的 `MentionKind(mode='content'|'directive')` | `reference_candidates()` / `resolve_reference()`；`@capability:id` 取代旧 `@skill:id` |
| 产物分组 | `ArtifactGroup`、`HostAdapter.artifact_groups()` / `artifact_group_entries()` | `runs.export_group` + `run_files.group` + `services/exports/groups.py` |
| 工作目录 | `Workspace(conversation_id)`、`mount_group()`、`ContextBuilder` 的工作目录段 | 默认目录、分组根、`artifact_group_guidance()` |
| 模型 | `conversations.provider/model`、`catalog.history_problems()` | 设置页/输入框 PATCH；会话详情 `turns` |
| 执行 | `TurnScheduler`、`subscribe(after)`、`GET /turns/<id>/events` | 前端 `selectConversation()` 重连；关闭 dock 不取消 |

## 后果

- 框架公开 API 变化（`skill` → `skills`，新增会话字段、ArtifactGroup、Workspace 会话根、调度设置），
  版本从 `0.1.30` 升到 `0.2.0`，重建 wheel 并替换 `vendor/agent_workspace-0.1.30-py3-none-any.whl`。
- `ai.db` 需要一次 schema 迁移：`turns.skills` / `pending_calls.skills` 取代单值 `skill`；
  `conversations` 增加 `provider/model/skills/workspace_*`。迁移前复制 `ai.db.pre-0.2.0`，运行时不保留
  旧字段的双读路径。
- 导出目录需要一次布局迁移；新写入只有一个目录来源（运行上下文的 `export_dir`），旧平铺布局在迁移后
  不再被读取。
- 前端新增多选技能、`@skill` 指令、分组树、工作目录 chip、逐轮模型标注和重连；`panels/exports.js`
  预计超过 600 行，按既有规则拆出 `panels/exports-tree.js` 并登记 `index.html`/`splits.json`。
- 所有新增用户文案进 `i18n_catalog/ai.py` 与浏览器 `static/js/i18n/ai.js` 的同一域，中英齐全；
  框架侧文案进框架自己的 `i18n.py`。

## 被否决的替代方案

- **在宿主复制技能路由/正文加载**：会形成第二份技能事实，和在框架里加领域分支同样有害。
- **把 `@skill` 继续当作文本展开**：正文进了用户消息，工具白名单不变，模型看得到却用不了。
- **按账号维护一个“当前工作目录”**：切换会话会互相覆盖；ADR-003 的会话隔离也要求按会话绑定。
- **只在前端把运行记录聚合成文件夹**：刷新、换设备、AI 读取时都没有同一个分组事实；而且一键挂载
  需要真实根路径。
- **把产物分组做成虚拟视图**：会让 `workspace_read/run_cmd` 与真实路径语义分叉；物理文件夹是更小的
  总复杂度。
- **进程重启后自动续跑半截供应商流**：供应商流没有可恢复的字节位置，假装续跑会重复计费或写出断裂的
  回答；`interrupted` + 重试是诚实的边界。
