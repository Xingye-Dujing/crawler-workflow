# AI 工作区四模块实施规划

- 日期：2026-11-25
- 状态：已实施（2026-11-25；模块 1–4 与框架 0.2.0 已接入，验收见文末）
- 决策记录：[ADR-004（提议）](ADR-004-ai-context-artifacts-sessions.md)
- 相关：[ADR-001](ADR-001-kernel-replacement.md)、[ADR-002](ADR-002-capability-manifest.md)、
  [ADR-003](ADR-003-durable-state.md)、[framework-parity](framework-parity.md)、
  [`docs/ai_workspace.md`](../ai_workspace.md)

这份文档回答四个问题：**每项落在哪一层、框架与采析绘通过什么契约协作、按什么顺序做、怎么证明做完了**。
它不描述“将来某天可能做”的方向；每一项都有可运行的验收。与 ADR 冲突的实现必须先改 ADR，不能默默绕过。

## 1. 结论先行

- **框架先行，宿主只做翻译。** 四个模块中属于“换一个宿主也需要”的部分全部进 `agent-workspace`：
  多技能集合、渐进披露、提及指令、产物分组元数据、会话工作目录、两级模型、回合调度与重连续传。
  采析绘只提供节点/工作流/运行记录/导出目录这些领域事实，以及 HTTP/UI 的薄接线。
- **模块 3 先做，再做模块 4（1）。** 没有“产物分组”这个一等事实，就没有可挂载的根路径；没有
  `conversations.workspace_dir`，挂载也无处持久化。因此顺序是 **3 → 4（2）→ 4（1）**。
- **模块 1 与模块 2 是一条链。** 先有“本轮技能集合”，才谈得上“AI 自己加载更多技能”；先有统一提及，
  才有 `@skill` 指令与 `@capability` 内容的区分。
- **模块 4（3）与 4（4）是会话基础设施的两半。** 模型两级选择先落库（4.3），重连与调度再把
  “回合属于会话、不属于连接”变成可观察的事实（4.4）。
- **框架版本升到 0.2.0。** 这是公开 API 变化（`skill` 字符串 → `skills` 数组、会话新字段、
  `ArtifactGroup`、`Workspace` 会话根、调度设置），不是补丁版本。宿主 `vendor/` 只保留新 wheel。

## 2. 现状核对（为什么不是从零开始）

| 事实 | 现状 | 缺口 |
|---|---|---|
| 回合与连接解耦 | `agent_workspace/turn_runner.py` 的 `ask()` 建 turn 后起后台线程；`subscribe(after)` 从 `turn_events` 续传；`test_a_closed_subscription_does_not_stop_the_turn` | 前端 `selectConversation()` 只 GET 消息，不查询活动回合，也不订阅 `/turns/<id>/events` |
| 持久中断 | `pending_calls` + `answer(call_id)`；重启 rehydrate；`test_the_interrupt_travels_through_a_restart` | 已回答/已中断的展示已有，但“活动回合”没有出现在会话详情里 |
| 技能 | `SkillSpec` + `Skills.route` 单值；`ChatRequest.skill` 字符串；`turns.skill`、`pending_calls.skill` | 没有多选、没有 `@skill` 指令、没有 L0/L1/L2、没有每轮 loaded 记录 |
| 技能上下文 | `SkillSpec.context` 已声明 | `ContextBuilder.build()` 不接收技能，`context` 实际未被消费 |
| `@` 引用 | `references.py` 的 `KINDS` 含 `skill`，`@skill:id` 展开为能力技能正文；单文件 1200 字、整轮 6000 字 | 文件引用读 `path/name` 而不是 `meta.text`；没有 root allowlist/类型白名单；没有“指令”与“内容”之分 |
| 能力技能 | `skill_catalog` / `skill_load` 生成 L1/L2 正文 | 与专家技能同名冲突；AI 没有统一的“专家技能检索”入口 |
| 产物 | `run_files` 已记录 `run_id → name/kind/node_id`；`export_dir` 平铺 | 没有分组列、没有文件夹、没有树；`resolve_export_file` 只接受一个 basename |
| 工作目录 | `Workspace.root()` 读账号 `prefs`；`/workspace` 是账号级 | 没有 `conversations.workspace_dir`；工具总是拿账号根 |
| 模型 | `request.model` 覆盖；`turns.model` 记录 | `conversations` 没有 `provider/model`；前端 PATCH 被 `patch_conversation` 白名单丢弃 |
| 并发 | 每个 `ask()` 一个线程；`_active_conversation` 只记最后一个 | 没有全局上限；同一会话可有多个活动回合；前端不重连 |

证据文件：`agent_workspace/agent/turn.py`（单 `skill`、`_system` 只用 `skill.prompt`）、
`agent_workspace/references.py`（`KINDS`、`_expand_one('file')`）、`agent_workspace/workspace.py`
（账号根）、`agent_workspace/store/transcript.py`（`patch_conversation` 白名单）、
`backend/ai_host/adapter.py`（`resolve_reference('skill')`、`run.get('id')` 取错字段）、
`backend/api/ai_workspace.py`（PATCH 只转发 `title/pinned/archived`）、
`backend/services/exports/browser.py`（“exports are flat by construction”）、
`backend/static/js/ai/features/sidebar.js`（`selectConversation`）。

## 3. 架构落点

### 3.1 分层图

