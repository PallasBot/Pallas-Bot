# 参考https://github.com/Monody-S/CustomMarkdownImage
from pydantic import BaseModel, Field

from src.common.webui import install_hot_reload_config, plugin_config_proxy


class StyleConfig(BaseModel):
    """样式配置"""

    name: str = Field(description="样式标识名，在 default_style 等处引用。")
    path: str = Field(description="样式资源目录，需含 elements.json/yml 与 setting.json/yml。")


class Config(BaseModel, extra="ignore"):
    """帮助插件配置"""

    default_style: str = Field(
        default="pallas_default",
        description="未指定样式时使用的默认样式名。",
    )
    enable_custom_style_loading: bool = Field(
        default=True,
        description="是否允许从磁盘加载 custom_styles 中的额外样式。",
    )
    default_styles: list[StyleConfig] = Field(
        default_factory=lambda: [StyleConfig(name="pallas_default", path="resource/styles/default")],
        description="内置默认可用样式列表（名称与目录路径）。",
    )
    custom_styles: list[StyleConfig] = Field(
        default_factory=list,
        description="用户追加样式列表，路径指向完整样式目录。",
    )
    side_paint_enabled: bool = Field(
        default=False,
        description="是否使用独立立绘（imgs）渲染；关闭时用语义元素中的叠图方式。",
    )
    side_paint_filename: str = Field(
        default="character.png",
        description="立绘目录下使用的文件名。",
    )
    side_paint_scale: float = Field(
        default=1.25,
        description="传入渲染库前对立绘做的像素倍率（正文高度仍会二次缩放）。",
    )
    side_paint_auto_page: bool = Field(
        default=False,
        description="是否按接近黄金比例自动分页长文（与立绘模式联动）。",
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
        description="生成帮助菜单时忽略的插件模块名列表。",
    )


def on_help_config_reload(cfg: Config) -> None:
    import src.plugins.help as help_pkg

    help_pkg.refresh_style_cache(cfg)


plugin_webui = install_hot_reload_config(
    Config,
    config_module=__name__,
    on_reload=on_help_config_reload,
)
get_help_config = plugin_webui.get
reload_help_config = plugin_webui.reload
plugin_config = plugin_config_proxy(get_help_config)
