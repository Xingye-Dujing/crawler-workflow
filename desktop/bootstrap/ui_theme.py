"""Words, colours and the page stylesheet of the online installer.

Kept apart from the server so the test suite can compare the palette with the application's own
``base.css`` tokens without starting anything. The page opens in the application's paper-white
light theme and offers the dark one as a switch — the installer is the first screen of the product,
so it should look like the same product in either mode.
"""

from __future__ import annotations

TEXT = {
    'zh': {
        'title': '采析绘安装器',
        'intro': '选择安装位置和要安装的组件。默认是“国内直连”，不需要翻墙。',
        'dir': '安装位置',
        'data_dir': '数据文件夹',
        'data_hint': '工作流、运行记录、Cookie 都放在这里；和程序分开放，换盘不用重装。',
        'browse': '浏览…',
        'preset': '安装方式',
        'preset_one': '一键安装（推荐，国内直连）',
        'preset_app': '仅主程序',
        'components': '组件（可取消勾选）',
        'size': '需要下载：{size}',
        'install': '开始安装',
        'launch': '启动采析绘',
        'open': '打开安装目录',
        'cancel': '取消',
        'quit': '退出',
        'installing': '正在安装 {name}…',
        'already_running': '正在安装，请等这一次结束。',
        'done': '安装完成。正在检查环境…',
        'failed': '安装失败：{err}',
        'no_selection': '至少选择主程序。',
        'disk': '目标磁盘剩余 {free}，需要 {need}。请换一个磁盘或减少组件。',
        'bad_path': (
            '这个文件夹所在的盘被 Windows 当作“网络位置”，装好的程序会无法加载界面组件：\n'
            '{path}\n请改选本机 C: 或 D: 上的文件夹（例如 C:\\Users\\你\\Programs\\CaiXiHui）。'
        ),
        'doctor_title': '环境检查',
        'doctor_head': '这台机器现在可以做什么：',
        'doctor_running': '正在检查环境…',
        'doctor_empty': '没有拿到环境报告。可以打开应用里的“环境与组件”重新检测。',
        'close': '关闭',
        'elevated_again': '已经用管理员权限重试过，这个目录仍然不可写。请换一个目录，或检查它的权限。',
        'elevate_failed': '没有拿到管理员权限，无法写入这个目录。请换一个目录，或手动以管理员身份运行安装器。',
        'relaunching': '这个目录需要管理员权限，正在请求一次；请在 Windows 弹窗里点“是”，新的安装器窗口会打开。',
        'license': '第三方组件按各自的许可证分发；Chrome 从 Google 官方测试通道下载，不随本安装器重新分发。',
        'vpn': '默认使用国内镜像（npmmirror / Gitee）；不需要翻墙。',
        'launched': '已启动采析绘，可以关闭这个页面。',
        'not_installed': '主程序还没有装好，先完成安装。',
        'theme_dark': '切换到深色',
        'theme_light': '切换到浅色',
        'unavailable_here': '此平台暂不提供',
    },
    'en': {
        'title': 'CaiXiHui Installer',
        'intro': 'Choose where to install and which components. The default is the domestic route; no VPN needed.',
        'dir': 'Install folder',
        'data_dir': 'Data folder',
        'data_hint': (
            'Workflows, run records and cookies live here; keeping them apart from the program '
            'means a drive change needs no reinstall.'
        ),
        'browse': 'Browse…',
        'preset': 'Preset',
        'preset_one': 'One-click (recommended, domestic)',
        'preset_app': 'Application only',
        'components': 'Components (untick any)',
        'size': 'Download size: {size}',
        'install': 'Install',
        'launch': 'Launch CaiXiHui',
        'open': 'Open folder',
        'cancel': 'Cancel',
        'quit': 'Quit',
        'installing': 'Installing {name}…',
        'already_running': 'An install is already running; wait for it to finish.',
        'done': 'Installed. Checking the environment…',
        'failed': 'Install failed: {err}',
        'no_selection': 'Select at least the application.',
        'disk': 'The target drive has {free} free but needs {need}. Choose another drive or fewer components.',
        'bad_path': (
            'Windows classifies that drive as a network location, so the installed application '
            'could not load its window components:\n{path}\n'
            'Choose a folder on local C: or D: instead.'
        ),
        'doctor_title': 'Environment check',
        'doctor_head': 'This machine can now:',
        'doctor_running': 'Checking the environment…',
        'doctor_empty': 'No environment report came back. Open 环境与组件 in the app to check again.',
        'close': 'Close',
        'elevated_again': (
            'Retried with administrator rights and the folder is still not writable. '
            'Choose another folder or check its permissions.'
        ),
        'elevate_failed': (
            'Administrator rights were not granted, so that folder cannot be written. '
            'Choose another folder or run the installer as administrator.'
        ),
        'relaunching': (
            'That folder needs administrator rights; asking once — choose “Yes” in the Windows '
            'prompt, and a new installer window will open.'
        ),
        'license': (
            'Third-party components keep their own licences; Chrome is downloaded from Google for '
            'Testing and is not redistributed here.'
        ),
        'vpn': 'Domestic mirrors (npmmirror / Gitee) are tried first; no VPN is needed.',
        'launched': 'CaiXiHui has started; this page can be closed.',
        'not_installed': 'The application is not installed yet; finish the install first.',
        'theme_dark': 'Switch to dark',
        'theme_light': 'Switch to light',
        'unavailable_here': 'not available on this platform',
    },
}

