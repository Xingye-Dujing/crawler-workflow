"""The desktop shell: a Windows system-tray icon and system notifications on both desktops.

The window may be minimised for hours while a crawl or a scheduled task runs, so the only way a
finish can reach the user is the operating system's own channel. This module owns that channel:

* **Windows** gets a tray icon (显示主窗口 / 打开数据目录 / 退出) and posts notifications through the
  same icon (``Shell_NotifyIcon``'s balloon, which Windows 10/11 surface as an app notification).
  ``pystray`` is imported lazily, so a source run, a Linux CI job and the macOS build never need it.
* **macOS** has no tray by convention — the Dock icon is always there — so it only posts
  notifications, through this process's own ``NSUserNotification`` (the bundle's name is the sender)
  with ``osascript`` as the fallback for a host without PyObjC.

Every entry point returns a sentence instead of raising: a tray that cannot be created is a lost
convenience, never a lost program. The notification decision itself lives in ``services.desktop``;
this file only delivers.
"""

from __future__ import annotations

import contextlib
import importlib
import subprocess
import sys
import threading
from pathlib import Path

from i18n import t


def _is_windows(platform: str) -> bool:
    return platform.startswith('win')


def _is_macos(platform: str) -> bool:
    return platform == 'darwin'


def open_folder(path: str | Path) -> None:
    """Show ``path`` in the platform's file manager (the tray's 打开数据目录)."""
    target = str(path)
    if _is_windows(sys.platform):
        starter = getattr(__import__('os'), 'startfile', None)
        if starter is not None:
            with contextlib.suppress(OSError, ValueError):
                starter(target)
        return
    command = ['open', target] if _is_macos(sys.platform) else ['xdg-open', target]
    with contextlib.suppress(OSError, ValueError):
        child = subprocess.Popen(command)  # fixed argv, never a shell
        threading.Thread(target=child.wait, name='cixi-open-folder', daemon=True).start()


def applescript_string(text: str) -> str:
    """One AppleScript string literal: backslash first, then the quote it introduces."""
    return '"' + str(text).replace('\\', '\\\\').replace('"', '\\"') + '"'


#: ``uxtheme``'s undocumented dark-mode entry points (Windows 10 1903+). A Win32 popup menu is drawn
#: by the system and ignores the application's palette, so these are the only way to make the tray
#: menu match a dark taskbar. Older builds do not export the ordinals; the call then raises and is
#: skipped, and the consequence is the system's own light menu — never a broken tray.
_UXTHEME_SET_PREFERRED_APP_MODE = 135
_UXTHEME_FLUSH_MENU_THEMES = 136
_FORCE_DARK = 2


def windows_prefers_dark() -> bool:
    """Whether Windows' app mode is dark (``AppsUseLightTheme`` = 0)."""
    try:
        import winreg
    except ImportError:  # not Windows
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize',
        ) as key:
            return int(winreg.QueryValueEx(key, 'AppsUseLightTheme')[0]) == 0
    except (OSError, ValueError, TypeError):
        return False


def prefer_dark_menus(platform: str | None = None) -> bool:
    """Ask uxtheme to draw this process's classic menus dark when Windows is dark.

    The opt-in is process-wide, which is the point: a message box raised later in the same launch
    should match the taskbar too. ``True`` only when the ordinals were found and called.
    """
    if not _is_windows(platform or sys.platform) or not windows_prefers_dark():
        return False
    try:
        import ctypes

        uxtheme = ctypes.WinDLL('uxtheme')
        uxtheme[_UXTHEME_SET_PREFERRED_APP_MODE](_FORCE_DARK)
        uxtheme[_UXTHEME_FLUSH_MENU_THEMES]()
    except (AttributeError, OSError, ValueError):
        return False
    return True


def _osascript(script: str) -> None:
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(['osascript', '-e', script], timeout=10, check=False, capture_output=True)


