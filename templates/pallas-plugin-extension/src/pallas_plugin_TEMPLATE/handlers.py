from pallas.api.commands import PluginHandlerContext

from .config import get_config


async def handle_template(context: PluginHandlerContext) -> None:
    cfg = get_config()
    if not cfg.template_enable:
        await context.finish("模板开关已关闭。")
    await context.finish("模板命令已生效。")
