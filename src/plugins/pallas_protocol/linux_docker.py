"""Linux：NapCat Docker（mlikiowa/napcat-docker）。"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

from . import docker_cli

docker_container_running = docker_cli.docker_inspect_running_async
docker_container_running_sync = docker_cli.docker_inspect_running_sync
docker_remove_force = docker_cli.docker_rm_force_async
docker_stop = docker_cli.docker_stop_async
docker_stop_sync = docker_cli.docker_stop_sync

__all__ = [
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
    "rewrite_onebot_ws_url_for_container",
    "sanitize_docker_name_suffix",
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
    if network_mode == "host":
        argv.extend(["--network", "host"])
    else:
        argv.extend(["-p", f"{host_map}:{in_port}"])
    argv.append(img)
    return argv


def rewrite_onebot_ws_url_for_container(url: str, docker_host: str) -> str:
    if not (url and url.startswith("ws://")):  # nosemgrep: javascript.lang.security.detect-insecure-websocket
        return url
    u = urlsplit(url)
    dhost = (docker_host or "").strip() or "172.17.0.1"
    if u.port is not None:
        netloc = f"{dhost}:{u.port}"
    else:
        netloc = dhost
    return urlunsplit((u.scheme, netloc, u.path, u.query, u.fragment))
