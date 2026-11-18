# 发版流程

本文只讲**主程序**的更新与发布。Chrome / chromedriver / Node / CatBus / BERT 模型包走“环境与组件”或在线安装器
（见 [`installer.md`](installer.md)），不属于自更新范围。

实现：`backend/services/update.py`、`backend/api/update.py`、`backend/services/version.py`、根目录 `version.json`、
`backend/static/js/update.js`；安装器一侧是 `backend/services/components/`（`feed.py`、`catalog.py`、
`default_catalog.json`）。

## 版本号

- 版本号写在 `backend/services/version.py` 的 `APP_VERSION`，同时写进根目录 `version.json` 的 `version`。
- 格式为日期加构建号（`2026.11.11.1`），按数字段逐段比较，所以 `.2` 一定比 `.1` 新。
- **两边必须一致**：只改 `APP_VERSION`，用户收不到提示；只改 `version.json`，更新后一直提示同一版本。
- 版本号是 **3 或 4 段数字**（`2026.11.14.2`）。构建脚本的 `-Version` 接受 `^\d+(\.\d+){2,3}$`，
  拒绝斜杠、空格与预发布后缀，且**必须显式传**：脚本默认 `1.0.0` 只服务于本机手工构建，漏传会把安装器与回执按
  `1.0.0` 盖章。四段只在 `APP_VERSION` 与 `version.json` 里使用。GitHub 发布 workflow 把 `version` 设为必填，
  并在打包前用 `tools/check_release_version.py` 拒绝任何不是 `APP_VERSION` 前缀的值。

## 发布清单（按顺序）

顺序不能换：`version.json` 一更新，已装客户端立刻开始提示，新下载的安装器也立刻装这一版。

1. 跑发布前检查（下节），0 失败才继续。
2. 改 `backend/services/version.py` 的 `APP_VERSION`。
3. 构建 Windows 包（`-Clean -Installer -Version <三段或四段>`），写 `dist/SHA256SUMS` 与 `dist/release-manifest.json`。
4. `tools/publish_gitee.py` 一条命令切片、腾 Gitee 空间、建 Release、上传。
5. 上传 GitHub（完整文件）——`gh release create` + `gh release upload`。
6. 用**新 tag** 触发 macOS workflow，两个 DMG 由它上传。
7. `tools/write_release_feed.py` 写 `version.json`：Windows 的字节数与摘要来自 `dist/`，macOS 的从 Release API 读回。
8. 按 `version.json` 的 `notes` 写 Release 说明。
9. 提交并推送 `version.json`、代码与 `docs/`。
10. 用 `CIXI_UPDATE_FEED` 指向这份清单排练一次更新（见“排练”）。

## 发布前必须通过

在仓库根目录、`.venv/` 下执行（Windows 的 `Scripts/`，Linux/macOS 为 `bin/`）：

```bash
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/ruff.exe check backend/ tests/
.venv/Scripts/ruff.exe format --check backend/ tests/
.venv/Scripts/python.exe tools/ci_lint_tiers.py product
.venv/Scripts/python.exe tools/ci_lint_tiers.py tests
```

全量 fast 必须 **0 失败**。失败不构建、不发布；CI 的 `fast (windows/ubuntu/macos)` 跑同样的测试与 lint，
不能靠放宽 gate 消红。涉及爬虫、LLM、checkpoint/resume 的改动另加设备层：

```bash
.venv/Scripts/python.exe -m pytest -q -m "integration or live_ollama"
```

## Windows 构建与上传

```powershell
powershell -ExecutionPolicy Bypass -File desktop\build_windows.ps1 -Clean -Installer -Version 2026.11.11
```

产出 `dist\CaiXiHui-Setup.exe` 与 `dist\CaiXiHui-win64.zip`。

**分片 + 腾空间 + 建 Release + 上传，一条命令**（`tools/publish_gitee.py`，2026.11.18.2 那次发布起）：

