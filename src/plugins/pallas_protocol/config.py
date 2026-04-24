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
        description="HTTP 第二路径段：挂载为 /protocol/<本字段>；空则使用 DEFAULT_PROTOCOL_BACKEND（见 contract）",
    )
    pallas_protocol_webui_path: str = Field(
        default="",
        description="非空则覆盖整段挂载 URL；空则按 web_implementation 或默认实现自动拼 /protocol/<slug>",
    )
    pallas_protocol_token: str = Field(
        default="",
        description="与页内 token 一致时鉴权本插件 HTTP；非 NapCat 内置 WebUI 密码",
    )
    pallas_protocol_bind_host: str = "127.0.0.1"
    pallas_protocol_default_command: str = "node"
    pallas_protocol_default_args: list[str] = ["napcat.mjs"]
    pallas_protocol_program_dir: str = ""
    pallas_protocol_default_working_dir: str = ""
    pallas_protocol_shell_template_dir: str = ""
    pallas_protocol_instances_root: str = Field(
        default="",
        description="账号数据根目录；空则使用 data/pallas_protocol/instances/",
    )
    pallas_protocol_max_log_lines: int = Field(default=500, ge=100, le=5000)
    pallas_protocol_webui_port_min: int = Field(default=6099, ge=1024, le=65534)
    pallas_protocol_webui_port_max: int = Field(default=7999, ge=1025, le=65535)
    # 从 GitHub Releases 直链下载 Shell/一键包（空字符串表示 latest）
    pallas_protocol_github_repo: str = Field(
        default_factory=default_release_repo_for_platform,
        description="空时按平台默认：Windows/非 Linux 使用 NapNeko/NapCatQQ，Linux 使用 NapNeko/NapCatAppImageBuild",
    )
    pallas_protocol_release_tag: str = ""
    pallas_protocol_release_asset: str = Field(
        default_factory=default_release_asset_for_platform,
        description="空则按平台：Windows 一键包；Linux/macOS 等为官方 NapCat.Shell.zip（与 Windows.* 区分）",
    )
    pallas_protocol_auto_download_runtime: bool = Field(
        default=False,
        description="启动时若未检测到 manifest 中的 program_dir，则后台尝试下载（可能较慢）",
    )
    # WS 固定 ws://host:port/onebot/v11/ws；优先 PALLAS_PROTOCOL_*，再与 NoneBot 共用 HOST/PORT/ACCESS_TOKEN
    pallas_protocol_onebot_host: str = Field(
        default="",
        description="反向 WS host，空则读 PALLAS_PROTOCOL_ONEBOT_HOST，再读 HOST、ONEBOT_HOST",
    )
    pallas_protocol_onebot_port: int | None = Field(
        default=None,
        description="反向 WS 端口，空则读 PALLAS_PROTOCOL_ONEBOT_PORT，再读 PORT、ONEBOT_PORT",
    )
    pallas_protocol_access_token: str = Field(
        default="",
        description="与协议端/NoneBot token 一致，空则读 PALLAS_PROTOCOL_ACCESS_TOKEN，再读 ACCESS_TOKEN",
    )
    pallas_protocol_onebot_client_name: str = Field(
        default="",
        description="onebot 连接名，空则读 PALLAS_PROTOCOL_ONEBOT_CLIENT_NAME，再读 ONEBOT_CLIENT_NAME 或 pallas",
    )
    # 可选：Linux + Docker 镜像无头；默认 false，与 Windows 一样走本机 node + 运行时，持久化/多开靠多账号目录与端口
    pallas_protocol_linux_use_docker: bool = Field(
        default=False,
        description=(
            "仅 Linux 为 true 时用 Docker 镜像；false 时本机 node+Shell 运行时，"
            "多账号=多进程+独立 data 与 webui_port"
        ),
    )
    pallas_protocol_linux_use_xvfb: bool = Field(
        default=True,
        description="仅 Linux 且非 Docker 时，是否用 xvfb-run 包裹本地启动（无头环境推荐开启）",
    )
    pallas_protocol_linux_xvfb_command: str = Field(
        default="xvfb-run",
        description="Linux 本地无头启动命令（通常为 xvfb-run）",
    )
    pallas_protocol_linux_xvfb_args: list[str] = Field(
        default_factory=lambda: ["--auto-servernum", "--server-args=-screen 0 1280x720x24"],
        description="xvfb-run 默认参数；可按机器图形栈调整",
    )
    pallas_protocol_linux_appimage_args: list[str] = Field(
        default_factory=lambda: ["--appimage-extract-and-run"],
        description="Linux 本地运行 AppImage 时追加参数（默认规避 FUSE 依赖）",
    )
    pallas_protocol_docker_image: str = Field(
        default="mlikiowa/napcat-appimage:latest",
        description="可换 ghcr.io/napneko/napcatappimagebuild:latest",
    )
    pallas_protocol_docker_onebot_host: str = Field(
        default="172.17.0.1",
        description="容器内访问宿主机 NoneBot 的地址（常见为 docker0）；连不上时改为宿主机内网 IP 或 host 网络方案",
    )
    pallas_protocol_docker_internal_webui_port: int = Field(
        default=6099,
        ge=1,
        le=65535,
        description="镜像内 WebUI 端口，与 -p 宿主机:该端口 映射",
    )

    def resolved_release_asset(self) -> str:
        asset = (self.pallas_protocol_release_asset or "").strip()
        return asset or default_release_asset_for_platform()


