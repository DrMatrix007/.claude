import os
import re
import shutil
import subprocess

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("phone-debugger")

IDENT_RE = re.compile(r"^[A-Za-z0-9_./:-]+$")
JDK_HOME = r"C:\Program Files\Java\jdk-21.0.12"
FLUTTER_FALLBACK = r"C:\Users\ofrih\Applications\Flutter\flutter\bin\flutter.bat"


def adb_path() -> str:
    return os.path.join(os.environ["LOCALAPPDATA"], "Android", "Sdk", "platform-tools", "adb.exe")


def flutter_path() -> str:
    return shutil.which("flutter") or FLUTTER_FALLBACK


def run(args: list[str], cwd: str | None = None, env: dict | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        return f"exit {result.returncode}\n{result.stdout}{result.stderr}"
    return result.stdout + result.stderr


def matching_lines(text: str, contains: str | None) -> list[str]:
    lines = text.splitlines()
    if contains is None:
        return lines
    needle = contains.lower()
    return [line for line in lines if needle in line.lower()]


@mcp.tool()
def adb_devices() -> str:
    return run([adb_path(), "devices", "-l"])


@mcp.tool()
def logcat_tail(lines: int = 200, contains: str | None = None) -> str:
    output = run([adb_path(), "logcat", "-d"])
    return "\n".join(matching_lines(output, contains)[-lines:])


@mcp.tool()
def logcat_clear() -> str:
    return run([adb_path(), "logcat", "-c"])


@mcp.tool()
def list_packages(contains: str | None = None) -> str:
    output = run([adb_path(), "shell", "pm", "list", "packages"])
    return "\n".join(matching_lines(output, contains))


@mcp.tool()
def pidof(package: str) -> str:
    if not IDENT_RE.match(package):
        return f"invalid package: {package}"
    return run([adb_path(), "shell", "pidof", package])


@mcp.tool()
def force_stop(package: str) -> str:
    if not IDENT_RE.match(package):
        return f"invalid package: {package}"
    return run([adb_path(), "shell", "am", "force-stop", package])


@mcp.tool()
def start_activity(component: str) -> str:
    if not IDENT_RE.match(component):
        return f"invalid component: {component}"
    return run([adb_path(), "shell", "am", "start", "-W", "-n", component])


@mcp.tool()
def install_apk(path: str) -> str:
    if not path.lower().endswith(".apk"):
        return f"path must end in .apk: {path}"
    if not os.path.isfile(path):
        return f"file not found: {path}"
    return run([adb_path(), "install", "-r", path])


@mcp.tool()
def screenshot(out_path: str) -> str:
    if not out_path.lower().endswith(".png"):
        return f"out_path must end in .png: {out_path}"
    result = subprocess.run([adb_path(), "exec-out", "screencap", "-p"], capture_output=True)
    if result.returncode != 0:
        return f"exit {result.returncode}\n{result.stderr.decode(errors='replace')}"
    with open(out_path, "wb") as f:
        f.write(result.stdout)
    return out_path


@mcp.tool()
def port_forward(local_port: int, device_port: int) -> str:
    return run([adb_path(), "forward", f"tcp:{local_port}", f"tcp:{device_port}"])


@mcp.tool()
def port_reverse(device_port: int, local_port: int) -> str:
    return run([adb_path(), "reverse", f"tcp:{device_port}", f"tcp:{local_port}"])


@mcp.tool()
def flutter_analyze(project_dir: str) -> str:
    return run([flutter_path(), "analyze"], cwd=project_dir)


@mcp.tool()
def flutter_build_apk(project_dir: str, mode: str = "debug") -> str:
    if mode not in {"debug", "release", "profile"}:
        return f"invalid mode: {mode}"
    env = os.environ.copy()
    env["JAVA_HOME"] = JDK_HOME
    env["PATH"] = os.path.join(JDK_HOME, "bin") + os.pathsep + env["PATH"]
    return run([flutter_path(), "build", "apk", f"--{mode}"], cwd=project_dir, env=env)


if __name__ == "__main__":
    mcp.run()