```text
agent-workspace（框架）
  domain/          types.py：SkillSpec / ChatRequest.skills / ArtifactGroup / Mention
                   references.py：MentionKind(content|directive) + 安全上限
  application/     skills.py：SkillRegistry.route_many + SkillContextProvider(L0/L1/L2)
                   context.py：ContextBuilder（技能 L0、活动技能 context、工作目录段）
                   workspace.py：Workspace(conversation_id) / mount_group
                   turn_runner.py：TurnScheduler + subscribe(after) + active_turn
                   agent/turn.py：本轮技能集合、每轮 allowed 重算、skill_load 激活
  infrastructure/  store/transcript.py：会话/回合/中断的新字段与迁移
  adapters/        adapters/flask.py：通用路由（可选；采析绘自带薄蓝图）
        ▲ HostAdapter
        │ （唯一反向注入点；框架不 import 宿主）
采析绘（宿主）
  ai_host/adapter.py     技能/工具/资源/产物分组/工作目录提示/模型兼容的领域翻译
  api/ai_workspace.py    /api/ai/ws 的请求映射与会话详情
  services/exports/      分组路径、树、下载/删除/迁移
  services/runs/store/   runs.export_group + run_files.group
  static/js/ai/          多选、@ 指令、工作目录、逐轮模型、重连
  static/js/panels/      产物树（必要时拆 exports-tree.js）
```

### 3.2 模块归属

| 模块 | 框架层 | 采析绘层 | 通信契约 |
|---|---|---|---|
| 1 多技能与 `@` | `types.ChatRequest.skills`、`Skills.route_many`、`references.MentionKind`、`agent/turn.py` | 输入框多选、`@` 菜单、`api/ai_workspace.py` 映射、`ai_host` 技能声明 | `ChatRequest.skills` / `turns.skills` / `meta.context.skills`；`reference_candidates`/`resolve_reference` |
| 2 AI 自检索 | `skills.py` 的 L0/L1/L2、`ContextBuilder`、`skill_load` 工具 | `HostAdapter.skill_resources/skill_resource`、能力技能 `capability_catalog/load` | `skill_load(skill_id, resource)` → `{body, resources}`；`turns.skills[].source='tool'` |
| 3 产物分组 | `types.ArtifactGroup`、`HostAdapter.artifact_groups/artifact_group_entries`、`Workspace` 分组根 | `runs.export_group`、`run_files.group`、`services/exports/groups.py`、树 API、`panels/exports.js` | `ArtifactGroup(id,label,root,kind,metadata)`；entries `{name,type,size,mtime,kind}` |
| 4（1）挂载分组 | `Workspace.mount_group`、`ContextBuilder` 工作目录段、`HostAdapter.artifact_group_guidance` | 一键入口、默认目录、分组根解析 | `POST /conversations/<id>/workspace {group_id}`；`workspace_dir/workspace_group` |
| 4（2）会话工作夹 | `conversations.workspace_*`、`Workspace.root(conversation_id)`、`AgentWorkspace.create_conversation` | 默认目录、侧栏分组、bootstrap 字段 | 会话详情/列表带 `workspace_label`；`DELETE /conversations/<id>/workspace` |
| 4（3）模型两级 | `ChatRequest.provider/model`、`conversations.provider/model`、`catalog.history_problems` | 模型选择器、逐轮标注、PATCH | `PATCH /conversations/<id> {provider,model}`；`turns[]` |
| 4（4）后台/并发 | `TurnScheduler`、`active_turn`、`subscribe(after)`、`turns.max_parallel` | 重连、关闭 dock 不取消、并发测试 | `GET /conversations/<id>` 的 `active_turn`；`GET /turns/<id>/events?after=` |

### 3.3 框架 ↛ 宿主的硬边界

- 框架代码里不出现 `workflow`、`dataset`、`export`、`run_id` 这类领域词作为分支条件；它们只能作为
  宿主提供的 `ArtifactGroup.metadata` 或技能资源名出现。
- 采析绘不复制回合循环、审批、事件序列化、技能路由或提及解析；`api/ai_workspace.py` 只做请求/响应映射。
- `tests/test_no_host_vocabulary.py` 增加新词表；任何“为了采析绘方便”的框架分支都按缺陷处理。

## 4. 模块 1：多技能与动态切换

### 4.1 数据与请求

```text
conversations.skills      JSON 数组，默认 []（auto）
ChatRequest.skills        list[str]，本轮显式集合；[] = auto
turns.skills              JSON 数组，元素 {id, source, score?}
pending_calls.skills      JSON 数组，回答恢复时复用
meta.context.skills       {requested: [...], auto: [...], loaded: [...], resolved: [...]}
```

- `source` 取值 `explicit` / `auto` / `tool`；`resolved` 是最终实际生效的 id 顺序。
- `turn.skills` 在 `_open_turn` 时写入显式集合；自动路由完成后由 `set_turn_origin` 更新；
  `skill_load` 工具执行时追加 `tool` 项（同一 id 不重复）。
- `ChatRequest.skills` 为空时读取 `conversations.skills`；两者都空才走 `auto`。
- 显式集合去重、保序；同一技能重复提及只算一次。显式数量上限 8（超过按名拒绝 `skills.tooMany`）。

### 4.2 自动多匹配

`Skills.route_many(text, account, limit=None)`：

1. 复用现有打分：`suggested` 整句 +5、`keywords` +词长、id 英文词 +3；
2. 分数 > 0 的候选按分数降序、id 升序；
3. 取前 `skills.auto_max`（默认 3），并丢掉分数低于最高分 50% 的候选；
4. 返回 `[{id, score}]`，不在这里做可用性过滤（可用性由回合决定，记录 `chosen`）。

`auto` 路由只在显式集合为空时运行。选中技能不可用时回落 `general`，但 `meta.context.skills.auto` 保留
路由原始候选，便于解释“为什么是 general”。

### 4.3 `@` 提及

- 文本正则识别 `@skill:<id>`、`@capability:<id>`、`@file:<id>`、`@group:<id>` 等；结构化 chip 走
  `references.resolve_rows()`。
- `skill` 是 `directive`：加入本轮显式集合，不展开文本；未知 id 按 `skill.unknown` 拒绝整轮。
- `capability` 是 `content`：展开能力技能正文（原 `@skill` 的语义迁移到这里），未知 id 留在
  `unresolved`，不阻断整轮。
