from nonebot.plugin import PluginMetadata

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="扩展插件模板",
    description="Pallas-Bot 4.0 官方扩展包模板。",
    usage="迁移完成后在 help 中展示；未安装时由主仓提示安装扩展包。",
    type="application",
    config=Config,
    supported_adapters={"~onebot.v11"},
)
