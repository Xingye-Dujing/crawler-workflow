# scatter（console）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/charts/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/charts/scatter.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

散点图：两个数值列做坐标，看相关关系与离群点。

## 何时使用

两个数值的关系：点赞与评论、两个模型的得分、热度与情感指数。

不要用于：

- 只有一个数值列时看分布用直方图。

## 字段

| 字段 | 角色 | 必填 | 默认列 | 控件 |
|---|---|---|---|---|
| `x_field` | value | 是 |  |  |
| `y_field` | value | 是 |  |  |

## 输出形状

ECharts/matplotlib 图（可另出 LaTeX 图/表），不是一张数据表。

## 引擎

- ECharts 与 matplotlib 都能画
- 有 LaTeX 孪生图/表

## 契约测试

- `tests/unit/capabilities/test_chart_manifests.py`
