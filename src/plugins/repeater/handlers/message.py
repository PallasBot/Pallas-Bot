"""群内消息：学习、回复与 LLM 回退。"""

# ruff: noqa: TC002

from __future__ import annotations

from nonebot import logger, on_message
from nonebot.adapters import Bot  # noqa: TC002
from nonebot.adapters.onebot.v11 import GroupMessageEvent, permission

from src.features.llm.fallback import maybe_submit_repeater_llm_fallback
from src.features.llm.polish import maybe_submit_repeater_llm_polish
from src.features.message_scrub import is_message_scrub_blocked_async
from src.features.message_scrub.log_preview import scrub_intercept_log_preview
from src.foundation.config import BotConfig
from src.foundation.db.pool_budget import is_pg_pool_timeout_error
from src.platform.observability import SlowPathTimer, slow_path_threshold_ms
from src.shared.utils.media_cache import insert_image

from ..event_gate import build_repeater_event_context
from ..learn_queue import enqueue_repeater_learn
from ..model import Chat
from ..reply_gate import should_prepare_repeater_reply

any_msg = on_message(
    priority=15,
    block=False,
    permission=permission.GROUP,
)


@any_msg.handle()
async def handle_group_message(bot: Bot, event: GroupMessageEvent):
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

    config = BotConfig(event.self_id, event.group_id)
    from ..fanout_reply import repeater_can_attempt_reply

    chat = Chat(event)
    can_reply = await repeater_can_attempt_reply(int(event.self_id), int(event.group_id))

    bundle = None
    fanout_gate = None
    if can_reply and should_prepare_repeater_reply(ctx.plain_body, sharding_active=ctx.sharding_active):
        from ..fanout_reply import resolve_fanout_gate

        fanout_gate = await resolve_fanout_gate(event)
        if fanout_gate.lost:
            bundle = None
        else:
            reply_timer = SlowPathTimer(
                "repeater.find_reply_bundle",
                threshold_ms=slow_path_threshold_ms("PALLAS_SLOW_REPEATER_BUNDLE_MS", 120.0),
            )
            try:
                bundle = await chat.find_reply_bundle()
            except Exception as exc:
                if is_pg_pool_timeout_error(exc):
                    logger.debug(
                        "repeater.find_reply_bundle db_timeout bot={} group={}",
                        event.self_id,
                        event.group_id,
                    )
                else:
                    logger.debug(
                        "repeater.find_reply_bundle failed bot={} group={}: {}",
                        event.self_id,
                        event.group_id,
                        exc,
                    )
                bundle = None
            reply_timer.mark("find_reply_bundle")
            reply_timer.finish(
                bot_id=int(event.self_id),
                group_id=int(event.group_id),
                user_id=int(event.user_id),
                can_reply=can_reply,
                found=bundle is not None,
                keywords_len=chat.chat_data.keywords_len,
                plain_text=chat.chat_data.is_plain_text,
            )

    for seg in event.message:
        if seg.type == "image":
            await insert_image(seg)

    await enqueue_repeater_learn(chat, event)

    if bundle is None:
        if can_reply:
            await maybe_submit_repeater_llm_fallback(event, user_text=ctx.plain_body)
        return

    if fanout_gate is not None and fanout_gate.won:
        from ..fanout_reply import dispatch_repeater_fanout

        await dispatch_repeater_fanout(event, fanout_gate.bot_ids, bundle)
        return

    candidate = next((item for item in bundle.answer_list if item and "[CQ:" not in item), "")
    if candidate:
        if await maybe_submit_repeater_llm_polish(event, candidate_text=candidate):
            return

    answers = await chat.answer_from_bundle(bundle)
    if answers is None:
        return

    await config.refresh_cooldown("repeat")
    from ..fanout_reply import dispatch_repeater_reply

    dispatch_repeater_reply(int(event.self_id), int(event.group_id), answers)
