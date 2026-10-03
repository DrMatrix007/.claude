import ctypes
import glob
import os
import subprocess
import time
from ctypes import wintypes

import win32com.client
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("watch-mcp")

LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

WM_COMMAND = 0x0111
MF_BYPOSITION = 0x400
ADB_CONNECTION_COMMANDS = {"start": 6033, "release": 6034}

_UNSAFE_CHARS = set(';&|<>$`\n\r')

user32 = ctypes.windll.user32
user32.GetMenu.restype = wintypes.HMENU
user32.GetSubMenu.restype = wintypes.HMENU
user32.GetMenuItemID.restype = wintypes.UINT


def _check_safe(value: str, label: str) -> None:
    if not value or any(c in _UNSAFE_CHARS for c in value):
        raise ValueError(f"invalid {label}: {value!r}")


def _sdk_dir() -> str:
    appdata = os.environ["APPDATA"]
    cfg_path = os.path.join(appdata, "Garmin", "ConnectIQ", "current-sdk.cfg")
    if os.path.isfile(cfg_path):
        with open(cfg_path) as f:
            candidate = f.read().strip()
        if os.path.isdir(candidate):
            return candidate
    sdks_dir = os.path.join(appdata, "Garmin", "ConnectIQ", "Sdks")
    candidates = sorted(glob.glob(os.path.join(sdks_dir, "connectiq-sdk-win-*")))
    if not candidates:
        raise FileNotFoundError(f"no Connect IQ SDK found under {sdks_dir}")
    return candidates[-1]


def _developer_key() -> str:
    return os.path.join(os.environ["APPDATA"], "Garmin", "ConnectIQ", "developer_key.der")


def _simulator_running() -> bool:
    result = subprocess.run(["tasklist"], capture_output=True, text=True)
    return "simulator.exe" in result.stdout


def _find_window_for_process(process_name: str) -> int | None:
    result = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {process_name}", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
    )
    target_pid = None
    for line in result.stdout.strip().splitlines():
        fields = line.strip('"').split('","')
        if len(fields) >= 2:
            target_pid = int(fields[1])
            break
    if target_pid is None:
        return None

    found = {}

    def callback(hwnd, _lparam):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == target_pid and user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
            found["hwnd"] = hwnd
            return False
        return True

    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(callback)
    user32.EnumWindows(enum_proc, 0)
    return found.get("hwnd")


