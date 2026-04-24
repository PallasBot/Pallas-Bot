# ruff: noqa: E501
import logging

from nonebot import get_app, get_driver, get_plugin_config, logger
from nonebot.plugin import PluginMetadata

from src.common.paths import plugin_data_dir
from src.common.web import public_base_url

from .config import Config, resolve_protocol_webui_base_path
from .service import PallasProtocolService
from .web import register_pallas_protocol_routes

__plugin_meta__ = PluginMetadata(
    name="Pallas 协议端",
    description="通过 /protocol/<实现名> 管理协议端；实现名默认见 contract.DEFAULT_PROTOCOL_BACKEND，可用 pallas_protocol_web_implementation 覆盖",
    usage="""
默认挂载 /protocol/<实现>/…（实现默认同 DEFAULT_PROTOCOL_BACKEND）；也可用 pallas_protocol_webui_path 整段覆盖。
鉴权：X-Pallas-Protocol-Token 或 ?token=（若已配置 pallas_protocol_token）
""".strip(),
    type="application",
    homepage="https://github.com/PallasBot/Pallas-Bot",
    supported_adapters={"~onebot.v11"},
    extra={"version": "0.3.0"},
)

plugin_config = get_plugin_config(Config)
app = get_app()
driver = get_driver()
manager = PallasProtocolService(plugin_data_dir("pallas_protocol"), plugin_config)

register_pallas_protocol_routes(app, manager=manager, plugin_config=plugin_config)


@driver.on_startup
async def _startup() -> None:
    if not plugin_config.pallas_protocol_enabled:
        return
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    await manager.initialize()
    if plugin_config.pallas_protocol_webui_enabled:
        dconf = get_driver().config
        base_u = public_base_url(
            host=getattr(dconf, "host", None),
            port=getattr(dconf, "port", None),
        )
        path = resolve_protocol_webui_base_path(plugin_config)
        logger.info(f"Pallas 协议端（浏览器）: {base_u}{path}/")
    await manager.start_all_enabled_accounts()