```powershell
$env:GITEE_TOKEN = '<带 projects 权限的私人令牌>'      # 只从环境变量读，命令行里不出现
.venv\Scripts\python.exe tools\publish_gitee.py exe-2026-11-19.1 --keep manual-2026-11 --dry-run
.venv\Scripts\python.exe tools\publish_gitee.py exe-2026-11-19.1 --keep manual-2026-11
```

它按这个顺序做四件事，顺序本身是有原因的：**切片**（`version.json` 与 Gitee 上传都按 **99,614,720 B** 一片，
最后一片通常更小；每片都**重写**，因为重建后的包第一片字节数相同而内容不同）→ **建 Release**（Gitee 的写接口
要求令牌与 `owner`/`repo` 作为表单字段，只放在路径和头里会回 400“验证失败，所有参数不能为空”）→ **腾空间**
（`prune_gitee_releases` 拒绝“要保留的 tag 还没有 Release”的调用，所以必须先建）→ **上传**（同名附件跳过，不覆盖
已发布的字节）。GitHub 那一半仍是 `gh release create` + `gh release upload`：传完整文件，不切片。

切片是为了下载页：Gitee 单个附件上限 100 MB，所以 `CaiXiHui-win64.zip` 与 `CaiXiHui-Setup.exe` **都要切**。
下载页让用户按顺序拼接（Windows：`copy /b CaiXiHui-Setup.exe.001+CaiXiHui-Setup.exe.002 CaiXiHui-Setup.exe`；
POSIX：`cat ... >`），再校验总 SHA-256。

**只保留当前 tag 的附件**：仓库 Release 附件总量上限 1 GB，而每个 Windows 版本的分片合计约 260 MB。
这条规则由 `prune_gitee_releases` 执行（上面的工具内部会调它，也可以单独跑）：

```powershell
.venv\Scripts\python.exe tools\prune_gitee_releases.py --tag exe-2026-11.13 --dry-run
.venv\Scripts\python.exe tools\prune_gitee_releases.py --tag exe-2026-11.13 --tag manual-2026-11
```

只删**附件**，Release 条目、说明与 git tag 都保留；要保留多个 tag 时把 `--tag` 写两遍（使用手册是独立的
`manual-2026-11`）。当前 tag 在远端没有 Release 时脚本按名拒绝——`--tag` 拼错会清空全仓资产，不能只靠小心。
生成的 `<tag>.zip`/`.tar.gz` 是源码链接，不是附件，不占那 1 GB。GitHub 没有这个额度，旧 tag 的附件照旧保留。

**上传**：GitHub 传 `CaiXiHui-Setup.exe`、`CaiXiHui-win64.zip`、`CaiXiHui-Online-Setup.exe`；
Gitee 传 `CaiXiHui-win64.zip.001/.002`、`CaiXiHui-Setup.exe.001/.002` 与不分片的在线安装器。
上传顺序不影响旧客户端，它们看的还是旧 `version.json`。

**在线安装器只在自身变化时重建**：安装器页面/流程、`backend/services/components/` 的代码、组件版本或地址改了才需要；
主程序出新版本不需要。每次发布仍建议把当前安装器一起上传，让下载页只有一处入口：

```powershell
powershell -ExecutionPolicy Bypass -File desktop\bootstrap\build.ps1 -Clean
desktop\.venv-build\Scripts\python.exe desktop\patch_manifest.py --check dist\CaiXiHui-Online-Setup.exe
```

`--check` 必须显示 `requireAdministrator`。附件按地址下载、摘要写在清单里，所以**新版本 = 新 tag**
（例如 `exe-2026-12`）：复用旧 tag 并换同名附件会让正在更新的客户端与上一版发出的安装器按旧摘要校验失败，
旧 tag 的附件一个字节都不要动。

## macOS

macOS 包只能由 `.github/workflows/macos-build.yml` 在 GitHub 的 macOS runner 上构建：

