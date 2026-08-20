"""分片孤儿进程 / TCP 监听清理（跨平台，供 lifecycle 与 scripts 复用）。"""

from __future__ import annotations

import os
import re
import signal
import subprocess
from pathlib import Path

from pallas.console.cli.process_util import is_windows, stop_pid

_SCRIPT_RE = re.compile(r"bot_(hub|worker)\.py")


def repo_python_script_pids(repo_root: Path, script_name: str) -> list[int]:
    repo_root = repo_root.resolve()
    out = _repo_python_script_pids_proc(repo_root, script_name)
    if out:
        return out
    return _repo_python_script_pids_psutil(repo_root, script_name)


def _repo_python_script_pids_proc(repo_root: Path, script_name: str) -> list[int]:
    proc = Path("/proc")
    if not proc.is_dir():
        return []
    out: list[int] = []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            cwd = (entry / "cwd").resolve()
        except OSError:
            continue
        if cwd != repo_root:
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        cmdline = raw.replace(b"\0", b" ").decode("utf-8", errors="replace")
        if script_name not in cmdline or "python" not in cmdline.lower():
            continue
        if not _SCRIPT_RE.search(cmdline):
            continue
        out.append(pid)
    out.sort()
    return out


def _repo_python_script_pids_psutil(repo_root: Path, script_name: str) -> list[int]:
    try:
        import psutil
    except ImportError:
        return []
    out: list[int] = []
    for proc in psutil.process_iter(["pid", "cwd", "cmdline", "name"]):
        try:
            cwd = proc.info.get("cwd")
            if not cwd or Path(cwd).resolve() != repo_root:
                continue
            cmdline_list = proc.info.get("cmdline") or []
            cmdline = " ".join(str(x) for x in cmdline_list)
            name = (proc.info.get("name") or "").lower()
            if script_name not in cmdline:
                continue
            if "python" not in cmdline.lower() and "python" not in name:
                continue
            if not _SCRIPT_RE.search(cmdline):
                continue
            out.append(int(proc.info["pid"]))
        except (psutil.Error, OSError, TypeError, ValueError):
            continue
    out.sort()
    return out


def tcp_listen_pids(port: int) -> list[int]:
    if port <= 0:
        return []
    pids = _tcp_listen_pids_ss(port)
    if pids:
        return pids
    pids = _tcp_listen_pids_psutil(port)
    if pids:
        return pids
    if is_windows():
        return _tcp_listen_pids_netstat(port)
    return []


def _tcp_listen_pids_ss(port: int) -> list[int]:
    try:
        completed = subprocess.run(
            ["ss", "-tlnp", f"sport = :{port}"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return []
    pids: set[int] = set()
    for line in completed.stdout.splitlines():
        pids.update(int(match.group(1)) for match in re.finditer(r"pid=(\d+)", line))
    return sorted(pids)


def _tcp_listen_pids_psutil(port: int) -> list[int]:
    try:
        import psutil
    except ImportError:
        return []
    pids: set[int] = set()
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.status != psutil.CONN_LISTEN:
                continue
            if conn.laddr and int(conn.laddr.port) == int(port) and conn.pid:
                pids.add(int(conn.pid))
    except (psutil.Error, OSError, AttributeError):
        return []
    return sorted(pids)


def _tcp_listen_pids_netstat(port: int) -> list[int]:
    try:
        completed = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return []
    pids: set[int] = set()
    needle = f":{port}"
    for line in completed.stdout.splitlines():
        upper = line.upper()
        if "LISTENING" not in upper and "LISTEN" not in upper:
            continue
        if needle not in line:
            continue
        parts = line.split()
        if not parts:
            continue
        raw = parts[-1]
        if raw.isdigit():
            pids.add(int(raw))
    return sorted(pids)


def kill_script_orphans(repo_root: Path, script_name: str, *, force: bool = False) -> None:
    for pid in repo_python_script_pids(repo_root, script_name):
        stop_pid(pid, timeout_s=5.0 if force else 15.0, force=force)


def kill_port_listeners(port: int, *, force: bool = False) -> None:
    for pid in tcp_listen_pids(port):
        stop_pid(pid, timeout_s=5.0 if force else 15.0, force=force)


def guard_main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="清理分片孤儿进程或端口监听者")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--script", choices=("bot_hub.py", "bot_worker.py"))
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--signal", choices=("TERM", "KILL"), default="TERM")
    parser.add_argument("--list", action="store_true", help="仅列出 pid，不发送信号")
    args = parser.parse_args(argv)
    force = args.signal.upper() == "KILL"
    targets: list[int] = []
    if args.script:
        targets.extend(repo_python_script_pids(args.repo, args.script))
    if args.port:
        targets.extend(tcp_listen_pids(args.port))
    unique = sorted(set(targets))
    if args.list:
        for pid in unique:
            print(pid)
        return 0
    if force:
        for pid in unique:
            stop_pid(pid, timeout_s=1.0, force=True)
        return 0
    for pid in unique:
        if is_windows():
            stop_pid(pid, timeout_s=15.0, force=False)
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    return 0
