# W7 算法与增量：已落地的一半，与剩下四件的做法

> W7 不是“再拆几个文件”，是四件会改变**花钱方式**或**采集语义**的改动。每件都要自己的验证方式，
> 混在一次提交里既证明不了，也回滚不了。本页记下：哪件已经完成、剩下的每件怎么开始、
> 以及验收必须看到什么。

## 已落地：内容寻址执行（第 1 件）

`(节点指纹, 上游资产哈希)` 已经是**可证明的复用条件**，不再是启发式：

- `node_assets` 表（`services/runs/store/assets.py`）为每个节点的产出记下 `sha256`/`size` 与
  `input_sha`（父节点资产的摘要，排序后拼接，含节点 id）。
- `engine/run/asset.py::lineage_conflict` 在复用判定里多问一句：**已知不一致才拒绝**。老库（没有资产行）、
  没有 `input_sha`、上游本来就没有资产，都退回原来的结构规则。
- 证据：`tests/unit/runs/test_run_asset.py` 用真 `RunStore` 走 `run_node_durable` 三条：
  首次运行写资产、同上游的 继续 恢复且不重跑、上游内容变了就重跑。

**验收（已满足）**：同一画布第二次运行 0 次浏览器启动、0 次模型调用——这是既有 继续 用例的性质，
现在由资产血缘保证“上游没变”这一半。

## 剩下四件

### 2. 算子级缓存 `(op, params, input_hash, columns)`

- 现状：LLM 步已有**行级**答案缓存（`llm_cache`，按 `(op, model, column, 文本)`）；纯 pandas 步每次重算。
- 做法：在 `services/analysis/pipeline.py` 的 `run_pipeline` 外套一层：键 =
  `(op, 规范化 params, 输入资产 input_sha, 读取/写出的列名)`。**列名必须在键里**：`正文` 与 `cleaned_text`
  是两条不同的曲线，同一个 op 换了列就不是同一个结果。
- 必须先回答的三个问题（这就是它要单独一片的原因）：
  1. 结果存哪：`node_rows` 已经存下游要的行，算子缓存存的是**中间表**，会成倍放大磁盘；
  2. 失效：`参数` 里哪些算“选择数据”（进键），哪些只是标签（不进键）——与 `_VOLATILE_PARAMS` 同一套判定；
  3. 命中率：没有真实画布上的命中率数字，就不要上缓存，否则只是多一次写盘。
- 验收：一个两步画布第二次运行，第二步的算子**没有**被执行（打点计数为 0），且结果与第一次逐行相等；
  换列名 → 未命中；换标签 → 命中。

### 3. 游标/账本值对象

- 现状：游标是 JSON dict（`save_cursor`/`get_cursor`），账本键是函数 `item_key(platform, comment_id)`；
  规则写在注释和测试里（“游标记位置不记内容”“账本键是站点身份，不是内容”）。
- 做法：`Cursor(proven: tuple[str, ...], position: str)` 与 `LedgerKey(platform: str, item_id: str)`
  两个 frozen dataclass，放在 `services/runs/store/values.py`；store 的读写边界接受它们并序列化，
  调用方（评论引擎、source 执行器）逐步换成值对象，**行为不变**。
- 为什么值得：这两条规则各自被违反过一次，类型比注释更难绕过；而且 `proven` 与 `position` 分开之后，
  “写入位置前必须先写行”的检查可以成为构造函数的一部分（一个只带 position 的 Cursor 造不出来）。
- 验收：现有断点续跑/游标语义测试全绿且不改断言（只改构造方式）；新增性质测试：
  `Cursor` 的 `proven` 顺序无关、幂等；`LedgerKey` 对同一站点身份相等、对 volatile 列不敏感。

### 4. 采集节流/风控纯函数化

- 现状：节流在 `crawlers/engine/pacing.py`（站点无关机械），轮换判定在账号池的闸门与执行器里，
  规则是“零行 + 站点明确 login_wall/risk 才轮换”，由测试钉住。
- 做法：把一次尝试抽成 `Attempt(account, exit, platform, outcome, stored_rows)` 与
  `RetryPolicy.decide(attempt) -> Decision(rotate|retry|stop)`，纯函数、无 I/O；账号池与执行器只做执行。
- 为什么独立：这条规则一旦写错就是**花用户的账号**，必须用性质测试穷举（网络故障永不轮换、
  有行就 PARTIAL 不轮换、未知失败不轮换），并且要在 device tier 上验证一次真实 wall。
- 验收：性质测试覆盖上述四条；device tier 一次真实 `login_wall` 只轮换一次账号并具名记录。

### 5. 工具检索式路由

- 现状：`tools.strict_local` 时按“用户原话排序”取 12 个工具（框架侧）。
- 做法：BM25 + embedding + RRF 融合，取前 K；**控制工具、配方当前步骤工具、核心读工具永远保留**。
- 为什么最后：它只影响“提供给模型的工具列表”，容易测（同一批问题选出同一批工具），
  但需要先有第 2 节那种可复现的评测集（`tools/eval_tool_routing.py`）作为基线。

## 与本次重构的关系

W0–W6 已经把 W7 需要的三块地基铺好：内容身份（`core/asset.py` + `node_assets`）、
一次运行一个包（`engine/run/`）、以及框架的端口与工具表（`ports.py`、`CONTROL_TOOLS`）。
剩下四件都可以在各自的域内完成，不需要再动共享层——这正是这批重构要达到的状态。
