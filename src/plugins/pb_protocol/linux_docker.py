"""Linux：NapCat Docker。"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

from . import docker_cli
from .docker_onebot_host import (
    docker_host_gateway_extra_args,
    effective_docker_onebot_host,
    resolve_docker_onebot_host_from_config,
)

docker_container_running = docker_cli.docker_inspect_running_async
docker_container_running_sync = docker_cli.docker_inspect_running_sync
docker_remove_force = docker_cli.docker_rm_force_async
docker_stop = docker_cli.docker_stop_async
docker_stop_sync = docker_cli.docker_stop_sync

__all__ = [
    "append_docker_resource_limits",
    "build_docker_run_argv",
    "docker_cache_path",
    "docker_container_name",
    "docker_container_running",
    "docker_container_running_sync",
    "docker_remove_force",
    "docker_stop",
    "docker_stop_sync",
    "docker_volume_paths",
    "is_linux",
    "apply_docker_runtime_toggle_to_ws_url",
    "is_plain_ws_url",
    "rewrite_onebot_ws_url_for_container",
    "sanitize_docker_name_suffix",
    "ws_url_host_should_rewrite_for_docker_bridge",
]

if TYPE_CHECKING:
    from .config import Config


def is_linux() -> bool:
    import sys

    return sys.platform.startswith("linux")


def sanitize_docker_name_suffix(account_id: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_.-]", "-", (account_id or "x").strip())[:40]
    return s or "x"


def docker_container_name(account: dict) -> str:
    return f"pallas-proto-{sanitize_docker_name_suffix(str(account.get('id', 'x')))}"


def docker_volume_paths(account: dict) -> tuple[Path, Path]:
    ad = Path(str(account.get("account_data_dir", "")).strip()).resolve()
    qq_dir = ad / ".config" / "QQ"
    legacy_qq_dir = ad / "docker" / "qq"
    if not qq_dir.exists() and legacy_qq_dir.exists():
        qq_dir = legacy_qq_dir
    return ad / "config", qq_dir


def docker_cache_path(account: dict) -> Path:
    ad = Path(str(account.get("account_data_dir", "")).strip()).resolve()
    return ad / "cache"


def append_docker_resource_limits(argv: list[str], config: Config) -> None:
    mem = str(getattr(config, "pallas_protocol_docker_memory_limit", "") or "").strip()
    if mem:
        argv.extend(["--memory", mem])
    swap = str(getattr(config, "pallas_protocol_docker_memory_swap", "") or "").strip()
    if swap:
        argv.extend(["--memory-swap", swap])
    shm = str(getattr(config, "pallas_protocol_docker_shm_size", "") or "").strip()
    if shm:
        argv.extend(["--shm-size", shm])


def build_docker_run_argv(
    account: dict,
    config: Config,
    resolve_qq,
) -> list[str]:
    _ = str(resolve_qq(account) or "").strip()
    img = (getattr(config, "pallas_protocol_docker_image", None) or "mlikiowa/napcat-docker:latest").strip()
    in_port = int(getattr(config, "pallas_protocol_docker_internal_webui_port", 6099) or 6099)
    wport = account.get("webui_port", in_port)
    try:
        host_map = int(wport)
    except (TypeError, ValueError):
        host_map = in_port
    if not (1 <= host_map <= 65535):
        host_map = in_port
    name = docker_container_name(account)
    cfg, qqd = docker_volume_paths(account)
    cache = docker_cache_path(account)
    network_mode = str(getattr(config, "pallas_protocol_docker_network_mode", "bridge") or "bridge").strip() or "bridge"
    uid = getattr(config, "pallas_protocol_docker_uid", None)
    gid = getattr(config, "pallas_protocol_docker_gid", None)
    if uid is None:
        uid = getattr(os, "getuid", lambda: 1000)()
    if gid is None:
        gid = getattr(os, "getgid", lambda: 1000)()
    if int(uid) < 0:
        uid = 1000
    if int(gid) < 0:
        gid = 1000
    argv: list[str] = [
        "run",
        "-d",
        "--name",
        name,
        "--label",
        "pallas.protocol=napcat",
        "--label",
        f"pallas.account_id={sanitize_docker_name_suffix(str(account.get('id', 'x')))}",
        "--restart",
        "unless-stopped",
        "-e",
        f"NAPCAT_UID={uid}",
        "-e",
        f"NAPCAT_GID={gid}",
        "-v",
        f"{cfg}:/app/napcat/config",
        "-v",
        f"{qqd}:/app/.config/QQ",
        "-v",
        f"{cache}:/app/napcat/cache",
    ]
    append_docker_resource_limits(argv, config)
    if network_mode == "host":
        argv.extend(["--network", "host"])
    else:
        argv.extend([*docker_host_gateway_extra_args(), "-p", f"{host_map}:{in_port}"])
    argv.append(img)
    return argv


def is_plain_ws_url(url: str) -> bool:
    """是否为 URI scheme ``ws``的 URL。"""
    u = str(url or "").strip()
    if not u:
        return False
    return urlsplit(u).scheme.lower() == "ws"


def rewrite_onebot_ws_url_for_container(url: str, docker_host: str) -> str:
    if not (url and is_plain_ws_url(url)):
        return url
    u = urlsplit(url)
    dhost = (docker_host or "").strip()
    if not dhost or dhost.lower() == "auto":
        dhost = effective_docker_onebot_host("", docker_network_mode="bridge")
    if u.port is not None:
        netloc = f"{dhost}:{u.port}"
    else:
        netloc = dhost
    return urlunsplit((u.scheme, netloc, u.path, u.query, u.fragment))


_IPV4_RE = re.compile(r"^(?:25[0-5]|2[0-4]\d|[01]?\d{1,3})(?:\.(?:25[0-5]|2[0-4]\d|[01]?\d{1,3})){3}$")


def ws_url_host_should_rewrite_for_docker_bridge(url: str) -> bool:
    """是否应把明文 ``ws`` URL 的主机替换为 Docker 侧可达地址（如网关）。

    用于 NapCat/SnowLuma 容器访问宿主机 Bot；对非 127 的 IPv4 与其它 IPv6字面量不替换。
    """
    if not (url and is_plain_ws_url(url)):
        return False
    host = (urlsplit(url).hostname or "").strip().lower()
    if not host:
        return True
    if host in ("localhost", "host.docker.internal"):
        return True
    if host == "::1":
        return True
    if ":" in host:
        return False
    if _IPV4_RE.match(host):
        return host.startswith("127.")
    return True


def apply_docker_runtime_toggle_to_ws_url(
    url: str,
    *,
    prev_docker_runtime: bool,
    now_docker_runtime: bool,
    config: Any,
) -> str | None:
    """Docker 与本地运行切换时，按规则改写 ``ws_url`` 主机。"""
    if prev_docker_runtime == now_docker_runtime:
        return None
    if not (url and is_plain_ws_url(url)):
        return None
    if now_docker_runtime:
        if not ws_url_host_should_rewrite_for_docker_bridge(url):
            return None
        dh = resolve_docker_onebot_host_from_config(config)
        new_url = rewrite_onebot_ws_url_for_container(url, dh)
        return new_url if new_url != url else None
    from .config import resolve_onebot_ws_settings

    dh = (resolve_docker_onebot_host_from_config(config) or "").strip().lower()
    u = urlsplit(url)
    h = (u.hostname or "").strip().lower()
    bridge_style = ws_url_host_should_rewrite_for_docker_bridge(url)
    host_is_docker_target = h == "host.docker.internal" or (bool(dh) and h == dh) or bridge_style
    if not host_is_docker_target:
        return None
    base_url, _, _ = resolve_onebot_ws_settings(config)
    if base_url:
        ub = urlsplit(base_url)
        new_host = (ub.hostname or "").strip() or "127.0.0.1"
        port = u.port if u.port is not None else ub.port
    else:
        new_host = "127.0.0.1"
        port = u.port if u.port is not None else 8088
    if not new_host:
        new_host = "127.0.0.1"
    netloc = f"{new_host}:{port}" if port is not None else new_host
    new_url = urlunsplit(("ws", netloc, u.path, u.query, u.fragment))
    return new_url if new_url != url else None
