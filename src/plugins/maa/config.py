from pydantic import BaseModel, Field

from src.common.webui import install_hot_reload_config


class Config(BaseModel, extra="ignore"):
    maa_public_base_url: str = Field(
        default="",
        description=(
            "MAA 客户端可访问的对外基址（含 http/https，末尾勿加斜杠），如 https://nb.example.com。"
            "一般仅配置此项即可：会与默认路径拼成 getTask / reportStatus 完整 URL（见帮助与绑定提示）。"
            "分片时请填 hub 对外地址；未填时按 hub 端口推断。单进程未填则回退本机 host/port。"
        ),
    )
    maa_get_task_endpoint: str = Field(
        default="",
        description=(
            "（可选）获取任务完整 URL；留空则使用 maa_public_base_url + maa_get_task_path。"
            "仅当基址+路径无法满足（反代路径特殊等）时再填。"
        ),
    )
    maa_report_status_endpoint: str = Field(
        default="",
        description=(
            "（可选）汇报任务完整 URL；留空则使用 maa_public_base_url + maa_report_status_path。"
            "仅当基址+路径无法满足时再填。"
        ),
    )
    maa_get_task_path: str = Field(
        default="/maa/getTask",
        description=(
            "获取任务相对路径（POST JSON）；与 maa_public_base_url 拼接。使用默认路由时无需修改，仅配置基址即可。"
        ),
    )
    maa_report_status_path: str = Field(
        default="/maa/reportStatus",
        description=(
            "汇报任务相对路径（POST JSON）；与 maa_public_base_url 拼接。使用默认路由时无需修改，仅配置基址即可。"
        ),
    )
    maa_attach_screenshot: bool = Field(
        default=True,
        description="用户下发指令后是否默认再排队一张截图任务。",
    )
    maa_seen_ttl_seconds: int = Field(
        default=86400,
        description="未绑定设备在内存中的保留时长（秒），超时需重新让 MAA 连一次再绑定。",
    )
    maa_combat_auto_prepare: bool = Field(
        default=True,
        description="牛牛作战前是否自动排队 Settings-Stage1（写入已保存的主关卡候选）。",
    )


def on_maa_config_reload(cfg: Config) -> None:  # noqa: ARG001
    from nonebot import get_app

    from .http_routes import remount_maa_http_routes

    remount_maa_http_routes(get_app())
    try:
        from src.plugins.help.plugin_manager import clear_help_cache

        clear_help_cache()
    except Exception:
        pass


plugin_webui = install_hot_reload_config(
    Config,
    config_module=__name__,
    on_reload=on_maa_config_reload,
)
get_maa_config = plugin_webui.get
reload_maa_config = plugin_webui.reload
clear_maa_config_cache = plugin_webui.clear_cache
