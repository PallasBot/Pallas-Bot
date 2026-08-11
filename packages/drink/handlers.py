from nonebot import on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.rule import Rule

from pallas.api.perm import group_message_permission_for_command
from pallas.core.platform.ingress.matcher_rule_prefilter import mark_exact_plaintext_rule

from . import service


@mark_exact_plaintext_rule("牛牛喝酒", "牛牛干杯", "牛牛继续喝")
async def is_drink_msg(event: GroupMessageEvent) -> bool:
    return event.get_plaintext().strip() in {"牛牛喝酒", "牛牛干杯", "牛牛继续喝"}


drink_msg = on_message(
    rule=Rule(is_drink_msg),
    priority=5,
    block=True,
    permission=group_message_permission_for_command("drink.drink"),
)


@drink_msg.handle()
async def handle_drink(event: GroupMessageEvent):
    await service.drink(event, drink_msg.send)


@mark_exact_plaintext_rule("牛牛醒一醒", "牛牛别喝了")
async def is_sober_up_msg(event: GroupMessageEvent) -> bool:
    return event.get_plaintext().strip() in {"牛牛醒一醒", "牛牛别喝了"}


sober_up_msg = on_message(
    rule=Rule(is_sober_up_msg),
    priority=5,
    block=True,
    permission=group_message_permission_for_command("drink.sober_up"),
)


@sober_up_msg.handle()
async def handle_sober_up(event: GroupMessageEvent):
    await service.sober_up(event, sober_up_msg.send)
