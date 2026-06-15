#!/usr/bin/env python3
"""Pallas-Bot 进程守护：定时探活，连续失败后结束子进程或执行 docker restart。

做什么
  默认每隔若干秒请求控制台 health：GET /pallas/api/health（需启用插件 pallas_webui）。
  连续失败达到阈值后：未使用 --docker-container 时结束当前子进程并重新执行启动命令；使用
  --docker-container 时在宿主机执行 docker restart <容器名>。

HOST / PORT 从哪来
  与 Bot 监听一致：当前进程的环境变量优先；否则从 --workdir 下的 .env 只读取 HOST、PORT、
  ONEBOT_PORT 三项（文件中每个键首行生效，不把整份 .env 写入 os.environ）。
  HOST 为 0.0.0.0、:: 或未设置时，HTTP 探活主机用 127.0.0.1。PORT 与 .env 皆无时端口默认 8088；
  未设置 PORT 时可读 ONEBOT_PORT（与协议插件习惯一致）。

谁负责启动 Bot
  · 由本脚本拉起：在仓库根执行，不要加 --no-spawn（默认子进程为 uv run nb run，可用 --start 改）。
  · Bot 已由 systemd、screen、Docker、另一终端等启动：必须加 --no-spawn，否则会双开端口。
  · Bot 在容器内、在宿主机上监护：--docker-container <名> --no-spawn（宿主机需能 docker restart）。

日志
  首轮探活成功打一条 INFO；之后仅在失败、恢复时继续打日志。

TCP 与 HTTP
  若只写 --tcp-probe（即使未写 --tcp-only），本脚本仍只按 TCP 探活、不请求上述 HTTP。若需 HTTP 与 TCP
  同时判定，请自行用外部编排或拆进程（本脚本不接收自定义 HTTP URL）。

用法示例（均在项目根目录，且已 uv sync）：

# 由守护进程启动 Bot；HOST/PORT 可读环境变量或 ./.env
  uv run python tools/scripts/bot_watchdog.py

# Bot 已在跑：只探活，不重复 uv run nb run
  uv run python tools/scripts/bot_watchdog.py --no-spawn

# .env 不在当前目录时，指向 Bot 工作目录
  uv run python tools/scripts/bot_watchdog.py --no-spawn --workdir /path/to/Pallas-Bot

# 自定义启动命令
  uv run python tools/scripts/bot_watchdog.py --start sh -c "uv run nb run"

# 未启用 WebUI、只测端口是否监听
  uv run python tools/scripts/bot_watchdog.py --tcp-only --tcp-probe 127.0.0.1:8088 --no-spawn

# Bot 在 Docker 内：宿主机探活，失败时 docker restart
  uv run python tools/scripts/bot_watchdog.py --docker-container pallasbot --no-spawn
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

logger = logging.getLogger("bot_watchdog")


def http_ok(url: str, timeout: float) -> bool:
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "pallas-bot-watchdog/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except OSError:
        return False


def tcp_ok(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def probe(
    urls: list[str],
    tcp: tuple[str, int] | None,
    timeout: float,
) -> bool:
    http_alive = True
    if urls:
        http_alive = any(http_ok(u, timeout) for u in urls)
    tcp_alive = True
    if tcp:
        tcp_alive = tcp_ok(tcp[0], tcp[1], timeout)
    return http_alive and tcp_alive


def terminate_process(proc: subprocess.Popen[bytes], grace: float) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.2)
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait(timeout=30)


def docker_restart(container: str) -> None:
    subprocess.run(
        ["docker", "restart", container],
        check=True,
        timeout=300,
    )


def parse_tcp(s: str) -> tuple[str, int]:
    host, _, port_s = s.rpartition(":")
    if not host or not port_s:
        raise argparse.ArgumentTypeError("TCP 探活格式应为 host:port，例如 127.0.0.1:8088")
    return host, int(port_s)


def read_bot_dotenv(workdir: Path) -> dict[str, str]:
    """解析 workdir/.env 中的 HOST、PORT、ONEBOT_PORT；各键首行生效，不写入 os.environ。"""
    wanted = frozenset({"HOST", "PORT", "ONEBOT_PORT"})
    out: dict[str, str] = {}
    path = workdir / ".env"
    if not path.is_file():
        return out
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key not in wanted or key in out:
            continue
        val = val.strip().strip('"').strip("'")
        val = val.split("#", 1)[0].strip()
        out[key] = val
    return out


def env_or_dotenv(key: str, file_env: dict[str, str]) -> str:
    return (os.environ.get(key) or file_env.get(key) or "").strip()


def resolve_bot_http_probe_host(file_env: dict[str, str]) -> str:
    h = env_or_dotenv("HOST", file_env)
    if not h or h == "0.0.0.0" or h in ("::", "[::]"):
        return "127.0.0.1"
    return h


def resolve_bot_listen_port(file_env: dict[str, str]) -> int:
    for key in ("PORT", "ONEBOT_PORT"):
        raw = env_or_dotenv(key, file_env)
        if raw:
            try:
                return int(raw)
            except ValueError as e:
                raise SystemExit(f"{key}={raw!r} 不是合法整数端口（来自环境或 .env）") from e
    return 8088


def build_parser(repo_root: Path) -> argparse.ArgumentParser:
    epilog = """常用示例（项目根）:
  uv run python tools/scripts/bot_watchdog.py
  uv run python tools/scripts/bot_watchdog.py --no-spawn
  uv run python tools/scripts/bot_watchdog.py --docker-container pallasbot --no-spawn
