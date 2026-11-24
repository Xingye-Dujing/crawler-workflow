# W7 算法与增量：已落地的三件，与剩下两件的做法

> W7 不是“再拆几个文件”，是会改变**花钱方式**或**采集语义**的改动。每件都要自己的验证方式，
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

## 已落地：游标与账本的值对象（原计划的第 3 件，2026-11-24）

`services/runs/store/values.py` 里两个 frozen 值对象，让两条“只写在注释里”的规则变成类型：

- `Cursor`：`position`（爬虫自己的词表：keyword/page/scanned…）与 `proven`/`total`
  （批量走查的**已证明前缀**，即 `url_index`/`url_total`）分开；`Cursor.proven_prefix()` 拒绝
  负数、拒绝超出批次的数字、拒绝没有批次的前缀。它读起来就是原来的 mapping（`get`/`in`/`dict()`），
  所以 9 个平台的 `resume_of` 一行不改语义；`get_cursor` 交回 `Cursor`，`save_cursor` 写下的 JSON
  与旧的 dict 形状逐字节相同（`{'keyword':…}` 与 `{'url_index':…, 'url_total':…}`）。
- `LedgerKey`：`kind` + `parts` 的单一摘要实现（`sha1_parts` 现在也是 `identity.py` 里
  `node_fingerprint`/`workflow_fingerprint`/`schema_digest` 用的那一个，不再有第二份 join）。
  `item_key()` 变成它的一次调用，键值不变：评论按 `(平台, 评论ID)`，没有 id 时按文章+作者+正文+评论时间，
  笔记按站点 id，其余按链接/文本/整行依次退让。
- 证据：`tests/unit/runs/test_store_values.py`（18 条）——mapping 读法、不可编辑且不别名调用方 dict、
  前缀越界被拒、经真 `RunStore` 的读写往返、`resume_of` 认得 store 交回的游标、
  评论换楼层不换键、签名链接换 token 不换键、每种身份形状只有一个键。
- 计划里“先写行再写位置”的那一半没做成构造函数（只有调用方知道行什么时候落地），所以这条仍是
  评论引擎里的顺序 + 注释；类型管的是它能管的那半（前缀的域、两个半边不混写）。

## 剩下两件（编号沿用原计划）

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

### 3. 采集节流/风控纯函数化（已落地 2026-11-24）

`services/pool/policy.py` 是这条规则的唯一住址：`Attempt(reason, stored_rows, pooled, stopped,
attempts_left)` → `decide()` → `Decision(ROTATE|SETTLE, reason)`，纯函数、无 I/O、无时钟。

- 规则合并了原来写死在两处的同一句话：source 执行器的两处 `if pool_mode and _proved_rows() <=
  stored_before` 与评论执行器的 `if status == BLOCKED and not rows and ...`。两处现在都只把事实
  交给 `decide()`；`services.pool` 里那份 `is_rotatable` 转发（唯一调用者就是评论执行器）随之删除。
- 顺序也是规则：停止 > 非池模式 > 未归因（network/未知）> 已有行 > 预算耗尽。每一条都对应一次
  实测事故（网络故障轮换走一个账号、有行的 wall 把行扔掉、停止后仍开新登录）。
- 预算：`attempts_left=None` 表示调用方不是预算持有者（source 在 raise 时还不知道还剩几个登录），
  有预算的一方（评论执行器 / 尝试循环）传数字，`<= 0` 一律 settle。
- 证据：`tests/unit/pool/test_pool_policy.py`（11 条性质）；既有的
  `tests/unit/executors/test_source_pool_rotation.py` 与 `tests/api/test_comment_pool_rotation.py`
  不改断言全绿（行为不变：同一输入同一结论）。
- 没做的：device tier 的一次真实 `login_wall` 轮换观测仍在待办里（要花账号，属 live 范畴）。

### 4. 工具检索式路由

- 现状：`tools.strict_local` 时按“用户原话排序”取 12 个工具（框架侧）。
- 做法：BM25 + embedding + RRF 融合，取前 K；**控制工具、配方当前步骤工具、核心读工具永远保留**。
- 为什么最后：它只影响“提供给模型的工具列表”，容易测（同一批问题选出同一批工具），
  但需要先有第 2 节那种可复现的评测集（`tools/eval_tool_routing.py`）作为基线。

## 与本次重构的关系

W0–W6 已经把 W7 需要的三块地基铺好：内容身份（`core/asset.py` + `node_assets`）、
一次运行一个包（`engine/run/`）、以及框架的端口与工具表（`ports.py`、`CONTROL_TOOLS`）。
剩下两件都可以在各自的域内完成，不需要再动共享层——这正是这批重构要达到的状态。
