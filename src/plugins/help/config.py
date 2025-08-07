# 参考https://github.com/Monody-S/CustomMarkdownImage
from pydantic import BaseModel


class StyleConfig(BaseModel):
    """样式配置"""

    name: str
    path: str


class Config(BaseModel, extra="ignore"):
    """帮助插件配置"""

    # 默认样式名称
    default_style: str = "pallas_default"

    # 是否启用自定义样式
    enable_custom_style_loading: bool = True
    # 默认的style
    default_styles: list[StyleConfig] = [StyleConfig(name="pallas_default", path="resource/styles/default")]

    # 用户自定义样式配置列表
    # 路径应指向包含elements.json/yml和setting.json/yml的目录
    custom_styles: list[StyleConfig] = []

    # 忽略的插件列表
    ignored_plugins: list[str] = ["nonebot_plugin_apscheduler", "auto_accept", "callback", "block", "greeting"]


# 默认使用的样式名称
# 可选值包括:
# - "default" - 库自带默认样式
# - "unicorn_sugar" - 独角兽Sugar风格，可爱系
# - "simple_beige" - 朴素米黄风格
# - "retro" - 最朴素的复古风格
# - 自定义的样式名称（在custom_styles中定义）
