# 淘宝（taobao）

| | |
|---|---|
| id / 别名 | `taobao` · `tb` |
| `item` 是 | 商品 |
| 登录 | **只能 cookie 导入**（www.taobao.com 的 Cookie，要有 `unb`） |

## 能做

- **读**：`user get`（参数只接受商品链接，返回这件商品的卖家）；`msg history` / `listen`。
- **写**：`msg send`（联系卖家、回复会话）；`media upload`。

淘宝的定位是“客服私信”：值守消息、按商品联系卖家。

## 做不到

**商品详情、搜索、评价**（`item get` / `search`、`comment list`）上游都没有，淘宝拿不到商品数据；用户要比价、看评价时直接说不支持（京东可以）。另外没有直播、推荐流、会话列表、查自己（`user get me`）。

## 参数

- 商品 `--item` / `user get` 的参数：纯数字 ID、淘宝 / 天猫商品链接，或 `m.tb.cn` 短链。
- 会话：`msg listen` / `msg history` 输出的 `conversation_id`，必须属于当前账号。

## 坑

- `msg send` **不支持 `--to`**（没有按用户发起会话的接口）：用 `--item <商品>` 联系卖家，或 `--conversation <id>` 回复。私信是发给真人的，按写操作规则确认。
- `msg history` 结果从旧到新排列。

## 示例

```bash
catbus taobao user get "https://item.taobao.com/item.htm?id=<id>"
catbus taobao msg listen --duration 30m
catbus taobao msg send "请问有货吗？" --item <商品>
```
