from nonebot import on_command
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, permission
from nonebot.internal.adapter import Event
from nonebot.permission import Permission

from src.common.cmd_perm import satisfies_command_permission
from src.common.config import GroupConfig
from src.common.service_probe import format_probe_text

from .probe_collect import probe_all_connectivity

CONNECTIVITY_COOLDOWN_KEY = "connectivity_probe_command"


def group_message_connectivity_permission() -> Permission:
    async def _checker(bot: Bot, event: Event) -> bool:
        if not await permission.GROUP(bot, event):
            return False
        return await satisfies_command_permission(
            bot,
            event,
            "connectivity.probe",
        ) or await satisfies_command_permission(bot, event, "pallas_image.gateway")

    return Permission(_checker)


connectivity_probe = on_command(
    "牛牛连通",
    priority=5,
    block=True,
    permission=group_message_connectivity_permission(),
)

connectivity_gateway_alias = on_command(
    "牛牛网关",
    priority=5,  # 与 pallas_image_min_priority 默认一致，避免加载期 import pallas_image
    block=True,
    permission=group_message_connectivity_permission(),
)


async def run_connectivity_probe(matcher) -> None:
    results = await probe_all_connectivity()
    if not results:
        await matcher.finish("未配置可探测的服务端点。")
    await matcher.finish(format_probe_text(results))


@connectivity_probe.handle()
async def connectivity_probe_handle(event: GroupMessageEvent) -> None:
    config = GroupConfig(event.group_id, cooldown=3)
    if not await config.is_cooldown(CONNECTIVITY_COOLDOWN_KEY):
        return
    await config.refresh_cooldown(CONNECTIVITY_COOLDOWN_KEY)
    await run_connectivity_probe(connectivity_probe)


@connectivity_gateway_alias.handle()
async def connectivity_gateway_alias_handle(event: GroupMessageEvent) -> None:
    config = GroupConfig(event.group_id, cooldown=3)
    if not await config.is_cooldown(CONNECTIVITY_COOLDOWN_KEY):
        return
    await config.refresh_cooldown(CONNECTIVITY_COOLDOWN_KEY)
    await run_connectivity_probe(connectivity_gateway_alias)