- `file` 是 `content`：优先读 `files.meta.text`；只有宿主声明了路径才读文件。读取前校验 root allowlist、
  文本后缀白名单、单文件 64 KB 与整轮预算，结果脱敏。
- `group` 是 `content`：展开分组名 + 顶层文件名列表（不含内容），为跨会话检索提供“整体引用”。
- 所有 mode 共用 `MAX_REFS=20`、单项 1200 字、整轮 6000 字；超出部分在 `context_meta` 里报告。

### 4.4 会话内切换与可追溯

- 输入框取消单个 `<select>`，改为“自动 chip + 已选技能 chips + 添加菜单”。chips 顺序就是本轮顺序；
  `@` 菜单选中的技能进入同一组 chips，并在发送时进入 `skills` 而不是 `references`。
- 会话默认值在用户通过选择器增删时 PATCH `conversations.skills`；`@` 提及只影响当前消息。
- 每轮 user 行 `meta.skills` 保存解析后的集合；assistant 气泡与侧栏检查器显示“显式/自动/工具加载”的来源。
- 刷新后 `selectConversation()` 从 `conversations.skills` 恢复选择器，从消息 `meta.skills` 恢复每轮标注。

### 4.5 验收

| 编号 | 情形 | 期望 | 证据 |
|---|---|---|---|
| SK-1 | `skills=['crawl','analysis']` 显式发一轮 | 两个技能的 prompt 段落都在系统提示；工具白名单是并集；`turns.skills` 两项 `explicit` | 框架 `test_skills_multi.py`；宿主 `test_ai_host_adapter.py` 用捕获 provider 的 prompt |
| SK-2 | 文本只写 `@skill:analysis`，选择器为空 | 本轮解析为 `analysis`，`meta.context.skills.requested` 含它；正文里不出现展开的能力技能正文 | 框架 references 测试；前端 harness |
| SK-3 | `auto` 问句同时命中两个技能 | `route_many` 返回两项，`turns.skills` 两项 `auto`；超过 3 个只取前三 | 路由单测 + 18 条语料扩展 |
| SK-4 | 显式技能本机不可用 | 整轮按 `skill.unavailable` 拒绝，错误里带技能 id | 框架 availability 测试；API 用例 |
| SK-5 | 同一会话第二轮换技能 | 不新建会话；第二轮 `turns.skills` 与第一轮不同；第一轮记录不变 | 框架 turns 测试；宿主 API 用例 |

## 5. 模块 2：AI 自主检索与渐进披露

### 5.1 L0 / L1 / L2

```text
L0  Skills.index(account, provider, model) -> [{id,name,description,available?,group}]
L1  Skills.body(id) -> SkillSpec.prompt（显式/自动直接进系统提示；工具加载作为 tool result）
L2  HostAdapter.skill_resources(id) -> [{name,description,bytes?}]
    HostAdapter.skill_resource(id, name) -> bounded text（≤12000 字）
    skill_catalog(query='', limit=30) -> [{id,name,description,available?,group}]
    skill_load(skill_id, resource='') -> {id, body?, resources:[...], resource?: text}
```

- `ContextBuilder` 在项目事实之后追加 `## 技能索引`，每个可用技能一行；不可用技能不出现（避免模型选中
  后才发现被拒）。索引超出 8k 字时按 group/id 截断并在 `context_meta.omitted` 记一项。
- 显式/自动技能的正文以 `## 技能：<id>` 段落进入系统提示；`skill_load` 加载的正文只作为工具结果进历史，
  避免同一段文字在系统提示与工具结果里各付一次 token。
- `skill_catalog` 是 L0 的按需检索（查询/上限），`skill_load` 返回 L1 正文与 L2 索引；带 `resource`
  参数时返回该资源正文。资源索引为空是正常结果，不是错误。
- 能力（节点/算子/图表/平台）文档改用 `capability_catalog` / `capability_load`（原 `skill_catalog`/
  `skill_load` 的实现迁到新名），与专家技能的 `skill_*` 词汇分开；系统提示用一句话说明两者区别。

### 5.2 激活与工具白名单

- 每轮开始解析 `activation = {explicit, auto, loaded}`；`allowed = union(skill.tools for activation) | universal`。
- 工具结果 `skill_load` 成功后，`activation.loaded` 增加该技能；下一轮重建 `allowed` 与 `priority`，
  所以新技能的工具从下一轮起可用。本轮已发出的工具列表不变（契约不回溯）。
- 配方遮罩、plan 模式、`chat_only` 仍然最后生效；技能不能绕过它们。

### 5.3 显式优先与共存

- 显式集合存在时，`auto` 不运行；AI 仍可 `skill_load` 其他技能，`meta.context.skills.loaded` 记录。
- 显式集合为空时，`auto` 先给候选；AI 再加载的技能与自动候选共存，`resolved` 是并集（显式/自动在前，
  工具加载在后）。
- 一轮结束的 `turns.skills` 是最终事实；`_TurnOutcome.summary()` 把它交给 `turn_finished`，通知/监控可以
  引用同一份集合。

### 5.4 验收

| 编号 | 情形 | 期望 | 证据 |
|---|---|---|---|
| SD-1 | 启动/首轮 | 系统提示只有技能索引，**没有**未选中技能的正文 | 捕获 provider payload；`test_skill_progressive_disclosure.py` |
| SD-2 | 问句需要未选技能，模型调 `skill_load` | 工具结果含正文；下一轮 `allowed` 含该技能工具；`turns.skills` 多一项 `tool` | 脚本 provider 两轮用例 |
| SD-3 | `skill_load(..., resource=...)` | 返回有界资源正文；超过 12k 截断并 `truncated:true` | 框架资源测试 |
| SD-4 | 显式 `@skill:crawl` + AI 再加载 `analysis` | 两项都在 `resolved`；显式在前 | meta 断言 |
| SD-5 | 能力文档查询 | `capability_catalog`/`capability_load` 仍工作；`skill_load` 不再返回能力技能正文 | 宿主工具测试 + `tool-descriptions` 门禁 |
| SD-6 | `skill_catalog(query)` | 只返回专家技能元信息；unknown id 不混入 | 框架工具测试 |

