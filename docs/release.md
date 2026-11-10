# 功能更新与发版流程

这份文档只讲**主程序**的更新与发布。Chrome / chromedriver / Node / CatBus / BERT 模型包仍走
“环境与组件”或在线安装器，不属于自更新范围。

相关实现：`backend/services/update.py`、`backend/api/update.py`、`backend/services/version.py`、
根目录 `version.json`、`backend/static/js/update.js`；安装器一侧是
`backend/services/components/feed.py`、`backend/services/components/catalog.py`、
`backend/services/components/default_catalog.json`。

## 版本号

- 版本号写在 `backend/services/version.py` 的 `APP_VERSION`，同时写进根目录 `version.json` 的 `version`。
- 格式是日期加构建号，例如 `2026.11.11.1`；比较时按数字段逐段比较，所以 `.2` 一定比 `.1` 新。
- **两边必须一致**：只改 `APP_VERSION` 不改 `version.json`，用户收不到提示；只改 `version.json` 不改代码，
  用户更新后会一直提示同一个版本。

## 安装器为什么不用每次重建

在线安装器（Windows 的 `CaiXiHui-Online-Setup.exe`、macOS 的 `CaiXiHui-Online-Setup-macOS-*.dmg`）不再把
主程序的下载地址、大小和 SHA-256 编进自己里面。它的组件清单里，`app` 一项写的是**发布清单地址**：

```json
"win32": {
  "archive": "zip", "install_as": "app", "strip_prefix": "CaiXiHui",
  "verify": ["CaiXiHui.exe"],
  "feed": [
    "https://gitee.com/Xingye-Dujing/crawler-workflow/raw/main/version.json",
    "https://raw.githubusercontent.com/Xingye-Dujing/crawler-workflow/main/version.json"
  ]
}
```

安装时它读这份 `version.json`，按当前系统/架构取包，校验 SHA-256 再安装。于是：

- **同一份安装器，永远安装当次最新的主程序**；只有安装器自己的代码或 Chrome/Node 这些组件版本变了才需要重建它；
- 主程序装好之后，后续功能更新走应用内的更新弹窗（`docs/installer.md` 的“主程序自更新”）；
- 清单读不到时安装器**按名字拒绝**（显示 URL 和原因），不会退回去装一个旧版本；“安装”按钮本身就是重试；
- `version.json` 里没有当前平台的包时同样拒绝，不会装错架构。

因此发版时**不要**再改 `default_catalog.json` 的 `app` 条目，也不要为了新版本重建在线安装器。

## 发布顺序（重要）

必须按下面的顺序，否则用户会看到“有新版本”但下载不到包：

1. 改代码、跑全量测试和 lint（见下）；
2. 改 `backend/services/version.py` 的 `APP_VERSION`；
3. 构建 Windows 和 macOS 新包；
4. 把新包上传到**新的 release tag**；
5. 更新 `version.json` 的版本号、大小、SHA-256、下载地址/分片；
6. 更新 Release 说明；
7. 提交并推送 `version.json`、`docs/`、代码。

`version.json` 是最后一步：它一更新，已装自更新版本的客户端会开始提示，**新下载的安装器也会立刻装到这一版**。

### 每个版本用新 tag，不要覆盖同名附件

Gitee/GitHub Release 的附件按“地址”下载，而摘要写在清单里。如果复用旧 tag 并把同名附件换成新字节：

- 旧 `version.json` 指向的包会变成另一份字节，正在更新的客户端校验失败；
- 上一版发出的在线安装器会下载到新字节却按旧摘要校验，直接失败。

所以：**新版本 = 新 tag**（例如 `exe-2026-12`），旧 tag 的附件一个字节都不要动。


## 发布前必须通过

在仓库根目录、`.venv/` 下执行：

```bash
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/ruff.exe check backend/ tests/
.venv/Scripts/ruff.exe format --check backend/ tests/
.venv/Scripts/python.exe tools/ci_lint_tiers.py product
.venv/Scripts/python.exe tools/ci_lint_tiers.py tests
```

全量 fast 必须 **0 失败**。失败了不构建、不发布；CI 的 `fast (windows/ubuntu/macos)` 会跑同样的
测试和 lint，不能靠放宽 gate 消红。

涉及爬虫、LLM、checkpoint/resume 的改动，发版前再加设备层：

```bash
.venv/Scripts/python.exe -m pytest -q -m "integration or live_ollama"
```

## Windows 构建与上传

### 1. 构建离线 Setup + 绿色版

```powershell
powershell -ExecutionPolicy Bypass -File desktop\build_windows.ps1 -Clean -Installer -Version 2026.11.11
```

