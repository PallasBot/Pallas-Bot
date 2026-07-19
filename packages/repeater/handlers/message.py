"""群内消息：学习、回复与 LLM 回退。"""

# ruff: noqa: TC002

from __future__ import annotations

from nonebot import logger, on_message
from nonebot.adapters import Bot  # noqa: TC002
from nonebot.adapters.onebot.v11 import GroupMessageEvent, permission

from pallas.core.foundation.config import BotConfig
from pallas.core.foundation.db.pool_budget import is_pg_pool_timeout_error
from pallas.core.platform.observability import SlowPathTimer, slow_path_threshold_ms
from pallas.core.shared.utils.media_cache import insert_image
from pallas.product.llm.behavior import classify_behavior_scene
from pallas.product.llm.fallback import maybe_submit_repeater_llm_fallback
from pallas.product.llm.kernel import (
    ConversationContext,
    behavior_scene_to_conversation_scene,
    decide_repeater_action,
    resolve_conversation_feature_level,
)
from pallas.product.llm.polish_lite import maybe_submit_repeater_corpus_llm
from pallas.product.llm.task_metrics import record_bot_llm_route
from pallas.product.message_scrub import is_message_scrub_blocked_async
from pallas.product.message_scrub.log_preview import scrub_intercept_log_preview

