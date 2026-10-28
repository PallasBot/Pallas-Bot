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
STARTUP_TIMEOUT_S = 60.0
STARTUP_POLL_INTERVAL_S = 0.25
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
    from concurrent.futures import ThreadPoolExecutor

    from pallas.console.cli.embedding_aux import stop_embed_aux
    from pallas.console.cli.work_aux import stop_work_aux

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(stop_embed_aux), pool.submit(stop_work_aux)]
        for future in futures:
            future.result()


def print_aux_services_status() -> None:
    from pallas.console.cli.embedding_aux import print_embed_aux_status
    from pallas.console.cli.maibot_aux import print_maibot_aux_status
    from pallas.console.cli.work_aux import print_work_aux_status

    print_embed_aux_status()
    print_work_aux_status()
    print_maibot_aux_status()


def start_managed_maibot() -> tuple[int, int | None]:
    """启动托管 MaiBot（若开启）并等待消息端口就绪；返回 (rc, 本次新起的 pid 或 None)。

    不吞配置错误：显式开启但配置无效时 ``start_maibot_aux`` 直接返回 rc=1，
    Pallas 启动因此失败，而不是静默忽略。
    """
    from pallas.console.cli import maibot_aux

    result = maibot_aux.start_maibot_aux()
    return result.rc, result.spawned_pid


def stop_spawned_maibot(pid: int | None) -> bool:
    """回滚本次新起的托管 pid（None 时不动作，不读 pid 文件）。返回是否已确认停止。"""
    if pid is None:
        return True
    from pallas.console.cli import maibot_aux

    return maibot_aux.stop_spawned_pid(pid)


def stop_managed_maibot() -> bool:
    """停止已核实身份的受管实例（Pallas/桥停止之后调用）；返回是否已确认停止。"""
    from pallas.console.cli import maibot_aux

    return maibot_aux.stop_maibot_aux()


def _rollback_started_bot(bot_pid: int | None, maibot_pid: int | None) -> None:
    """未成功启动时回滚本次 spawn 的 Bot（用具体 pid，不依赖失败 PID 文件），再回滚托管 MaiBot。

    仅在本次确实 spawn 过 Bot 时停 aux（无本次 Bot 不误停）；aux 停失败也继续回滚 Bot 与 MaiBot。
    """
    try:
        if bot_pid is not None:
            try:
                stop_aux_services()
            finally:
                if pid_alive(bot_pid):
                    stop_pid(bot_pid, timeout_s=30.0)
                clear_pid_file(PID_FILE)
    finally:
        stop_spawned_maibot(maibot_pid)


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
    stamp = datetime.now(UTC).strftime("%Y-%m-%d_%H-%M-%S_%f")
    return LOG_DIR / f"bot_{stamp}.log"


