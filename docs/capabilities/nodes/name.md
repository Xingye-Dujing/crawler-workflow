# 工作流命名（name）

命名节点只提供运行分组用的名字，**不产生任何行**。因此它必须在链路头部（没有上游连线），并且必须连到真正干活的节点；一个没有下游的标签不会把任何工作归到这个名字下。

- 清单：`backend/capabilities_kernel/nodes/name/manifest.py`
- 行为：`backend/nodes/executors/name.py`
- 契约测试：`tests/unit/capabilities/test_name_manifest.py`

## 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `workflow_name` | 空 | 必填。运行历史按它分组；空白在运行前按名拒绝。 |
| `layout_order` | 空 | 画布布局提示，不参与执行。 |

## 校验

- `engine.name_no_label`：名字为空。
- `engine.name_not_head`：有上游连线。
- `engine.name_no_downstream`：没有下游连线。

## 典型画布

```text
工作流命名（“知乎评论 · 10 月”）→ 数据源 / 上传 → 清洗 → 分词 → 保存
```
