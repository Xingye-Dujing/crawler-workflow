# 数据源（source）

数据源是“采一个平台、一个模式”的节点：搜索、榜单、作者主页、文章/笔记清单，或一批链接。
它的表单不是固定字段，而是由平台矩阵决定——平台 × 采集后端（Selenium / CatBus）× 模式共同决定
有哪些字段、哪些必填、是否需要登录。所以这个节点在清单里不声明参数，而是用
`ui.defaults_from='capabilities'` 告诉前端去问矩阵。

- 清单：`backend/capabilities_kernel/nodes/source/manifest.py`
- 行为：`backend/nodes/executors/source.py`
- 矩阵：`backend/capabilities_kernel/platforms/<平台>/manifest.py`
- 契约测试：`tests/unit/capabilities/test_source_manifest.py`

## 参数

没有静态参数表。新节点的字段来自平台矩阵；切换平台、后端或模式会重新生成表单。代码里会读到的通用字段
（由矩阵声明）包括 `platform`、`collect`（模式）、`backend`、`account`、`recrawl`、`target_count`、
`part_size`、`keep_parts`、`format`，以及各模式自己的关键字、作者链接、链接列等。

账号字段的空白表示**默认账号**（一个真实账号，不是通配符）；`@pool` 表示从账号池轮换，此时
`CookieManager` 永远不会收到这个值。

## 运行前校验

校验由 `nodes.executors.source.validate_node` 回答，和 executor 读同一份矩阵：

- `engine.source_no_platform`：节点没有平台。
- `engine.source_unknown_platform` / `engine.source_unknown_mode`：这个平台/后端不提供所选模式。
- `engine.source_bad_backend`：采集后端不是 `selenium`/`catbus`。
- `engine.source_needs_machine`：该模式在这台机器上永远跑不了（例如只能在 Windows 或云端运行的采集）。
- `engine.source_catbus`：CatBus 适配器自己给出的缺失原因（没有 Node、没有适配器、没有该单元等）。
- `engine.source_missing` / `engine.source_bad_option`：必填字段为空，或值不在矩阵给出的选项里。
- `engine.source_feed_no_mode` / `_no_column` / `_no_input`：上游表与模式的喂送形状不一致。
- 会话类键（`engine.source_no_cookie_account`、`_pool_empty`、`_pool_cooling`）：需要登录的模式，
  所选账号在该平台没有可用会话；匿名模式不会被问。
- `engine.watermarkUnsupported` / `engine.watermarkRecrawl`：增量水位只支持哔哩哔哩作者模式，
  且不能与“重新采集”同时开启。

## 失败与续跑

- 已提交的行留在运行库里；登录墙/风控按名结算为失败，画布出现“继续”，游标只记录已证明完成的前缀。
- 分批输出（`part_size`）在爬取过程中就落盘，中断后仍可在“运行文件”里打开。
- 账号池只在“本次没有存下任何行且站点明确回答登录墙/风控”时轮换，已存下的行不会被重付。

## 典型画布

```text
数据源（微博搜索）→ 清洗 → 分词 → 词云
数据源（知乎问题链接）→ 评论采集 → 情感分析
名称 → 数据源（笔记清单）
```
