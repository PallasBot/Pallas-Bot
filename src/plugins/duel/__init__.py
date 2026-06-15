import re

from nonebot import get_driver, logger, on_message
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment, permission
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from nonebot.typing import T_State

from src.features.cmd_perm import group_message_permission_for_command
from src.features.cmd_perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from src.features.cmd_perm.metadata_text import SCENE_GROUP, join_usage, usage_line
from src.platform.ingress.policy_registry import text_matches_plugin_fanout
from src.plugins.duel import duel_penalty  # noqa: F401 — 注册惩罚消息 matcher
from src.plugins.duel.config import plugin_config
from src.plugins.duel.duel_bots import (
    duel_narrator_bot_id,
    infer_duel_defender_when_at_self_hidden,
    is_bot_qq,
    parse_duel_at_qqs,
    raw_message_has_at,
    resolve_duel_round_count,
)
from src.plugins.duel.duel_penalty import apply_duel_penalties
from src.plugins.duel.duel_qte import complete_duel_qte, duel_qte_exact_rule
from src.plugins.duel.duel_round_engine import (
    begin_duel_command,
    end_duel_group,
    play_duel_rounds,
    reload_event_pools,
    try_claim_duel_message,
    try_claim_duel_user_reply,
)
from src.plugins.duel.duel_session import clear_duel_pair, start_duel_pair


@get_driver().on_startup
async def _ensure_duel_arknights_resources() -> None:
    from src.shared.utils.arknights_duel_resource import schedule_arknights_duel_resource_sync

    schedule_arknights_duel_resource_sync(
        sync_json=plugin_config.duel_auto_sync_operators,
        bulk_avatars=plugin_config.duel_avatar_download_on_startup,
    )


