# 写操作

发布、评论、点赞、收藏、转发、关注、删除。这些都会真实改变用户的账号，别人看得到，有的删不掉。

## 流程

1. **确认意图**：用户明确要做这件事，并且给出了对象和内容。不替用户想内容去发，不顺手点赞、关注。
2. **查平台支持**：读 `platforms/<id>.md`，再看 `catbus <p> item publish --help`：哪些选项能用（没列出的会报 `UNSUPPORTED`）、`--visibility` 能取哪些值。
3. **说清后果**：公开还是仅自己可见、能不能删掉、会不会花钱（B 站投币、直播送礼）。
4. **执行**，把返回对象的 `url` 给用户，让他自己去看一眼。

## 发布

```bash
catbus weibo item publish --text "测试" --visibility private
catbus xhs item publish --title 周末露营 --text @note.md --image 1.jpg --image 2.jpg --visibility private
catbus bilibili item publish --title 标题 --video a.mp4 --cover c.jpg --category <id> --visibility private
```

- **默认加 `--visibility private`**，除非用户明确说公开。
- 只支持公开的：**闲鱼**（会真的上架商品）、**X**、**B 站动态**（`dynamic publish`）。发之前告诉用户会公开，得到同意再发。
- 本地文件直接传路径，catbus 自动上传；`--text @file` 从文件读正文。
- 删不掉的：小红书、快手、微博的 `item delete` 还没有实现，发出去只能让用户在 App 里手动删。这也是要先用 private 的原因。

各平台的差异：

| 平台 | 要点 |
|---|---|
| xhs | `--image` 与 `--video` 二选一；视频必须给 `--cover`；地点要 `--poi-name` |
| douyin | 目前**发布会被风控拦下**（报 `RISK_CONTROL`），写操作还没真机跑通，先告诉用户 |
| tiktok | 写操作要用浏览器会话 JSON 登录，只有 cookie 时会报 `AUTH_REQUIRED`；视频要 `--cover`，只读 MP4 |
| bilibili | 只能发视频；`--category` 取自 `item categories` |
| kuaishou | 图集 1～31 张或一个视频；没有 `--cover` |
| weibo | `--visibility` 支持 `public` `private` `friends` `fans` |
| xianyu | 只能公开，会真的上架；`--price` 售价（元），运费、自提等见平台文件 |
| x | 只能公开；超过 280 权重自动发长推，需要 Premium |

## 互动

```bash
catbus bilibili item like BV1xx411c7mD
catbus x comment add <推文> "内容"
catbus tiktok user follow <user>
```

- 点赞、收藏、关注有反操作（`unlike`、`uncollect`、`unfollow`），做错了可以撤回。
- 评论、转发发出去就是公开的，先把内容给用户过目。
- **抖音**的点赞、收藏、评论还没有真机验证通过，实测点赞可能让登录态失效。用户坚持要做时先说明风险。

## 危险操作

所有 `delete`、`msg revoke`、B 站的 `item coin`（花硬币）/ `item triple`、`live send --gift`（花钱）需要确认。你在非交互环境里运行，不带 `-y` 会报 `CONFIRM_REQUIRED`（退出码 2）。

**只在用户明确同意这一次具体操作后才加 `-y`**。不要为了省事默认加，也不要把一次同意推广到后面的操作。

## 批量

不要批量发布、评论、关注、私信。用户要求对很多对象做同样的写操作时，说明会被当作刷量、很可能被风控或封号，确认后逐条执行，每条之间留出较长间隔，出现 `RISK_CONTROL` 立即停。
