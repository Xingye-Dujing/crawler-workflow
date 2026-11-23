# reply_graph（social）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/reply_graph.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

按评论者、楼层与父楼层还原“谁回复谁”的关系，输出带权重的边表。

## 何时使用

要画互动网络、找关键传播者或社区结构时。

不要用于：

- 表里没有楼层/父楼层字段时无法还原回复关系，请先确认采集列。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `author_col` | string | `评论者` |  |  |
| `floor_col` | string | `楼层` |  |  |
| `parent_floor_col` | string | `父楼层` |  |  |
| `article_col` | string | `文章URL` |  |  |

## 读取的列

- 必须存在的一列：`author_col`、`floor_col`、`parent_floor_col`

## 输出形状

新表，列固定：`src_author`、`dst_author`、`weight`。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