**`-Version` 必须显式传，而且是三段数字**（Inno 的 `VersionInfoVersion` 会自己补 `.0`）：脚本默认值是
`1.0.0`，漏传会把安装器/收据按 1.0.0 盖章，而应用内 `APP_VERSION` 是四段（`2026.11.11.2`）。
四段版本只存在于 `backend/services/version.py` 与 `version.json`；构建脚本只接受 `^\d+\.\d+\.\d+$`。

产出：

- `dist\CaiXiHui-Setup.exe`
- `dist\CaiXiHui-win64.zip`

记录两个文件的字节数和 SHA-256。

### 2. 分片

`version.json` 和 Gitee 上传都使用 **99,614,720 B** 一片。切完后记录每一片的 SHA-256 和大小；
最后一片通常小于 99,614,720 B。

Gitee 单个附件的上限是 100 MB，所以 **`CaiXiHui-win64.zip` 和 `CaiXiHui-Setup.exe` 都要切**
（上一版 Gitee 上的资产就是 `.001`/`.002` 的 Setup 与 zip）；GitHub 传完整文件。下载页要让用户先
按顺序拼接（Windows：`copy /b CaiXiHui-Setup.exe.001+CaiXiHui-Setup.exe.002 CaiXiHui-Setup.exe`，
POSIX：`cat ... > CaiXiHui-Setup.exe`），再校验总 SHA-256。

### 3. 更新 version.json 的 win32 条目

把 `CaiXiHui-win64.zip` 的总 SHA-256、总大小，以及两个分片的 URL/SHA-256/大小写进 `version.json` 的
`platforms.win32`（**不是** `default_catalog.json`）：

```
https://gitee.com/Xingye-Dujing/crawler-workflow/releases/download/<新tag>/CaiXiHui-win64.zip.001
```

**只发 Windows 的版本不要保留旧的 `darwin-*` 条目**：`version.json` 的版本号一升，Mac 客户端会提示更新，
然后去下载上一版 DMG（装回去仍是旧版本，形成循环）。删掉 `darwin-*` 后 `asset_ready` 为假，Mac 端不提示，
下次带 macOS 构建时再加回来。

### 4. 在线安装器（只在安装器本身变化时重建）

```powershell
powershell -ExecutionPolicy Bypass -File desktop\bootstrap\build.ps1 -Clean
desktop\.venv-build\Scripts\python.exe desktop\patch_manifest.py --check dist\CaiXiHui-Online-Setup.exe
```

`patch_manifest.py --check` 必须显示 `requireAdministrator`。产出 `dist\CaiXiHui-Online-Setup.exe`。

需要重建的只有：安装器页面/流程改了、`backend/services/components/` 里的代码改了、Chrome/chromedriver/Node/
CatBus 的版本或地址变了。**主程序出新版本不需要重建它**——它读 `version.json` 决定装哪一版。
新发布里仍建议把当前这份安装器一起上传，让下载页只有一处入口。

### 5. 上传 Windows 资产

上传到 GitHub Release（完整文件）和 Gitee Release（国内直连以 Gitee 为准；Gitee 只传分片）：

GitHub：

- `CaiXiHui-Setup.exe`
- `CaiXiHui-win64.zip`
- `CaiXiHui-Online-Setup.exe`

Gitee：

- `CaiXiHui-win64.zip.001`、`.002`（`version.json` 的 win32 `parts` 指向这里）
- `CaiXiHui-Setup.exe.001`、`.002`（手动下载页拼接用）
- `CaiXiHui-Online-Setup.exe`（13 MB，不需要分片）

上传后再用 `version.json` 指向它们。上传顺序不影响旧客户端，因为它们看的还是旧 `version.json`。

## macOS 构建与上传

macOS 包由 GitHub Actions 的 `.github/workflows/macos-build.yml` 构建，不能在 Windows 上直接打：

1. 先推代码并把 release tag 推到新 tag；
2. 手动触发 workflow，`release_tag` 填新 tag；
3. workflow 产出并上传：
   - `CaiXiHui-macOS-arm64.dmg`
   - `CaiXiHui-macOS-x86_64.dmg`
   - `CaiXiHui-Online-Setup-macOS-arm64.dmg`
   - `CaiXiHui-Online-Setup-macOS-x86_64.dmg`
4. 从 Release API 读取四个文件的字节数和 SHA-256，把两个**应用 DMG**写进 `version.json` 的
   `platforms.darwin-arm64` / `platforms.darwin-x64`：

```json
"darwin-arm64": {
  "archive": "dmg",
  "url": "https://github.com/Xingye-Dujing/crawler-workflow/releases/download/<新tag>/CaiXiHui-macOS-arm64.dmg",
  "sha256": "<应用 DMG 的 SHA-256>",
  "size": 123456789
}
```