## 6. 模块 3：产物文件夹分组与树状面板

### 6.1 运行记录拥有分组

```text
runs.export_group          TEXT DEFAULT ''    -- 最终文件夹名；续跑复用
run_files.group            TEXT DEFAULT ''    -- 文件所属分组
run_files.name             TEXT               -- 仍是 basename
export_dir/<group>/<name>                     -- 唯一的新布局
```

- 运行启动时（`begin_run`，拿到 `run_id` 与 `workflow_name/started_at` 之后）计算分组名并写
  `runs.export_group`；续跑（`resume_run_id`）直接复用旧值。
- 分组名：`sanitize_filename(workflow_name, 80 bytes) + '_' + time.strftime('%Y-%m-%d_%H-%M-%S')`；
  目录已存在时追加 `-2`、`-3`，用 `os.mkdir` 的 `FileExistsError` 原子占位。
- 目录只在第一次写文件时创建；没有产出的运行没有文件夹，也不会出现在树里。
- 手动导出/工作室图表：`_手动导出` 分组（稳定名，不按时间分桶）。

### 6.2 运行上下文携带目录

- `engine/run` 在认领时把 `export_dir`（`paths.active().export_dir/<group>`）放进运行上下文。
- `source.py` / `comment.py` 的 `PartWriter`、`analysis/llm.py` 的 `SnapshotWriter`、`output.py` 的
  `DataExporter.save`、`api/report.py` 的论文生成、`api/studio.py` 的图表落盘都从上下文取目录；
  不再各自拼账号级 `EXPORT_DIR`。
- `record_file(ctx, node_id, name, kind)` 从 `ctx` 取 `group`，写 `run_files(group,name,kind,node_id)`。
  `run_files` 的主键仍是 `(run_id,name)`（同一运行内 basename 唯一）。
- `services/exports/groups.py` 是分组路径的唯一住址：`group_dir()`、`resolve_member()`、
  `list_group()`、`rename/group_name()`；浏览器、writer、API、workspace 挂载都读它。

### 6.3 读写接口

```text
GET  /api/exports/tree?limit=200
  -> {ok, groups:[{id(label), label, kind, created_at, count, bytes,
                   files:[{name, path, kind, size, mtime, downloadable}]}], totals}
GET  /api/exports/download?group=<g>&name=<n>
POST /api/exports/delete {group, name}
POST /api/exports/clear {confirm:true}
POST /api/exports/clear-run {run_id, confirm:true}
POST /api/exports/clear-run-parts {run_id, node_id, confirm:true}
POST /api/exports/clear-name {group, name, confirm:true}
```

- `resolve_member(export_dir, group, name)` 同时校验两段：group 必须是已知分组名（来自 `runs.export_group`
  或 `_手动导出/_历史产物`），name 必须是单段；解析后的 realpath 必须留在 `export_dir/<group>` 内。
- 下载拒绝 `.py/.js/.html/...` 的规则保持不变；报告仍走 `resolve_report_path`，只是接受 group。
- 删除一个分组的最后一个文件不自动删目录：运行记录还在时，分组仍应在树里显示为空（或由前端显示“空”）。
- `run_ledger()` 带 `group`；智能清除按 `run_id` 找 `run_files`，不再靠文件名猜。

### 6.4 树状面板

- `panels/exports.js` 改为树渲染：分组行（文件夹图标、展开箭头、名称、文件数/大小、挂载按钮、
  按运行清除/固定）与文件行（类型图标、名称、大小、时间、下载/查看/删除/固定）。
- 缩进用 CSS 变量 `--depth`，`role="tree"/"treeitem"`、`aria-expanded`；展开状态存
  `exportsManager._expanded`（页面内记忆，不写服务器）。
- 文件/文件夹视觉区分只用 OMM-ZEN token：文件夹用线框图标 + 名称加粗，文件用类型图标 + 次级文字；
  不引入第二套颜色。
- 行数预计超过 600：拆 `panels/exports-tree.js`（纯渲染 + 展开状态），`panels/exports.js` 保留动作与
  请求；两处都登记 `index.html` 与 `tests/frontend/splits.json`，harness 用 `sourcesWithCompanions`。

### 6.5 存量迁移

`tools/migrate_export_groups.py`：

1. `--dry-run` 打印 `run_id → group → files` 与无法归属的文件；
2. 运行时先复制 `runs.db` 与 `data/exports` 的清单到 `migration_manifest.json`（记录原路径/新路径/sha256）；
3. 按 `run_files` 把平铺文件移入 `export_dir/<group>/`；没有账本的文件进 `_历史产物`；
4. 更新 `runs.export_group` 与 `run_files.group`；
5. 反向模式按 manifest 移回。

迁移不在服务启动时自动跑；它是发布/升级步骤，必须先 `--dry-run`。运行时只有新布局，不保留双读路径。

### 6.6 验收

| 编号 | 情形 | 期望 | 证据 |
|---|---|---|---|
| AG-1 | 一次运行两个 output 节点 | `export_dir/<wf>_<time>/` 下有两个文件；`run_files` 两行同 group | `test_export_groups.py` + 运行 store 用例 |
| AG-2 | 并行两个运行 | 两个不同文件夹；分组名冲突时 `-2` | 并行/并发用例 |
| AG-3 | 续跑同一运行 | 复用 `export_group`，不新建文件夹 | `test_run_resume_export_group` |
| AG-4 | 树接口 | 分组按 started_at 倒序；文件嵌套；无绝对路径 | API 用例 |
| AG-5 | 越界请求 | `group=../x` 或 `name=../../y` 一律 404/400，不泄露存在性 | 安全用例 |
| AG-6 | 前端树 | 展开/折叠、缩进、文件夹/文件图标、挂载按钮 | `harness_exports_tree.mjs` |
| AG-7 | 迁移 dry-run/回滚 | 不移动文件；manifest 可逆；幂等 | `test_migrate_export_groups.py` |