def _find_window_by_title(title_contains: str) -> int | None:
    found = {}

    def callback(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if user32.IsWindowVisible(hwnd) and length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if title_contains in buf.value:
                found["hwnd"] = hwnd
                return False
        return True

    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(callback)
    user32.EnumWindows(enum_proc, 0)
    return found.get("hwnd")


def _strip_mnemonic(text: str) -> str:
    return text.replace("&", "")


_SCREENSHOT_SCRIPT = """
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class Win32Capture {
    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
    [DllImport("user32.dll")]
    public static extern bool PrintWindow(IntPtr hwnd, IntPtr hdcBlt, uint nFlags);
    public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
}
"@
Add-Type -AssemblyName System.Drawing
$hwnd = [IntPtr]__HWND__
$rect = New-Object Win32Capture+RECT
[Win32Capture]::GetWindowRect($hwnd, [ref]$rect) | Out-Null
$width = $rect.Right - $rect.Left
$height = $rect.Bottom - $rect.Top
$bitmap = New-Object System.Drawing.Bitmap $width, $height
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$hdc = $graphics.GetHdc()
[Win32Capture]::PrintWindow($hwnd, $hdc, 0) | Out-Null
$graphics.ReleaseHdc($hdc)
$bitmap.Save('__PATH__', [System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose()
$bitmap.Dispose()
"""


@mcp.tool()
def build(project_dir: str, device: str, out_name: str = "App", release: bool = False) -> str:
    _check_safe(device, "device")
    _check_safe(out_name, "out_name")
    sdk = _sdk_dir()
    monkeyc = os.path.join(sdk, "bin", "monkeyc.bat")
    out_path = os.path.join("bin", f"{out_name}.prg")
    args = [monkeyc, "-f", "monkey.jungle", "-o", out_path, "-y", _developer_key(), "-d", device, "-w"]
    if release:
        args.append("-r")
    result = subprocess.run(args, cwd=project_dir, capture_output=True, text=True)
    output = result.stdout + result.stderr
    status = "BUILD SUCCESSFUL" if "BUILD SUCCESSFUL" in output else "BUILD FAILED"
    return f"{status}\n{output}"


@mcp.tool()
def is_simulator_running() -> bool:
    return _simulator_running()


@mcp.tool()
def start_simulator() -> str:
    if _simulator_running():
        return "simulator already running"
    sdk = _sdk_dir()
    connectiq = os.path.join(sdk, "bin", "connectiq.bat")
    subprocess.Popen([connectiq], creationflags=subprocess.DETACHED_PROCESS, close_fds=True)
    return "simulator starting"


@mcp.tool()
def stop_simulator() -> str:
    result = subprocess.run(["taskkill", "/IM", "simulator.exe", "/F"], capture_output=True, text=True)
    return result.stdout + result.stderr


@mcp.tool()
def run_in_simulator(project_dir: str, prg_relative_path: str, device: str) -> str:
    _check_safe(device, "device")
    _check_safe(prg_relative_path, "prg_relative_path")
    sdk = _sdk_dir()
    monkeydo = os.path.join(sdk, "bin", "monkeydo.bat")
    prg_path = os.path.join(project_dir, prg_relative_path)
    log_path = os.path.join(LOGS_DIR, f"monkeydo_{int(time.time())}.log")
    log_file = open(log_path, "w")
    proc = subprocess.Popen(
        [monkeydo, prg_path, device],
        cwd=project_dir,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.DETACHED_PROCESS,
    )
    log_file.close()
    return f"pid={proc.pid} log={log_path}"


@mcp.tool()
def read_log(log_path: str, tail_lines: int = 50) -> str:
    with open(log_path) as f:
        lines = f.readlines()
    return "".join(lines[-tail_lines:])


@mcp.tool()
def adb_connection(action: str) -> str:
    if action not in ADB_CONNECTION_COMMANDS:
        raise ValueError(f"action must be one of {sorted(ADB_CONNECTION_COMMANDS)}")
    hwnd = _find_window_for_process("simulator.exe")
    if hwnd is None:
        return "simulator window not found"
    command_id = ADB_CONNECTION_COMMANDS[action]
    user32.PostMessageW(hwnd, WM_COMMAND, command_id, 0)
    return f"posted {action} ({command_id}) to simulator window"


@mcp.tool()
def click_menu_item(menu_path: str) -> str:
    hwnd = _find_window_for_process("simulator.exe")
    if hwnd is None:
        return "simulator window not found"
    segments = menu_path.split(">")
    current_menu = user32.GetMenu(hwnd)
    resolved_id = None
    for i, segment in enumerate(segments):
        count = user32.GetMenuItemCount(current_menu)
        position = None
        siblings = []
        for pos in range(count):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetMenuStringW(current_menu, pos, buf, 256, MF_BYPOSITION)
            text = _strip_mnemonic(buf.value)
            siblings.append(text)
            if text == segment:
                position = pos
                break
        if position is None:
            raise ValueError(
                f"menu path {menu_path!r}: segment {segment!r} not found; available here: {siblings}"
            )
        if i == len(segments) - 1:
            submenu = user32.GetSubMenu(current_menu, position)
            if submenu:
                raise ValueError(
                    f"menu path {menu_path!r}: segment {segment!r} is a submenu, not a clickable command"
                )
            resolved_id = user32.GetMenuItemID(current_menu, position)
        else:
            submenu = user32.GetSubMenu(current_menu, position)
            if not submenu:
                raise ValueError(
                    f"menu path {menu_path!r}: segment {segment!r} has no submenu to descend into"
                )
            current_menu = submenu
    user32.PostMessageW(hwnd, WM_COMMAND, resolved_id, 0)
    return f"posted {menu_path!r} (id={resolved_id}) to simulator window"


@mcp.tool()
def list_window_children(title_contains: str) -> str:
    hwnd = _find_window_by_title(title_contains)
    if hwnd is None:
        return f"no window found with title containing {title_contains!r}"
    children = []

    def callback(child_hwnd, _lparam):
        class_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(child_hwnd, class_buf, 256)
        length = user32.GetWindowTextLengthW(child_hwnd)
        text_buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(child_hwnd, text_buf, length + 1)
        visible = bool(user32.IsWindowVisible(child_hwnd))
        children.append(
            f"hwnd={int(child_hwnd)} class={class_buf.value!r} text={text_buf.value!r} visible={visible}"
        )
        return True

    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(callback)
    user32.EnumChildWindows(hwnd, enum_proc, 0)
    if not children:
        return f"window containing {title_contains!r} has no child windows"
    return "\n".join(children)


@mcp.tool()
def get_window_rect(title_contains: str) -> str:
    hwnd = _find_window_by_title(title_contains)
    if hwnd is None:
        return f"no window found with title containing {title_contains!r}"
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    return f"{rect.left},{rect.top},{rect.right},{rect.bottom} size={width}x{height}"


@mcp.tool()
def screenshot(out_path: str) -> str:
    if not out_path.lower().endswith(".png"):
        raise ValueError("out_path must end with .png")
    hwnd = _find_window_for_process("simulator.exe")
    if hwnd is None:
        return "simulator window not found"
    script = _SCREENSHOT_SCRIPT.replace("__HWND__", str(int(hwnd))).replace("__PATH__", out_path.replace("'", "''"))
    result = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True)
    if result.returncode != 0:
        return f"screenshot failed: {result.stderr}"
    return f"saved screenshot to {out_path}"


