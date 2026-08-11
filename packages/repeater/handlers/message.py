"""群内消息：学习与回复。"""

# ruff: noqa: TC002

from __future__ import annotations

from nonebot import logger, on_message
from nonebot.adapters import Bot  # noqa: TC002
from nonebot.adapters.onebot.v11 import GroupMessageEvent, permission

from pallas.core.foundation.config import BotConfig
from pallas.core.shared.utils.media_cache import insert_image
from pallas.product.message_scrub import is_message_scrub_blocked_async
from pallas.product.message_scrub.log_preview import scrub_intercept_log_preview

from ..event_gate import build_repeater_event_context
from ..learn_queue import enqueue_repeater_learn
from ..model import Chat
from ..reply_preparation import prepare_repeater_reply

any_msg = on_message(
    priority=15,
    block=False,
    permission=permission.GROUP,
)


async def execute_repeater_message(bot: Bot, event: GroupMessageEvent) -> None:
    ctx = await build_repeater_event_context(int(bot.self_id), event)
    if ctx is None:
        return

    if await is_message_scrub_blocked_async(plain_text=ctx.plain_body, raw_message=ctx.norm_raw):
        pv = scrub_intercept_log_preview(ctx.plain_body, ctx.norm_raw)
        logger.info(
            f"bot [{event.self_id}] repeater capture skipped (message_scrub) in group [{event.group_id}] "
            f"user [{event.user_id}] msg_id [{event.message_id}] preview [{pv}]"
        )
        return

    from pallas.product.llm.reply_target_candidates import record_reply_target_candidate

    record_reply_target_candidate(
        group_id=int(event.group_id),
        message_id=int(event.message_id),
        sender_id=int(event.user_id),
        text=ctx.plain_body,
    )

    config = BotConfig(event.self_id, event.group_id)
    chat = Chat(event)
    prepared = await prepare_repeater_reply(
        event,
        chat,
        plain_body=ctx.plain_body,
        sharding_active=ctx.sharding_active,
    )
    bundle = prepared.bundle
    fanout_gate = prepared.fanout_gate

    for seg in event.message:
        if seg.type == "image":
            await insert_image(
                seg,
                bot_id=int(event.self_id),
                group_id=int(event.group_id),
                message_id=int(event.message_id),
            )

    await enqueue_repeater_learn(chat, event)

    if event.is_tome():
        return

    if bundle is None:
        return

    if fanout_gate is not None and fanout_gate.won:
        from ..fanout_reply import dispatch_repeater_fanout

        await dispatch_repeater_fanout(event, fanout_gate.bot_ids, bundle)
        return

    answers = await chat.answer_from_bundle(bundle)
    if answers is None:
        return

    await config.refresh_cooldown("repeat")
    from pallas.core.platform.ingress.hotpath_metrics import record_reply_local_dispatched

    from ..fanout_reply import dispatch_repeater_reply

    record_reply_local_dispatched()
    dispatch_repeater_reply(int(event.self_id), int(event.group_id), answers)


@any_msg.handle()
async def handle_group_message(bot: Bot, event: GroupMessageEvent) -> None:
    await execute_repeater_message(bot, event)
