from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .contract import resolve_public_mount_path
from .runtime.installer import default_release_asset_for_platform, default_release_repo_for_platform


class Config(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pallas_protocol_enabled: bool = True
    pallas_protocol_webui_enabled: bool = True
    pallas_protocol_web_implementation: str = Field(
        default="",
        description="/protocol/<slug> 的 slug；空为默认 console",
    )
    pallas_protocol_webui_path: str = Field(
        default="",
        description="非空则整段 URL 覆盖",
    )

    pallas_protocol_bind_host: str = "127.0.0.1"
    pallas_protocol_default_command: str = "node"
    pallas_protocol_default_args: list[str] = ["napcat.mjs"]
    pallas_protocol_program_dir: str = ""
    pallas_protocol_snowluma_program_dir: str = Field(
        default="",
        description="SnowLuma 发行根；空走资源或账号 program_dir",
    )
    pallas_protocol_snowluma_github_repo: str = Field(
        default="SnowLuma/SnowLuma",
        description="SnowLuma GitHub Owner/Name",
    )
    pallas_protocol_snowluma_release_tag: str = Field(
        default="",
        description="Release tag；空为 latest",
    )
    pallas_protocol_snowluma_release_asset: str = Field(
        default="",
        description="资产名或 URL；空按平台",
    )
    pallas_protocol_default_working_dir: str = ""
    pallas_protocol_shell_template_dir: str = ""
    pallas_protocol_instances_root: str = Field(
        default="",
        description="实例根；空为 data/pallas_protocol/instances/",
    )
    pallas_protocol_max_log_lines: int = Field(default=500, ge=100, le=5000)
    pallas_protocol_webui_port_min: int = Field(default=6099, ge=1024, le=65534)
    pallas_protocol_webui_port_max: int = Field(default=7999, ge=1025, le=65535)
    pallas_protocol_github_token: str = Field(
        default="",
        description="GitHub PAT，可选，提高 API 限额",
    )
    pallas_protocol_github_repo: str = Field(
        default_factory=default_release_repo_for_platform,
        description="NapCat 仓库；空按平台默认",
    )
    pallas_protocol_release_tag: str = ""
    pallas_protocol_release_asset: str = Field(
        default_factory=default_release_asset_for_platform,
        description="NapCat 资产；空按平台",
    )
    pallas_protocol_auto_download_runtime: bool = Field(
        default=False,
        description="无本地运行时后台下载",
    )
    pallas_protocol_onebot_client_name: str = Field(
        default="",
        description="OneBot 连接名；空读 env 或 pallas",
    )
    pallas_protocol_onebot_ws_url: str = Field(
        default="",
        description="完整 WS URL",
    )
    pallas_protocol_onebot_ws_host: str = Field(
        default="",
        description="WS host",
    )
    pallas_protocol_onebot_ws_port: int = Field(
        default=0,
        ge=0,
        le=65535,
        description="WS port",
    )
    pallas_protocol_onebot_ws_path: str = Field(
        default="",
        description="WS path；空为 /onebot/v11/ws",
    )
    pallas_protocol_linux_use_docker: bool = Field(
        default=False,
        description="Linux 用 Docker 起 NapCat",
    )
    pallas_protocol_snowluma_linux_use_docker: bool = Field(
        default=False,
        description="Linux 用 Docker 起 SnowLuma（可与 NapCat 独立）",
    )
    pallas_protocol_linux_use_xvfb: bool = Field(
        default=True,
        description="Linux 非 Docker 时用 xvfb-run",
    )
    pallas_protocol_linux_xvfb_command: str = Field(
        default="xvfb-run",
        description="xvfb 命令",
    )
    pallas_protocol_linux_xvfb_args: list[str] = Field(
        default_factory=lambda: ["--auto-servernum", "--server-args=-screen 0 1280x720x24"],
        description="xvfb 参数",
    )
    pallas_protocol_linux_appimage_args: list[str] = Field(
        default_factory=lambda: ["--appimage-extract-and-run"],
        description="AppImage 额外参数",
    )
    pallas_protocol_docker_image: str = Field(
        default="mlikiowa/napcat-docker:latest",
        description="NapCat 镜像",
    )
    pallas_protocol_docker_onebot_host: str = Field(
        default="",
        description="容器访问宿主机 Bot 的主机名或 IP；"
        "空或 auto：Linux bridge 为 docker0 地址或 172.17.0.1，host 为 127.0.0.1，其它常为 host.docker.internal",
    )
    pallas_protocol_docker_internal_webui_port: int = Field(
        default=6099,
        ge=1,
        le=65535,
        description="容器内 NapCat WebUI 端口",
    )
    pallas_protocol_follow_bot_lifecycle: bool = Field(
        default=True,
        description="实例随 Bot 启停",
    )
    pallas_protocol_docker_network_mode: str = Field(
        default="bridge",
        description="bridge 或 host",
    )
    pallas_protocol_docker_uid: int | None = Field(
        default=None,
        description="NAPCAT_UID；空自动",
    )
    pallas_protocol_docker_gid: int | None = Field(
        default=None,
        description="NAPCAT_GID；空自动",
    )
    pallas_protocol_snowluma_docker_image: str = Field(
        default="motricseven7/snowluma:latest",
        description="SnowLuma 镜像",
    )
    pallas_protocol_snowluma_docker_internal_webui_port: int = Field(
        default=5099,
        ge=1,
        le=65535,
        description="容器内 SnowLuma WebUI",
    )
    pallas_protocol_snowluma_docker_internal_onebot_http_port: int = Field(
        default=3000,
        ge=1,
        le=65535,
        description="容器内 OneBot HTTP",
    )
    pallas_protocol_snowluma_docker_internal_onebot_ws_port: int = Field(
        default=3001,
        ge=1,
        le=65535,
        description="容器内 OneBot WS",
    )
    pallas_protocol_snowluma_docker_shm_size: str = Field(
        default="1g",
        description="--shm-size",
    )
    pallas_protocol_snowluma_docker_vnc_passwd: str = Field(
        default="",
        description="VNC_PASSWD",
    )
    pallas_protocol_snowluma_docker_host_novnc_port: int = Field(
        default=0,
        ge=0,
        le=65535,
        description="宿主机 noVNC；0 不映射",
    )
    pallas_protocol_snowluma_docker_host_vnc_port: int = Field(
        default=0,
        ge=0,
        le=65535,
        description="宿主机 VNC；0 不映射",
    )
    pallas_protocol_snowluma_docker_internal_novnc_port: int = Field(
        default=6081,
        ge=1,
        le=65535,
        description="容器 noVNC",
    )
    pallas_protocol_snowluma_docker_internal_vnc_port: int = Field(
        default=5900,
        ge=1,
        le=65535,
        description="容器 VNC",
    )
    # SnowLuma Docker 多实例：自动挑选宿主机端口区间（与已登记账号及本机 bind 检测）
    pallas_protocol_snowluma_docker_auto_bind_port_lo: int = Field(
        default=17100,
        ge=1024,
        le=65533,
        description="自动 OneBot HTTP/WS 宿主机端口扫描下限",
    )
    pallas_protocol_snowluma_docker_auto_bind_port_hi: int = Field(
        default=19998,
        ge=1026,
        le=65535,
        description="自动 OneBot 端口扫描上限（与 HTTP 成对占用 HTTP+1）",
    )
    pallas_protocol_snowluma_docker_auto_aux_bind_lo: int = Field(
        default=23100,
        ge=1024,
        le=65534,
        description="自动 noVNC/VNC 宿主机端口扫描下限",
    )
    pallas_protocol_snowluma_docker_auto_aux_bind_hi: int = Field(
        default=29998,
        ge=1026,
        le=65535,
        description="自动 noVNC/VNC 宿主机端口扫描上限",
    )

    def resolved_release_asset(self) -> str:
        asset = (self.pallas_protocol_release_asset or "").strip()
        return asset or default_release_asset_for_platform()


def resolve_protocol_webui_base_path(config: Any) -> str:
    return resolve_public_mount_path(
        path_override=str(getattr(config, "pallas_protocol_webui_path", "") or ""),
        implementation_slug=str(getattr(config, "pallas_protocol_web_implementation", "") or ""),
    )


def instances_root_for(plugin_data_dir: Path, config: Any) -> Path:
    raw = str(getattr(config, "pallas_protocol_instances_root", "") or "").strip()
    if raw:
        return Path(raw)
    return plugin_data_dir / "instances"


_ONEBOT_WS_PATH = "/onebot/v11/ws"


def _ob_env_first(*keys: str) -> str:
    for k in keys:
        v = (os.environ.get(k) or "").strip()
        if v:
            return v
    return ""


def _ob_driver_first(*keys: str) -> str:
    try:
        from nonebot import get_driver

        dconf = get_driver().config
    except Exception:
        return ""
    for k in keys:
        for attr in (k, k.lower()):
            try:
                v = getattr(dconf, attr, None)
            except Exception:
                v = None
            s = str(v or "").strip()
            if s:
                return s
    return ""


def _ob_parse_port(raw: object) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw if 1 <= raw <= 65535 else None
    s = str(raw).strip()
    if not s:
        return None
    try:
        p = int(s, 10)
    except ValueError:
        return None
    return p if 1 <= p <= 65535 else None


def _ob_normalize_target_host(raw_host: str) -> str:
    h = (raw_host or "").strip()
    if h in ("0.0.0.0", "::", "[::]"):
        return "127.0.0.1"
    return h


def resolve_onebot_ws_settings(config: Config) -> tuple[str, str, str]:
    cfg_name = str(getattr(config, "pallas_protocol_onebot_client_name", "") or "").strip()
    name = (
        cfg_name or _ob_env_first("PALLAS_PROTOCOL_ONEBOT_CLIENT_NAME", "ONEBOT_CLIENT_NAME") or "pallas"
    ).strip() or "pallas"

    token = _ob_env_first("ACCESS_TOKEN")
    if not token:
        token = _ob_driver_first("access_token")

    cfg_url = str(getattr(config, "pallas_protocol_onebot_ws_url", "") or "").strip()
    if cfg_url:
        return cfg_url, name, token

    cfg_host = str(getattr(config, "pallas_protocol_onebot_ws_host", "") or "").strip()
    cfg_port = _ob_parse_port(getattr(config, "pallas_protocol_onebot_ws_port", 0) or 0)
    cfg_path = str(getattr(config, "pallas_protocol_onebot_ws_path", "") or "").strip()
    ws_path = cfg_path or _ONEBOT_WS_PATH

    host = cfg_host
    port = cfg_port or None

    if not host:
        host = _ob_env_first("HOST", "ONEBOT_HOST") or _ob_driver_first("host", "onebot_host")
    if port is None:
        port = _ob_parse_port(_ob_env_first("PORT", "ONEBOT_PORT"))
    if port is None:
        port = _ob_parse_port(_ob_driver_first("port", "onebot_port"))

    host = _ob_normalize_target_host(host)
    if not host or port is None:
        return "", name, token
    return (
        f"ws://{host}:{port}{ws_path}",  # nosemgrep: javascript.lang.security.detect-insecure-websocket
        name,
        token,
    )


def onebot_connection_hints(config: Config) -> dict[str, object]:
    url, name, tok = resolve_onebot_ws_settings(config)
    cfg_host = str(getattr(config, "pallas_protocol_onebot_ws_host", "") or "").strip()
    cfg_port = _ob_parse_port(getattr(config, "pallas_protocol_onebot_ws_port", 0) or 0)
    h = cfg_host or _ob_env_first("HOST", "ONEBOT_HOST") or _ob_driver_first("host", "onebot_host")
    port = cfg_port
    if port is None:
        port = _ob_parse_port(_ob_env_first("PORT", "ONEBOT_PORT"))
    if port is None:
        port = _ob_parse_port(_ob_driver_first("port", "onebot_port"))
    return {
        "onebot_ws_url": url,
        "onebot_ws_name": name,
        "onebot_host": h,
        "onebot_port": port,
        "onebot_has_token": bool(tok),
        "onebot_configured": bool(url),
    }
