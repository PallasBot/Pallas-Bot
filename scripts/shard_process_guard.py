#!/usr/bin/env python3
"""分片启停：识别本仓库 bot_hub / bot_worker 孤儿进程与 TCP 监听者（供脚本与测试复用）。"""

from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import sys
from pathlib import Path

_SCRIPT_RE = re.compile(r"bot_(hub|worker)\.py")


def repo_python_script_pids(repo_root: Path, script_name: str) -> list[int]:
    repo_root = repo_root.resolve()
    out: list[int] = []
    proc = Path("/proc")
    if not proc.is_dir():
        return out
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


def tcp_listen_pids(port: int) -> list[int]:
    if port <= 0:
        return []
    try:
        completed = subprocess.run(
            ["ss", "-tlnp", f"sport = :{port}"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return []
    pids: set[int] = set()
    for line in completed.stdout.splitlines():
        for match in re.finditer(r"pid=(\d+)", line):
            pids.add(int(match.group(1)))
    return sorted(pids)


def kill_pids(pids: list[int], sig: signal.Signals) -> None:
    for pid in pids:
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="清理分片孤儿进程或端口监听者")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--script", choices=("bot_hub.py", "bot_worker.py"))
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--signal", choices=("TERM", "KILL"), default="TERM")
    parser.add_argument("--list", action="store_true", help="仅列出 pid，不发送信号")
    args = parser.parse_args(argv)
    sig = signal.SIGTERM if args.signal == "TERM" else signal.SIGKILL
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
    kill_pids(unique, sig)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