from ..event_gate import build_repeater_event_context
from ..learn_queue import enqueue_repeater_learn
from ..llm_pipeline import build_repeater_llm_plan, build_stitch_candidate, run_repeater_llm_plan
from ..model import Chat
from ..opportunity_gate import (
    build_opportunity_trace_payload,
    estimate_candidate_style_score,
    should_attempt_repeater_opportunity,
)
from ..opportunity_trace import append_conversation_decision_trace
from ..reply_gate import should_prepare_repeater_reply
from ..responder import Responder

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

    if event.is_tome():
        return

    if bundle is None:
        if can_reply:
            record_bot_llm_route("repeater_fallback", "pipeline_generate")
            await maybe_submit_repeater_llm_fallback(event, user_text=ctx.plain_body, reply_mode="normal")
        return

    if fanout_gate is not None and fanout_gate.won:
        from ..fanout_reply import dispatch_repeater_fanout

        await dispatch_repeater_fanout(event, fanout_gate.bot_ids, bundle)
        return

    from pallas.product.llm.config import get_llm_config

    from ..message_store import MessageStore

    llm_cfg = get_llm_config()
    feature_level = resolve_conversation_feature_level(llm_cfg)
    recent_group_messages = list(MessageStore._message_dict.get(int(event.group_id), []))
    has_candidate_pool = bool(bundle.message_pool or bundle.answer_list)
    recent_human_user_ids = [
        int(getattr(msg, "user_id", 0) or 0)
        for msg in recent_group_messages
        if getattr(msg, "user_id", None) is not None
    ]
    bot_recently_replied = any(
        int(getattr(reply, "user_id", 0) or 0) == int(event.self_id) for reply in recent_group_messages[-2:]
    )
    has_recent_back_and_forth = (
        len({user_id for user_id in recent_human_user_ids[-4:] if user_id and user_id != int(event.self_id)}) >= 2
    )
    plan = build_repeater_llm_plan(
        bundle,
        llm_enabled=llm_cfg.llm_chat_enabled,
        select_enabled=llm_cfg.llm_select_enabled,
        polish_enabled=llm_cfg.llm_polish_enabled,
        polish_lite_enabled=llm_cfg.llm_polish_lite_enabled,
    )
    candidate_style_score = estimate_candidate_style_score(
        plan.candidate_pool or ([plan.candidate_text] if plan.candidate_text else []),
        reply_mode=bundle.reply_mode,
    )
    behavior_scene = classify_behavior_scene(
        user_text=ctx.plain_body,
        recent_texts=[
            str(getattr(msg, "plain_text", "") or "").strip()
            for msg in recent_group_messages[-6:]
            if str(getattr(msg, "plain_text", "") or "").strip()
        ],
        has_multi_party_overlap=has_recent_back_and_forth,
    )
    decision_ctx = ConversationContext.for_repeater(
        plain_text=ctx.plain_body,
        group_id=int(event.group_id),
        bot_id=int(event.self_id),
        user_id=int(event.user_id),
        reply_mode=bundle.reply_mode,
        unique_users=len({user_id for user_id in recent_human_user_ids if user_id}),
        recent_message_count=len(recent_group_messages),
        has_candidate_pool=has_candidate_pool,
        candidate_pool_size=len(plan.candidate_pool),
        candidate_style_score=candidate_style_score,
        has_recent_back_and_forth=has_recent_back_and_forth,
        bot_recently_replied=bot_recently_replied,
        scene=behavior_scene_to_conversation_scene(behavior_scene),
    )
    opportunity_accepted = should_attempt_repeater_opportunity(
        ctx.plain_body,
        unique_users=decision_ctx.unique_users,
        recent_message_count=decision_ctx.recent_message_count,
        has_candidate_pool=has_candidate_pool,
        candidate_pool_size=len(plan.candidate_pool),
        candidate_style_score=candidate_style_score,
        has_recent_back_and_forth=has_recent_back_and_forth,
        bot_recently_replied=bot_recently_replied,
        reply_mode=bundle.reply_mode,
        is_to_me=bool(event.is_tome()),
    )
    decision = decide_repeater_action(
        decision_ctx,
        llm_enabled=llm_cfg.llm_chat_enabled,
        select_enabled=llm_cfg.llm_select_enabled,
        polish_enabled=llm_cfg.llm_polish_enabled,
        polish_lite_enabled=llm_cfg.llm_polish_lite_enabled,
        has_grounded_candidate=bool(plan.candidate_text or plan.candidate_pool),
        opportunity_accepted=opportunity_accepted,
        opportunity_trace_extra=build_opportunity_trace_payload(
            ctx.plain_body,
            unique_users=decision_ctx.unique_users,
            recent_message_count=decision_ctx.recent_message_count,
            has_candidate_pool=has_candidate_pool,
            candidate_pool_size=len(plan.candidate_pool),
            candidate_style_score=candidate_style_score,
            has_recent_back_and_forth=has_recent_back_and_forth,
            bot_recently_replied=bot_recently_replied,
            reply_mode=bundle.reply_mode,
            is_to_me=bool(event.is_tome()),
            accepted=opportunity_accepted,
        ),
        feature_level=feature_level,
    )
    append_conversation_decision_trace({
        "group_id": int(event.group_id),
        "bot_id": int(event.self_id),
        **decision.trace.to_trace_row(),
    })
    should_try_llm_opportunity = decision.opportunity_accepted

    async def stage_runner(stage_name: str) -> bool:
        if stage_name in {"select", "rewrite"}:
            if stage_name == "select":
                record_bot_llm_route("repeater_select", "pipeline_select")
            else:
                task_name = "repeater_polish_lite" if llm_cfg.llm_polish_lite_enabled else "repeater_polish"
                record_bot_llm_route(task_name, "pipeline_rewrite")
            return await maybe_submit_repeater_corpus_llm(
                event,
                user_text=ctx.plain_body,
                candidates=plan.candidate_pool,
                candidate_text=plan.candidate_text,
                reply_mode=bundle.reply_mode,
            )
        if stage_name == "stitch":
            from pallas.product.persona import resolve_persona_for_message
            from pallas.product.persona.loader import load_affect_triggers

            stitched = build_stitch_candidate(plan.candidate_pool)
            recent_sent = [
                str(r.get("reply") or "")
                for r in Chat._reply_dict[int(event.group_id)][int(event.self_id)][-Responder.DUPLICATE_REPLY :]
                if r.get("reply") and r["reply"] != Responder.REPLY_FLAG
            ]
            persona = await resolve_persona_for_message(
                int(event.self_id),
                int(event.group_id),
                ctx.plain_body,
            )
            affect_triggers = await load_affect_triggers(int(event.group_id))
            accepted, _score = Responder.evaluate_llm_candidate_text(
                stitched,
                base_score=0.7,
                min_score=0.55,
                recent_sent=recent_sent,
                persona=persona,
                affect_triggers=affect_triggers,
                reply_mode=bundle.reply_mode,
            )
            if not accepted:
                return False
            answers = await chat.answer_from_bundle(bundle, plan=([stitched], bundle.answer_keywords))
            if answers is None:
                return False
            await config.refresh_cooldown("repeat")
            from ..fanout_reply import dispatch_repeater_reply

            record_bot_llm_route("repeater_polish", "pipeline_stitch")
            dispatch_repeater_reply(int(event.self_id), int(event.group_id), answers)
            return True
        if stage_name == "generate":
            record_bot_llm_route("repeater_fallback", "pipeline_generate")
            return await maybe_submit_repeater_llm_fallback(
                event,
                user_text=ctx.plain_body,
                reply_mode=bundle.reply_mode,
            )
        return False

    if should_try_llm_opportunity and await run_repeater_llm_plan(plan, stage_runner=stage_runner):
        return

    answers = await chat.answer_from_bundle(bundle)
    if answers is None:
        return

    await config.refresh_cooldown("repeat")
    from ..fanout_reply import dispatch_repeater_reply

    dispatch_repeater_reply(int(event.self_id), int(event.group_id), answers)
