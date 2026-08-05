"""单进程 unified 启停（Python 实现，跨平台；替代 run_unified_bot.sh 核心逻辑）。"""

from __future__ import annotations

import argparse
import os
import runpy
import sys
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from pallas.console.cli.process_util import (
    clear_pid_file,
    pid_alive,
    read_pid_file,
    spawn_detached,
    stop_pid,
    uv_run_python_cmd,
    write_pid_file,
)
from pallas.core.foundation.paths import PROJECT_ROOT
from pallas.core.platform.shard.registry.sync_unified_protocol_ports import (
    format_unified_sync_user_message,
    resolve_unified_listen_port,
    sync_accounts_ws_urls_unified,
)

RUN_DIR = PROJECT_ROOT / "data" / "pallas_unified" / "run"
LOG_DIR = PROJECT_ROOT / "data" / "pallas_unified" / "logs"
ACCOUNTS_JSON = PROJECT_ROOT / "data" / "pallas_protocol" / "accounts.json"
PID_FILE = RUN_DIR / "bot.pid"
LOG_FILE = LOG_DIR / "bot.log"
LOG_RETENTION_DAYS = 14
ENV_PATH = PROJECT_ROOT / ".env"


def start_aux_services() -> int:
    from pallas.console.cli.embedding_aux import start_embed_aux, stop_embed_aux
    from pallas.console.cli.work_aux import start_work_aux

    if start_embed_aux() != 0:
        return 1
    if start_work_aux() == 0:
        return 0
    stop_embed_aux()
    return 1


def stop_aux_services() -> None:
    from pallas.console.cli.embedding_aux import stop_embed_aux
    from pallas.console.cli.work_aux import stop_work_aux

    stop_embed_aux()
    stop_work_aux()


def print_aux_services_status() -> None:
    from pallas.console.cli.embedding_aux import print_embed_aux_status
    from pallas.console.cli.work_aux import print_work_aux_status

    print_embed_aux_status()
    print_work_aux_status()


def is_bot_running() -> bool:
    pid = read_pid_file(PID_FILE)
    return pid is not None and pid_alive(pid)


def read_listen_port() -> int:
    raw = os.environ.get("PORT", "").strip()
    if raw.isdigit():
        return int(raw)
    env_path = ENV_PATH if ENV_PATH.is_file() else None
    return resolve_unified_listen_port(env_path=env_path)


def prepare_unified_ports(port: int, *, skip_port_sync: bool) -> int:
    if skip_port_sync or not ACCOUNTS_JSON.is_file():
        return 0
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    backup = RUN_DIR / "accounts.json.pre_sync"
    env_path = ENV_PATH if ENV_PATH.is_file() else None
    try:
        result = sync_accounts_ws_urls_unified(
            ACCOUNTS_JSON,
            env_path=env_path,
            backup_path=backup,
            port=port,
        )
    except (FileNotFoundError, ValueError, OSError) as err:
        print("unified 协议端端口同步失败", file=sys.stderr)
        print(f"  {err}", file=sys.stderr)
        return 1
    if result.changed_count or result.onebot_drift_count:
        msg = format_unified_sync_user_message(result, backup_path=backup)
        for line in msg.splitlines():
            print(f"  {line}")
    return 0


def bot_environment(port: int) -> dict[str, str]:
    return {
        "PALLAS_SHARD_ENABLED": "false",
        "PALLAS_BOT_ROLE": "unified",
        "PORT": str(port),
    }


def launcher_log_path() -> Path:
    stamp = datetime.now(UTC).strftime("%Y-%m-%d_%H-%M-%S")
    return LOG_DIR / f"bot_{stamp}.log"


