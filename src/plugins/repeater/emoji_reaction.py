import asyncio
import random
import time
from collections import defaultdict

from nonebot import get_plugin_config, logger, on_message, on_notice, require
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent, NoticeEvent
from nonebot.exception import ActionFailed
from nonebot.rule import Rule
from nonebot.typing import T_State
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import Config

EMOJI_IDS = (
    4,
    5,
    8,
    9,
    10,
    12,
    14,
    16,
    21,
    23,
    24,
    25,
    26,
    27,
    28,
    29,
    30,
    32,
    33,
    34,
    38,
    39,
    41,
    42,
    43,
    49,
    53,
    60,
    63,
    66,
    74,
    75,
    76,
    78,
    79,
    85,
    89,
    96,
    97,
    98,
    99,
    100,
    101,
    102,
    103,
    104,
    106,
    109,
    111,
    116,
    118,
    120,
    122,
    123,
    124,
    125,
    129,
    144,
    147,
    171,
    173,
    174,
    175,
    176,
    179,
    180,
    181,
    182,
    183,
    201,
    203,
    212,
    214,
    219,
    222,
    227,
    232,
    240,
    243,
    246,
    262,
    264,
    265,
    266,
    267,
    268,
    269,
    270,
    271,
    272,
    273,
    278,
    281,
    282,
    284,
    285,
    287,
    289,
    290,
    293,
    294,
    297,
    298,
    299,
    305,
    306,
    307,
    314,
    315,
    318,
    319,
    320,
    322,
    324,
    326,
    9728,
    9749,
    9786,
    10024,
    10060,
    10068,
    127801,
    127817,
    127822,
    127827,
    127836,
    127838,
    127847,
    127866,
    127867,
    127881,
    128027,
    128046,
    128051,
    128053,
    128074,
    128076,
    128077,
    128079,
    128089,
    128102,
    128104,
    128147,
    128157,
    128164,
    128166,
    128168,
    128170,
    128235,
    128293,
    128513,
    128514,
    128516,
    128522,
    128524,
    128527,
    128530,
    128531,
    128532,
    128536,
    128538,
    128540,
    128541,
    128557,
    128560,
    128563,
)  # 官方文档就这么多


SUPPORTED_PROTOCOLS = ("Lagrange", "NapCat")  # 一统天下的日子还没来吗


def get_random_emoji() -> str:
    return str(random.choice(EMOJI_IDS))


sent_reactions: dict[str, dict[int, float]] = {}
last_cleanup_time = 0
last_successful_protocol: dict[str, str] = {}
plugin_config = get_plugin_config(Config)


RETRY_MAX_ATTEMPTS = 3
TIMEOUT = 10
bot_locks = defaultdict(lambda: defaultdict(asyncio.Lock))
last_used_time = {}


def should_trigger_reaction() -> bool:
    return random.random() < plugin_config.reaction_probability


def has_sent_reaction(bot_id: str, message_id: int) -> bool:
    if bot_id not in sent_reactions:
        sent_reactions[bot_id] = {}
    return message_id in sent_reactions[bot_id]


def mark_reaction_sent(bot_id: str, message_id: int):
    if bot_id not in sent_reactions:
        sent_reactions[bot_id] = {}
    sent_reactions[bot_id][message_id] = time.time()