def cleanup_launcher_logs() -> None:
    cutoff = time.time() - LOG_RETENTION_DAYS * 24 * 60 * 60
    for path in LOG_DIR.glob("bot_*.log"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue


def wait_for_bot_startup(log_path: Path) -> bool | None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    while True:
        try:
            log = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            log = ""
        if "Application startup failed. Exiting." in log:
            return False
        if "Application startup complete." in log:
            return True
        if not is_bot_running():
            return False
        if time.monotonic() >= deadline:
            return None
        time.sleep(STARTUP_POLL_INTERVAL_S)


def print_startup_failure(log_path: Path) -> None:
    print(f"unified 启动失败，启动器日志 {log_path}", file=sys.stderr)
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    errors = [line for line in lines if "[ERROR" in line and "Traceback" not in line]
    details = errors[:5] if errors else lines[-8:]
    for line in details:
        print(f"  {line}", file=sys.stderr)


def start_bot(*, skip_port_sync: bool = False, detach: bool = False) -> int:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if is_bot_running():
        print(f"unified 已在运行 (pid {read_pid_file(PID_FILE)})")
        from pallas.console.cli import maibot_aux

        if maibot_aux.config_sync_requested():
            print(
                "unified 已在运行；已启用 MaiBot 配置同步，需 restart 才能应用（本次不写文件）",
                file=sys.stderr,
            )
            return 1
        state = maibot_aux.managed_runtime_state()
        if state == "invalid":
            print("unified 已在运行，但托管 MaiBot 配置无效；请修复后 restart", file=sys.stderr)
            return 1
        if state == "off":
            return start_aux_services()
        if state == "running":
            return start_aux_services()
        print(
            "unified 已在运行，但托管 MaiBot 未运行；Pallas 运行中不会新起 MaiBot（桥无自动重连），请先 restart",
            file=sys.stderr,
        )
        return 1
    port = read_listen_port()
    sync_rc = prepare_unified_ports(port, skip_port_sync=skip_port_sync)
    if sync_rc != 0:
        return sync_rc

    env = bot_environment(port)
    old_env = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    try:
        if not detach:
            print(f"unified 前台运行 · port {port}")
            print(f"控制台 http://127.0.0.1:{port}/pallas/")
            print("提示：保持当前终端查看实时日志；需后台运行请使用 uv run pallas -d。")
            print("按 Ctrl+C 停止 Bot 与本次自动启动的辅进程。")
            maibot_rc, maibot_pid = start_managed_maibot()
            if maibot_rc != 0:
                print("unified 启动失败：托管 MaiBot 未就绪", file=sys.stderr)
                return 1
            cleaned = False

            def cleanup_foreground_runtime() -> None:
                nonlocal cleaned
                if cleaned:
                    return
                cleaned = True
                try:
                    clear_pid_file(PID_FILE)
                    stop_aux_services()
                finally:
                    stop_spawned_maibot(maibot_pid)

            try:
                if start_aux_services() != 0:
                    return 1
                write_pid_file(PID_FILE, os.getpid())
                from pallas.core.foundation.asgi_runner import (
                    clear_process_shutdown_callback,
                    register_process_shutdown_callback,
                )

                register_process_shutdown_callback(cleanup_foreground_runtime)
                try:
                    runpy.run_path(str(PROJECT_ROOT / "bot.py"), run_name="__main__")
                except KeyboardInterrupt:
                    print("\nunified 正在停止…")
                finally:
                    clear_process_shutdown_callback()
                    cleanup_foreground_runtime()
                return 0
            finally:
                cleanup_foreground_runtime()

        maibot_rc, maibot_pid = start_managed_maibot()
        if maibot_rc != 0:
            return maibot_rc
        bot_ok = False
        bot_pid: int | None = None
        try:
            cleanup_launcher_logs()
            cmd = uv_run_python_cmd("bot.py")
            log_path = launcher_log_path()
            bot_pid = spawn_detached(cmd, cwd=PROJECT_ROOT, env=env, log_path=log_path)
            write_pid_file(PID_FILE, bot_pid)
            time.sleep(2)
            if not is_bot_running():
                print_startup_failure(log_path)
                return 1
            if start_aux_services() != 0:
                return 1

            startup = wait_for_bot_startup(log_path)
            if startup is False:
                print_startup_failure(log_path)
                return 1
            if startup is True:
                print(f"unified 已转入后台 · pid {read_pid_file(PID_FILE)} · port {port}")
                print(f"控制台 http://127.0.0.1:{port}/pallas/")
                print(f"启动器日志 {log_path}")
            else:
                print(f"unified 仍在后台启动，尚未确认就绪；启动器日志 {log_path}")
            bot_ok = True
            return 0
        except OSError as err:
            print(f"unified 启动失败: {err}", file=sys.stderr)
            return 1
        finally:
            if not bot_ok:
                _rollback_started_bot(bot_pid, maibot_pid)
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def stop_bot(*, stop_managed: bool = True) -> int:
    stop_aux_services()
    pid = read_pid_file(PID_FILE)
    if pid is None or not pid_alive(pid):
        clear_pid_file(PID_FILE)
        managed_ok = stop_managed_maibot() if stop_managed else True
        print("unified 未运行")
        return 0 if managed_ok else 1
    stop_pid(pid, timeout_s=30.0)
    clear_pid_file(PID_FILE)
    managed_ok = stop_managed_maibot() if stop_managed else True
    print("unified 已停止")
    return 0 if managed_ok else 1


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
        if stop_bot() != 0:
            print("unified 停止失败，取消重启（请手动处理）", file=sys.stderr)
            return 1
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
