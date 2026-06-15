from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.console.webui import install_hot_reload_config, plugin_config_proxy
from src.console.webui.field_help import field_help

from .contract import resolve_public_mount_path
from .runtime.installer import default_release_asset_for_platform, default_release_repo_for_platform


class Config(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pallas_protocol_enabled: bool = Field(
        default=True,
        description=field_help(
            "是否启用 QQ 协议端管理功能",
            "开启后可在控制台管理 NapCat、SnowLuma 等登录实例",
        ),
    )
    pallas_protocol_webui_enabled: bool = Field(
        default=True,
        description=field_help(
            "是否提供协议端的网页管理界面",
            "关闭后仍可用牛牛命令，但浏览器里打不开协议端页面",
        ),
    )
    pallas_protocol_web_implementation: str = Field(
        default="",
        description=field_help(
            "使用哪一套协议端网页实现",
            "一般留空即可；高级用户可填实现标识，对应 /protocol/标识 路径",
        ),
    )
    pallas_protocol_webui_path: str = Field(
        default="",
        description=field_help(
            "完全自定义协议网页的挂载路径",
            "非空时覆盖默认路径；不懂请留空",
        ),
    )

    pallas_protocol_bind_host: str = Field(
        default="127.0.0.1",
        description=field_help(
            "协议相关本地服务监听哪个网卡",
            "仅本机访问用 127.0.0.1；需局域网访问可改为 0.0.0.0",
        ),
    )
    pallas_protocol_default_command: str = Field(
        default="node",
        description=field_help(
            "启动 NapCat 时使用的命令",
            "一般为 node，表示用 Node.js 运行",
        ),
    )
    pallas_protocol_default_args: list[str] = Field(
        default_factory=lambda: ["napcat.mjs"],
        description=field_help(
            "启动命令后面跟的参数",
            "JSON 数组，默认包含 napcat.mjs 入口脚本",
        ),
    )
    pallas_protocol_program_dir: str = Field(
        default="",
        description=field_help(
            "NapCat 程序解压后的根目录",
            "留空时程序会尝试自动下载或使用内置路径",
        ),
    )
    pallas_protocol_snowluma_program_dir: str = Field(
        default="",
        description=field_help(
            "SnowLuma 程序根目录",
            "留空则使用资源包或每个账号单独配置的目录",
        ),
    )
    pallas_protocol_snowluma_github_repo: str = Field(
        default="SnowLuma/SnowLuma",
        description=field_help(
            "从网上下载 SnowLuma 时使用的 GitHub 仓库",
            "格式：所有者/仓库名",
        ),
    )
    pallas_protocol_snowluma_release_tag: str = Field(
        default="",
        description=field_help(
            "要下载的 SnowLuma 版本号",
            "留空表示最新版",
        ),
    )
    pallas_protocol_snowluma_release_asset: str = Field(
        default="",
        description=field_help(
            "发布包文件名或直链",
            "留空则按当前系统自动选默认包",
        ),
    )
    pallas_protocol_default_working_dir: str = Field(
        default="",
        description=field_help(
            "启动子进程时的工作目录",
            "留空使用每个实例数据目录下的默认位置",
        ),
    )
    pallas_protocol_shell_template_dir: str = Field(
        default="",
        description=field_help(
            "自定义启动脚本模板所在文件夹",
            "留空使用插件自带模板",
        ),
    )
    pallas_protocol_instances_root: str = Field(
        default="",
        description=field_help(
            "所有 QQ 协议账号数据放在哪个总目录",
            "留空为 data/pallas_protocol/instances/",
        ),
    )
    pallas_protocol_max_log_lines: int = Field(
        default=500,
        ge=100,
        le=5000,
        description=field_help(
            "协议端日志一次最多显示多少行",
            "填 100～5000 的整数",
        ),
    )
    pallas_protocol_webui_port_min: int = Field(
        default=6099,
        ge=1024,
        le=65534,
        description=field_help(
            "自动分配 NapCat 网页端口时的最小值",
            "与下一项一起构成可用端口范围",
        ),
    )
    pallas_protocol_webui_port_max: int = Field(
        default=7999,
        ge=1025,
        le=65535,
        description=field_help(
            "自动分配 NapCat 网页端口时的最大值",
            "需大于上一项",
        ),
    )
    pallas_protocol_github_token: str = Field(
        default="",
        description=field_help(
            "访问 GitHub 下载发布包用的令牌",
            "可选；填写后可减少限流、支持私有仓库",
        ),
    )
    pallas_protocol_github_repo: str = Field(
        default_factory=default_release_repo_for_platform,
        description=field_help(
            "下载 NapCat 时使用的 GitHub 仓库",
            "留空则按操作系统选默认仓库",
        ),
    )
    pallas_protocol_release_tag: str = Field(
        default="",
        description=field_help(
            "要下载的 NapCat 版本标签",
            "留空表示最新版",
        ),
    )
    pallas_protocol_release_asset: str = Field(
        default_factory=default_release_asset_for_platform,
        description=field_help(
            "NapCat 发布包文件名或下载直链",
            "留空按系统选默认安装包",
        ),
    )
    pallas_protocol_auto_download_runtime: bool = Field(
        default=False,
        description=field_help(
            "本地缺少 NapCat 时是否自动后台下载",
            "开启省事但需能访问 GitHub；关闭则需自行放置程序",
        ),
    )
    pallas_protocol_onebot_client_name: str = Field(
        default="",
        description=field_help(
            "协议端连接牛牛时使用的名称",
            "留空则用环境变量或默认名 pallas",
        ),
    )
    pallas_protocol_onebot_ws_url: str = Field(
        default="",
        description=field_help(
            "牛牛接收 QQ 消息的完整连接地址",
            "填 ws:// 开头的完整地址后，不再使用下面的主机、端口、路径三项",
        ),
    )
    pallas_protocol_onebot_ws_host: str = Field(
        default="",
        description=field_help(
            "未填完整地址时，牛牛监听的主机名或 IP",
            "例如 127.0.0.1",
        ),
    )
    pallas_protocol_onebot_ws_port: int = Field(
        default=0,
        ge=0,
        le=65535,
        description=field_help(
            "未填完整地址时，牛牛监听的端口",
            "填 0 表示使用环境变量或牛牛默认监听端口",
        ),
    )
    pallas_protocol_onebot_ws_path: str = Field(
        default="",
        description=field_help(
            "连接地址里的路径部分",
            "留空为 /onebot/v11/ws",
        ),
    )
    pallas_protocol_linux_use_docker: bool = Field(
        default=False,
        description=field_help(
            "在 Linux 上是否用 Docker 容器跑 NapCat",
            "熟悉 Docker 可开启；否则用本机直接运行",
        ),
    )
    pallas_protocol_snowluma_linux_use_docker: bool = Field(
        default=False,
        description=field_help(
            "在 Linux 上是否用 Docker 跑 SnowLuma",
            "可与 NapCat 分开设置",
        ),
    )
    pallas_protocol_linux_use_xvfb: bool = Field(
        default=True,
        description=field_help(
            "Linux 不用 Docker 时是否用虚拟显示器",
            "无图形界面服务器上一般需开启",
        ),
    )
    pallas_protocol_linux_xvfb_command: str = Field(
        default="xvfb-run",
        description=field_help(
            "虚拟显示器封装命令",
            "默认 xvfb-run，一般无需修改",
        ),
    )
    pallas_protocol_linux_xvfb_args: list[str] = Field(
        default_factory=lambda: ["--auto-servernum", "--server-args=-screen 0 1280x720x24"],
        description=field_help(
            "传给虚拟显示器命令的参数",
            "JSON 数组，默认分辨率 1280x720",
        ),
    )
    pallas_protocol_linux_appimage_args: list[str] = Field(
        default_factory=lambda: ["--appimage-extract-and-run"],
        description=field_help(
            "运行 AppImage 安装包时的额外参数",
            "默认会先解压再运行",
        ),
    )
    pallas_protocol_docker_image: str = Field(
        default="mlikiowa/napcat-docker:latest",
        description=field_help(
            "NapCat 使用的 Docker 镜像名称",
            "例如 mlikiowa/napcat-docker:latest",
        ),
    )
    pallas_protocol_docker_onebot_host: str = Field(
        default="",
        description=field_help(
            "容器里访问宿主机上牛牛用的地址",
            "留空或填 auto 由程序按网络模式自动选择；填 127.0.0.1 表示本机",
        ),
    )
    pallas_protocol_docker_internal_webui_port: int = Field(
        default=6099,
        ge=1,
        le=65535,
        description=field_help(
            "容器内部 NapCat 网页控制台端口",
            "需与 Docker 端口映射一致",
        ),
    )
    pallas_protocol_follow_bot_lifecycle: bool = Field(
        default=True,
        description=field_help(
            "牛牛启动/关闭时是否自动启停对应 QQ 实例",
            "开启便于无人值守；手动管理时可关闭",
        ),
    )
    pallas_protocol_docker_network_mode: str = Field(
        default="bridge",
        description=field_help(
            "Docker 网络模式",
            "bridge 为桥接（常用）；host 表示与宿主机共用网络",
        ),
    )
    pallas_protocol_docker_uid: int | None = Field(
        default=None,
        description=field_help(
            "容器内运行用户的数字 ID（UID）",
            "留空由程序自动选择，用于避免文件权限问题",
        ),
    )
    pallas_protocol_docker_gid: int | None = Field(
        default=None,
        description=field_help(
            "容器内用户组的数字 ID（GID）",
            "留空由程序自动选择",
        ),
    )
    pallas_protocol_docker_memory_limit: str = Field(
        default="",
        description=field_help(
            "NapCat Docker 容器内存上限",
            "例如 768m；留空表示不限制",
        ),
    )
    pallas_protocol_docker_memory_swap: str = Field(
        default="",
        description=field_help(
            "NapCat Docker 容器 memory+swap 总量",
            "例如 1g；需不小于内存上限；留空表示不单独设置",
        ),
    )
    pallas_protocol_docker_shm_size: str = Field(
        default="",
        description=field_help(
            "NapCat Docker 容器 /dev/shm 大小",
            "Electron 建议 256m 及以上；留空使用 Docker 默认 64m",
        ),
    )
    pallas_protocol_snowluma_docker_image: str = Field(
        default="motricseven7/snowluma:latest",
        description=field_help(
            "SnowLuma 使用的 Docker 镜像名称",
            "与 NapCat 镜像相互独立",
        ),
    )
    pallas_protocol_snowluma_docker_internal_webui_port: int = Field(
        default=5099,
        ge=1,
        le=65535,
        description=field_help(
            "容器内 SnowLuma 网页控制台端口",
            "映射到宿主机时需与此一致",
        ),
    )
    pallas_protocol_snowluma_docker_internal_onebot_http_port: int = Field(
        default=3000,
        ge=1,
        le=65535,
        description=field_help(
            "容器内 HTTP 方式连接牛牛的端口",
            "与下一项成对使用",
        ),
    )
    pallas_protocol_snowluma_docker_internal_onebot_ws_port: int = Field(
        default=3001,
        ge=1,
        le=65535,
        description=field_help(
            "容器内 WebSocket 方式连接牛牛的端口",
            "通常比 HTTP 端口大 1",
        ),
    )
    pallas_protocol_snowluma_docker_shm_size: str = Field(
        default="1g",
        description=field_help(
            "容器共享内存大小",
            "例如 1g；适当增大可减少浏览器组件崩溃",
        ),
    )
    pallas_protocol_snowluma_docker_vnc_passwd: str = Field(
        default="",
        description=field_help(
            "远程桌面（VNC）登录密码",
            "留空则使用镜像默认策略",
        ),
    )
    pallas_protocol_snowluma_docker_host_novnc_port: int = Field(
        default=0,
        ge=0,
        le=65535,
        description=field_help(
            "在宿主机上暴露网页版远程桌面的端口",
            "填 0 表示不映射到宿主机",
        ),
    )
    pallas_protocol_snowluma_docker_host_vnc_port: int = Field(
        default=0,
        ge=0,
        le=65535,
        description=field_help(
            "在宿主机上暴露原生 VNC 的端口",
            "填 0 表示不映射",
        ),
    )
    pallas_protocol_snowluma_docker_internal_novnc_port: int = Field(
        default=6081,
        ge=1,
        le=65535,
        description=field_help(
            "容器内网页版远程桌面端口",
            "与宿主机映射端口配合使用",
        ),
    )
    pallas_protocol_snowluma_docker_internal_vnc_port: int = Field(
        default=5900,
        ge=1,
        le=65535,
        description=field_help(
            "容器内 VNC 服务端口",
            "默认 5900",
        ),
    )
    pallas_protocol_snowluma_docker_auto_bind_port_lo: int = Field(
        default=17100,
        ge=1024,
        le=65533,
        description=field_help(
            "多开 SnowLuma 时自动分配牛牛连接端口的范围下限",
            "程序在范围内找空闲端口",
        ),
    )
    pallas_protocol_snowluma_docker_auto_bind_port_hi: int = Field(
        default=19998,
        ge=1026,
        le=65535,
        description=field_help(
            "自动分配牛牛连接端口的范围上限",
            "HTTP 与 WS 会占用相邻两个端口",
        ),
    )
    pallas_protocol_snowluma_docker_auto_aux_bind_lo: int = Field(
        default=23100,
        ge=1024,
        le=65534,
        description=field_help(
            "自动映射远程桌面到宿主机的端口范围下限",
            "多实例时避免端口冲突",
        ),
    )
    pallas_protocol_snowluma_docker_auto_aux_bind_hi: int = Field(
        default=29998,
        ge=1026,
        le=65535,
        description=field_help(
            "自动映射远程桌面到宿主机的端口范围上限",
            "需大于上一项",
        ),
    )

    def resolved_release_asset(self) -> str:
        asset = (self.pallas_protocol_release_asset or "").strip()
        return asset or default_release_asset_for_platform()


def on_pallas_protocol_config_reload(cfg: Config) -> None:
    try:
        import src.plugins.pallas_protocol as pkg

        mgr = getattr(pkg, "manager", None)
        if mgr is not None:
            mgr._config = cfg
    except Exception:
        pass


plugin_webui = install_hot_reload_config(
    Config,
    config_module=__name__,
    on_reload=on_pallas_protocol_config_reload,
)
get_pallas_protocol_config = plugin_webui.get
plugin_config = plugin_config_proxy(get_pallas_protocol_config)


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
            from src.platform.shard import context as shard_ctx
            from src.platform.shard.registry.store import resolve_onebot_ws_url_for_bot

            if shard_ctx.sharding_active():
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