@retry(
    stop=stop_after_attempt(RETRY_MAX_ATTEMPTS),
    wait=wait_exponential(multiplier=1, max=10),
    retry=retry_if_exception_type((ActionFailed, asyncio.TimeoutError)),
    reraise=True,
)
async def _attempt_send(bot: Bot, event: Event, emoji_code: str, protocol: str):
    bot_id = str(bot.self_id)
    message_id = event.message_id

    try:
        if protocol == "Lagrange":
            await asyncio.wait_for(
                bot.call_api(
                    "set_group_reaction",
                    group_id=event.group_id,
                    message_id=message_id,
                    code=emoji_code,
                    is_add=True,
                ),
                timeout=TIMEOUT,
            )
        elif protocol == "NapCat":
            await asyncio.wait_for(
                bot.call_api(
                    "set_msg_emoji_like",
                    message_id=message_id,
                    emoji_id=emoji_code,
                    set=True,
                ),
                timeout=TIMEOUT,
            )

        last_successful_protocol[bot_id] = protocol
        mark_reaction_sent(bot_id, message_id)

        logger.info(
            f"[Reaction] Bot {bot_id} successfully sent emoji {emoji_code} via {protocol} in group {event.group_id}"
        )
    except (TimeoutError, ActionFailed) as e:
        logger.warning(
            f"[Reaction] Bot {bot_id} failed to send emoji via {protocol} in group {event.group_id}: {str(e)}",
            exc_info=True,
        )
        raise
    except Exception as e:
        logger.error(
            f"[Reaction] Unexpected error when sending emoji via {protocol}: {str(e)}",
            exc_info=True,
        )
        raise


async def send_reaction(bot: Bot, event: Event, emoji_code: str) -> None:
    bot_id = str(bot.self_id)
    message_id = event.message_id
    group_id = event.group_id

    if has_sent_reaction(bot_id, message_id):
        logger.debug(f"[Reaction] Bot {bot_id} already reacted to message {message_id}")
        return

    async with bot_locks[bot_id][group_id]:
        last_used_time[(bot_id, group_id)] = time.time()

        if bot_id in last_successful_protocol:
            protocol = last_successful_protocol[bot_id]
            try:
                await _attempt_send(bot, event, emoji_code, protocol)
                return
            except (TimeoutError, ActionFailed):
                if bot_id in last_successful_protocol:
                    del last_successful_protocol[bot_id]

        for protocol in SUPPORTED_PROTOCOLS:
            try:
                await _attempt_send(bot, event, emoji_code, protocol)
                return
            except (TimeoutError, ActionFailed):
                continue

        logger.error(
            f"[Reaction] Bot {bot_id} failed to send emoji {emoji_code} "
            f"in group {event.group_id} using all available protocols",
            exc_info=True,
        )
        raise ActionFailed("All protocols failed to send reaction")


async def reaction_enabled(bot: Bot, event: Event, state: T_State) -> bool:
    return plugin_config.enable_reaction


async def subfeature_enabled(flag_name: str):
    async def _enabled_check(bot: Bot, event: Event, state: T_State) -> bool:
        return getattr(plugin_config, flag_name, True)

    return _enabled_check


reaction_msg = on_message(
    rule=Rule(reaction_enabled) & Rule(lambda bot, event, state: random.random() < plugin_config.reaction_probability),
    priority=16,
)


@reaction_msg.handle()
async def handle_reaction(bot: Bot, event: GroupMessageEvent):
    """对所有消息，满足概率回应表情"""
    if not plugin_config.enable_probability_reaction:
        logger.debug(
            "[Reaction] Probability reaction is disabled",
            extra={"bot_id": str(bot.self_id)},
        )
        return

    bot_id = str(bot.self_id)
    emoji_code = get_random_emoji()

    try:
        await send_reaction(bot, event, emoji_code)
    except ActionFailed as e:
        logger.error(
            f"[Reaction] Bot {bot_id} failed to send emoji {emoji_code} in group {event.group_id}: {str(e)}",
            exc_info=True,
        )


async def has_face(bot: Bot, event: GroupMessageEvent, state: T_State) -> bool:
    return any(seg.type == "face" for seg in event.message)


reaction_msg_with_face = on_message(
    rule=Rule(reaction_enabled) & Rule(has_face),
    priority=15,
)


@reaction_msg_with_face.handle()
async def handle_reaction_with_face(bot: Bot, event: GroupMessageEvent):
    """对话里带表情的回应"""
    if not plugin_config.enable_face_reaction:
        logger.debug("[Reaction] Face reaction is disabled", extra={"bot_id": str(bot.self_id)})
        return

    bot_id = str(bot.self_id)
    emoji_code = get_random_emoji()

    try:
        await send_reaction(bot, event, emoji_code)
    except ActionFailed as e:
        logger.error(
            f"[Reaction] Bot {bot_id} failed to send face reaction emoji {emoji_code}: {str(e)}",
            exc_info=True,
        )


