# 数据累积（accumulate）

数据累积把经过它的行追加到一个命名 lineage。它把上游表的形状原样传下去：上游未知，输出也未知。
`identity=row` 追加每一行；`identity=columns` 只追加键列组合尚未存在的行。必须有且只有一个表父节点。

- 清单：`backend/capabilities_kernel/nodes/accumulate/manifest.py`
- 行为：`backend/nodes/executors/accumulate.py`
- 契约测试：`tests/unit/capabilities/test_accumulate_manifest.py`

## 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `lineage_name` | 空 | 必填。跨运行累积的同一个名字。 |
| `identity` | `row` | `row` 或 `columns`。 |
| `key_columns` | 空 | `columns` 模式下的键列，逗号分隔（支持中文逗号）。 |

## 校验

- `engine.accumulate_no_name`：名字为空。
- `engine.accumulate_bad_identity`：identity 不是 row/columns。
- `engine.accumulate_no_keys`：columns 模式但没有键列。
- `engine.accumulate_one_parent`：父节点不是恰好一个。
- `engine.accumulate_bad_parent`：父节点不是行表。

## 典型画布

```text
数据源 → 数据累积（知乎评论, row）→ 保存
```
