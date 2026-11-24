# AI 工具描述规范与目录

> 工具是模型能做的**动词**，也是它的全部权限面。本页是 `backend/ai/tools/` 这七个模块的人工页；
> 机器可读的唯一真源是各模块末尾的 `TOOLS` 元组，`ai.tools.TOOLS` 只是它们的合并字典。
> 门禁 `tests/unit/gates/test_tool_descriptions.py` 拒绝：名字里没有域前缀、描述短于 40 字、
> 参数超过 8 个、任何叫 `code`/`script`/`command` 的自由文本参数、权限不在已知动词里、本页漏列或多列。

## 命名

`<域>_<名词>[_<限定>]`，域取 `dataset` / `run` / `workflow` / `export` / `model` / `code` / `skill` / `ai`。

- 名字要让小模型**按名字选得出来**：`dataset_query` 比 `query` 好，`query` 会与分析算子词汇撞车。
- 同一域的动作按同一顺序出现（读 → 写 → 删除），因为技能白名单和提示词里也按这个顺序读。
- 控制工具（`ask_user_question` / `update_plan` / `present_artifact` / `request_approval`）由框架拦截，
  不在本目录里，也不在本包的 `TOOLS` 里。

## 三条硬规则

1. **参数 ≤ 8 个，且没有一个是可执行文本。** 需要代码就写 Python 脚本走 `ai_allow_python` 的脚本面，
   不要给只读工具加 `code` 参数——那会把读工具变成执行面。
2. **读写分离。** 读工具返回有界 JSON；写工具只生成**产物**（用户应用）或受审批的确切调用。
   `dataset_query` 是这条的样板：它是一张封闭的算子表，不是“跑一段 pandas”。
3. **描述里必须有“什么时候不该用”。** 例：`dataset_peek` 说“够了就停”，`workflow_stop` 说
   “没在跑也安全”，`rerun_node` 说“不会把画布加载回来”。缺这句话，模型会一路读到整张表。

## 目录（按模块）

### `catalog.py` — 这个构建会什么

| 工具 | 权限 | 读什么 / 什么时候不该用 |
|---|---|---|
| `ai_coverage` | read:project | 能力→AI 入口矩阵；缺格是产品缺口，不是提示词问题——不要用它猜某一个节点怎么用 |
| `skill_catalog` | read:project | 一级技能目录（id、一句摘要、何时用/何时不用）；不要拿它当正文 |
| `skill_load` | read:project | 二级正文（步骤、例子、模板、重新渲染的参数表）；不确定一个能力时才读，别把全部技能都读进来 |
| `catbus_status` | read:project | 第二采集后端的工具链探测；只读，**绝不安装** |
| `chart_catalog` | read:project | 图表注册表与各图所需列 |
| `analysis_catalog` | read:project | 分析算子清单与列契约 |

### `datasets.py` — 有界地读数据

| 工具 | 权限 | 读什么 / 什么时候不该用 |
|---|---|---|
| `list_datasets` | read:project | 本账号数据集列表 |
| `dataset_profile` | read:project | 列、类型、缺失、样本；永不返回整表 |
| `dataset_peek` | read:project | **先看这个**：5 行、120 字截断；足够就停 |
| `dataset_page` | read:project | 需要某一页时才用；行预算来自账号设置与本次授权 |
| `dataset_sample` | read:project | 与 page 同形，默认更小；列与 offset 都尊重 |
| `request_dataset_access` | ask（永远要审批） | 为本次会话申请行预算；它只登记授权，不会自己放大预算 |
| `dataset_query` | read:project | 精确的量化问题（count/mean/groupby/filter…）；**别用 peek 的 5 行估一个数**，也别为了算数把整表拉下来 |

### `runs.py` — 一次运行

| 工具 | 权限 | 读什么 / 什么时候不该用 |
|---|---|---|
| `list_runs` | read:project | 最近的运行记录 |
| `run_status` | read:project | 一次运行 + 每节点状态；诊断前先读它 |
| `run_console` | read:project | 持久控制台的尾部 |
| `app_errors` | read:project | 后端日志尾部 + 最近失败/部分运行；先看它，再提修改 |
| `apply_node_result` | write:project | 确认用户编辑过的节点结果，供 `rerun_node` 重放 |
| `apply_codebook` | write:project | 保存用户编辑过的码本为新版本，再重跑编码节点 |
| `rerun_node` | write:project | 从**保存的文件**重跑失败子树；不会把画布加载回来，画布变了按名拒绝 |

### `workflows.py` — 保存的工作流与导出

| 工具 | 权限 | 读什么 / 什么时候不该用 |
|---|---|---|
| `workflow_schema` | read:project | 全部合法词汇（节点类型、种子参数、文件形状、规则）；写草稿前读 |
| `workflow_validate` | read:project | 草稿校验；**提给用户之前必须过** |
| `workflow_list` | read:project | 本账号保存的工作流 |
| `workflow_read` | read:project | 读一个文件全文；编辑前读 |
| `workflow_update` | write:project | 校验后**同名**替换；名字不存在就不写 |
| `workflow_rename` | write:project | 改名；重名拒绝，永不覆盖 |
| `workflow_delete` | write:project（永远要审批） | 删除一个工作流并写审计行 |
| `workflow_export` | write:project | 打项目包（工作流 + 它读的数据集/可复用模板）到导出目录 |
| `workflow_run` | write:project | 走与定时任务同一个启动路径；忙时排队而不是拒绝 |
| `workflow_stop` | write:project | 停止本账号的活动运行；没在跑也安全（返回 `idle`） |
| `export_list` | read:project | 导出文件列表 |
| `export_delete` | write:project（永远要审批） | 删一个导出文件并写审计行 |

### `models.py` — 本机模型

| 工具 | 权限 | 读什么 / 什么时候不该用 |
|---|---|---|
| `models_catalog` | read:project | 注册模型、量测质量、本机能不能跑；**选模型前读** |
| `model_infer` | exec:model | 一次最多 200 行的小任务；整表属于工作流节点 |
| `model_rerank` | exec:model | 最多 50 个候选的重排；不要对整表用 |

### `code.py` — 源码（仅本机/桌面）

| 工具 | 权限 | 读什么 / 什么时候不该用 |
|---|---|---|
| `code_search` | read:code | 有界源码搜索（20 条命中）；云端按名拒绝 |
| `code_read` | read:code | 一个源码文件（≤400 行）；只用于引用或补丁提案 |

### `policy.py` — 三张名单

`UNIVERSAL_TOOLS`（每轮都提供）、`APPROVAL_TOOLS`（auto-approve 关闭时需确切参数授权）、
`ALWAYS_APPROVAL_TOOLS`（删除与数据授权，auto-approve 也不覆盖）。改一个工具的权限就是改这三张表之一，
不是在新地方加一个 `if`。