安装器的构建步骤不再需要应用 DMG 或 tag（`desktop/build_macos_installer.py --clean --arch <arch>`）：
它和 Windows 一样从 `version.json` 取包，所以同一份安装器可以跨版本使用。两个安装器 DMG 的摘要不写进
`version.json`，它们只是下载入口。

macOS 自更新从 GitHub Release 下载 DMG。访问不了 GitHub 的 Mac 仍应使用在线安装器或完整 DMG。

## 更新清单的可选签名（建议开启）

`version.json` 里的 SHA-256 只能证明"下载到的字节 = 清单说的字节"，而清单本身就是**最先被改的那一份**：
能改 Gitee/GitHub 上 `version.json` 的人，同时改掉 `url` 与 `sha256` 即可让客户端装上一份任意程序。
所以客户端支持对清单做**离线签名校验**，且是"配置了公钥就失败即拒绝"（fail closed）：

- 公钥位置：环境变量 `CIXI_UPDATE_PUBKEY`（PEM 文本，或指向 PEM 文件的路径），或打包版数据根下的
  `update-pubkey.pem`。**没有配置公钥时**自更新照常可用，但 `/api/update/check` 会返回 `signed: false`，
  面板与日志会说明这条链没有信任根。
- 签名方式：对清单去掉 `signature` 字段后的 JSON（`sort_keys=True`、紧凑分隔符、`ensure_ascii=True`）做
  Ed25519 签名，结果以 base64 写回清单的 `signature` 字段。校验用 `cryptography`（`requirements.txt` 已声明）。
- 配套规则（与签名一起生效，避免"签了名却仍可从明文/畸形地址取包"）：
  - 下载地址必须是 `https://`，**每一跳重定向都重新校验**（302 到 `http://`/`ftp://` 会被拒绝）；
  - 单包上限 4 GiB，超过即中止；
  - 清单里的 `version` 必须是点分版本号，客户端只用它当作 `data/updates/` 下的**一个目录名**（带 `..`、
    分隔符的版本号一律按名拒绝——这个值直接进 `shutil.rmtree` 的路径）。

发行脚本若要生成签名，用仓库根的工具（需要私钥，**私钥不要进仓库**）：

```bash
python tools/sign_release_feed.py version.json --key release-private.pem   # 写回 signature 字段
```

未签名 → 已签名的切换是兼容的：没配公钥的旧客户端忽略 `signature` 字段。

## version.json 模板

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

`version.json` 由仓库 raw 地址提供，客户端依次尝试：

```
https://gitee.com/Xingye-Dujing/crawler-workflow/raw/main/version.json
https://raw.githubusercontent.com/Xingye-Dujing/crawler-workflow/main/version.json
```

两个地址都要能读到同一份文件；Gitee 是主路径。

## 更新时保留什么

自更新只替换程序本体，以下内容不会被覆盖：

- 安装器选的数据目录：`data-root.txt`（在线安装布局在 `app/data-root.txt`，便携版在 exe 旁边）；
- `portable.txt`、`install-manifest.json`、`components/`；
- `data/` / `Data/`、`logs/`、`mplconfig/`、Cookie、模型、BERT 模型、上传文件、导出文件；
- Windows 旧程序放 `app.previous`，macOS 旧 `.app` 放 `CaiXiHui.app.previous` 作为回滚。

Windows 更新脚本按“逐项替换程序文件”的方式换 `CaiXiHui.exe`、`_internal`、`seed`、`samples` 等，
不会整目录删掉 `app/`，所以 `data-root.txt`、`portable.txt` 和用户数据都留在原处。

如果安装目录不可写（例如装在 `Program Files` 且当前用户无权限），应用会拒绝更新并提示用安装器，
不会先退出再失败。

## 回滚

- Windows：关闭程序，把 `app.previous` 里的程序文件移回原位；保留 `data/`、`components/` 等。
- macOS：把 `CaiXiHui.app.previous` 改回 `CaiXiHui.app`。
- 更新脚本在复制中途失败会自动移回旧程序并重新启动。

## 首次安装与后续更新

- **旧版本（没有自更新代码）不会自己弹窗**：先手动安装一次本版本。
- 之后的**主程序**更新，用户可以只在应用内点“立即更新”完成，不需要每次重新下载完整安装器。
- 组件更新（Chrome / chromedriver / Node / CatBus / BERT）仍走“环境与组件”或在线安装器；
  如果新版本需要新的组件版本，发版说明里要单独写清楚。
- 应用每次启动检查一次，之后每 6 小时检查一次；离线或读不到 `version.json` 时静默跳过，不阻塞工作区。