def _find_device_folder(shell, device_name_hint: str, path_parts: list[str]):
    this_pc = shell.Namespace(0x11)
    devices = [item for item in this_pc.Items() if device_name_hint.lower() in item.Name.lower()]
    if not devices:
        names = [item.Name for item in this_pc.Items()]
        raise ValueError(f"no device matching {device_name_hint!r} found under This PC; available devices: {names}")
    current = devices[0]
    for part in path_parts:
        items = list(current.GetFolder().Items())
        matches = [item for item in items if item.Name == part]
        if not matches:
            siblings = [item.Name for item in items]
            raise ValueError(
                f"path segment {part!r} not found under device {device_name_hint!r}; available here: {siblings}"
            )
        current = matches[0]
    return current


@mcp.tool()
def list_portable_devices() -> str:
    shell = win32com.client.Dispatch("Shell.Application")
    names = [item.Name for item in shell.Namespace(0x11).Items()]
    if not names:
        return "no portable devices found under This PC"
    return "\n".join(names)


@mcp.tool()
def deploy_to_device(prg_path: str, device_name_hint: str) -> str:
    if not os.path.isfile(prg_path):
        raise FileNotFoundError(prg_path)
    if not prg_path.lower().endswith(".prg"):
        raise ValueError(f"prg_path must end with .prg: {prg_path!r}")
    shell = win32com.client.Dispatch("Shell.Application")
    apps_item = _find_device_folder(shell, device_name_hint, ["Internal Storage", "GARMIN", "Apps"])
    apps_folder = apps_item.GetFolder()
    apps_folder.CopyHere(prg_path, 0x14)
    time.sleep(1.5)
    basename = os.path.basename(prg_path)
    names = [item.Name for item in apps_folder.Items()]
    presence = "found" if basename in names else "NOT found"
    listing = "\n".join(names)
    return (
        f"copy requested; {basename} {presence} in GARMIN\\Apps after copy\n"
        f"current Apps listing:\n{listing}\n"
        "the watch won't install this until the USB session ends - unplug/replug the cable "
        "or exit the Connected screen on the watch"
    )


@mcp.tool()
def list_device_path(device_name_hint: str, relative_path: str) -> str:
    parts = [p for p in relative_path.replace("/", "\\").split("\\") if p]
    shell = win32com.client.Dispatch("Shell.Application")
    item = _find_device_folder(shell, device_name_hint, ["Internal Storage"] + parts)
    if not item.IsFolder:
        return f"{relative_path} is a file, not a folder (size={item.Size})"
    lines = [f"{child.Name} ({child.Size})" for child in item.GetFolder().Items()]
    if not lines:
        return f"{relative_path} is empty"
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
