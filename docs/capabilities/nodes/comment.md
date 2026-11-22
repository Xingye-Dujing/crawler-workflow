# 评论采集（comment）

评论采集把一批文章链接（或红果剧名）逐条走近评论区，按批次产出评论行表。它和“数据源 → 评论”模式使用
同一套断点、去重与分片机制：已经采集过的评论不会重付，游标只记录**已证明完成的前缀**，所以遇到登录墙或
采集不足时“继续”会从第一个缺口重走。

- 清单：`backend/capabilities_kernel/nodes/comment/manifest.py`
- 行为：`backend/nodes/executors/comment.py`
- 契约测试：`tests/unit/capabilities/test_comment_manifest.py`

## 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `urls` | 空 | 必填。每行一个文章链接；矩阵声明支持名字的平台（红果）也可以写剧名。 |
| `comment_limit` | 0 | 每篇最多取多少条评论；0 = 全部。 |
| `part_size` | 50 | 每多少条落一个分片；0 = 只出最终文件。 |
| `per_article_file` | `true` | 每篇文章一个文件。 |
| `keep_parts` | `false` | 是否保留分片。 |
| `recrawl` | `false` | 释放去重账本重新采集；续跑时不生效（账本本身就是续跑机制）。 |
| `format` | `csv` | `csv` 或 `json`。 |

表单上还有账号（`account`）、`include_replies`（爬楼中楼，默认开）、按评论时间的过滤
（`comment_start`/`comment_end`）等字段；它们由该节点的自定义表单渲染，不进入新节点种子。

## 运行前校验

- `engine.comment_no_urls`：没有填写任何链接。
- `engine.source_no_cookie_account`：链接涉及的某个平台，在所选账号下没有可用登录。空白账号表示
  **默认账号**（一个真实账号，不是通配符）；不会借用别的账号，也不会静默少采。
- `engine.source_pool_empty` / `engine.source_pool_cooling`：账号写的是 `@pool`，而池里没有登录，
  或全部在冷却/停用。
- CatBus 节点不在这里被问 Cookie：它的登录在适配器自己的目录里，由适配器的预检回答。

## 失败与续跑

- 被登录墙挡住的链接计为 BLOCKED，节点按失败结算，游标停在缺口前；“继续”只重走被挡的链接。
- 浏览器级故障（driver 失联、导航不返回）同样失败并可续跑，不会结算成 DONE。
- 采得不足（站点自己给了目标条数却没收满）按 U1 规则失败并说明缺口。

## 典型画布

```text
数据源（帖子清单）→ 评论采集（链接列喂送）→ 保存
评论采集（手写链接）→ 清洗 → 分词 → 词云
```
