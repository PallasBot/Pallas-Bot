from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .contract import resolve_public_mount_path
from .runtime.installer import default_release_asset_for_platform, default_release_repo_for_platform


class Config(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pallas_protocol_enabled: bool = Field(
        default=True,
        description="是否启用协议端插件（账号工作区、NapCat/SnowLuma 实例管理等）。",
    )
    pallas_protocol_webui_enabled: bool = Field(
        default=True,
        description="是否挂载协议端内置网页控制台及相关路由。",
    )
    pallas_protocol_web_implementation: str = Field(
        default="",
        description="协议页实现标识，对应路径 /protocol/<slug>；留空为默认控制台。",
    )
    pallas_protocol_webui_path: str = Field(
        default="",
        description="非空时覆盖协议端 Web 的完整挂载路径（高级用法）。",
    )

    pallas_protocol_bind_host: str = Field(
        default="127.0.0.1",
        description="本地子进程或辅助服务绑定的监听地址；对外暴露时可改为 0.0.0.0。",
    )
    pallas_protocol_default_command: str = Field(
        default="node",
        description="启动 NapCat 等使用的可执行文件名，一般为 node。",
    )
    pallas_protocol_default_args: list[str] = Field(
        default_factory=lambda: ["napcat.mjs"],
        description="传给默认启动命令的参数列表（如入口脚本 napcat.mjs）。",
    )
    pallas_protocol_program_dir: str = Field(
        default="",
        description="NapCat 程序根目录；留空则配合自动下载或内置资源解析。",
    )
    pallas_protocol_snowluma_program_dir: str = Field(
        default="",
        description="SnowLuma 发行版根目录；留空则使用资源包或账号级 program_dir。",
    )
    pallas_protocol_snowluma_github_repo: str = Field(
        default="SnowLuma/SnowLuma",
        description="SnowLuma 的 GitHub 仓库（Owner/Repo），用于在线拉取发行包。",
    )
    pallas_protocol_snowluma_release_tag: str = Field(
        default="",
        description="SnowLuma Release 标签；留空表示使用 latest。",
    )
    pallas_protocol_snowluma_release_asset: str = Field(
        default="",
        description="SnowLuma 资产文件名或直链；留空则按当前平台选择默认资产。",
    )
    pallas_protocol_default_working_dir: str = Field(
        default="",
        description="子进程默认工作目录；留空则使用实例或数据目录下的约定路径。",
    )
    pallas_protocol_shell_template_dir: str = Field(
        default="",
        description="自定义 shell 启动模板目录；留空使用插件内置模板。",
    )
    pallas_protocol_instances_root: str = Field(
        default="",
        description="所有协议账号实例的根目录；留空为 data/pallas_protocol/instances/。",
    )
    pallas_protocol_max_log_lines: int = Field(
        default=500,
        ge=100,
        le=5000,
        description="日志视图或下载接口单次返回的最大行数。",
    )
    pallas_protocol_webui_port_min: int = Field(
        default=6099,
        ge=1024,
        le=65534,
        description="为本机 NapCat WebUI 自动分配端口时的下限。",
    )
    pallas_protocol_webui_port_max: int = Field(
        default=7999,
        ge=1025,
        le=65535,
        description="为本机 NapCat WebUI 自动分配端口时的上限。",
    )
    pallas_protocol_github_token: str = Field(
        default="",
        description="GitHub 个人访问令牌（可选），用于提高 API 速率限额与私有资源访问。",
    )
    pallas_protocol_github_repo: str = Field(
        default_factory=default_release_repo_for_platform,
        description="NapCat 的 GitHub 仓库；留空按当前操作系统使用默认仓库。",
    )
    pallas_protocol_release_tag: str = Field(
        default="",
        description="NapCat Release 标签；留空表示使用 latest。",
    )
    pallas_protocol_release_asset: str = Field(
        default_factory=default_release_asset_for_platform,
        description="NapCat 下载资产文件名或 URL；留空按平台选择默认包。",
    )
    pallas_protocol_auto_download_runtime: bool = Field(
        default=False,
        description="检测到本地缺少运行时是否在后台自动下载 NapCat 等依赖。",
    )
    pallas_protocol_onebot_client_name: str = Field(
        default="",
        description="上报给 NoneBot 的 OneBot 连接名称；留空读取环境变量或默认 pallas。",
    )
    pallas_protocol_onebot_ws_url: str = Field(
        default="",
        description="Bot 连接 NapCat 的完整 WebSocket URL（若填写则不再拼接 host/port/path）。",
    )
    pallas_protocol_onebot_ws_host: str = Field(
        default="",
        description="未填完整 URL 时使用的 WebSocket 主机名或 IP。",
    )
    pallas_protocol_onebot_ws_port: int = Field(
        default=0,
        ge=0,
        le=65535,
        description="未填完整 URL 时使用的 WebSocket 端口；0 表示改用环境变量或 NoneBot 驱动端口。",
    )
    pallas_protocol_onebot_ws_path: str = Field(
        default="",
        description="WebSocket 路径；留空为 /onebot/v11/ws。",
    )
    pallas_protocol_linux_use_docker: bool = Field(
        default=False,
        description="在 Linux 上是否通过 Docker 启动 NapCat 容器。",
    )
    pallas_protocol_snowluma_linux_use_docker: bool = Field(
        default=False,
        description="在 Linux 上是否通过 Docker 启动 SnowLuma（可与 NapCat 独立配置）。",
    )
    pallas_protocol_linux_use_xvfb: bool = Field(
        default=True,
        description="Linux 非 Docker 场景下是否用 xvfb-run 提供虚拟显示。",
    )
    pallas_protocol_linux_xvfb_command: str = Field(
        default="xvfb-run",
        description="虚拟显示封装命令，一般为 xvfb-run。",
    )
    pallas_protocol_linux_xvfb_args: list[str] = Field(
        default_factory=lambda: ["--auto-servernum", "--server-args=-screen 0 1280x720x24"],
        description="传给 xvfb-run 等的参数列表。",
    )
    pallas_protocol_linux_appimage_args: list[str] = Field(
        default_factory=lambda: ["--appimage-extract-and-run"],
        description="运行 AppImage 时追加的参数（如解压再执行）。",
    )
    pallas_protocol_docker_image: str = Field(
        default="mlikiowa/napcat-docker:latest",
        description="拉取或启动 NapCat 时使用的 Docker 镜像名。",
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
        description="容器内 NapCat WebUI 监听端口（与端口映射配合）。",
    )
    pallas_protocol_follow_bot_lifecycle: bool = Field(
        default=True,
        description="是否在 NoneBot 连接/断开时自动启停对应协议实例。",
    )
    pallas_protocol_docker_network_mode: str = Field(
        default="bridge",
        description="Docker 网络模式：bridge（桥接）或 host（主机网络）。",
    )
    pallas_protocol_docker_uid: int | None = Field(
        default=None,
        description="映射到容器内用户的 UID（NAPCAT_UID）；留空由插件自动选择。",
    )
    pallas_protocol_docker_gid: int | None = Field(
        default=None,
        description="映射到容器内用户组的 GID（NAPCAT_GID）；留空由插件自动选择。",
    )
    pallas_protocol_snowluma_docker_image: str = Field(
        default="motricseven7/snowluma:latest",
        description="SnowLuma 容器使用的 Docker 镜像名。",
    )
    pallas_protocol_snowluma_docker_internal_webui_port: int = Field(
        default=5099,
        ge=1,
        le=65535,
        description="容器内 SnowLuma Web 控制台端口。",
    )
    pallas_protocol_snowluma_docker_internal_onebot_http_port: int = Field(
        default=3000,
        ge=1,
        le=65535,
        description="容器内 OneBot HTTP 服务端口。",
    )
    pallas_protocol_snowluma_docker_internal_onebot_ws_port: int = Field(
        default=3001,
        ge=1,
        le=65535,
        description="容器内 OneBot WebSocket 服务端口。",
    )
    pallas_protocol_snowluma_docker_shm_size: str = Field(
        default="1g",
        description="Docker --shm-size，增大可减少浏览器类组件崩溃。",
    )
    pallas_protocol_snowluma_docker_vnc_passwd: str = Field(
        default="",
        description="容器内 VNC 访问密码（VNC_PASSWD）；空则使用镜像默认或关闭认证策略依镜像而定。",
    )
    pallas_protocol_snowluma_docker_host_novnc_port: int = Field(
        default=0,
        ge=0,
        le=65535,
        description="映射到宿主机的 noVNC 端口；0 表示不映射。",
    )
    pallas_protocol_snowluma_docker_host_vnc_port: int = Field(
        default=0,
        ge=0,
        le=65535,
        description="映射到宿主机的原生 VNC 端口；0 表示不映射。",
    )
    pallas_protocol_snowluma_docker_internal_novnc_port: int = Field(
        default=6081,
        ge=1,
        le=65535,
        description="容器内 noVNC Web 端口。",
    )
    pallas_protocol_snowluma_docker_internal_vnc_port: int = Field(
        default=5900,
        ge=1,
        le=65535,
        description="容器内 VNC 服务端口。",
    )
    pallas_protocol_snowluma_docker_auto_bind_port_lo: int = Field(
        default=17100,
        ge=1024,
        le=65533,
        description="SnowLuma 多实例时，在宿主机上为 OneBot HTTP/WS 自动挑选端口的扫描下限。",
    )
    pallas_protocol_snowluma_docker_auto_bind_port_hi: int = Field(
        default=19998,
        ge=1026,
        le=65535,
        description="上述自动端口的扫描上限；HTTP 与 WS 成对占用相邻端口。",
    )
    pallas_protocol_snowluma_docker_auto_aux_bind_lo: int = Field(
        default=23100,
        ge=1024,
        le=65534,
        description="自动映射 noVNC/VNC 到宿主机时使用的端口区间下限。",
    )
    pallas_protocol_snowluma_docker_auto_aux_bind_hi: int = Field(
        default=29998,
        ge=1026,
        le=65535,
        description="自动映射 noVNC/VNC 到宿主机时使用的端口区间上限。",
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


def resolve_onebot_ws_settings(config: Config, *, bot_id: str = "") -> tuple[str, str, str]:
    """默认返回 hub/全局 WS；分片开启且提供 ``bot_id`` 时返回该牛所在 worker 的 WS。"""
    if bot_id:
        try:
            from src.common.shard.registry.config import is_sharding_active
            from src.common.shard.registry.store import resolve_onebot_ws_url_for_bot

            if is_sharding_active():
                url, name, tok = resolve_onebot_ws_url_for_bot(
                    bot_id,
                    name=str(getattr(config, "pallas_protocol_onebot_client_name", "") or "").strip()
                    or _ob_env_first("PALLAS_PROTOCOL_ONEBOT_CLIENT_NAME", "ONEBOT_CLIENT_NAME")
                    or "pallas",
                    token=_ob_env_first("ACCESS_TOKEN") or _ob_driver_first("access_token"),
                )
                if url:
                    return url, name, tok
        except Exception:
            pass
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
