from pydantic import BaseModel, Field

from src.console.webui import install_hot_reload_config
from src.console.webui.field_help import field_help


class Config(BaseModel, extra="ignore"):
    maa_public_base_url: str = Field(
        default="",
        description=field_help(
            "手机或模拟器上的 MAA 要能访问到的牛牛对外网址",
            "填 https://你的域名，末尾不要加斜杠；程序会自动拼「取任务」「报状态」两条路径",
            "多台牛牛分片时请填总机对外地址；单台本机部署可留空由程序推断",
        ),
    )
    maa_get_task_endpoint: str = Field(
        default="",
        description=field_help(
            "「取任务」接口的完整网址（高级）",
            "只有反代路径很特殊、无法靠「对外网址 + 相对路径」拼出来时才填",
            "留空即可",
        ),
    )
    maa_report_status_endpoint: str = Field(
        default="",
        description=field_help(
            "「报状态」接口的完整网址（高级）",
            "与上一项相同，一般留空",
        ),
    )
    maa_get_task_path: str = Field(
        default="/maa/getTask",
        description=field_help(
            "取任务接口在网址后面的路径",
            "默认 /maa/getTask，与牛牛内置路由一致时无需修改",
        ),
    )
    maa_report_status_path: str = Field(
        default="/maa/reportStatus",
        description=field_help(
            "报状态接口在网址后面的路径",
            "默认 /maa/reportStatus，一般无需修改",
        ),
    )
    maa_attach_screenshot: bool = Field(
        default=True,
        description=field_help(
            "用户发 MAA 相关指令后是否默认再截一张图",
            "开启便于在群里看到当前界面；不需要截图可关闭",
        ),
    )
    maa_seen_ttl_seconds: int = Field(
        default=86400,
        description=field_help(
            "未绑定设备在内存里保留多久（秒）",
            "例如 86400 表示一天；超时后需要让 MAA 再连一次完成绑定",
        ),
    )
    maa_combat_auto_prepare: bool = Field(
        default=True,
        description=field_help(
            "「牛牛作战」前是否自动准备关卡设置",
            "开启会先排队 Settings-Stage1，使用你已保存的主关卡候选",
        ),
    )


def on_maa_config_reload(cfg: Config) -> None:  # noqa: ARG001
    from nonebot import get_app

    from src.platform.bot_runtime.roles import is_hub_role
    from src.platform.shard import context as shard_ctx

    app = get_app()
    if is_hub_role():
        from src.platform.shard.coord.maa_hub_routes import remount_maa_hub_forward_routes

        from .http_routes import unmount_maa_http_routes

        unmount_maa_http_routes(app)
        remount_maa_hub_forward_routes(app)
    elif not shard_ctx.sharding_active() or shard_ctx.is_worker():
        from .http_routes import remount_maa_http_routes

        remount_maa_http_routes(app)
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