## 7. 模块 4（1）：一键引用产物分组为工作目录

### 7.1 框架契约

```python
# 框架内部（不 import 宿主）
group = host.artifact_group(account, group_id)      # ArtifactGroup
workspace.mount_group(account, conversation_id, group) -> dict
workspace.root(conversation_id) -> str
host.artifact_group_guidance(group) -> str          # 目录元数据 → 提示词扩展
```

- 挂载前校验 `group.root` 是目录、解析后的 realpath 在宿主声明的产物根内；不合法按
  `workspace.groupRefused` 拒绝。
- 写入 `conversations.workspace_dir=group.root`、`workspace_group=group.id`、`workspace_label=group.label`。
- 读取仍用 `workspace_list`/`workspace_read`；上下文只加“工作目录”段：`Workspace.snapshot()`（≤40 个
  顶层条目）+ `artifact_group_guidance(group)`。**不读取文件内容**。
- `workspace_write`/`run_cmd` 在只读分组上按名拒绝（`group.readOnly`）；`workspace_import` 也拒绝。
  本地普通目录仍可写。

### 7.2 采析绘实现

- `CaiXiHuiHost.artifact_groups(account)` 从 `run_ledger()` + `export_dir` 生成分组；`metadata` 含
  `run_id/workflow_name/status/file_kinds`，`root` 是服务端绝对路径。
- `artifact_group_entries()` 读 `services/exports/groups.list_group()`，只返回相对条目。
- `artifact_group_guidance()` 返回该产品配置的说明：这是某次工作流运行的导出目录；先读文件名/类型，
  再按需读 CSV/JSON；不要一次读整个目录；报告/图表是只读产物；目录内没有密钥。
- 一键入口：产物树的文件夹行“用作 AI 工作目录” → 确保会话存在 → `POST /conversations/<id>/workspace
  {group_id}` → 工作区顶部 chip 显示分组名；`DELETE` 恢复会话默认目录。
- 云端：分组仍可浏览/下载；挂载返回 `workspace.cloudRefused`，前端隐藏按钮（服务端判决，前端不猜）。

### 7.3 验收

| 编号 | 情形 | 期望 | 证据 |
|---|---|---|---|
| WM-1 | 点击分组“用作工作目录” | `conversations.workspace_dir/group/label` 持久化；重开会话仍在 | API + store 重启用例 |
| WM-2 | 挂载后问“这个目录里有什么” | 系统提示有目录名/顶层条目/分组说明；没有文件正文；AI 调 `workspace_list/read` | 捕获 payload + 脚本 provider |
| WM-3 | 只读分组 | `workspace_write`/`run_cmd` 按名拒绝；普通本地目录仍可写 | 工具用例 |
| WM-4 | 路径逃逸 | 伪造 group id/root 被拒；前端不收到绝对路径 | 安全用例 |
| WM-5 | 云端 | 挂载按钮消失；直接 POST 按名拒绝 | API 用例 |

## 8. 模块 4（2）：每会话工作文件夹与侧栏分组

### 8.1 数据

```text
conversations.workspace_dir     TEXT DEFAULT ''
conversations.workspace_group   TEXT DEFAULT ''   -- ArtifactGroup.id；空=会话自有目录
conversations.workspace_label   TEXT DEFAULT ''
```

- 新会话：框架 `AgentWorkspace.create_conversation()` 建行后调用 `Workspace.ensure_default()`，在
  `host.data_dir()/workspaces/<conversation_id>` 建目录并写入字段；云端不建目录（字段空）。
- 用户手动选目录（现有 `/workspace/pick`）：写 `workspace_dir`、`workspace_group=''`、
  `workspace_label=basename`。
- 挂载分组：覆盖三项；分组被删除/移动后，读取时返回 `missing` 状态，AI 工具按名拒绝，不静默回退。
- 删除会话不删除工作文件夹（可能是用户数据）；侧栏显示“孤立工作区”入口由后续需求决定，本计划不做。

### 8.2 侧栏

- `bootstrap.conversations` 每行带 `workspace_label`、`workspace_group`、`workspace_dir` 的显示名（不暴露
  绝对路径）；`_renderSessions()` 先按 `workspace_group || workspace_dir || 'default'` 分组，再在组内按
  pinned/updated_at 排序。
- 组头：文件夹图标 + label + 会话数 + 折叠按钮；折叠状态存页面内存。搜索仍跨组过滤。
- 没有绑定目录的会话归入“未绑定”；旧会话迁移时 `workspace_label='默认工作区'`，不强行建目录。

### 8.3 验收

| 编号 | 情形 | 期望 | 证据 |
|---|---|---|---|
| SW-1 | 新建会话 | 有独立目录（本地）；`workspace_dir` 持久化；重启后路径不变 | store/API 用例 |
| SW-2 | 两个会话同组 | 侧栏一个组头、两个会话；搜索/置顶/归档仍工作 | `harness_sidebar_workspace.mjs` |
| SW-3 | 会话挂载分组 | 该会话移到分组组头；其他会话不变 | 前端 harness + API |
| SW-4 | 云端 | 不建本地目录；侧栏归“云端（无工作目录）” | API/前端用例 |

## 9. 模块 4（3）：会话级与轮次级模型选择

### 9.1 数据与解析

