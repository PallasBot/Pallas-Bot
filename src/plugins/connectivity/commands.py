from nonebot import on_command
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent, permission
from nonebot.internal.adapter import Event
from nonebot.permission import Permission

from src.features.cmd_perm import satisfies_command_permission
from src.features.command_limits import is_command_cooldown_ready, refresh_command_cooldown
from src.shared.service_probe import format_probe_text

from .probe_collect import probe_all_connectivity


def connectivity_message_permission() -> Permission:
    async def _checker(bot: Bot, event: Event) -> bool:
        is_group = await permission.GROUP(bot, event)
        is_private = await permission.PRIVATE(bot, event)
        if not (is_group or is_private):
            return False
        return await satisfies_command_permission(
            bot,
            event,
            "connectivity.probe",
        ) or await satisfies_command_permission(bot, event, "draw.gateway")

    return Permission(_checker)


connectivity_probe = on_command(
    "牛牛连通",
    priority=5,
    block=True,
    permission=connectivity_message_permission(),
)

connectivity_gateway_alias = on_command(
    "牛牛网关",
    priority=5,  # 与 pallas_image_min_priority 默认一致，避免加载期 import draw
    block=True,
    permission=connectivity_message_permission(),
)


async def run_connectivity_probe(matcher) -> None:
    results = await probe_all_connectivity()
    if not results:
        await matcher.finish("未配置可探测的服务端点。")
    await matcher.finish(format_probe_text(results))


async def handle_connectivity_probe(event: MessageEvent, matcher) -> None:
    if isinstance(event, GroupMessageEvent):
        if not await is_command_cooldown_ready(event, "connectivity.probe"):
            return
        await refresh_command_cooldown(event, "connectivity.probe")
    await run_connectivity_probe(matcher)


@connectivity_probe.handle()
async def connectivity_probe_handle(event: MessageEvent) -> None:
    await handle_connectivity_probe(event, connectivity_probe)


@connectivity_gateway_alias.handle()
async def connectivity_gateway_alias_handle(event: MessageEvent) -> None:
    await handle_connectivity_probe(event, connectivity_gateway_alias)
