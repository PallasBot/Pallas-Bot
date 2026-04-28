"""Linux：基于 mlikiowa/napcat-docker（NapCat-Docker）无头跑 NapCat。

参考: https://github.com/NapNeko/NapCat-Docker
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

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
    return ad / "config", ad / "docker" / "qq"


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


async def docker_container_running(name: str) -> bool:
    if not shutil.which("docker"):
        return False
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "inspect",
        "-f",
        "{{.State.Running}}",
        name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        return False
    return b"true" in (out or b"").lower()


async def docker_remove_force(name: str) -> None:
    if not shutil.which("docker"):
        return
    p = await asyncio.create_subprocess_exec("docker", "rm", "-f", name, stderr=asyncio.subprocess.DEVNULL)
    await p.wait()


def docker_container_running_sync(name: str) -> bool:
    if not shutil.which("docker"):
        return False
    try:
        r = subprocess.run(  # noqa: S603
            ["docker", "inspect", "-f", "{{.State.Running}}", name],
            check=False,
            capture_output=True,
            text=True,
            timeout=6,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if r.returncode != 0:
        return False
    return "true" in (r.stdout or "").lower()


def docker_stop_sync(name: str) -> None:
    if not shutil.which("docker"):
        return
    try:
        subprocess.run(["docker", "stop", name], check=False, capture_output=True, timeout=60)  # noqa: S603
    except (OSError, subprocess.TimeoutExpired):
        pass
