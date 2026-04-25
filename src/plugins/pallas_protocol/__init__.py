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
    description="提供协议端账号管理与启动控制页面。",
    usage="""
默认挂载：
/protocol/napcat

常用能力：
新增账号、启动/停止/重启账号、查看日志、同步配置

鉴权方式：
X-Pallas-Protocol-Token 或 ?token=
""".strip(),
    type="application",
    homepage="https://github.com/PallasBot/Pallas-Bot",
    supported_adapters={"~onebot.v11"},
    extra={
        "version": "0.3.0",
        "menu_data": [
            {
                "func": "协议端管理页",
                "trigger_method": "http",
                "trigger_condition": "/protocol/napcat",
                "brief_des": "管理协议账号与进程",
                "detail_des": "可在页面执行创建账号、启动、停止、重启与日志查看。",
            },
            {
                "func": "协议端 API",
                "trigger_method": "http",
                "trigger_condition": "/protocol/*",
                "brief_des": "提供协议管理接口",
                "detail_des": "提供账号、配置、运行时下载与状态查询接口。",
            },
        ],
    },
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
        logger.info(f"Pallas 协议端 | WebUI={base_u}{path}/")
    await manager.start_all_enabled_accounts()
