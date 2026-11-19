# 闲鱼（xianyu）

| | |
|---|---|
| id / 别名 | `xianyu` · `goofish` `xy` |
| `item` 是 | 闲置商品 |
| 登录 | **扫码**（闲鱼 App → 扫一扫）· cookie |

## 能做

- **读**：`item get`；`user get`（只 me，昵称可能为 null）；`msg history` / `listen`。
- **写**：`item publish`（上架闲置）；`msg send`；`media upload`。

闲鱼的定位是“私信与上架”：适合值守消息、按商品联系卖家、发布闲置。

## 做不到

**商品搜索、推荐流**（`item search`、`feed list`）、查看别人的主页和在售商品、会话列表（`msg list`）、收藏。用户想在闲鱼上找东西时，告诉他目前不支持搜索。

## 参数

- 商品：纯数字 ID、`goofish.com/item?id=<id>`、分享短链或整段分享文本。
- 用户：`me`、数字用户 ID、主页链接 `goofish.com/personal?userId=<id>`。
- 会话：`msg listen` / `msg send` 输出的 `conversation_id`。

## 坑

- **`item publish` 会真的上架商品，而且只能公开**（`--visibility public`）。发之前把标题、价格、图片给用户确认。
  - `--price` 售价（元），`--original-price` 原价；`--shipping free|distance|fixed|none`（默认包邮），`fixed` 时配 `--postage`；`--pickup` 支持自提。
  - 类目由闲鱼自动推荐，发布地点取账号的第一个常用地址。
- `msg send`：`--item <商品>` 联系卖家；`--to <用户> --item <商品>` 就这件商品联系对方（卖家联系买家）；`--conversation <id>` 回复已有会话。私信是发给真人的，按写操作规则确认。
- `msg history` 结果从旧到新排列。

## 示例

```bash
catbus xianyu item get "https://www.goofish.com/item?id=<id>"
catbus xianyu msg listen --duration 30m
catbus xianyu msg history <会话 id> --limit 50
catbus xianyu msg send "还在吗？" --item <商品>
```
