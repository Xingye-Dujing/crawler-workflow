# 文件上传（upload）

文件上传把已存储的数据集（上传/粘贴/导入）发布成普通行表。下游节点看到的形状与一次采集完全相同，因此任何需要数据的节点都可以接它，而不需要自己的上传界面。

- 清单：`backend/capabilities_kernel/nodes/upload/manifest.py`
- 行为：`backend/nodes/executors/upload.py`
- 契约测试：`tests/unit/capabilities/test_upload_manifest.py`

## 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `dataset_id` | 空 | 必填。数据面板里的数据集 id。 |
| `dataset_name` | 空 | 重新绑定时的提示：按名字与行数找回被删掉的数据集。 |
| `row_count` | 空 | 同上；只用于重绑定，不参与执行。 |

## 行为与失败模式

- 数据集被删除时，执行器先按 `dataset_name` + `row_count` 找替代；找不到才拒绝（`upload.stale`），绝不返回空表冒充成功。
- 没有 `dataset_id`：运行前 `engine.upload_no_file`。
- 血缘视图通过 `emit_columns` 读数据集的真实列；数据集不存在/未选时回答“未知”，不猜列名。

## 典型画布

```text
文件上传（comments.csv）→ 清洗 → 分词 → 词云
```