STATE_LABEL = {
    'zh': {'ok': '可用', 'degraded': '可用（有降级）', 'missing': '不可用', 'unknown': '无法核对'},
    'en': {'ok': 'available', 'degraded': 'available (degraded)', 'missing': 'unavailable', 'unknown': 'not checked'},
}

#: The application's light tokens (``backend/static/css/base.css``). The page opens light; dark is
#: a switch, not the default, because a first-run screen should look like the paper-white product.
PALETTE = {
    'bg': '#ffffff',
    'paper': '#faf9f6',
    'text': '#1a1a1a',
    'dim': '#6b6b6b',
    'faint': '#c9c9c9',
    'line': '#dcdcdc',
    'line2': '#f0f0f0',
    'hover': '#f4f2ee',
    'accent': '#9a7740',
    'accent_hover': '#8a6a38',
    'ok': '#4e8061',
    'warn': '#9a7740',
    'err': '#a85454',
    'on_accent': '#ffffff',
}

#: The same tokens from ``base.css``'s ``:root[data-theme="dark"]`` block, flattened where the CSS
#: uses alpha (Tk-free page, but the panel still reads as one surface).
DARK = {
    'bg': '#14161b',
    'paper': '#1c2027',
    'text': '#e7e5df',
    'dim': '#9a9a94',
    'faint': '#3b414b',
    'line': '#3b414b',
    'line2': '#24272e',
    'hover': '#23262d',
    'accent': '#c79a5b',
    'accent_hover': '#d6ad72',
    'ok': '#6aa884',
    'warn': '#c79a5b',
    'err': '#cf7a7a',
    'on_accent': '#14161b',
}

#: A 16 px check mark as a data URI: the page needs no extra asset for the tick. The stroke is the
#: page ground, because the box fills with the ink colour; the dark theme flips that pair.
_CHECK_SVG = (
    'data:image/svg+xml;utf8,'
    "<svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 16 16'>"
    "<path d='M3.5 8.4l3.1 3.1 6-6.9' fill='none' stroke='%23ffffff' stroke-width='2' "
    "stroke-linecap='round' stroke-linejoin='round'/></svg>"
)
_CHECK_SVG_DARK = (
    'data:image/svg+xml;utf8,'
    "<svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 16 16'>"
    "<path d='M3.5 8.4l3.1 3.1 6-6.9' fill='none' stroke='%2314161b' stroke-width='2' "
    "stroke-linecap='round' stroke-linejoin='round'/></svg>"
)


def _variables(c: dict) -> str:
    return f"""
  --bg: {c['bg']};
  --paper: {c['paper']};
  --text: {c['text']};
  --dim: {c['dim']};
  --faint: {c['faint']};
  --line: {c['line']};
  --line2: {c['line2']};
  --hover: {c['hover']};
  --accent: {c['accent']};
  --accent-hover: {c['accent_hover']};
  --ok: {c['ok']};
  --warn: {c['warn']};
  --err: {c['err']};
  --on-accent: {c['on_accent']};
"""


