# Python 节点（python）

Python 节点在一个已保存脚本上运行上游行表。脚本存放在账号的脚本库（与 AI 的 Python 工具共用），
节点只保存 `script_id`，不内联代码：画布因此可审阅、可复用、可版本化。

- 清单：`backend/capabilities_kernel/nodes/python/manifest.py`
- 行为：`backend/nodes/executors/python_node.py`
- 契约测试：`tests/unit/capabilities/test_python_manifest.py`

## 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `script_id` | 空 | 脚本库里的 id 或名字。空/未知由执行器按名拒绝。 |
| `args` | `{}` | JSON 对象，脚本从 `CIXI_ARGS` 读取。 |
| `timeout` | 120 | 1–3600 秒。 |
| `max_rows` | 200000 | 输出行数上限，运行时另有硬上限。 |

## 边界

- **仅本地/桌面**：云模式按名拒绝（`ai.pythonCloud`）；它不是沙箱，脚本拥有进程权限。
- 执行契约：`CIXI_INPUT` 进、`CIXI_OUTPUT` 出，JSON Lines；详见 Python 扩展文档。
- 失败：空/未知脚本 `ai.pythonUnknown`；`args` 不是 JSON 对象 `ai.pythonArgs`；超时/行数不是数字
  `ai.pythonBadNumber`。

## 典型画布

```text
数据源 → Python 节点（clean_links, args={"drop_empty": true}）→ 保存
```