1. 推代码并把 release tag 推到新 tag；
2. 触发 workflow：推 tag（workflow 用 `github.ref_name`），或手动触发填 `release_tag`。
   tag 必须以 `exe-` 开头，否则打包前按名退出；上传不带 `--clobber`，同名资产让 workflow 失败而不是覆盖已发布字节。
3. 产出并上传 `CaiXiHui-macOS-arm64.dmg`、`CaiXiHui-macOS-x86_64.dmg`、
   `CaiXiHui-Online-Setup-macOS-arm64.dmg`、`CaiXiHui-Online-Setup-macOS-x86_64.dmg`。
4. 从 Release API 读四个文件的大小与 SHA-256，把两个**应用 DMG**写进 `version.json` 的
   `platforms.darwin-arm64` / `platforms.darwin-x64`。

安装器构建不需要应用 DMG 或 tag（`desktop/build_macos_installer.py --clean --arch <arch>`），它和 Windows 一样
从 `version.json` 取包，所以同一份安装器跨版本可用。两个安装器 DMG 的摘要不写进 `version.json`，它们只是下载入口。
macOS 自更新从 GitHub Release 下载 DMG；访问不了 GitHub 的 Mac 用在线安装器或完整 DMG。

## version.json

**由工具写，不手抄**。三个数字里有两个根本不是人能记住的（总包摘要、每片摘要），手写一次错一次：

```powershell
.venv\Scripts\python.exe tools\write_release_feed.py 2026.12.01.1 exe-2026-12-01.1 --notes-file notes.md
# 只发 Windows 时必须显式说，否则旧的 darwin-* 条目会被 Mac 客户端当成“有新版本”
.venv\Scripts\python.exe tools\write_release_feed.py 2026.12.01.1 exe-2026-12-01.1 --notes-file notes.md --windows-only
```

- Windows 的数字取自 `dist/`（`CaiXiHui-win64.zip` 与它的 `.001`/`.002`），**并校验分片之和等于总包**——
  重建后残留的旧分片会被当场拒绝，而不是写进清单让用户拼出一个坏包。
- macOS 的数字从 Release API 读回（`gh release view <tag> --json assets` 的 `digest`/`size`）；某个 DMG 还没传上去
  时按名拒绝，不写“看起来对”的摘要。
- 缺 `notes`、缺平台、版本号不是三段或四段数字，都按名拒绝。
- 写出的清单必须能被客户端自己的校验器读（`services.update._valid_feed` / `_asset_usable`）——
  这条由 `tests/unit/tools/test_write_release_feed.py` 端着，改清单形状时先看它。

```json
{
  "schema": 1,
  "version": "2026.12.01.1",
  "released": "2026-12-01",
  "notes": "这一版的主要变化，用户更新时会看到。",
  "platforms": {
    "win32": {
      "archive": "zip",
      "sha256": "<CaiXiHui-win64.zip 总 SHA-256>",
      "size": 130000000,
      "parts": [
        { "url": "<新tag>/CaiXiHui-win64.zip.001", "sha256": "...", "size": 99614720 },
        { "url": "<新tag>/CaiXiHui-win64.zip.002", "sha256": "...", "size": 30000000 }
      ]
    },
    "darwin-arm64": {
      "archive": "dmg",
      "url": "<新tag>/CaiXiHui-macOS-arm64.dmg",
      "sha256": "...",
      "size": 177000000
    },
    "darwin-x64": {
      "archive": "dmg",
      "url": "<新tag>/CaiXiHui-macOS-x86_64.dmg",
      "sha256": "...",
      "size": 188000000
    }
  }
}
```

- `win32` 可给单包 `url`，也可给 `parts`（Gitee 分片）；两种都能装。
- **总包与每个分片都必须有 `sha256`**，缺摘要的条目不算可下载，客户端连下载都不开始。
- 只发 Windows 的版本**删掉旧的 `darwin-*` 条目**：版本号一升，Mac 客户端会提示并去下载上一版 DMG，
  形成循环；删掉后 `asset_ready` 为假，Mac 端不提示。