def stylesheet() -> str:
    """The page CSS, written in the application's own design language.

    The layout is one screen: no outer scroll, no inner scroll for the component list — the six
    catalogue entries fit, and a form that needs scrolling hides its own primary button.
    """
    return f"""
:root {{{_variables(PALETTE)}
  --radius: 2px;
  --font: "Literata", Georgia, "Songti SC", SimSun, serif;
  --check: url("{_CHECK_SVG}");
}}
:root[data-theme="dark"] {{{_variables(DARK)}
  --check: url("{_CHECK_SVG_DARK}");
}}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; height: 100%; }}
body {{
  background: var(--bg);
  color: var(--text);
  font-family: var(--font);
  font-size: 13.5px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
  overflow: hidden;
  transition: background .15s, color .15s;
}}
.page {{
  height: 100%; max-width: 960px; margin: 0 auto; padding: 0 30px;
  display: flex; flex-direction: column;
}}
header.page-head {{ padding: 18px 0 12px; border-bottom: 1px solid var(--line); flex: none; }}
.scroll {{ flex: 1; min-height: 0; overflow: hidden; display: flex; flex-direction: column; }}
.brand-row {{ display: flex; align-items: center; gap: 12px; }}
h1 {{ margin: 0; font-size: 22px; font-weight: 600; letter-spacing: 0.2px; }}
.lang {{ margin-left: auto; display: flex; gap: 2px; align-items: center; }}
.lang button, #theme {{
  border: 1px solid transparent; background: none; color: var(--dim);
  padding: 3px 8px; cursor: pointer; font: inherit; font-size: 11.5px; border-radius: var(--radius);
}}
.lang button:hover, #theme:hover {{ color: var(--text); border-color: var(--line); background: var(--hover); }}
.lang button[aria-pressed="true"] {{ color: var(--text); border-color: var(--line); background: var(--hover); }}
#theme {{
  width: 28px; height: 24px; padding: 0; display: inline-flex;
  align-items: center; justify-content: center;
}}
#theme .icon {{ width: 14px; height: 14px; display: block; }}
#theme .icon-sun {{ display: none; }}
:root[data-theme="dark"] #theme .icon-sun {{ display: block; }}
:root[data-theme="dark"] #theme .icon-moon {{ display: none; }}
.intro {{ margin: 4px 0 0; color: var(--dim); font-size: 12px; max-width: 760px; }}
section {{ padding: 9px 0; border-bottom: 1px solid var(--line2); flex: none; }}
section:last-of-type {{ border-bottom: none; }}
h2 {{
  margin: 0 0 5px; color: var(--dim); font-size: 10px; font-weight: 600;
  letter-spacing: 1.1px; text-transform: uppercase;
}}
.path-row {{ display: flex; gap: 8px; align-items: center; }}
input[type="text"] {{
  flex: 1; width: 100%; background: var(--bg); color: var(--text);
  border: 1px solid var(--line); border-radius: var(--radius);
  padding: 6px 9px; font: inherit; font-size: 12.5px;
}}
input[type="text"]:focus {{ outline: none; border-color: var(--text); }}
button {{
  font: inherit; color: var(--text); background: transparent; cursor: pointer;
  border: 1px solid var(--line); border-radius: var(--radius); padding: 6px 12px;
  transition: border-color .12s, background .12s, color .12s;
}}
button:hover {{ border-color: var(--text); background: var(--hover); }}
button:disabled {{ color: var(--faint); border-color: var(--line2); background: transparent; cursor: default; }}
/* The application's "primary" is an ink underline, not a coloured fill (see .studio-btn.primary).
   The brown accent stays for node types, where the front end actually uses it. */
button.primary {{
  background: var(--hover); border-color: var(--line); color: var(--text);
  font-weight: 600; box-shadow: inset 0 -2px 0 var(--text);
}}
button.primary:hover {{ background: var(--hover); border-color: var(--text); }}
button.primary:disabled {{
  background: transparent; border-color: var(--line2); color: var(--faint); box-shadow: none;
}}
.hint {{ color: var(--dim); font-size: 11px; margin: 4px 0 0; }}
.presets {{ display: flex; gap: 22px; flex-wrap: wrap; }}
label.choice {{ display: inline-flex; align-items: center; gap: 7px; cursor: pointer; font-size: 12.5px; }}
input[type="radio"], input[type="checkbox"] {{
  appearance: none; -webkit-appearance: none; margin: 0; flex: none;
  width: 14px; height: 14px; border: 1px solid var(--faint); background: var(--bg);
  border-radius: var(--radius); cursor: pointer; position: relative;
}}
input[type="radio"] {{ border-radius: 50%; }}
input[type="radio"]:checked {{ border: 4px solid var(--text); }}
input[type="checkbox"]:checked {{
  background: var(--text); border-color: var(--text);
  background-image: var(--check); background-size: 11px 11px; background-position: center;
  background-repeat: no-repeat;
}}
input[type="checkbox"]:disabled {{ border-color: var(--line2); background-color: var(--line2); }}
.components {{ display: flex; flex-direction: column; gap: 3px; margin-top: 2px; }}
.component {{ display: flex; align-items: baseline; gap: 9px; font-size: 12.5px; line-height: 1.4; }}
.component .name {{ flex: 1; }}
.component .meta {{ color: var(--dim); font-size: 11px; white-space: nowrap; }}
.component.manual .name {{ color: var(--dim); }}
.notes {{ color: var(--dim); font-size: 11px; margin: 7px 0 0; }}
.notes p {{ margin: 2px 0; }}
.total {{ margin: 7px 0 0; color: var(--dim); font-size: 12px; }}
.progress {{ height: 3px; background: var(--line2); margin: 6px 0 4px; overflow: hidden; }}
.progress > span {{ display: block; height: 100%; width: 0; background: var(--text); transition: width .25s; }}
.status {{ color: var(--dim); font-size: 11px; min-height: 16px; }}
.status:empty {{ min-height: 0; }}
/* The run pane owns the leftover height: every server log line is rendered (the old four-line
   slice plus a 54 px clip cut off Node/CatBus), and the pane scrolls internally only when the
   lines genuinely exceed one screen. The page itself stays one screen, no page scrollbar. */
section.run {{ flex: 1; min-height: 0; display: flex; flex-direction: column; border-bottom: none; }}
section.run .log {{ flex: 1; min-height: 0; max-height: none; overflow-y: auto; }}
.log {{
  margin-top: 5px; max-height: 54px; overflow: hidden; background: var(--paper);
  border: 1px solid var(--line2); padding: 5px 8px; color: var(--dim);
  font-family: "Cascadia Mono", Consolas, monospace; font-size: 10.5px; white-space: pre-wrap;
}}
.log:empty {{ display: none; }}
footer.actions {{
  display: flex; align-items: center; gap: 9px; flex: none;
  padding: 11px 0 14px; border-top: 1px solid var(--line);
}}
footer.actions .spacer {{ flex: 1; }}
.notice {{
  margin-top: 8px; padding: 7px 10px; border: 1px solid var(--line);
  border-left: 2px solid var(--text); background: var(--paper); font-size: 12px;
}}
.notice[hidden] {{ display: none; }}
.overlay {{
  position: fixed; inset: 0; background: rgba(26, 26, 26, 0.28);
  display: flex; align-items: center; justify-content: center; padding: 24px;
}}
.overlay[hidden] {{ display: none; }}
.dialog {{
  width: min(740px, 100%); max-height: 82vh; display: flex; flex-direction: column;
  background: var(--bg); border: 1px solid var(--line); border-radius: var(--radius);
  box-shadow: 0 18px 48px rgba(0, 0, 0, 0.16); padding: 22px;
}}
.dialog h3 {{ margin: 0 0 10px; font-size: 18px; font-weight: 600; }}
.dialog .rows {{ overflow: auto; margin-bottom: 14px; }}
.row {{ display: flex; gap: 10px; padding: 5px 0; border-bottom: 1px solid var(--line2); }}
.row:last-child {{ border-bottom: none; }}
.row .state {{ flex: 0 0 92px; color: var(--dim); font-size: 11px; }}
.row .state.ok {{ color: var(--ok); }}
.row .state.degraded {{ color: var(--warn); }}
.row .state.missing {{ color: var(--err); }}
.row .text {{ flex: 1; font-size: 12.5px; }}
.dialog .buttons {{ display: flex; gap: 9px; align-items: center; }}
.dialog .buttons .spacer {{ flex: 1; }}
/* A窗口 smaller than this design cannot hold the whole form; let it scroll rather than clip the
   action row, and drop the least important prose first. */
@media (max-height: 620px), (max-width: 700px) {{
  body {{ overflow: auto; }}
  .page {{ height: auto; min-height: 100%; padding: 0 18px; }}
  .scroll {{ overflow: visible; }}
  .notes {{ display: none; }}
  .component {{ align-items: flex-start; flex-direction: column; gap: 1px; }}
}}
"""