__plugin_meta__ = PluginMetadata(
    name="牛牛决斗",
    description="泰拉风味多幕决斗，支持群友、双牛与八角笼。",
    usage=join_usage(
        usage_line("牛牛决斗 @对手 [N幕|N回合]", "与一名对手对决"),
        usage_line("牛牛决斗 @牛A @牛B", "指定两只牛牛对决"),
        usage_line("八角笼牛 [N幕|N回合]", "随机两只在线牛牛"),
        usage_line("决斗事件重载", "热更新剧情包与干员表"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "command_permissions": [
            {"id": "duel.duel", "label": "牛牛决斗", "default": "everyone"},
            {"id": "duel.cage", "label": "八角笼牛", "default": "everyone"},
            {
                "id": "duel.reload_events",
                "label": "决斗事件重载",
                "default": "group_moderator",
            },
        ],
        "command_limits": [
            {"id": "duel.duel", "cd_sec": 5},
            {"id": "duel.cage", "cd_sec": 5},
        ],
        "ingress_fanout": {
            "scope": "always",
            "regexes": [r"^八角笼(?:牛|斗)(?:\s*\d{1,2}\s*(?:幕|回合))?\s*$"],
        },
        "menu_data": [
            {
                "func": "牛牛决斗",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "牛牛决斗 @一名对手 [N幕|N回合]",
                "command_permission": "duel.duel",
                "brief_des": "发起多幕决斗",
                "detail_des": (
                    "挑战者 @ 一名决斗者即可开战；可在指令中带「N幕」或「N回合」（如 牛牛决斗 @对手 7幕），"
                    "不写幕数则使用插件默认场数；按终局血量判胜负，一方可先被 KO。"
                ),
            },
            {
                "func": "双牛决斗",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "牛牛决斗 @牛A @牛B [N幕|N回合]",
                "command_permission": "duel.duel",
                "brief_des": "指定两只牛牛同台对决",
                "detail_des": (
                    "两名被 @ 者须均为牛牛账号，规则与单人决斗相同，可附带 N幕/N回合；对战期间两头牛在本群互可见消息。"
                ),
            },
            {
                "func": "八角笼牛",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "八角笼牛 [N幕|N回合]",
                "command_permission": "duel.cage",
                "brief_des": "随机抽两只在线牛牛对决",
                "detail_des": (
                    "从本群当前在线的牛牛账号中随机配对开战，无需手动 @；"
                    "可在指令中带「N幕」或「N回合」（如 八角笼牛 7幕），不写则用默认场数。"
                ),
            },
            {
                "func": "决斗抢答",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "按幕面提示发干员名或关键词",
                "brief_des": "限时抢答影响血量",
                "detail_des": (
                    "幕面出现抢答时，在时限内发送正确干员全名或关键词可占优；"
                    "干员乱入须喊出正确名字，认错会挨技能。发错、超时同样失利。"
                    "牛牛参与时可能自动应答。"
                ),
            },
            {
                "func": "决斗事件重载",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "决斗事件重载",
                "command_permission": "duel.reload_events",
                "brief_des": "热更新泰拉剧情包与干员名单",
                "detail_des": ("立即重载 default 剧情包与干员表，并取消进行中的抢答。"),
            },
        ],
    },
)

BLOCK_LIST: list[int] = []


async def is_reload_duel_events(bot: Bot, event: GroupMessageEvent, state: T_State) -> bool:
    if event.group_id in BLOCK_LIST:
        return False
    return event.get_plaintext().strip() == "决斗事件重载"


async def is_duel_msg(bot: Bot, event: GroupMessageEvent, state: T_State) -> bool:
    if event.group_id in BLOCK_LIST:
        return False
    return event.get_plaintext().strip().startswith("牛牛决斗")


async def is_cage_msg(bot: Bot, event: GroupMessageEvent, state: T_State) -> bool:
    if event.group_id in BLOCK_LIST:
        return False
    return text_matches_plugin_fanout(event.get_plaintext(), "duel")


duel_msg = on_message(
    priority=3,
    block=True,
    rule=Rule(is_duel_msg),
    permission=group_message_permission_for_command("duel.duel"),
)
cage_msg = on_message(
    priority=3,
    block=True,
    rule=Rule(is_cage_msg),
    permission=group_message_permission_for_command("duel.cage"),
)
duel_qte_msg = on_message(
    priority=2,
    block=True,
    rule=duel_qte_exact_rule,
    permission=permission.GROUP,
)
reload_duel_events_msg = on_message(
    priority=10,
    block=False,
    rule=Rule(is_reload_duel_events),
    permission=group_message_permission_for_command("duel.reload_events"),
)


async def send_duel_user_reply(matcher, group_id: int, message: str | Message) -> None:
    if not await try_claim_duel_user_reply(group_id):
        return
    await matcher.send(message)


async def send_duel_user_reply_owned(
    matcher,
    group_id: int,
    message: str | Message,
    *,
    message_claimed: bool,
) -> bool:
    """已抢占同条群消息时直接发送，避免广播占位被协调耗时耗尽。"""
    if message_claimed or await try_claim_duel_user_reply(group_id):
        await matcher.send(message)
        return True
    return False


def duel_fight_start_message(a: str, b: str) -> Message:
    return (
        MessageSegment.text("战斗开始！")
        + MessageSegment.at(int(a))
        + MessageSegment.text(" 与 ")
        + MessageSegment.at(int(b))
        + MessageSegment.text(" 登台。")
    )


def duel_handler_is_narrator(
    event: GroupMessageEvent,
    challenger_id: str,
    defender_id: str,
    *,
    dual_bot: bool,
) -> bool:
    """非主持牛不抢跑开团、不发幕。"""
    narrator = duel_narrator_bot_id(challenger_id, defender_id, dual_bot=dual_bot)
    return narrator is None or int(event.self_id) == narrator


async def run_duel_match(
    matcher,
    bot: Bot,
    event: GroupMessageEvent,
    challenger_id: str,
    defender_id: str,
    *,
    dual_bot: bool = False,
    command_gate: str | None = None,  # "ok"：入口已 begin_duel_command
    total_rounds: int | None = None,
) -> None:
    """开团：群级占用与指令 CD；command_gate=ok 表示入口已抢占。"""
    if not duel_handler_is_narrator(event, challenger_id, defender_id, dual_bot=dual_bot):
        if command_gate == "ok":
            end_duel_group(event.group_id)
        return
    if duel_narrator_bot_id(challenger_id, defender_id, dual_bot=dual_bot) is None:
        if not await try_claim_duel_message(event):
            return

    challenger_is_bot = is_bot_qq(challenger_id)
    defender_is_bot = is_bot_qq(defender_id)
    bot_mode = dual_bot or (challenger_is_bot and defender_is_bot)

    if command_gate is None:
        gate = await begin_duel_command(event.group_id, command_id="duel.duel")
    else:
        gate = command_gate
    if gate == "busy":
        await send_duel_user_reply(matcher, event.group_id, "此群台上正有决斗未散，且待战歌落幕。")
        return
    if gate == "cooldown":
        return

    if bot_mode:
        await start_duel_pair(event.group_id, int(challenger_id), int(defender_id))

    try:
        stacks = await play_duel_rounds(
            matcher,
            bot,
            event.group_id,
            challenger_id,
            defender_id,
            bot_mode=bot_mode,
            challenger_is_bot=challenger_is_bot,
            defender_is_bot=defender_is_bot,
            total_rounds=total_rounds,
        )
    finally:
        end_duel_group(event.group_id)
        if bot_mode:
            await clear_duel_pair(event.group_id)

    if stacks is None:
        await send_duel_user_reply(
            matcher,
            event.group_id,
            "节庆剧目表读不出来……请检查插件内 event_packs/default 下 JSON。",
        )
        return

    await apply_duel_penalties(
        event.group_id,
        int(event.self_id),
        challenger_id,
        defender_id,
        stacks,
        dual_bot=bot_mode,
    )


async def duel_bot_pair(
    matcher,
    bot: Bot,
    event: GroupMessageEvent,
    a: str,
    b: str,
    *,
    total_rounds: int | None = None,
) -> None:
    if a == b:
        await send_duel_user_reply(matcher, event.group_id, "博士，我就是我自己啊")
        return
    if not duel_handler_is_narrator(event, a, b, dual_bot=True):
        return
    gate = await begin_duel_command(event.group_id, command_id="duel.duel")
    if gate == "busy":
        await send_duel_user_reply(matcher, event.group_id, "此群台上正有决斗未散，且待战歌落幕。")
        return
    if gate == "cooldown":
        return
    try:
        await matcher.send(duel_fight_start_message(a, b))
        await run_duel_match(
            matcher,
            bot,
            event,
            a,
            b,
            dual_bot=True,
            command_gate="ok",
            total_rounds=total_rounds,
        )
    finally:
        end_duel_group(event.group_id)


async def duel(matcher, bot: Bot, event: GroupMessageEvent, state: T_State) -> None:
    total_rounds, round_err = resolve_duel_round_count(event)
    if round_err:
        await send_duel_user_reply(matcher, event.group_id, round_err)
        return

    ats = parse_duel_at_qqs(event)
    if len(ats) == 0:
        inferred = infer_duel_defender_when_at_self_hidden(event)
        if inferred:
            ats = [inferred]

    if len(ats) >= 2:
        if not (is_bot_qq(ats[0]) and is_bot_qq(ats[1])):
            await send_duel_user_reply(
                matcher,
                event.group_id,
                "双 @ 决斗仅支持两名牛牛；人类请 @ 一名对手。",
            )
            return
        await duel_bot_pair(matcher, bot, event, ats[0], ats[1], total_rounds=total_rounds)
        return

    if len(ats) == 0:
        if raw_message_has_at(event):
            return
        if not await try_claim_duel_message(event):
            return
        await send_duel_user_reply(matcher, event.group_id, "台上还缺一位对手，无法开演。")
        return

    defender = ats[0]
    match = re.search(r"user_id=(\d+)", str(event.sender))
    if not match:
        await send_duel_user_reply(matcher, event.group_id, "无法识别挑战者。")
        return
    challenger = match.group(1)

    if challenger == defender:
        await send_duel_user_reply(matcher, event.group_id, "左脚踩右脚也不能上天哦。")
        return

    if not duel_handler_is_narrator(event, challenger, defender, dual_bot=False):
        return

    await run_duel_match(matcher, bot, event, challenger, defender, total_rounds=total_rounds)


@duel_msg.handle()
async def _(bot: Bot, event: GroupMessageEvent, state: T_State) -> None:
    await duel(duel_msg, bot, event, state)


@cage_msg.handle()
async def _(bot: Bot, event: GroupMessageEvent, state: T_State) -> None:
    if event.group_id in BLOCK_LIST:
        return
    total_rounds, round_err = resolve_duel_round_count(event)
    if round_err:
        await send_duel_user_reply(cage_msg, event.group_id, round_err)
        return

    plain = (event.get_plaintext() or "").strip() or "八角笼牛"
    from src.plugins.duel.shard_cage import cage_narrator_offline_for_reply, resolve_cage_duel_pair

    pair = await resolve_cage_duel_pair(bot, event, plain=plain)
    if not pair:
        if not await try_claim_duel_message(event):
            return
        await send_duel_user_reply(
            cage_msg,
            event.group_id,
            "没有另一位对手呢，博士，八角笼无法开演……",
        )
        return
    a, b = str(pair[0]), str(pair[1])
    narrator = min(int(a), int(b))
    if cage_narrator_offline_for_reply(narrator):
        if not await try_claim_duel_message(event):
            return
        await send_duel_user_reply(
            cage_msg,
            event.group_id,
            "主持牛暂未连线，八角笼改日再战。",
        )
        return
    if int(event.self_id) != narrator:
        return
    if not await try_claim_duel_message(event):
        logger.warning(
            "duel.cage: message claim lost group={} narrator={} pair={}",
            event.group_id,
            narrator,
            pair,
        )
        return
    from src.platform.shard.coord.duel_group import try_reclaim_orphan_duel_group

    await try_reclaim_orphan_duel_group(event.group_id)
    gate = await begin_duel_command(event.group_id, command_id="duel.cage")
    if gate == "busy":
        if not await send_duel_user_reply_owned(
            cage_msg,
            event.group_id,
            "此群台上正有决斗未散，且待战歌落幕。",
            message_claimed=True,
        ):
            logger.warning(
                "duel.cage: busy but user reply slot lost group={} narrator={}",
                event.group_id,
                narrator,
            )
        return
    if gate == "cooldown":
        if not await send_duel_user_reply_owned(
            cage_msg,
            event.group_id,
            "博士，战鼓刚歇，稍待片刻再开八角笼。",
            message_claimed=True,
        ):
            logger.warning(
                "duel.cage: cooldown but user reply slot lost group={} narrator={}",
                event.group_id,
                narrator,
            )
        return
    try:
        await cage_msg.send(duel_fight_start_message(a, b))
        await run_duel_match(
            cage_msg,
            bot,
            event,
            a,
            b,
            dual_bot=True,
            command_gate="ok",
            total_rounds=total_rounds,
        )
    finally:
        end_duel_group(event.group_id)


@duel_qte_msg.handle()
async def _(bot: Bot, event: GroupMessageEvent, state: T_State) -> None:
    if event.group_id in BLOCK_LIST:
        return
    complete_duel_qte(event)


@reload_duel_events_msg.handle()
async def _(bot: Bot, event: GroupMessageEvent, state: T_State) -> None:
    if event.group_id in BLOCK_LIST:
        return
    await reload_duel_events_msg.send(reload_event_pools())
