# 采集校验（verify）

采集校验比较**两张数据表**：承诺的清单（链接 + 评论数）与采集结果（文章URL）。它匹配键、比较期望条数
与实际行数，输出 `采集状态`、`期望条数`、`实际条数`、`缺失条数`、`完成度`。`gaps` 是可直接重采的缺口表，
`all` 是完整审计表。

- 清单：`backend/capabilities_kernel/nodes/verify/manifest.py`
- 行为：`backend/nodes/executors/verify.py`
- 契约测试：`tests/unit/capabilities/test_verify_manifest.py`

## 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `input_key_column` | 链接 | 清单的键列。 |
| `result_key_column` | 文章URL | 采集结果的键列。 |
| `expected_count_column` | 评论数 | 清单里的期望条数；空表示不比较数量。 |
| `match_mode` | `url` | 键匹配方式。 |
| `tolerance` | 0 | 允许的条数差。 |
| `per_link_limit` | 空 | 每个链接的采集上限提示。 |
| `output_mode` | `gaps` | `gaps` 或 `all`。 |
| `swap_tables` | `false` | 交换两张表的角色。 |
| `ignore_case` | `false` | 键匹配忽略大小写。 |

## 校验

- `engine.verify_two_inputs`：不是恰好两个数据父节点（命名节点不计）。
- `engine.verify_need_list_col` / `engine.verify_need_result_col`：缺少清单/结果键列。
- 键列不在对应表中：执行器按名拒绝。

## 输出契约

`emit_columns` 回答下游能读哪些列：**清单那一侧**的列（第一根线，`swap_tables` 时是第二根）+ 五个审计列。
结果表的列（`评论内容`…）不在报告里，因此也绝不承诺给下游；任一侧未知时整条回答是 `None`（未知），
而不是一个可能漏列的清单。

## 典型画布

```text
数据源（帖子清单）─┐
                    ├→ 采集校验（gaps）→ 数据源（只采缺口）/ 保存
评论采集（结果）  ─┘
```