```text
conversations.provider/model   会话默认值
ChatRequest.provider/model     本轮覆盖（现有）
turns.provider/model           解析后的实际值（现有）
```

- `_open_turn` 解析顺序：请求值 → 会话值 → `settings.chat.default_model` → 供应商第一个模型。
- `PATCH /conversations/<id>` 接受 `provider/model`；未知 provider/model 按名拒绝；保存前调用
  `catalog.history_problems(provider, model, messages)`，不兼容返回 `model.historyIncompatible` 与第一个
  不兼容块（`tool_use` / `image`）。
- 会话详情 `turns` 摘要：`[{id,state,provider,model,skills,created_at,stop_reason}]`，只读；前端按
  `turn_id` 标注每轮，不把模型写进 assistant 行（避免两处事实）。
- 输入框切换模型：PATCH 会话默认；本轮发送仍带当前 `provider/model`。下一轮不改变已存回合。

### 9.2 验收

| 编号 | 情形 | 期望 | 证据 |
|---|---|---|---|
| MM-1 | 第一轮 A 模型，第二轮 B 模型 | 不重建会话；两轮 `turns.provider/model` 分别为 A/B；刷新后逐轮标注 A/B | 框架 turns + 宿主 API + 前端 harness |
| MM-2 | 前端切换模型 | PATCH 不再被白名单丢弃；会话列表/详情显示新默认 | API 用例（当前 `_rememberConversationModel` 的回归） |
| MM-3 | 切到不支持 tools 的模型，历史有 tool_use | `model.historyIncompatible`，会话模型不改变 | 框架 catalog 测试 + API 用例 |
| MM-4 | 未知模型 | 按名拒绝，不写入 | API 用例 |

## 10. 模块 4（4）：后台持续、断线恢复、多会话并发

### 10.1 已成立的事实与要补的部分

已成立：回合在后台线程；`turn_events` 持久；`subscribe(after)` 可重放；关闭订阅不取消回合；pending
问题可跨重启回答。要补：

1. **会话详情带活动回合**：`GET /conversations/<id>` 返回 `active_turn {id,state,last_seq}`（state ∈
   new/context/streaming/tool）；`awaiting_user` 仍走 `pending` 卡片。
2. **前端重连**：`selectConversation()` 在加载消息后，如果 `active_turn` 存在，调用
   `_reattachTurn(id)`：用 SSE GET `/turns/<id>/events?after=0` 从 0 重放，过滤该 turn 的已存 assistant
   行，重建一个 live 气泡；`done` 后重新 GET 会话并落到存储行。关闭 dock/切会话只断订阅，不发 stop。
3. **同一会话只允许一个活动回合**：`ask()` 发现 `_active_conversation` 有 live turn 时，把消息放进邮箱
   （`notice turn.queued` + `done stop_reason=queued`），和待答问题的邮箱语义一致；不并行开第二轮。
4. **全局有界调度**：`TurnScheduler` + `turns.max_parallel`（默认 4，0=不限）。每会话一个活动回合；
   超出上限的回合线程等待；等待期间 stop 生效；start 时先检查取消位。
5. **进程重启**：沿用 ADR-003，把非终态回合收敛为 `interrupted`；不做半截供应商流的自动续跑。界面显示
   中断并提供重试；重试复用原回合 provider/model/skills/context。

### 10.2 验收

| 编号 | 情形 | 期望 | 证据 |
|---|---|---|---|
| TR-1 | 关闭 SSE/刷新/切会话再回来 | 回合继续；重连从 0 重建到当前增量；最终文本与存储行一致 | 框架 `test_closed_subscription...` + 宿主前端 harness + integration |
| TR-2 | 关闭 dock 再打开 | 不向 `/stop` 发请求；活动回合仍在；状态连续 | `harness_ai_workspace.mjs` |
| TR-3 | 两个会话同时跑 | 两套 provider 调用/工作目录/事件日志；停止 A 不影响 B；无跨会话文本 | 框架 `test_turn_scheduler.py` + 宿主 API 并发用例 |
| TR-4 | 同一会话连发两条 | 第二条进邮箱，不并行；第一条结束后按 mailbox 执行 | 框架 turns 用例 |
| TR-5 | 5 个回合、上限 2 | 同时最多 2 个 provider 调用；其余等待；stop 等待者可取消 | 调度器单测 |
| TR-6 | 进程重启 | 半途回合 `interrupted`；问题保留；重试复用原参数 | 框架重启用例 + 宿主 API |

## 11. 实施顺序

### 批次 0：契约冻结（0.5 天）

- 确认 ADR-004 的 7 条决策；把“提议”改为“已接受”。
- 在框架仓库建 0.2.0 分支；先写失败测试的契约骨架（类型、事件字段、路由空实现不合并）。
- 明确删除清单（见 §13），避免新旧两套并行落地。

### 批次 1：模块 3（框架分组契约 + 宿主物理分组 + 树）

1. 框架：`ArtifactGroup`、`HostAdapter.artifact_groups/entries`、`Workspace.groups` 与测试；框架测试全绿。
2. 宿主：`runs.export_group`、`run_files.group`、`services/exports/groups.py`；改所有运行内写方使用
   `ctx['export_dir']`；`record_file` 带 group。
3. 宿主：`/api/exports/tree|download|delete|clear*` 改为 `(group,name)`；安全用例。
4. 宿主：`panels/exports-tree.js` + `panels/exports.js` 接线；`index.html`/`splits.json`/harness。
5. 迁移工具 `tools/migrate_export_groups.py` + dry-run 测试。
6. 文档：`docs/ai_workspace.md` 的产物段、`docs/api.md` 的导出端点、README 的用户说明。

**DoD**：AG-1…AG-7 全绿；运行既有输出节点/批处理/报告/工作室图表仍能下载删除；设备层不回归。

### 批次 2：模块 4（2）会话工作夹