class DesktopShell:
    """One tray icon / notification sender for this launch."""

    def __init__(
        self,
        *,
        title: str,
        icon_path: str | Path | None = None,
        on_show=None,
        on_quit=None,
        on_open_data=None,
        platform: str | None = None,
    ) -> None:
        self.title = str(title)
        self.icon_path = Path(icon_path) if icon_path else None
        self._on_show = on_show
        self._on_quit = on_quit
        self._on_open_data = on_open_data
        self._platform = platform or sys.platform
        self._icon = None
        self._thread: threading.Thread | None = None
        #: ``tray`` (Windows), ``notifications`` (macOS) or ``''`` when this host has neither.
        self.mode = ''
        #: Why the tray could not be created, when it could not; '' on success.
        self.error = ''

    # ── start / stop ─────────────────────────────────────────────────────

    def start(self) -> str:
        """Create the shell if this platform has one; return the failure sentence or ``''``."""
        if _is_windows(self._platform):
            return self._start_tray()
        if _is_macos(self._platform):
            self.mode = 'notifications'
            return ''
        self.mode = ''
        self.error = f'这个平台没有桌面托盘：{self._platform}'
        return self.error

    def _start_tray(self) -> str:
        # Before the icon exists: the classic menu must be drawn by uxtheme in the system's mode,
        # otherwise it stays light over a dark taskbar (pystray does not opt in).
        prefer_dark_menus(self._platform)
        try:
            import pystray
            from PIL import Image
        except Exception as exc:  # a missing extra, not a broken app
            self.error = f'托盘组件没有加载成功：{exc}'
            self.mode = ''
            return self.error
        try:
            image = self._icon_image(Image)
            menu = pystray.Menu(*self._menu_items(pystray))
            self._icon = pystray.Icon(self.title, image, self.title, menu)
        except Exception as exc:
            self.error = f'托盘图标没能创建：{exc}'
            self.mode = ''
            return self.error
        # ``Icon.run`` owns its own Win32 message loop and must not run on the GUI thread.
        self._thread = threading.Thread(target=self._run_icon, name='cixi-tray', daemon=True)
        self._thread.start()
        self.mode = 'tray'
        return ''

    def _run_icon(self) -> None:
        icon = self._icon
        if icon is None:
            return
        try:
            icon.run()
        except Exception as exc:
            # The window is already up; a tray that died later is printed, never raised into a
            # thread nobody joins.
            self.error = f'托盘停止工作：{exc}'
            print(self.error, flush=True)

    def _menu_items(self, pystray) -> list:
        items = [pystray.MenuItem(t('desktop.show'), self._show, default=True)]
        if self._on_open_data is not None:
            items.append(pystray.MenuItem(t('desktop.openData'), self._open_data))
        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem(t('desktop.quit'), self._quit))
        return items

    def _icon_image(self, image_module):
        if self.icon_path is not None:
            try:
                image = image_module.open(self.icon_path)
            except Exception:
                image = None
            if image is not None:
                image = image.convert('RGBA')
                image.thumbnail((64, 64))
                return image
        # No bundled art (a stripped install): a bare square reads as a broken image, so draw a
        # placeholder instead of failing.
        image = image_module.new('RGBA', (64, 64), (0, 0, 0, 0))
        try:
            from PIL import ImageDraw

            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((4, 4, 60, 60), radius=12, fill=(26, 26, 26, 255))
            draw.text((22, 18), '采', fill=(255, 255, 255, 255))
        except Exception:
            pass
        return image

    def stop(self) -> None:
        icon, self._icon = self._icon, None
        if icon is None:
            return
        with contextlib.suppress(Exception):
            icon.stop()

    # ── the three menu answers ───────────────────────────────────────────

    def _show(self, *_args) -> None:
        if self._on_show is not None:
            self._on_show()

    def _open_data(self, *_args) -> None:
        if self._on_open_data is not None:
            self._on_open_data()

    def _quit(self, *_args) -> None:
        self.stop()
        if self._on_quit is not None:
            self._on_quit()

    # ── delivery ─────────────────────────────────────────────────────────

    def notify(self, title: str, message: str = '') -> None:
        """Deliver one notification; a failure is a no-op, never an exception."""
        if _is_macos(self._platform):
            self._notify_macos(title, message)
            return
        icon = self._icon
        if icon is None:
            return
        with contextlib.suppress(Exception):
            # pystray's signature is (message, title).
            icon.notify(str(message), str(title))

    def _notify_macos(self, title: str, message: str) -> None:
        try:
            # PyObjC exists only on macOS, and this module is linted on Windows/Linux too; a static
            # import would make the lint tier report a missing module on the two platforms that can
            # never have it. The framework is the real sender, so the notification carries the app's
            # own name instead of "Script Editor".
            foundation = importlib.import_module('Foundation')
            note = foundation.NSUserNotification.alloc().init()
            note.setTitle_(str(title))
            note.setInformativeText_(str(message))
            foundation.NSUserNotificationCenter.defaultUserNotificationCenter().deliverNotification_(note)
            return
        except Exception:
            pass
        # PyObjC missing or the framework refused: AppleScript still reaches Notification Center.
        script = f'display notification {applescript_string(message)} with title {applescript_string(title)}'
        _osascript(script)