def _check_reaction_event(event: NoticeEvent) -> bool:
    if event.notice_type == "reaction" and event.sub_type == "add":
        return getattr(event, "operator_id", None) != getattr(event, "self_id", None)

    # NapCat只能支持别人贴Bot
    if event.notice_type == "group_msg_emoji_like":
        operator_id = getattr(event, "user_id", None)
        self_id = getattr(event, "self_id", None)
        return operator_id != self_id

    return False


auto_reaction_add = on_notice(
    rule=Rule(_check_reaction_event),
)


@auto_reaction_add.handle()
async def handle_auto_reaction(bot: Bot, event: NoticeEvent, state: T_State):
    """跟着别人回应"""
    bot_id = str(bot.self_id)
    if not plugin_config.enable_auto_reply_on_reaction:
        logger.debug(f"[Reaction] Bot {bot_id} auto reply on reaction is disabled")
        return
    message_id = event.message_id
    emoji_code = ""
    if hasattr(event, "likes") and isinstance(event.likes, list) and len(event.likes) > 0:
        emoji_code = str(event.likes[0].get("emoji_id", ""))
    elif hasattr(event, "code"):
        emoji_code = str(event.code)

    if not emoji_code:
        logger.warning(f"[Reaction] No valid emoji found in event for message {message_id}")
        return
    reply_emoji = str(emoji_code) if plugin_config.reply_with_same_emoji else get_random_emoji()

    if has_sent_reaction(bot_id, message_id):
        logger.debug(f"[Reaction] Bot {bot_id} already reacted to message {message_id} in group {event.group_id}")
        return

    try:
        logger.debug(
            f"[Reaction] Bot {bot_id} sending auto reply emoji {reply_emoji} "
            f"for message {message_id} in group {event.group_id}"
        )

        await send_reaction(bot, event, reply_emoji)
        mark_reaction_sent(bot_id, message_id)
    except ActionFailed as e:
        logger.warning(
            f"[Reaction] Bot {bot_id} failed to send emoji {reply_emoji} in group {event.group_id}: {str(e)}"
        )


scheduler = require("nonebot_plugin_apscheduler").scheduler


@scheduler.scheduled_job("cron", hour=1)
def cleanup_expired_records():
    global last_cleanup_time
    current_time = time.time()
    cleanup_protocol_cache()

    for bot_id in list(sent_reactions.keys()):
        sent_reactions[bot_id] = {
            msg_id: timestamp for msg_id, timestamp in sent_reactions[bot_id].items() if current_time - timestamp < 3600
        }
        if not sent_reactions[bot_id]:
            del sent_reactions[bot_id]

    last_cleanup_time = current_time
    logger.info(f"[Reaction] Cleanup completed. Total reactions cached: {sum(len(r) for r in sent_reactions.values())}")


def cleanup_protocol_cache():
    active_bots = set(sent_reactions.keys())
    for bot_id in list(last_successful_protocol.keys()):
        if bot_id not in active_bots:
            del last_successful_protocol[bot_id]


async def async_cleanup_idle_locks():
    cutoff = time.time() - 3600  # 清理超过1小时未使用的锁
    logger.info(f"[Reaction] Cleaning up idle bot locks (Total before: {len(bot_locks)})")

    for bot_id in list(bot_locks.keys()):
        group_locks = bot_locks[bot_id]
        for group_id in list(group_locks.keys()):
            if last_used_time.get((bot_id, group_id), 0) < cutoff:
                del group_locks[group_id]
                last_used_time.pop((bot_id, group_id), None)
        if not group_locks:
            del bot_locks[bot_id]

    logger.info(f"[Reaction] Lock cleanup completed. Remaining bot locks: {sum(len(g) for g in bot_locks.values())}")


scheduler.add_job(async_cleanup_idle_locks, "interval", minutes=5)