1. 框架 schema：`conversations.workspace_*` + `AgentWorkspace.create_conversation` 默认目录；
   `Workspace.root(conversation_id)` 与测试。
2. 宿主 API：会话列表/详情带显示名；`PATCH` 不接受路径（路径只走专用路由）；`/workspace` 支持会话参数。
3. 前端：侧栏分组、组头折叠；`bootstrap` 显示名；不暴露绝对路径。
4. 测试：SW-1…SW-4；旧会话默认归组。

**DoD**：新建/重开/切换会话路径稳定；侧栏按工作夹分组；云端不建本地目录。

### 批次 3：模块 4（1）挂载产物分组

1. 框架：`Workspace.mount_group()`、`ContextBuilder` 工作目录段、`artifact_group_guidance` 调用；
   只读分组的写/命令拒绝。
2. 宿主：`CaiXiHuiHost.artifact_groups/entries/guidance`；一键挂载/取消路由；产物树按钮。
3. 前端：工作目录 chip、挂载成功/失败提示、云端隐藏。
4. 测试：WM-1…WM-5；用真实临时导出目录做读取，不 mock `Workspace.resolve`。

**DoD**：一键挂载后 AI 能列目录并按需读一个文件；上下文不含文件正文；路径逃逸拒绝。

### 批次 4：模块 1 多技能与 `@` 指令

1. 框架：`ChatRequest.skills`、`turns.skills`/`pending_calls.skills` 迁移；`Skills.route_many`；
   `references.MentionKind`（content/directive）+ 文件安全校验。
2. 宿主：`api/ai_workspace.py` 映射 `skills`；`@capability` 改名；前端多选 chips、`@` 菜单、发送分流。
3. 前端：每轮技能来源标注；会话默认技能 PATCH/恢复。
4. 测试：SK-1…SK-5；扩展 `tools/eval_skill_routing.py` 为多标签语料并记录读数。

**DoD**：`@skill` 实际改变本轮集合；同一会话两轮不同集合；不可用技能按名拒绝。

### 批次 5：模块 2 渐进披露与 AI 自检索

1. 框架：L0 索引、`skill_catalog`/`skill_load`（含 `resource`）、每轮 `allowed` 重算；能力工具改名。
2. 宿主：`skill_resources/skill_resource`（catbus 文档、python 脚本、developer 源码）；
   `capability_catalog/load` 承接原能力技能实现。
3. 前端：加载来源显示；侧栏检查器列出本轮 loaded。
4. 测试：SD-1…SD-5；token 预算测量；`test_no_host_vocabulary` 扩展。

**DoD**：首轮只有元信息；AI 调 `skill_load` 后下一轮工具可用；显式与工具加载共存且可追溯。

### 批次 6：模块 4（3）模型两级

1. 框架：`conversations.provider/model`、PATCH 白名单、`catalog.history_problems`、会话详情 `turns`。
2. 宿主：模型选择 PATCH、逐轮标注、错误文案；修复 `_rememberConversationModel` 的静默丢弃。
3. 测试：MM-1…MM-4。

**DoD**：同一会话两轮不同模型；刷新后逐轮标注；不兼容历史按名拒绝。

### 批次 7：模块 4（4）重连与调度

1. 框架：`active_turn` 查询、`TurnScheduler`、`turns.max_parallel`、同会话邮箱化。
2. 宿主：会话详情字段；前端 `_reattachTurn`；关闭 dock 不取消；同一会话连发第二条进邮箱。
3. 测试：TR-1…TR-6；二会话并发 + 独立工作目录。
4. 设备层：真实浏览器关闭/重开 dock、刷新、两会话同时运行。

**DoD**：关闭弹窗后重开状态连续；两个会话互不干扰；同一会话不并行两轮；进程重启边界诚实。

### 批次 8：收口

- 框架 0.2.0 wheel 重建；`vendor/` 替换旧 wheel；`requirements.txt`/`desktop/requirements-runtime.txt`/
  `vendor/README.md` 同步；删除旧 wheel。
- 全量 fast tier + ruff check/format + 两个 pylint tier + `doctor.py --all` + `/smoke-verify`。
- 文档：ADR-004 改“已接受”、本计划勾选完成项、`docs/ai_workspace.md`、`docs/api.md`、README、
  `docs/architecture/framework-parity.md`、`docs/capabilities/tool-descriptions.md`。
- i18n 双语键、浏览器目录、`tests/i18n` 与前后端 contract 门禁。
- 未做项写回本节，不留在代码里。

## 12. 验收矩阵（汇总）

| 编号 | 可验证事实 | 最低证据 |
|---|---|---|
| A1 | `@skill:analysis` 单独出现时，本轮 `turns.skills` 含 `analysis`，且工具白名单含其工具 | 框架 references/turn 测试 + 宿主 API |
| A2 | 同一会话两轮使用不同技能集合，第一轮记录不被改写 | 框架 turns 测试 |
| A3 | 自动问句命中 2–3 个技能，超过上限只取前三 | `test_skill_routing.py` + 语料读数 |
| A4 | 首轮系统提示只有技能索引，无未选中正文 | 捕获 provider payload |
| A5 | AI 调 `skill_load` 后下一轮工具表扩大，`turns.skills` 记 `tool` | 脚本 provider 两轮 |
| A6 | 一次运行的多个 output 落在同一 `export_dir/<group>/` | 运行 store + 真临时目录 |
| A7 | 树面板按运行分组、可展开、缩进/图标/文件夹区分 | `harness_exports_tree.mjs` |
| A8 | 越界 `group/name` 一律拒绝，不泄露路径 | API 安全用例 |
| A9 | 一键挂载分组后 `workspace_list/read` 能读文件，上下文无正文 | API + 捕获 payload |
| A10 | 会话 `workspace_dir` 重启后不变；侧栏按工作夹分组 | store 重启 + 前端 harness |
| A11 | 同一会话两轮模型不同，刷新后逐轮标注 | API + 前端 harness |
| A12 | 关闭 SSE/刷新/切会话后回合继续，重连看到完整状态 | 框架 subscribe + 前端 harness + integration |
| A13 | 两个会话并发运行，工作目录/上下文/停止互不影响 | 框架调度 + 宿主并发 API |
| A14 | 同一会话连发两条，第二条进邮箱而非并行 | 框架 turns |
| A15 | 进程重启后半途回合 `interrupted`，问题保留，重试复用原参数 | 框架重启用例 |

