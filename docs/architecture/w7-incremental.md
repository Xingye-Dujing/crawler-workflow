# W7 算法与增量：四件都已收口（一件是量过的决定）

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

## 四件的位置（编号沿用原计划）

### 2. 算子级缓存 `(op, params, input_hash, columns)` —— 量过了，决定不做（2026-11-24）

计划自己立的门槛是“没有真实画布上的命中率数字就不要上缓存”。现在有了：`tests/unit/analysis/
test_operator_cache_measure.py` 走真 `RunStore` + `run_node_durable`（真复用判定），给两步分析节点
的每种情形数算子执行次数：

| 情形 | 节点结局 | 算子执行次数 | 缓存能省下的次数 |
|---|---|---|---|
| 同一画布 继续（什么都没改） | `restored` | 0 | 0——节点根本没跑 |
| 上游多了一行（重新采集后继续） | `done` | 2 | 0——键里带输入哈希，全部未命中 |
| 在管道**末尾追加**一步 | `done` | 3 | 2（前两步的输入与参数都没变） |
| 改管道中间某步 | `done` | N | 该步之前的全部 |

也就是说它只在一个场景里有活干：**用户编辑管道尾部（或中间），前缀步被重算**。而那几个前缀步是纯
pandas，秒级、不花钱；真正贵的 LLM 步早有**行级**答案缓存（`llm_cache`，按 `(op, model, column, 文本)`），
重算时一样不付钱。代价却是实打实的：`node_rows` 只存最终表，算子缓存要为每个节点每次输入哈希多存
N−1 张中间表（爬下来的文本表），磁盘成倍放大，还要一套失效规则。

结论：**不建这层缓存**，W7-2 以“量过的决定”收口。将来若真的出现“长管道频繁改尾步”的画布，重开这
一页时先拿这张表去量——不要先写缓存再找理由。

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

### 4. 工具检索式路由（已落地 2026-11-24，含一处真缺陷）

计划写的是“BM25 + embedding + RRF”。做之前先量了一遍真实注册表，量出来的不是排序差，而是
**预算坏了**：

| 实测（真宿主 + 0.1.26 框架） | 数字 |
|---|---|
| 严格模式一次回合真正发出去的工具 | **27 个**（承诺 12）——控制 6 + 全部 21 个 `UNIVERSAL_TOOLS` |
| 这 27 个里属于当前技能自己的 | **0 个** |
| 18 个技能 × 3 种提问，丢掉自有工具的技能 | **18 / 18** |

原因两条：框架把 core 工具排在最前、计数在最后；宿主把 21 个通用工具全声明成 core。于是
“12 个工具”实际变成 27 个，而 `dataset_query`、`chart_catalog`、`code_search`、`web_search` 这些
技能真正的动词一个都发不出去。

已做的三件（框架 0.1.27 + 宿主）：

1. **预算就是预算**：非控制工具 ≤ `limit`；core 只占优先位，装不下按相关度裁。
2. **技能自有工具是预算地板**：`schemas(..., priority=skill.tools)`，技能声明超过 12 就把预算抬到
   它的规模（conductor 21、python 19），绝不裁掉技能自己的动词。
3. **BM25 取代子串计数**（IDF + 长度归一 + 名字按 `_` 拆词），并把 core 从 21 收成 2
   （`request_dataset_access`、`skill_load`）。

再测：技能自有工具丢失 **0 / 18**；26 条原话在对应技能的允许表下可达 **22/26**（剩下 4 条是
`workflow_*` 这类通用动词，见下）。

**没做 embedding + RRF，理由是一条测量到的边界：中文提问对英文描述没有词法信号**——所有分都是 0，
排序退化成按名字，这正是“技能地板”存在的理由。跨语言检索需要多语言 embedding（本机 Ollama 没有
embedding 模型，装一个等于给产品加一条模型依赖），留着等有了嵌入端点再量。旧簇式做法里“12 个工具
提高小模型准确率”的假设也不成立：全量列表在 `tools/eval_tool_routing.py` 上 4b 就是 **26/26**，所以
这层预算换来的是上下文长度与鲁棒性，不是准确率。

**边界（已知，不修）**：通用动词在词法无信号时按名字排，`workflow_run` 这类可能被裁到列表外。它只裁
“广告”——`_dispatch` 仍按 `allowed` 放行，模型从上下文里知道名字就还能调；真要让它们每次都出现，得
先把通用表拆成“每回合必备”和“按需”两组。

## 与本次重构的关系

W0–W6 已经把 W7 需要的三块地基铺好：内容身份（`core/asset.py` + `node_assets`）、
一次运行一个包（`engine/run/`）、以及框架的端口与工具表（`ports.py`、`CONTROL_TOOLS`）。
四件都在各自的域内完成，没有动共享层——这正是这批重构要达到的状态。
