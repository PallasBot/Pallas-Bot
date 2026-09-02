"""持久化后台任务辅进程启停。"""

from __future__ import annotations

import os
import sys
import time

from pallas.console.cli.process_util import (
    clear_pid_file,
    pid_alive,
    read_pid_file,
    report_process_stop,
    spawn_detached,
    stop_pid,
    uv_run_python_cmd,
    write_pid_file,
)
from pallas.core.foundation.paths import PROJECT_ROOT

RUN_DIR = PROJECT_ROOT / "data" / "pallas_work" / "run"
LOG_DIR = PROJECT_ROOT / "data" / "pallas_work" / "logs"
PID_FILE = RUN_DIR / "work.pid"
LOG_FILE = LOG_DIR / "work.log"


def work_aux_should_run() -> bool:
    try:
        from pallas.core.foundation.config.repo_settings import apply_repo_settings_to_environ
        from pallas.core.foundation.db import get_db_backend

        apply_repo_settings_to_environ()
        return str(get_db_backend() or "").strip().lower() in {"postgresql", "mongodb"}
    except Exception:
        return False


def work_aux_running() -> bool:
    pid = read_pid_file(PID_FILE)
    return pid is not None and pid_alive(pid)


def start_work_aux(*, dry_run: bool = False) -> int:
    if not work_aux_should_run():
        print("  · work 辅进程：跳过（仅 PostgreSQL / MongoDB 可用）")
        return 0
    if work_aux_running():
        print("  · work 辅进程：已在运行")
        return 0
    if dry_run:
        print("  · work 辅进程：将启动（预览）")
        return 0
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        pid = spawn_detached(
            uv_run_python_cmd("bot_work_aux.py"),
            cwd=PROJECT_ROOT,
            env={**os.environ, "PALLAS_BOT_ROLE": "work"},
            log_path=LOG_FILE,
        )
    except OSError as err:
        print(f"  · work 辅进程：启动失败 {err}", file=sys.stderr)
        return 1
    write_pid_file(PID_FILE, pid)
    print(f"  · work 辅进程：已启动（日志 {LOG_FILE}）")
    return 0


def stop_work_aux(*, force: bool = False, dry_run: bool = False) -> None:
    if not work_aux_running():
        clear_pid_file(PID_FILE)
        print("  · work 辅进程：未在运行")
        return
    if dry_run:
        print("  · work 辅进程：将停止（预览）")
        return
    pid = read_pid_file(PID_FILE)
    if pid is not None:
        started = time.monotonic()
        stop_pid(pid, timeout_s=15.0, force=force)
        report_process_stop("work", pid, time.monotonic() - started)
    clear_pid_file(PID_FILE)


def print_work_aux_status() -> None:
    if work_aux_running():
        print(f"  · work 辅进程：运行中 pid={read_pid_file(PID_FILE)} 日志 {LOG_FILE}")
    elif work_aux_should_run():
        print("  · work 辅进程：未运行（配置可用但进程不在）")
    else:
        print("  · work 辅进程：不需要（仅 PostgreSQL / MongoDB 可用）")