## 13. 删除清单（同一变更内完成）

- `ChatRequest.skill`、`turns.skill`、`pending_calls.skill` 的单值字段与所有读写；迁移后不保留双读。
- `Skills.route` 单值路由；只保留 `route_many`。
- 宿主 `skill_catalog`/`skill_load` 的**能力文档实现**；同一对名字改由框架承载专家技能，能力文档改为
  `capability_catalog`/`capability_load`。
- 旧 `@skill:id` 的“能力技能正文”语义；改为 `@capability:id`。
- `resolve_export_file(export_dir, name)` 的平铺版本；改为 `(export_dir, group, name)`。
- `list_exports()` 作为面板数据源的用法；树 API 取代它（若内部仍有调用，必须重新论证）。
- `Workspace.root()` 的账号级唯一语义；改为 `root(conversation_id='')`。
- 前端 `_rememberConversationModel` 的“发了但服务器不认”状态；修复白名单后保留方法本身。
- 任何为旧布局/旧字段保留的兼容分支、转发别名、测试；迁移工具除外。

## 14. 风险与回滚

| 风险 | 处理 |
|---|---|
| 多技能提示词互相矛盾/膨胀 | 显式上限 8、自动上限 3、去重保序；技能正文分段标注 id；超预算在检查器可见 |
| 自动多匹配噪声 | 只取 >0 且 ≥最高分 50%；18 条语料扩为多标签并记录 precision/recall；不达标就降上限 |
| 文件引用路径逃逸 | root allowlist + realpath 包含检查 + 文本后缀白名单 + 64 KB 上限；测试覆盖 `..`/绝对路径/符号链接 |
| 导出布局迁移丢文件 | `--dry-run` + manifest + sha256；迁移前备份 `runs.db`；反向模式；服务启动不自动迁移 |
| Windows 路径超限 | 分组名 80 bytes、文件名沿用 `sanitize_filename` 200 bytes；路径总长测试；跨系统 CI |
| 会话工作目录被删 | 读取时返回 `missing`，工具按名拒绝，不静默回退；侧栏显示状态 |
| 模型切换历史不兼容 | `history_problems` 统一判定；PATCH 先检查后写入；错误带第一个不兼容块 |
| 重连重复渲染 | 从 0 重放 + 过滤该 turn 的已存 assistant 行；done 后重新 GET 落到存储行；harness 钉住 |
| 调度上限导致排队 | 默认 4、0=不限；同一会话邮箱化；stop 在等待期生效；单会话长任务不占满所有槽 |
| 框架 API 变更 | 0.2.0 wheel 钉版；框架测试先绿；宿主只经 HostAdapter，不复制引擎 |
| 进程重启半截回合 | 按 ADR-003 收敛 `interrupted`；不自动续跑供应商流；重试复用原参数 |

回滚：框架回退到 0.1.30 wheel + 宿主回退到迁移前提交；`ai.db` 用迁移前备份恢复；导出目录按
`migration_manifest.json` 反向移动。迁移工具与备份是发布步骤，不是运行时开关。

## 15. 文档、i18n 与发布

- 框架文档：`docs/architecture.md`（技能集合、L0/L1/L2、调度、重连）、`docs/tools_skills.md`
  （`skill_search/skill_load` 与 `capability_*` 的区别）、`docs/host_integration.md`（ArtifactGroup、
  workspace、skill resources）、`docs/api_reference.md`（会话字段/事件字段）。
- 采析绘文档：`docs/ai_workspace.md`（技能多选/@/进度披露/工作目录/模型/重连）、`docs/api.md`
  （`/api/exports/tree` 与会话 PATCH）、`docs/ARCHITECTURE.md`（导出分组与工作目录落点）、
  `docs/architecture/capabilities-kernel.md`（能力文档工具改名）、`docs/architecture/framework-parity.md`
  （新行）、`README.md`（用户可见变化）。
- i18n：`i18n_catalog/ai.py` + `backend/static/js/i18n/ai.js`（技能多选、@ 类型、工作目录、模型标注、
  重连/中断）、`i18n_catalog/api.py` + 浏览器 `api.js`（导出树/分组错误）。中英齐全，键只在一个域声明。
- 工具描述：`docs/capabilities/tool-descriptions.md` 与 `test_tool_descriptions.py` 同步新工具名/参数。
- 发布：`vendor/agent_workspace-0.2.0-py3-none-any.whl`，删除 0.1.30；`requirements.txt` 与
  `desktop/requirements-runtime.txt` 同步；`version.json`/`APP_VERSION` 按发布流程升版。

## 16. 需要确认的四项

1. **自动技能上限**：建议 3；超过 3 的候选只进 `meta` 解释，不进系统提示。
2. **默认会话工作夹**：建议每个会话一个独立目录（满足“独立、持久”），侧栏把未挂载分组的会话归入
   “独立工作区”；挂载产物分组后按分组聚合。
3. **存量导出**：建议一次性迁移到 `export_dir/<group>/`，保留 manifest 与反向模式；不保留平铺双读。
4. **能力工具改名**：建议把原 `skill_catalog/skill_load` 的**能力文档实现**改名为
   `capability_catalog/capability_load`，`skill_*` 由框架承载专家技能；这是一次性 wire/提示词变更，
   不保留别名。
