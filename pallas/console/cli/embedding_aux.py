"""Embedding 辅进程启停（unified / shard 共用，非分片专属）。"""

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

RUN_DIR = PROJECT_ROOT / "data" / "pallas_embed" / "run"
LOG_DIR = PROJECT_ROOT / "data" / "pallas_embed" / "logs"
PID_FILE = RUN_DIR / "embed.pid"
LOG_FILE = LOG_DIR / "embed.log"


def embed_aux_should_run() -> bool:
    """local Embedding + Redis 可用时才启辅进程。"""
    try:
        from pallas.core.foundation.config.repo_settings import apply_repo_settings_to_environ
        from pallas.product.llm.config import clear_llm_config_cache, get_llm_config
        from pallas.product.llm.knowledge.embed_redis import redis_embed_available
        from pallas.product.llm.knowledge.embedding_provider import (
            clear_embedding_provider_cache,
            local_embedding_dependency_available,
            resolve_embedding_provider_name,
        )

        apply_repo_settings_to_environ()
        clear_llm_config_cache()
        clear_embedding_provider_cache()
        cfg = get_llm_config()
        if resolve_embedding_provider_name(cfg) != "local":
            return False
        if not local_embedding_dependency_available():
            return False
        return redis_embed_available()
    except Exception:
        return False


def embed_aux_running() -> bool:
    pid = read_pid_file(PID_FILE)
    return pid is not None and pid_alive(pid)


def start_embed_aux(*, dry_run: bool = False) -> int:
    if not embed_aux_should_run():
        print("  · embed 辅进程：跳过（非 local、无 Redis 或未装 fastembed）")
        return 0
    if embed_aux_running():
        print("  · embed 辅进程：已在运行")
        return 0
    if dry_run:
        print("  · embed 辅进程：将启动（预览）")
        return 0
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "PALLAS_BOT_ROLE": "embed",
    }
    try:
        pid = spawn_detached(
            uv_run_python_cmd("bot_embed.py"),
            cwd=PROJECT_ROOT,
            env=env,
            log_path=LOG_FILE,
        )
    except OSError as err:
        print(f"  · embed 辅进程：启动失败 {err}", file=sys.stderr)
        return 1
    write_pid_file(PID_FILE, pid)
    print(f"  · embed 辅进程：已启动（日志 {LOG_FILE}）")
    return 0


def stop_embed_aux(*, force: bool = False, dry_run: bool = False) -> None:
    if not embed_aux_running():
        clear_pid_file(PID_FILE)
        print("  · embed 辅进程：未在运行")
        return
    if dry_run:
        print("  · embed 辅进程：将停止（预览）")
        return
    pid = read_pid_file(PID_FILE)
    if pid is not None:
        started = time.monotonic()
        stop_pid(pid, timeout_s=15.0, force=force)
        report_process_stop("embed", pid, time.monotonic() - started)
    clear_pid_file(PID_FILE)


def print_embed_aux_status() -> None:
    if embed_aux_running():
        pid = read_pid_file(PID_FILE)
        print(f"  · embed 辅进程：运行中 pid={pid} 日志 {LOG_FILE}")
    elif embed_aux_should_run():
        print("  · embed 辅进程：未运行（配置需要但进程不在）")
    else:
        print("  · embed 辅进程：不需要（非 local 或无 Redis / fastembed）")
