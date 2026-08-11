"""Pallas-Bot 控制台：与主程序分离的 Web 前端，通过本插件挂载静态与 API；配置原因见主插件 __init__ 说明。"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

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
        default="PallasBot/Pallas-Bot-WebUI",
        description=field_help(
            "自动下载前端时使用的 GitHub 仓库",
            "格式为 所有者/仓库名，例如 PallasBot/Pallas-Bot-WebUI",
            "默认使用 WebUI 仓库 Release；仅在上面的 zip 直链留空时生效",
        ),
        json_schema_extra=_ui("前端包", 20),
    )

    @field_validator("pallas_webui_dist_zip_repo", mode="before")
    @classmethod
    def normalize_legacy_webui_dist_zip_repo(cls, value: object) -> object:
        from .manager import normalize_webui_dist_zip_repo

        return normalize_webui_dist_zip_repo(value)

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
    pallas_webui_auto_update_enabled: bool = Field(
        default=False,
        description=field_help(
            "是否自动更新控制台前端包",
            "开启后按共用调度从 GitHub Release 拉取 dist.zip；默认关闭",
            "推荐在「更新」页统一配置",
        ),
        json_schema_extra=_ui("自动更新", 10),
    )
    pallas_bot_update_track: Literal["release", "branch"] = Field(
        default="release",
        description=field_help(
            "Bot 本体更新轨道",
            "release=只跟 GitHub 正式版 tag；branch=git pull 跟踪分支最新提交",
            "推荐在「更新」页切换；Docker 镜像部署仍需自行拉镜像",
        ),
        json_schema_extra=_ui("自动更新", 11),
    )
    pallas_bot_update_branch: str = Field(
        default="dev",
        description=field_help(
            "分支轨道跟踪的分支名",
            "仅「branch」轨道生效；仅允许 dev 或 main（控制台下拉同限）",
            "默认 dev，始终跟开发线 tip；稳定线选 main",
        ),
        json_schema_extra=_ui("自动更新", 12),
    )
    pallas_bot_auto_update_enabled: bool = Field(
        default=False,
        description=field_help(
            "是否自动更新 Bot 本体",
            "release 仅干净正式版自动 checkout 新 tag；branch 可对 git 副本自动 pull（排除 Docker）",
            "推荐在「更新」页统一配置",
        ),
        json_schema_extra=_ui("自动更新", 13),
    )
    pallas_plugins_auto_update_enabled: bool = Field(
        default=False,
        description=field_help(
            "是否自动更新已安装插件",
            "对有新版本的官方扩展与社区插件执行更新，完成后尝试安排重启",
            "推荐在「更新」页统一配置",
        ),
        json_schema_extra=_ui("自动更新", 14),
    )
    pallas_auto_update_notify_superusers: bool = Field(
        default=False,
        description=field_help(
            "自动更新成功后私聊超管",
            "有目标成功应用时，用指定牛（或任一头在线牛）私聊通知 SUPERUSERS",
            "默认关闭；失败不私聊以免刷屏",
        ),
        json_schema_extra=_ui("自动更新", 16),
    )
    pallas_auto_update_notify_bot_id: int = Field(
        default=0,
        ge=0,
        description=field_help(
            "汇报用牛牛 QQ",
            "发私聊通知时使用的 Bot 账号；填 0 表示任选当前在线的一头牛",
            "指定号必须在线，否则跳过本次汇报",
        ),
        json_schema_extra=_ui("自动更新", 17),
    )
    pallas_webui_auto_update_schedule_mode: Literal["interval", "cron"] = Field(
        default="interval",
        description=field_help(
            "自动更新的共用调度方式",
            "interval=按间隔；cron=每天定时（机器本地时区）；WebUI / Bot / 插件共用",
            "任一自动更新开启时生效",
        ),
        json_schema_extra=_ui("自动更新", 20),
    )
    pallas_webui_auto_update_interval_hours: int = Field(
        default=6,
        ge=1,
        le=168,
        description=field_help(
            "按间隔自动检查的小时数",
            "1～168；调度方式为间隔时生效（各目标共用）",
            "例如 6 表示大约每 6 小时检查一次",
        ),
        json_schema_extra=_ui("自动更新", 30),
    )
    pallas_webui_auto_update_cron_hour: int = Field(
        default=4,
        ge=0,
        le=23,
        description=field_help(
            "每天定时检查的小时（0～23）",
            "调度方式为每天定时时生效；按机器本地时区（各目标共用）",
            "例如 4 表示凌晨 4 点",
        ),
        json_schema_extra=_ui("自动更新", 40),
    )
    pallas_webui_auto_update_cron_minute: int = Field(
        default=0,
        ge=0,
        le=59,
        description=field_help(
            "每天定时检查的分钟（0～59）",
            "调度方式为每天定时时生效（各目标共用）",
            "与上面的小时组成每天 HH:MM",
        ),
        json_schema_extra=_ui("自动更新", 50),
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
        logger.warning("[控制台] 已关闭 API 与静态页鉴权（仅限本机开发）")
    else:
        logger.info("[控制台] 已恢复控制台 API 与静态页鉴权")
    logger.info(
        "[控制台] frontend={}（静态目录在启动时绑定，切换栈请重启）",
        frontend,
    )
    try:
        from .webui_auto_update import reschedule_webui_auto_update_job

        reschedule_webui_auto_update_job(cfg)
    except Exception:  # noqa: BLE001
        logger.exception("[控制台] 重载 WebUI 自动更新调度失败")


plugin_webui = install_hot_reload_config(
    Config,
    config_module=__name__,
    on_reload=on_pallas_webui_config_reload,
)
get_pallas_webui_config = plugin_webui.get
plugin_config = plugin_config_proxy(get_pallas_webui_config)
