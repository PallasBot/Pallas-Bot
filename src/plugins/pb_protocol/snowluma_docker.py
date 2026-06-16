"""Linux：SnowLuma Docker 镜像。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import docker_cli
from .docker_onebot_host import docker_host_gateway_extra_args
from .linux_docker import sanitize_docker_name_suffix

snowluma_docker_container_running = docker_cli.docker_inspect_running_async
snowluma_docker_container_running_sync = docker_cli.docker_inspect_running_sync
snowluma_docker_remove_force = docker_cli.docker_rm_force_async
snowluma_docker_remove_force_sync = docker_cli.docker_rm_force_sync

__all__ = [
    "build_snowluma_docker_run_argv",
    "snowluma_docker_container_name",
    "snowluma_docker_container_running",
    "snowluma_docker_container_running_sync",
    "snowluma_docker_effective_host_novnc_port",
    "snowluma_docker_effective_host_vnc_port",
    "snowluma_docker_program_dir_marker",
    "snowluma_docker_remove_force",
    "snowluma_docker_remove_force_sync",
    "snowluma_docker_stop",
    "snowluma_docker_stop_sync",
    "snowluma_docker_volume_paths",
]


def snowluma_docker_container_name(account: dict) -> str:
    return f"pallas-proto-sl-{sanitize_docker_name_suffix(str(account.get('id', 'x')))}"


def snowluma_docker_volume_paths(account: dict) -> tuple[Path, Path, Path]:
    ad = Path(str(account.get("account_data_dir", "")).strip()).resolve()
    base = ad / "docker" / "snowluma"
    return base / "snowluma-data", base / "dot-config", base / "dot-local-share"


def _internal_webui_port(config: Any) -> int:
    return int(getattr(config, "pallas_protocol_snowluma_docker_internal_webui_port", 5099) or 5099)


def _internal_onebot_http_port(config: Any) -> int:
    return int(getattr(config, "pallas_protocol_snowluma_docker_internal_onebot_http_port", 3000) or 3000)


def _internal_onebot_ws_port(config: Any) -> int:
    return int(getattr(config, "pallas_protocol_snowluma_docker_internal_onebot_ws_port", 3001) or 3001)


def snowluma_docker_effective_host_novnc_port(account: dict, config: Any) -> int:
    if "snowluma_docker_host_novnc_port" in account:
        try:
            return int(str(account["snowluma_docker_host_novnc_port"]).strip())
        except (TypeError, ValueError):
            return 0
    return int(getattr(config, "pallas_protocol_snowluma_docker_host_novnc_port", 0) or 0)


def snowluma_docker_effective_host_vnc_port(account: dict, config: Any) -> int:
    if "snowluma_docker_host_vnc_port" in account:
        try:
            return int(str(account["snowluma_docker_host_vnc_port"]).strip())
        except (TypeError, ValueError):
            return 0
    return int(getattr(config, "pallas_protocol_snowluma_docker_host_vnc_port", 0) or 0)


def build_snowluma_docker_run_argv(account: dict, config: Any, resolve_qq) -> list[str]:
    _ = str(resolve_qq(account) or "").strip()
    img = (
        str(getattr(config, "pallas_protocol_snowluma_docker_image", "") or "").strip()
        or "motricseven7/snowluma:latest"
    )
    in_webui = _internal_webui_port(config)
    in_http = _internal_onebot_http_port(config)
    in_ws = _internal_onebot_ws_port(config)
    try:
        host_webui = int(str(account.get("webui_port", "")).strip())
    except (TypeError, ValueError):
        host_webui = 0
    if not (1 <= host_webui <= 65535):
        host_webui = in_webui
    try:
        host_http = int(str(account.get("snowluma_docker_host_onebot_http", "")).strip())
    except (TypeError, ValueError):
        host_http = 0
    try:
        host_ws = int(str(account.get("snowluma_docker_host_onebot_ws", "")).strip())
    except (TypeError, ValueError):
        host_ws = 0
    if not (1 <= host_http <= 65535) or not (1 <= host_ws <= 65535):
        msg = "SnowLuma Docker 需要有效的 snowluma_docker_host_onebot_http / snowluma_docker_host_onebot_ws"
        raise ValueError(msg)

    name = snowluma_docker_container_name(account)
    data_dir, cfg_dir, local_share = snowluma_docker_volume_paths(account)
    shm = str(getattr(config, "pallas_protocol_snowluma_docker_shm_size", "") or "").strip() or "1g"
    vnc_pw = str(getattr(config, "pallas_protocol_snowluma_docker_vnc_passwd", "") or "").strip()

    argv: list[str] = [
        "run",
        "-d",
        "--name",
        name,
        "--label",
        "pallas.protocol=snowluma",
        "--label",
        f"pallas.account_id={sanitize_docker_name_suffix(str(account.get('id', 'x')))}",
        "--restart",
        "unless-stopped",
        *docker_host_gateway_extra_args(),
        "--shm-size",
        shm,
        "--cap-add",
        "SYS_PTRACE",
        "--security-opt",
        "seccomp=unconfined",
        # WebUI 以挂载 runtime.json 为准；env 供镜像入口可选。
        "-e",
        f"SNOWLUMA_WEBUI_PORT={in_webui}",
        "-v",
        f"{data_dir}:/app/snowluma-data",
        "-v",
        f"{cfg_dir}:/app/.config",
        "-v",
        f"{local_share}:/app/.local/share",
        "-p",
        f"{host_webui}:{in_webui}",
        "-p",
        f"{host_http}:{in_http}",
        "-p",
        f"{host_ws}:{in_ws}",
    ]
    if vnc_pw:
        argv.extend(["-e", f"VNC_PASSWD={vnc_pw}"])

    novnc = snowluma_docker_effective_host_novnc_port(account, config)
    vnc = snowluma_docker_effective_host_vnc_port(account, config)
    in_novnc = int(getattr(config, "pallas_protocol_snowluma_docker_internal_novnc_port", 6081) or 6081)
    in_vnc = int(getattr(config, "pallas_protocol_snowluma_docker_internal_vnc_port", 5900) or 5900)
    if 1 <= novnc <= 65535:
        argv.extend(["-p", f"{novnc}:{in_novnc}"])
    if 1 <= vnc <= 65535:
        argv.extend(["-p", f"{vnc}:{in_vnc}"])

    argv.append(img)
    return argv


def snowluma_docker_program_dir_marker(config: Any) -> str:
    img = (
        str(getattr(config, "pallas_protocol_snowluma_docker_image", "") or "").strip()
        or "motricseven7/snowluma:latest"
    )
    return f"docker:snowluma:{img}"


async def snowluma_docker_stop(name: str) -> None:
    await docker_cli.docker_stop_async(name, wait_timeout=120)


def snowluma_docker_stop_sync(name: str) -> None:
    docker_cli.docker_stop_sync(name, subprocess_timeout=120)
