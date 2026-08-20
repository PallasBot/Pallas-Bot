"""跨平台进程探测、后台启动与停止；解析 bash 供仍依赖 shell 脚本的路径使用。"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence  # noqa: TC003
from pathlib import Path


def is_windows() -> bool:
    return sys.platform == "win32"


# 从 Bot venv 启动 AI 子进程时需剥掉，否则 uv 会警告 VIRTUAL_ENV 与项目 .venv 不一致
_NESTED_PROJECT_ENV_DROP = (
    "VIRTUAL_ENV",
    "VIRTUAL_ENV_PROMPT",
    "UV_PROJECT",
    "UV_PROJECT_ENVIRONMENT",
    "PYTHONHOME",
)


def env_for_nested_project(
    base: Mapping[str, str] | None = None,
    *,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """为「另一份 uv/venv 项目」（如 AI Runtime）准备子进程环境。

    Bot 进程常带 ``VIRTUAL_ENV=…/Pallas-Bot/.venv``；在 AI 仓跑 ``uv run`` 时会刷
    「does not match the project environment path」警告。剥掉相关键后由 AI 仓自有 ``.venv`` 接管。
    """
    out = dict(os.environ if base is None else base)
    for key in _NESTED_PROJECT_ENV_DROP:
        out.pop(key, None)
    if extra:
        out.update({str(k): str(v) for k, v in extra.items()})
    return out


def _linux_pid_state(pid: int) -> str | None:
    """读取 ``/proc/<pid>/stat`` 的进程状态字符；非 Linux 或不可读返回 None。"""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return raw.split(") ", 1)[1].split()[0]
    except IndexError:
        return None


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if is_windows():
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    # 僵尸进程是已退出但未被 wait 回收的残留，os.kill 仍会命中，须视为已死，
    # 否则 stop_pid 会一直等到超时（如 uv 包装进程退出后残留为 Z）。
    return _linux_pid_state(pid) != "Z"


def _windows_pid_alive(pid: int) -> bool:
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    process_query_limited_information = 0x1000
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if handle:
        kernel32.CloseHandle(handle)
        return True
    return False


def read_pid_file(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw.isdigit():
        return None
    return int(raw)


def write_pid_file(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{pid}\n", encoding="utf-8")


def clear_pid_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def uv_run_python_cmd(*script_args: str) -> list[str]:
    """``uv run --no-sync python …``，与启停脚本保持一致。"""
    return ["uv", "run", "--no-sync", "python", *script_args]


def spawn_detached(
    cmd: Sequence[str],
    *,
    cwd: Path | str,
    env: Mapping[str, str] | None = None,
    log_path: Path | None = None,
) -> int:
    """后台启动进程，返回子进程 pid；可选将 stdout/stderr 追加到日志。"""
    cwd_s = str(cwd)
    popen_env = dict(os.environ)
    if env:
        popen_env.update({str(k): str(v) for k, v in env.items()})

    stdout = subprocess.DEVNULL
    stderr = subprocess.DEVNULL
    log_fh = None
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_fh = log_path.open("a", encoding="utf-8")
        stdout = log_fh
        stderr = subprocess.STDOUT

    creationflags = 0
    kwargs: dict = {
        "args": list(cmd),
        "cwd": cwd_s,
        "env": popen_env,
        "stdin": subprocess.DEVNULL,
        "stdout": stdout,
        "stderr": stderr,
    }
    if is_windows():
        creationflags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        kwargs["creationflags"] = creationflags
        kwargs["close_fds"] = True
    else:
        kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen(**kwargs)  # noqa: S603
    finally:
        if log_fh is not None:
            # 子进程已继承 fd，父进程可关
            try:
                log_fh.close()
            except OSError:
                pass
    return int(proc.pid)


def stop_pid(
    pid: int,
    *,
    timeout_s: float = 30.0,
    force: bool = False,
) -> None:
    """温和停止进程；超时或 force 时强制结束。

    Unix 下优先对会话组发信号（``spawn_detached`` 使用 ``start_new_session``），
    避免只杀掉 ``uv`` 父进程而留下孤儿 ``python``。
    """
    if pid <= 0 or not pid_alive(pid):
        return
    if is_windows():
        _windows_stop_pid(pid, force=force or False, timeout_s=timeout_s)
        return

    def _send(sig: int) -> None:
        try:
            os.killpg(pid, sig)
        except OSError:
            try:
                os.kill(pid, sig)
            except OSError:
                pass

    if force:
        _send(signal.SIGKILL)
        return

    _send(signal.SIGTERM)

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return
        time.sleep(0.5)
    _send(signal.SIGKILL)


def report_process_stop(name: str, pid: int, elapsed_s: float) -> None:
    """辅进程停止后经统一日志上报耗时与终止方式。"""
    forced = elapsed_s >= 14.0
    outcome = "SIGKILL 强制结束" if forced else "已停止"
    try:
        from nonebot import logger

        logger.info(
            "[ShutDown] 辅进程 [{}] 进程号 [{}] {}，耗时 [{:.1f}]s",
            name,
            pid,
            outcome,
            elapsed_s,
        )
    except Exception:
        pass


def _windows_stop_pid(pid: int, *, force: bool, timeout_s: float) -> None:
    # taskkill：先尝试无 /F，失败或 force 再强制
    flags = ["/PID", str(pid), "/T"]
    if force:
        flags.append("/F")
    try:
        subprocess.run(  # noqa: S603
            ["taskkill", *flags],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return
    if force:
        return
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return
        time.sleep(0.5)
    try:
        subprocess.run(  # noqa: S603
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


def is_wsl_system_bash(path: Path) -> bool:
    """Windows ``System32\\bash.exe`` 是 WSL 入口，不能直接吃 ``F:\\...`` 反斜杠路径。"""
    normalized = str(path).replace("/", "\\").lower()
    return normalized.endswith(("\\system32\\bash.exe", "\\system32\\bash"))


def windows_git_bash_candidates() -> list[Path]:
    return [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Git" / "bin" / "bash.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Git" / "bin" / "bash.exe",
    ]


def windows_path_to_wsl(path: Path) -> str:
    """``F:\\foo\\bar`` → ``/mnt/f/foo/bar``，供 WSL system bash 使用。"""
    text = str(path)
    if len(text) >= 2 and text[1] == ":":
        drive = text[0].lower()
        rest = text[2:].replace("\\", "/")
        if not rest.startswith("/"):
            rest = "/" + rest
        return f"/mnt/{drive}{rest}"
    return text.replace("\\", "/")


def path_for_bash(path: Path, bash: Path) -> str:
    """把路径转成指定 bash 可直接作为 argv 使用的形式。"""
    if is_windows() and is_wsl_system_bash(bash):
        return windows_path_to_wsl(path)
    return str(path)


def resolve_bash() -> Path | None:
    """解析可用 bash：Windows 优先 Git Bash，避免 PATH 上的 WSL system32 bash。"""
    if is_windows():
        for path in windows_git_bash_candidates():
            if path.is_file():
                return path
        found = shutil.which("bash")
        if found:
            cand = Path(found)
            if not is_wsl_system_bash(cand):
                return cand
            # 仅有 WSL bash 时仍返回，调用方须用 path_for_bash 转换路径
            return cand
        return None

    found = shutil.which("bash")
    if found:
        return Path(found)
    for path in (Path("/bin/bash"), Path("/usr/bin/bash")):
        if path.is_file():
            return path
    return None


def bash_script_cmd(script: Path, *args: str, bash: Path | None = None) -> list[str] | None:
    """构造 ``[bash, script, *args]``；找不到 bash 时返回 None。"""
    resolved = bash if bash is not None else resolve_bash()
    if resolved is None:
        return None
    return [str(resolved), path_for_bash(script, resolved), *args]


def bash_missing_message(*, purpose: str) -> str:
    if is_windows():
        return (
            f"{purpose} 需要 bash（当前未找到）。\n"
            "请安装 Git for Windows（推荐，bash 在 Git\\bin），"
            "勿仅依赖 C:\\Windows\\System32\\bash.exe（WSL，无法直接跑盘符路径脚本）；"
            "单进程 Bot 请直接使用：uv run pallas（已不依赖 bash）。"
        )
    return f"{purpose} 需要 bash，但系统未找到（请安装 bash 或检查 PATH）。"


def run_bash_script(
    script: Path,
    args: Sequence[str] = (),
    *,
    cwd: Path | str | None = None,
    env: Mapping[str, str] | None = None,
    purpose: str = "该操作",
) -> int:
    """用已解析的 bash 执行脚本；找不到 bash 时打印说明并返回 1。"""
    cmd = bash_script_cmd(script, *args)
    if cmd is None:
        print(bash_missing_message(purpose=purpose), file=sys.stderr)
        return 1
    if not script.is_file():
        print(f"缺少脚本 {script}", file=sys.stderr)
        return 1
    popen_env = None
    if env is not None:
        popen_env = dict(os.environ)
        popen_env.update({str(k): str(v) for k, v in env.items()})
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            cwd=str(cwd) if cwd is not None else None,
            env=popen_env,
            check=False,
        )
    except OSError as err:
        print(f"无法执行 {script}: {err}", file=sys.stderr)
        return 1
    return int(proc.returncode or 0)