def resolve_protocol_webui_base_path(config: Any) -> str:
    """管理页 HTTP 基路径（含 /protocol/<实现> 或用户整段覆盖）。"""
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


def resolve_onebot_ws_settings(config: Config) -> tuple[str, str, str]:
    cfg_host = str(getattr(config, "pallas_protocol_onebot_host", "") or "").strip()
    cfg_port = getattr(config, "pallas_protocol_onebot_port", None)
    cfg_tok = str(getattr(config, "pallas_protocol_access_token", "") or "").strip()
    cfg_name = str(getattr(config, "pallas_protocol_onebot_client_name", "") or "").strip()
    host = cfg_host or _ob_env_first("PALLAS_PROTOCOL_ONEBOT_HOST", "HOST", "ONEBOT_HOST")
    if not host:
        host = _ob_driver_first("host", "onebot_host")
    port: int | None = _ob_parse_port(cfg_port) if cfg_port is not None else None
    if port is None:
        port = _ob_parse_port(
            _ob_env_first("PALLAS_PROTOCOL_ONEBOT_PORT", "PORT", "ONEBOT_PORT")
        )
    if port is None:
        port = _ob_parse_port(_ob_driver_first("port", "onebot_port"))
    token = cfg_tok or _ob_env_first("PALLAS_PROTOCOL_ACCESS_TOKEN", "ACCESS_TOKEN")
    if not token:
        token = _ob_driver_first("access_token")
    name = (
        cfg_name
        or _ob_env_first("PALLAS_PROTOCOL_ONEBOT_CLIENT_NAME", "ONEBOT_CLIENT_NAME")
        or "pallas"
    ).strip() or "pallas"
    if not host or port is None:
        return "", name, token
    return f"ws://{host}:{port}{_ONEBOT_WS_PATH}", name, token


def onebot_connection_hints(config: Config) -> dict[str, object]:
    url, name, tok = resolve_onebot_ws_settings(config)
    cfg_host = str(getattr(config, "pallas_protocol_onebot_host", "") or "").strip()
    env_host = _ob_env_first("PALLAS_PROTOCOL_ONEBOT_HOST", "HOST", "ONEBOT_HOST")
    h = cfg_host or env_host or _ob_driver_first("host", "onebot_host")
    cfg_port = getattr(config, "pallas_protocol_onebot_port", None)
    port: int | None = _ob_parse_port(cfg_port) if cfg_port is not None else None
    if port is None:
        port = _ob_parse_port(
            _ob_env_first("PALLAS_PROTOCOL_ONEBOT_PORT", "PORT", "ONEBOT_PORT")
        )
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