- 清单由仓库 raw 地址提供，两个地址都要读到同一份文件，Gitee 为主：

  ```
  https://gitee.com/Xingye-Dujing/crawler-workflow/raw/main/version.json
  https://raw.githubusercontent.com/Xingye-Dujing/crawler-workflow/main/version.json
  ```

## 清单的可选签名

`version.json` 的 SHA-256 只证明“下载到的字节 = 清单说的字节”，而清单本身是最先被改的那一份。客户端因此支持
清单离线签名，规则是“配置了公钥就失败即拒绝”：

- 公钥：环境变量 `CIXI_UPDATE_PUBKEY`（PEM 文本或文件路径），或打包版数据根下的 `update-pubkey.pem`。
  没配公钥时自更新照常可用，但 `/api/update/check` 返回 `signed: false`，更新卡片说明这条链没有信任根。
- 签名对象是清单去掉 `signature` 后的 JSON（`sort_keys=True`、紧凑分隔符、`ensure_ascii=True`），Ed25519 签名后
  以 base64 写回 `signature`；校验用 `cryptography`（已声明在 `requirements.txt`）。
- 与签名一起生效的规则：下载地址必须 `https://` 且**每一跳重定向都重新校验**；清单限读 1 MiB；单包上限 4 GiB；
  传输 60 秒没有新字节按名失败；清单的 `version` 必须是点分版本号（它直接进 `data/updates/` 的目录名）；
  解压后过**形状校验**（`CaiXiHui.exe` 与 `_internal`，macOS 是 `.app` 里的可执行文件）。
- 生成签名用仓库根工具（私钥不进仓库，未签名到已签名是兼容的）：

  ```bash
  python tools/sign_release_feed.py version.json --key release-private.pem
  ```

## 更新时保留什么

自更新只替换程序本体，以下内容不会被覆盖：

- 安装器选的数据目录：`data-root.txt`（在线安装布局在 `app/data-root.txt`，便携版在 exe 旁边）；
- `portable.txt`、`install-manifest.json`、`components/`；
- `data/`、`logs/`、`mplconfig/`、Cookie、模型、BERT 模型、上传与导出文件；
- Windows 旧程序放 `app.previous`（每次替换前重建，不累积），macOS 旧 `.app` 放 `CaiXiHui.app.previous`。

Windows 更新脚本逐项替换 `CaiXiHui.exe`、`_internal`、`seed`、`samples` 等，不整目录删 `app/`，所以
`data-root.txt`、`portable.txt` 与用户数据留在原处。被占用的文件最多重试 20 秒，失败就逐项移回并启动旧版本。
唯一的非程序写入是**安装回执**：新版本启动时把 `current-version` 与 `versions/<新版本>/install.json` 改成自己的版本
（`backend/services/update_receipt.py`，`method: self-update`），让“安装器装的是哪一版”继续等于“现在跑的是哪一版”。
安装目录不可写时（如在 `Program Files` 且当前用户无权限）拒绝更新并提示用安装器，不先退出再失败。

## 排练与回滚

`CIXI_UPDATE_FEED` 覆盖清单地址（逗号分隔可给多个），指向本地/内网清单即可走完整条链路。

必看四条：下载中关窗口后能装完并自启；清单 `sha256` 改错会按名失败且**程序不退出**；替换脚本换成立刻退出的程序会得到
“更新程序没能启动（10 秒内没有回执）”而不是进程消失；采集进行中“立即更新”可以下载，“重启并完成更新”被服务端拒绝。

回滚：

- Windows：关闭程序，把 `app.previous` 里的程序文件移回原位，保留 `data/`、`components/`。
- macOS：把 `CaiXiHui.app.previous` 改回 `CaiXiHui.app`。
- 替换中途失败与“新版本 15 秒内退出”会自动回滚，原因写 `<data>/updates/update.log`，启动后按名显示
  （`update.err.swap_lost` / `update.err.<code>`）。

客户端每次启动检查一次，之后每 6 小时一次；离线或读不到 `version.json` 时静默跳过，不阻塞工作区。
