# 帮助图 Markdown 渲染
from pydantic import BaseModel, Field

from pallas.console.webui import install_hot_reload_config, plugin_config_proxy
from pallas.console.webui.field_help import field_help


class StyleConfig(BaseModel):
    """样式配置"""

    name: str = Field(
        description=field_help("帮助图样式的内部名称", "英文或拼音标识，需在默认样式名等处引用"),
    )
    path: str = Field(
        description=field_help(
            "样式资源所在的文件夹",
            "相对或绝对路径；目录里需包含 elements 与 setting 的配置文件（json 或 yml）",
        ),
    )


class Config(BaseModel, extra="ignore"):
    """帮助插件配置"""

    default_style: str = Field(
        default="pallas_default",
        description=field_help(
            "用户未指定样式时默认用哪一套",
            "填样式列表里的 name，例如 pallas_default",
        ),
    )
    enable_custom_style_loading: bool = Field(
        default=True,
        description=field_help(
            "是否加载「自定义样式」列表里的额外样式",
            "关闭则只使用「内置样式」列表中的项",
        ),
    )
    default_styles: list[StyleConfig] = Field(
        default_factory=lambda: [StyleConfig(name="pallas_default", path="resource/styles/default")],
        description=field_help(
            "内置自带的帮助图样式",
            "JSON 数组，每项含 name 与 path；一般保持默认即可",
        ),
    )
    custom_styles: list[StyleConfig] = Field(
        default_factory=list,
        description=field_help(
            "你自己添加的帮助图样式",
            "JSON 数组，每项指向一个完整样式目录",
            "需开启上一项「允许加载自定义样式」",
        ),
    )
    side_paint_enabled: bool = Field(
        default=False,
        description=field_help(
            "是否在帮助图一侧显示角色立绘",
            "开启使用 imgs 目录下的立绘；关闭则用样式里自带的叠图方式",
        ),
    )
    side_paint_filename: str = Field(
        default="character.png",
        description=field_help(
            "立绘图片的文件名",
            "放在对应样式资源目录下，例如 character.png",
        ),
    )
    side_paint_scale: float = Field(
        default=1.25,
        description=field_help(
            "立绘在成图前的放大倍数",
            "填小数，例如 1.25；最终高度仍会按版式再缩放",
        ),
    )
    side_paint_auto_page: bool = Field(
        default=False,
        description=field_help(
            "长帮助文是否自动分页",
            "开启后按版式比例拆成多页，适合立绘模式下的长说明",
        ),
    )
    ignored_plugins: list[str] = Field(
        default=[
            "nonebot-plugin-alconna",
            "nonebot_plugin_apscheduler",
            "nonebot_plugin_waiter",
            "uniseg",
            "callback",
            "block",
        ],
        description=field_help(
            "生成帮助菜单时不展示哪些插件",
            "JSON 字符串数组，填插件模块名",
            "用于隐藏框架或内部插件，避免菜单过长",
        ),
    )


def on_help_config_reload(cfg: Config) -> None:
    from packages.help.plugin_availability import invalidate_plugin_help_availability_cache
    from packages.help.renderer import invalidate_help_image_cache_suffix
    from packages.help.style_cache import refresh_style_cache

    invalidate_plugin_help_availability_cache()
    invalidate_help_image_cache_suffix()
    refresh_style_cache(cfg)


plugin_webui = install_hot_reload_config(
    Config,
    config_module=__name__,
    on_reload=on_help_config_reload,
)
get_help_config = plugin_webui.get
reload_help_config = plugin_webui.reload
plugin_config = plugin_config_proxy(get_help_config)
