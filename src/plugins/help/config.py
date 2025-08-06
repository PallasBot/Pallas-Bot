# 参考https://github.com/Monody-S/CustomMarkdownImage
# 在resource/styles/目录下也有放自定义教程
from pydantic import BaseModel


class StyleConfig(BaseModel):
    """样式配置"""

    name: str
    path: str


class Config(BaseModel, extra="ignore"):
    """帮助插件配置"""

    # 默认样式名称
    default_style: str = "style7"

    # 是否启用自定义样式
    enable_custom_style_loading: bool = True

    # 自定义样式配置列表
    # 路径应指向包含elements.json/yml和setting.json/yml的目录
    custom_styles: list[StyleConfig] = [StyleConfig(name="style7", path="resource/styles/经典")]

    # 忽略的插件列表
    ignored_plugins: list[str] = ["auto_accept", "callback", "block", "nonebot_plugin_apscheduler", "greeting"]


# 默认使用的样式名称
# 可选值包括:
# - "default" - 默认样式
# - "unicorn_sugar" - 独角兽Sugar风格，可爱系
# - "simple_beige" - 朴素米黄风格
# - "retro" - 最朴素的复古风格
# - 自定义的样式名称（在custom_styles中定义）
