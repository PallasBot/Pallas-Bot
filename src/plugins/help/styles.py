from pathlib import Path

import pillowmd
from nonebot import get_plugin_config, logger

from .config import Config


def load_config() -> Config:
    """加载插件配置"""
    return get_plugin_config(Config)


def load_custom_styles(config) -> dict[str, object]:
    """根据配置加载自定义样式"""

    styles = {}

    for i in range(1, 6):
        styles[f"style{i}"] = getattr(pillowmd.SampleStyles, f"STYLE{i}")

    named_styles = {
        "unicorn_sugar": pillowmd.SampleStyles.STYLE1,  # 独角兽Sugar风格，可爱系
        "unicorn_gif": pillowmd.SampleStyles.STYLE2,  # 独角兽Suagar-GIF风格，GIF示例
        "function_bg": pillowmd.SampleStyles.STYLE3,  # 函数绘制背景示例
        "simple_beige": pillowmd.SampleStyles.STYLE4,  # 朴素米黄风格
        "retro": pillowmd.SampleStyles.STYLE5,  # 最朴素的复古风格
        "default": pillowmd.MdStyle(),  # 默认样式
    }
    styles.update(named_styles)

    # 加载内置默认样式
    if config.default_styles:
        _load_user_defined_styles(config.default_styles, styles)

    # 如果启用自定义样式加载且有配置的自定义样式
    if config.enable_custom_style_loading and config.custom_styles:
        _load_user_defined_styles(config.custom_styles, styles)

    return styles


def _load_user_defined_styles(custom_styles, styles_dict):
    """加载用户自定义样式"""
    for style_config in custom_styles:
        try:
            style_path = Path(style_config.path).resolve()
            if not style_path.exists():
                logger.warning(f"样式路径不存在 '{style_path}'")
                continue

            custom_style = pillowmd.LoadMarkdownStyles(style_path)
            styles_dict[style_config.name] = custom_style
        except Exception as e:
            logger.warning(f"无法加载样式 '{style_config.name}' 从路径 '{style_config.path}': {e}")


def get_default_style(config) -> str:
    """获取默认样式名称"""
    if config is None:
        config = get_plugin_config(Config)
    return config.default_style


HelpConfig = load_config()