说明: 默认 HTTP 依赖 pallas_webui；HOST/PORT 优先环境变量，否则读 --workdir/.env 中三项。
完整说明见本文件顶部文档字符串或 docs/Deployment.md「进程守护脚本」一节。"""

    p = argparse.ArgumentParser(
        description="Pallas-Bot 探活与自动重启（详见模块文档与 Deployment.md）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog,
    )
    p.add_argument(
        "--tcp-probe",
        type=parse_tcp,
        metavar="HOST:PORT",
        help="TCP 探活；若指定则不再使用默认 HTTP health（与是否加 --tcp-only 无关）",
    )
    p.add_argument(
        "--tcp-only",
        action="store_true",
        help="与 --tcp-probe 联用：仅 TCP 探活，不请求默认 HTTP health",
    )
    p.add_argument("--interval", type=float, default=15.0, help="探活间隔（秒），默认 15")
    p.add_argument("--timeout", type=float, default=5.0, help="单次 HTTP/TCP 超时（秒），默认 5")
    p.add_argument("--fail-threshold", type=int, default=3, help="连续失败多少次后触发重启，默认 3")
    p.add_argument("--cooldown", type=float, default=5.0, help="重启后暂停计数的等待秒，默认 5")
    p.add_argument("--grace-stop", type=float, default=20.0, help="SIGTERM 后等待子进程退出的秒，默认 20")
    p.add_argument(
        "--workdir",
        type=Path,
        default=repo_root,
        help="子进程 cwd；默认同仓库根。读取 .env 时也是该目录下的 .env（仅 HOST/PORT/ONEBOT_PORT）",
    )
    p.add_argument(
        "--start",
        nargs=argparse.REMAINDER,
        default=None,
        help="启动 Bot 的完整命令，必须放在命令行最后；默认 uv run nb run",
    )
    p.add_argument(
        "--docker-container",
        metavar="NAME",
        help="探活失败时对宿主机执行 docker restart NAME（不通过本脚本启动容器内进程）",
    )
    p.add_argument(
        "--no-spawn",
        action="store_true",
        help="启动瞬间不拉起子进程；Bot 已由 systemd/其它终端/Docker 跑起来时必须加上",
    )
    return p


def resolve_defaults(args: argparse.Namespace) -> tuple[list[str], list[str], tuple[str, int] | None]:
    tcp_probe: tuple[str, int] | None = args.tcp_probe
    file_env = read_bot_dotenv(args.workdir.resolve())

    if args.tcp_only:
        if not tcp_probe:
            raise SystemExit("--tcp-only 需要同时指定 --tcp-probe")
        urls: list[str] = []
    elif tcp_probe is not None:
        urls = []
    else:
        host = resolve_bot_http_probe_host(file_env)
        port = resolve_bot_listen_port(file_env)
        urls = [f"http://{host}:{port}/pallas/api/health"]

    start_argv: list[str]
    if args.start is not None and len(args.start) > 0:
        start_argv = list(args.start)
    else:
        start_argv = ["uv", "run", "nb", "run"]

    return urls, start_argv, tcp_probe


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    parser = build_parser(repo_root)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    urls, start_argv, tcp_probe = resolve_defaults(args)
    if not urls and not tcp_probe:
        raise SystemExit("至少需要 HTTP 探活（默认 /pallas/api/health，需 HOST/PORT 或 --workdir/.env）或 --tcp-probe")
    workdir: Path = args.workdir.resolve()

    docker_container = (args.docker_container or "").strip() or None

    if docker_container:
        logger.info("模式: 探活失败时在宿主机执行 docker restart %s（不通过本脚本启动容器内进程）", docker_container)
    else:
        logger.info("模式: 子进程 %s，工作目录 %s", start_argv, workdir)

    logger.info(
        "探活参数: 间隔 %.1fs | 连续失败阈值 %s | HTTP=%s | TCP=%s",
        args.interval,
        args.fail_threshold,
        urls or "(无)",
        tcp_probe or "(无)",
    )

    child: subprocess.Popen[bytes] | None = None
    fails = 0
    stopping = False
    seen_first_ok = False

    def handle_stop(signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True
        logger.info("收到信号 %s，准备退出", signum)

    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)

    def spawn_child() -> subprocess.Popen[bytes]:
        logger.info("启动子进程: %s", start_argv)
        return subprocess.Popen(
            start_argv,
            cwd=str(workdir),
            start_new_session=True,
            stdin=subprocess.DEVNULL,
        )

    if not docker_container and not args.no_spawn:
        logger.info(
            "将立即拉起子进程（默认 uv run nb run）。若 Bot 已在其它终端或 systemd 中运行，请中断后改用 --no-spawn",
        )
        child = spawn_child()
    elif not docker_container and args.no_spawn:
        logger.info(
            "未拉起子进程（--no-spawn）：仅探活；达阈值后会执行启动命令尝试恢复。"
            "若 Bot 已由 systemd 等托管，请避免两边同时自动拉起",
        )

    try:
        while not stopping:
            ok = probe(urls, tcp_probe, args.timeout)
            if ok:
                if fails > 0:
                    logger.info("探活已恢复")
                elif not seen_first_ok:
                    logger.info(
                        "探活正常（已连通）：每 %.0fs 轮询；成功时默认仅本行，失败见 WARNING/ERROR",
                        args.interval,
                    )
                fails = 0
                seen_first_ok = True
            else:
                fails += 1
                logger.warning("探活失败 %s/%s", fails, args.fail_threshold)

            need_restart = fails >= args.fail_threshold
            if need_restart and docker_container:
                logger.error("探活连续失败，执行 docker restart")
                try:
                    docker_restart(docker_container)
                except (OSError, subprocess.SubprocessError):
                    logger.exception("docker restart 失败")
                fails = 0
                time.sleep(args.cooldown)
                continue

            if need_restart and not docker_container:
                logger.error("探活连续失败，重启本地子进程")
                if child is not None and child.poll() is None:
                    terminate_process(child, args.grace_stop)
                child = spawn_child()
                fails = 0
                time.sleep(args.cooldown)
                continue

            if not docker_container and child is not None and child.poll() is not None:
                code = child.returncode
                logger.error("子进程已退出 code=%s，立即重新拉起", code)
                child = spawn_child()
                fails = 0
                time.sleep(args.cooldown)
                continue

            time.sleep(args.interval)
    finally:
        if child is not None and child.poll() is None:
            logger.info("正在结束子进程…")
            terminate_process(child, args.grace_stop)

    return 0


if __name__ == "__main__":
    sys.exit(main())
