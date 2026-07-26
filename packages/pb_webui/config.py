"""Pallas-Bot 控制台：与主程序分离的 Web 前端，通过本插件挂载静态与 API；配置原因见主插件 __init__ 说明。"""

from typing import Literal

from pydantic import BaseModel, Field

from pallas.console.webui import install_hot_reload_config, plugin_config_proxy
from pallas.console.webui.field_help import field_help


def _ui(group: str, order: int, **extra: object) -> dict[str, object]:
    return {"ui_group": group, "ui_order": order, **extra}


class Config(BaseModel):
    pallas_webui_enabled: bool = Field(
        default=True,
        description=field_help(
            "是否为本牛牛提供网页控制台",
            "开启后可通过浏览器打开管理界面并调用相关接口",
            "关闭后无法访问控制台页面",
        ),
        json_schema_extra=_ui("基础", 10),
    )
    pallas_webui_http_base: str = Field(
        default="/pallas",
        description=field_help(
            "控制台在网址中的路径前缀",
            "一般填 /pallas，需与发布的前端包配置一致",
            "例如反代后访问地址为 https://域名/pallas/",
        ),
        json_schema_extra=_ui("基础", 20),
    )
    pallas_webui_frontend: Literal["vue", "react"] = Field(
        default="react",
        description=field_help(
            "控制台前端栈（同路径整包切换）",
            "react=data/pb_webui/public-react；vue=data/pb_webui/public",
            "修改后需重启牛牛；默认 react",
        ),
        json_schema_extra=_ui("基础", 30),
    )
    pallas_webui_dist_zip_url: str = Field(
        default="",
        description=field_help(
            "控制台前端压缩包的下载地址",
            "填 zip 文件的完整直链",
            "留空时程序会按下面三项从 GitHub 发布页自动拼下载地址",
        ),
        json_schema_extra=_ui("前端包", 10),
    )
    pallas_webui_dist_zip_repo: str = Field(
        default="PallasBot/Pallas-Bot",
        description=field_help(
            "自动下载前端时使用的 GitHub 仓库",
            "格式为 所有者/仓库名，例如 PallasBot/Pallas-Bot",
            "dist.zip 随主仓 Release 发布；仅在上面的 zip 直链留空时生效",
        ),
        json_schema_extra=_ui("前端包", 20),
    )
    pallas_webui_dist_zip_tag: str = Field(
        default="",
        description=field_help(
            "要下载的发布版本标签",
            "例如 v1.0.0；留空表示使用最新版 latest",
            "仅在上面的 zip 直链留空时生效",
        ),
        json_schema_extra=_ui("前端包", 30),
    )
    pallas_webui_dist_zip_asset: str = Field(
        default="dist.zip",
        description=field_help(
            "发布页里压缩包的文件名",
            "一般为 dist.zip，与 GitHub Release 上的资产名一致",
            "仅在上面的 zip 直链留空时生效",
        ),
        json_schema_extra=_ui("前端包", 40),
    )
    pallas_webui_cors: bool = Field(
        default=False,
        description=field_help(
            "是否允许浏览器从别的域名访问控制台接口",
            "仅在本机用 npm 开发前端、需要连远程牛牛时开启",
            "开启后必须同时填写下面的「允许的来源」列表",
        ),
        json_schema_extra=_ui("开发与跨域", 10),
    )
    pallas_webui_allowed_origins: list[str] = Field(
        default_factory=list,
        description=field_help(
            "允许跨域访问的前端地址列表",
            'JSON 数组，例如 ["http://localhost:5173"]',
            "留空且未开启跨域时不生效；列表里写 * 表示任意来源（不推荐生产环境）",
        ),
        json_schema_extra=_ui("开发与跨域", 20),
    )
    pallas_webui_dev_mode: bool = Field(
        default=False,
        description=field_help(
            "开发模式：临时跳过控制台登录校验",
            "仅在本机调试时开启；也可在控制台顶栏快速切换",
            "公网或生产环境务必关闭，否则任何人可改配置",
        ),
        json_schema_extra=_ui("开发与跨域", 30),
    )
    pallas_webui_log_lines_max: int = Field(
        default=20000,
        ge=50,
        le=20000,
        description=field_help(
            "控制台「运行日志」一次最多显示多少行",
            "填 50～20000 之间的整数；多台分片机器时会合并各机日志",
            "数值越大占用内存越多",
        ),
        json_schema_extra=_ui("日志", 10),
    )


def on_pallas_webui_config_reload(cfg: Config) -> None:
    from nonebot import logger

    from .console_meta_store import patch_console_meta

    dev_mode = bool(cfg.pallas_webui_dev_mode)
    frontend = str(cfg.pallas_webui_frontend or "react").strip().lower()
    if frontend not in ("vue", "react"):
        frontend = "react"
    patch_console_meta(pallas_webui_dev_mode=dev_mode, frontend=frontend)
    if dev_mode:
        logger.warning("Pallas-Bot 控制台: 已关闭 API 与静态页鉴权（仅限本机开发）")
    else:
        logger.info("Pallas-Bot 控制台: 已恢复控制台 API 与静态页鉴权")
    logger.info(
        "Pallas-Bot 控制台: frontend={}（静态目录在启动时绑定，切换栈请重启）",
        frontend,
    )


plugin_webui = install_hot_reload_config(
    Config,
    config_module=__name__,
    on_reload=on_pallas_webui_config_reload,
)
get_pallas_webui_config = plugin_webui.get
plugin_config = plugin_config_proxy(get_pallas_webui_config)
