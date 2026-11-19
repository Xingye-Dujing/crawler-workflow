# 京东（jd）

| | |
|---|---|
| id / 别名 | `jd` · `jingdong` |
| `item` 是 | 商品 SKU |
| 登录 | **扫码**（京东 App）· 短信 · cookie（要有 `thor` 和 `pin`） |

## 能做

- **读**：`item search` / `get` / `related`；`comment list`（商品评价，只有第一页）；`keyword hot` / `suggest`；`user get`（只 me）/ `collects`；`history list`（浏览历史）；`msg list` / `history` / `listen`；扩展命令 `order list`（订单）、`cart count`（购物车数量）、`coupon list <item>`（可用优惠券）。
- **写**：`msg send`（联系商家客服）。

京东是唯一有商品搜索、价格、评价、订单的电商平台，比价、看评价找它。

## 做不到

收藏 / 取消收藏商品、推荐流、`msg read` / `revoke` / `delete`；没有发布和互动。

## 参数

- 商品：SKU（纯数字）、`item.jd.com/<sku>.html`、M 站或全球购链接，或 `3.cn` / `u.jd.com` 短链。
- 用户：只支持 `me`。
- 会话：商家的 `venderId`（`msg list` 输出的 `id`），京东自营客服是 `1`。
- 订单：订单号（`order list` 输出的 `id`）或订单详情页 URL。

## 筛选与私有选项

- `item search`：`--sort general|sales|price_asc|price_desc|comments`。
- `--area <地区编码>`：收货地区，影响价格和库存，`省_市_区_镇` 格式如 `1_2800_55812_0`；默认取登录态里的地区。`item get` / `search` / `related`、`coupon list`、`cart count`、`history list`、`user collects` 都能用。
- `order list --range 3m|this_year|<年份>`，默认近三个月。

## 坑

- **风控很严**：测试账号真机验证时被封过。控制频率，命令之间留长间隔，不要批量翻页；出现 `RISK_CONTROL` 立即停。
- `comment list` 只有第一页：`--limit N` 在一次请求里取 N 条，不会翻页。
- `item related` 是近似结果（用第一个相关搜索词的搜索结果）。
- `msg send` 只支持文本，不支持 `--to`：用 `--item <商品>` 联系商家、`--conversation <venderId>` 回复，`--order <订单>` 按订单咨询（可单独用，联系自营客服）。

## 示例

```bash
catbus jd item search 机械键盘 --sort sales --limit 20
catbus jd item get 100012043978
catbus jd comment list 100012043978 --limit 30
catbus jd coupon list 100012043978
catbus jd order list --range this_year
```
