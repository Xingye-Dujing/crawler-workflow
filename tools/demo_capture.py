"""Screen-capture command for demo recordings, one table for all three platforms.

A recording targeted at a WINDOW is preferred over a whole-desktop grab: the desktop grab caught
the OpenChamber host instead of the browser page the demo was running in. Callers pass a window
title (or an hwnd) and the platform table turns it into an ffmpeg input; without one the whole
desktop is the honest fallback and the caller should say so in its log.

Windows: gdigrab `title=…` / `hwnd=…`. Linux: x11grab with `-window_id`. macOS: avfoundation's
screen device (window targeting is not exposed by the device). A host with no screen source refuses
by name rather than producing an empty file.
"""

import os
import platform
import shutil


class CaptureUnavailableError(RuntimeError):
    """No screen source, no window match, or no ffmpeg on this host."""


def ffmpeg_binary() -> str:
    override = os.environ.get('CIXI_FFMPEG', '').strip()
    found = override or shutil.which('ffmpeg') or ''
    if not found or not os.path.isfile(found):
        raise CaptureUnavailableError('ffmpeg not found; set CIXI_FFMPEG to the executable path')
    return found


def screen_input(fps: int, title: str = '', hwnd: str = '') -> list[str]:
    """The OS-specific input half of the ffmpeg command."""
    system = platform.system().lower()
    if system == 'windows':
        if hwnd:
            return ['-f', 'gdigrab', '-framerate', str(fps), '-i', f'hwnd={hwnd}']
        if title:
            return ['-f', 'gdigrab', '-framerate', str(fps), '-i', f'title={title}']
        return ['-f', 'gdigrab', '-framerate', str(fps), '-i', 'desktop']
    if system == 'linux':
        display = os.environ.get('DISPLAY', '').strip()
        if not display:
            raise CaptureUnavailableError('DISPLAY is not set; an X server is required for x11grab')
        command = ['-f', 'x11grab', '-framerate', str(fps), '-i', display]
        if hwnd:  # x11grab calls a window id a window_id
            command += ['-window_id', hwnd]
        return command
    if system == 'darwin':
        device = os.environ.get('CIXI_CAPTURE_DEVICE', '0').strip()
        return ['-f', 'avfoundation', '-framerate', str(fps), '-i', device]
    raise CaptureUnavailableError(f'no screen-capture recipe for platform {system!r}')


def find_window(substring: str = '') -> tuple[str, str]:
    """``(title, hwnd)`` of the first visible window whose title contains ``substring``.

    Only Windows exposes a usable title/HWND enumeration through the standard library; other
    systems fall back to a desktop capture, which the caller must label as such. The title is
    returned EXACTLY as the window reports it, so ffmpeg's `title=` matcher gets a literal.
    """
    if not substring or platform.system().lower() != 'windows':
        return '', ''
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    found: list[tuple[str, str]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(handle, _unused):
        if not user32.IsWindowVisible(handle):
            return True
        length = user32.GetWindowTextLengthW(handle)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(handle, buffer, length + 1)
        title = buffer.value
        if substring.lower() in title.lower():
            found.append((title, hex(handle)))
        return len(found) == 0

    user32.EnumWindows(visit, 0)
    return found[0] if found else ('', '')


def focus_window(hwnd: str, *, fullscreen: bool = False) -> None:
    """Foreground + MAXIMIZE the browser, optionally toggling F11 fullscreen.

    A background or small browser window answers gdigrab with a black frame or a narrow strip of
    the page. The recording must show the browser at its real desktop size, so focusing and sizing
    are part of the capture contract rather than a cosmetic extra.
    """
    if not hwnd or platform.system().lower() != 'windows':
        return
    import ctypes

    handle = int(hwnd, 16)
    user32 = ctypes.windll.user32
    user32.ShowWindow(handle, 9)  # SW_RESTORE first, then maximize
    user32.ShowWindow(handle, 3)  # SW_MAXIMIZE
    user32.SetForegroundWindow(handle)
    if fullscreen:
        user32.keybd_event(0x7A, 0, 0, 0)  # VK_F11 down
        user32.keybd_event(0x7A, 0, 2, 0)  # key up


def capture_command(output: str, fps: int = 12, width: int = 0, title: str = '', hwnd: str = '') -> list[str]:
    """A full ffmpeg command; `width=0` keeps the browser window's native size."""
    command = [ffmpeg_binary(), *screen_input(fps, title=title, hwnd=hwnd)]
    if width > 0:
        command += ['-vf', f'scale={width}:-1']
    command += ['-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-y', output]
    return command