def cleanup_launcher_logs() -> None:
    cutoff = time.time() - LOG_RETENTION_DAYS * 24 * 60 * 60
    for path in LOG_DIR.glob("bot_*.log"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue


def start_bot(*, skip_port_sync: bool = False, detach: bool = False) -> int:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if is_bot_running():
        print(f"unified 已在运行 (pid {read_pid_file(PID_FILE)})")
        return start_aux_services()
    port = read_listen_port()
    sync_rc = prepare_unified_ports(port, skip_port_sync=skip_port_sync)
    if sync_rc != 0:
        return sync_rc

    env = bot_environment(port)
    if not detach:
        print(f"unified 前台运行 · port {port}")
        print(f"控制台 http://127.0.0.1:{port}/pallas/")
        print("提示：保持当前终端查看实时日志；需后台运行请使用 uv run pallas -d。")
        print("按 Ctrl+C 停止 Bot 与本次自动启动的辅进程。")
        if start_aux_services() != 0:
            return 1
        write_pid_file(PID_FILE, os.getpid())
        old_env = {key: os.environ.get(key) for key in env}
        os.environ.update(env)
        try:
            runpy.run_path(str(PROJECT_ROOT / "bot.py"), run_name="__main__")
        except KeyboardInterrupt:
            print("\nunified 正在停止…")
        finally:
            clear_pid_file(PID_FILE)
            stop_aux_services()
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        return 0

    cleanup_launcher_logs()
    cmd = uv_run_python_cmd("bot.py")
    try:
        pid = spawn_detached(cmd, cwd=PROJECT_ROOT, env=env, log_path=launcher_log_path())
    except OSError as err:
        print(f"unified 启动失败: {err}", file=sys.stderr)
        return 1
    write_pid_file(PID_FILE, pid)
    time.sleep(2)
    if is_bot_running():
        print(f"unified 已转入后台 · pid {read_pid_file(PID_FILE)} · port {port}")
        print(f"控制台 http://127.0.0.1:{port}/pallas/")
        print(f"启动器日志 {LOG_DIR}")
        if start_aux_services() == 0:
            return 0
        stop_bot()
        return 1
    print(f"unified 启动失败，查看 {LOG_DIR}", file=sys.stderr)
    clear_pid_file(PID_FILE)
    return 1


def stop_bot() -> int:
    stop_aux_services()
    pid = read_pid_file(PID_FILE)
    if pid is None or not pid_alive(pid):
        clear_pid_file(PID_FILE)
        print("unified 未运行")
        return 0
    stop_pid(pid, timeout_s=30.0)
    clear_pid_file(PID_FILE)
    print("unified 已停止")
    return 0


def status_bot() -> int:
    port = read_listen_port()
    print("Pallas · 统一运行时")
    print(f"  监听端口   {port}")
    if is_bot_running():
        print(f"  消息实例   运行中 · pid {read_pid_file(PID_FILE)}")
        print(f"  控制台     http://127.0.0.1:{port}/pallas/")
    else:
        print("  消息实例   未运行")
    print(f"  业务日志   {PROJECT_ROOT / 'data' / 'bot'}")
    print_aux_services_status()
    print("  更多日志   uv run pallas logs")
    return 0


def observability_bot() -> int:
    if not is_bot_running():
        print("unified 未运行，无法读取 dispatch 指标", file=sys.stderr)
        return 1
    script = PROJECT_ROOT / "scripts" / "ingress_dispatch_status.py"
    if not script.is_file():
        print(f"缺少 {script}", file=sys.stderr)
        return 1
    import subprocess

    proc = subprocess.run(  # noqa: S603
        uv_run_python_cmd(str(script)),
        cwd=str(PROJECT_ROOT),
        check=False,
    )
    return int(proc.returncode or 0)


def run_unified_action(
    action: str,
    *,
    skip_port_sync: bool = False,
    detach: bool = False,
) -> int:
    normalized = (action or "status").strip().lower()
    if normalized == "start":
        return start_bot(skip_port_sync=skip_port_sync, detach=detach)
    if normalized == "stop":
        return stop_bot()
    if normalized == "restart":
        stop_bot()
        return start_bot(skip_port_sync=skip_port_sync, detach=detach)
    if normalized == "status":
        return status_bot()
    if normalized == "observability":
        return observability_bot()
    print(
        f"未知动作: {action}（期望 start|stop|restart|status|observability）",
        file=sys.stderr,
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pallas unified 启停（Python）")
    parser.add_argument(
        "action",
        nargs="?",
        default="status",
        choices=("start", "stop", "restart", "status", "observability"),
    )
    parser.add_argument(
        "--skip-port-sync",
        action="store_true",
        help="启动前不同步协议端 ws_url",
    )
    args = parser.parse_args(argv)
    return run_unified_action(args.action, skip_port_sync=args.skip_port_sync)


if __name__ == "__main__":
    raise SystemExit(main())
