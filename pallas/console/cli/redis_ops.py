"""项目管理 Redis 的显式初始化。"""

from __future__ import annotations

import subprocess
import sys

_CONTAINER = "pallas-redis"
_IMAGE = "redis:7-alpine"
_VOLUME = "pallas-redis-data"


def configured_redis_url() -> str:
    from pallas.core.foundation.config.repo_settings import apply_repo_settings_to_environ, repo_env_raw_value

    apply_repo_settings_to_environ()
    return str(repo_env_raw_value("REDIS_URL") or "").strip()


def redis_url_reachable(url: str) -> bool:
    if not url:
        return False
    try:
        import redis

        client = redis.Redis.from_url(url, socket_connect_timeout=1.0, socket_timeout=1.0)
        return bool(client.ping())
    except Exception:
        return False


def docker_ready() -> bool:
    try:
        result = subprocess.run(  # noqa: S603
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def docker_command(args: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(  # noqa: S603
            ["docker", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def docker_container_port() -> int | None:
    result = docker_command([
        "inspect",
        "--format",
        '{{(index (index .NetworkSettings.Ports "6379/tcp") 0).HostPort}}',
        _CONTAINER,
    ])
    if result is None or result.returncode != 0:
        return None
    raw = result.stdout.strip()
    return int(raw) if raw.isdigit() else None


def ensure_docker_redis() -> int | None:
    inspected = docker_command(["container", "inspect", _CONTAINER])
    if inspected is None:
        return None
    if inspected.returncode == 0:
        started = docker_command(["start", _CONTAINER])
        if started is None or started.returncode != 0:
            return None
    else:
        created = docker_command([
            "run",
            "-d",
            "--name",
            _CONTAINER,
            "--restart",
            "unless-stopped",
            "--volume",
            f"{_VOLUME}:/data",
            "--publish",
            "127.0.0.1::6379",
            _IMAGE,
            "redis-server",
            "--appendonly",
            "yes",
        ])
        if created is None or created.returncode != 0:
            return None
    return docker_container_port()


def persist_redis_url(url: str) -> None:
    from pallas.core.foundation.config.repo_settings import upsert_repo_settings_items

    upsert_repo_settings_items({"REDIS_URL": url})


def start_redis() -> int:
    configured = configured_redis_url()
    if configured and redis_url_reachable(configured):
        print(f"Redis 已可用：复用 {configured}")
        return 0
    if configured:
        print(f"已配置的 Redis 不可达：{configured}", file=sys.stderr)
    if not docker_ready():
        print("未检测到可用 Docker，未创建 Redis；Bot 可继续使用数据库 outbox。", file=sys.stderr)
        print("可安装 Docker 后执行: uv run pallas redis start", file=sys.stderr)
        return 1
    port = ensure_docker_redis()
    if port is None:
        print("Docker Redis 启动失败，请检查 docker ps -a 与容器日志。", file=sys.stderr)
        return 1
    url = f"redis://127.0.0.1:{port}/0"
    if not redis_url_reachable(url):
        print("Docker Redis 尚未就绪，请稍后重试。", file=sys.stderr)
        return 1
    persist_redis_url(url)
    print(f"Redis 已启动并写入 REDIS_URL：{url}")
    return 0


def redis_status() -> int:
    url = configured_redis_url()
    if not url:
        print("Redis 未配置（单进程 Bot 可继续使用数据库 outbox）")
        return 0
    if redis_url_reachable(url):
        print(f"Redis 可达：{url}")
        return 0
    print(f"Redis 不可达：{url}", file=sys.stderr)
    return 1
