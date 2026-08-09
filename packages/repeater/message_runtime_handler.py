from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from pallas.core.platform.message_runtime.models import (
    CrossWorkerAction,
    DeferredAction,
    HandlingOutcome,
    LlmSelectAction,
    MessageContext,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from nonebot.adapters import Bot, Event


def build_repeater_local_reply_outcome(bot_id: int, group_id: int, answers: Any) -> HandlingOutcome:
    from packages.repeater.fanout_reply import _run_repeater_reply_send

    async def dispatch() -> None:
        await _run_repeater_reply_send(bot_id, group_id, answers)

    return HandlingOutcome(
        handled=True,
        deferred_actions=(
            DeferredAction(
                name=f"repeater_reply_{bot_id}_{group_id}",
                run=dispatch,
            ),
        ),
    )


def build_repeater_fanout_outcome(event: Any, bot_ids: tuple[int, ...], bundle: Any) -> HandlingOutcome:
    from packages.repeater.fanout_reply import _delayed_local_reply, fanout_payload_from_event
    from pallas.core.platform.shard import context as shard_ctx
    from pallas.core.platform.shard.presence import bot_has_cluster_connection, bot_has_local_connection

    payload = fanout_payload_from_event(event, bundle, fanout_bot_ids=bot_ids)
    group_id = int(payload["group_id"])
    deferred_actions: list[DeferredAction] = []
    cross_worker_actions: list[CrossWorkerAction] = []
    for index, bot_id in enumerate(bot_ids):
        if not bot_has_cluster_connection(bot_id):
            continue
        delay_sec = index * 0.35
        if bot_has_local_connection(bot_id):
            deferred_actions.append(
                DeferredAction(
                    name=f"repeater_fanout_{bot_id}_{group_id}",
                    run=lambda bot_id=bot_id, delay_sec=delay_sec: _delayed_local_reply(delay_sec, bot_id, payload),
                )
            )
        elif shard_ctx.sharding_active():
            remote_payload = {**payload, "delay_sec": delay_sec}
            cross_worker_actions.append(
                CrossWorkerAction(
                    kind="repeater.fanout_reply",
                    target_bot_id=bot_id,
                    payload=remote_payload,
                    idempotency_key=f"repeater.fanout:{group_id}:{int(event.time)}:{bot_id}",
                )
            )
    return HandlingOutcome(
        handled=True,
        deferred_actions=tuple(deferred_actions),
        cross_worker_actions=tuple(cross_worker_actions),
    )


def build_repeater_capture_and_learn_action(event: Any, chat: Any) -> DeferredAction:
    async def capture_and_learn() -> None:
        from packages.repeater.learn_queue import enqueue_repeater_learn
        from pallas.core.shared.utils.media_cache import insert_image

        for segment in event.message:
            if segment.type == "image":
                await insert_image(
                    segment,
                    bot_id=int(event.self_id),
                    group_id=int(event.group_id),
                    message_id=int(event.message_id),
                )
        await enqueue_repeater_learn(chat, event)

    return DeferredAction(
        name=f"repeater_capture_learn_{int(event.self_id)}_{int(event.group_id)}_{int(event.message_id)}",
        run=capture_and_learn,
    )


def build_repeater_llm_select_outcome(
    event: Any,
    *,
    user_text: str,
    candidates: list[str],
    candidate_text: str,
    reply_mode: str,
    scene_tier: str,
    bundle: Any,
    capabilities: Any,
    run_local_bundle: Callable[[], Awaitable[None]],
) -> HandlingOutcome:
    return HandlingOutcome(
        handled=True,
        llm_select_actions=(
            LlmSelectAction(
                bot_id=int(event.self_id),
                group_id=int(event.group_id),
                event=event,
                user_text=user_text,
                candidates=tuple(candidates),
                candidate_text=candidate_text,
                reply_mode=reply_mode,
                scene_tier=scene_tier,
                bundle=bundle,
                capabilities=capabilities,
                run_local_bundle=run_local_bundle,
            ),
        ),
    )


async def try_build_repeater_llm_select_outcome(
    event: Event,
    *,
    plain_body: str,
    bundle: Any,
    capabilities: Any,
) -> HandlingOutcome | None:
    from packages.repeater.llm_pipeline import build_repeater_llm_plan
    from packages.repeater.message_store import MessageStore
    from packages.repeater.opportunity_gate import (
        decide_llm_attempt,
        estimate_candidate_style_score,
        resolve_scene_tier,
        should_attempt_repeater_opportunity,
    )
    from pallas.product.llm.config import get_llm_config
    from pallas.product.llm.runtime_api import ConversationFeatureLevel, resolve_conversation_feature_level

    llm_cfg = get_llm_config()
    feature_level = resolve_conversation_feature_level(llm_cfg)
    if feature_level == ConversationFeatureLevel.LEGACY_REPEATER:
        return None
    plan = build_repeater_llm_plan(
        bundle,
        llm_enabled=capabilities.llm_enabled,
        select_enabled=capabilities.select_enabled,
        polish_enabled=capabilities.polish_enabled,
        polish_lite_enabled=capabilities.polish_lite_enabled,
    )
    if plan.stage_names != ["select"]:
        return None
    recent_messages = list(MessageStore._message_dict.get(int(event.group_id), []))
    recent_human_user_ids = [
        int(getattr(message, "user_id", 0) or 0)
        for message in recent_messages
        if getattr(message, "user_id", None) is not None
    ]
    bot_recently_replied = any(
        int(getattr(message, "user_id", 0) or 0) == int(event.self_id) for message in recent_messages[-2:]
    )
    has_recent_back_and_forth = (
        len({user_id for user_id in recent_human_user_ids[-4:] if user_id and user_id != int(event.self_id)}) >= 2
    )
    scene_tier = resolve_scene_tier(
        plain_body,
        candidate_pool_size=len(plan.candidate_pool),
        has_candidate_pool=bool(bundle.message_pool or bundle.answer_list),
        has_recent_back_and_forth=has_recent_back_and_forth,
        is_to_me=bool(event.is_tome()),
    )
    opportunity_accepted = should_attempt_repeater_opportunity(
        plain_body,
        unique_users=len({user_id for user_id in recent_human_user_ids if user_id}),
        recent_message_count=len(recent_messages),
        has_candidate_pool=bool(bundle.message_pool or bundle.answer_list),
        candidate_pool_size=len(plan.candidate_pool),
        candidate_style_score=estimate_candidate_style_score(
            plan.candidate_pool or ([plan.candidate_text] if plan.candidate_text else []),
            reply_mode=bundle.reply_mode,
        ),
        has_recent_back_and_forth=has_recent_back_and_forth,
        bot_recently_replied=bot_recently_replied,
        reply_mode=bundle.reply_mode,
        is_to_me=bool(event.is_tome()),
        bot_id=int(event.self_id),
        scene_tier=scene_tier,
    )
    should_try_llm, _attempt_roll, _attempt_skip = decide_llm_attempt(
        scene_tier=scene_tier,
        opportunity_accepted=opportunity_accepted,
        strong_attempt_rate=float(llm_cfg.llm_repeater_strong_attempt_rate),
    )
    if not should_try_llm:
        return None

    async def run_local_bundle() -> None:
        from packages.repeater.fanout_reply import _run_repeater_reply_send
        from packages.repeater.model import Chat
        from pallas.core.foundation.config import BotConfig
        from pallas.core.platform.ingress.hotpath_metrics import record_reply_local_dispatched

        answers = await Chat(event).answer_from_bundle(bundle)
        if answers is None:
            return
        await BotConfig(int(event.self_id), int(event.group_id)).refresh_cooldown("repeat")
        record_reply_local_dispatched()
        await _run_repeater_reply_send(int(event.self_id), int(event.group_id), answers)

    return build_repeater_llm_select_outcome(
        event,
        user_text=plain_body,
        candidates=plan.candidate_pool,
        candidate_text=plan.candidate_text,
        reply_mode=bundle.reply_mode,
        scene_tier=scene_tier,
        bundle=bundle,
        capabilities=capabilities,
        run_local_bundle=run_local_bundle,
    )


class RepeaterNativeHandler:
    handler_id = "repeater.message"
    modules = frozenset({"repeater"})
    passive = True
    fallback_on_error = False

    def accepts(self, context: MessageContext) -> bool:
        return not context.is_to_me

    async def build_fanout_plan(
        self,
        context: MessageContext,
        *,
        bot: Bot,
        event: Event,
    ) -> HandlingOutcome:
        from pallas.product.llm.config import get_llm_config
        from pallas.product.llm.runtime_api import resolve_repeater_capabilities

        capabilities = resolve_repeater_capabilities(get_llm_config())
        from packages.repeater.event_gate import build_repeater_event_context
        from packages.repeater.model import Chat
        from packages.repeater.reply_preparation import prepare_repeater_reply
        from pallas.product.message_scrub import is_message_scrub_blocked_async

        repeater_context = await build_repeater_event_context(int(bot.self_id), event)
        if repeater_context is None:
            return HandlingOutcome(handled=False, fallback_to_legacy=True)
        if await is_message_scrub_blocked_async(
            plain_text=repeater_context.plain_body,
            raw_message=repeater_context.norm_raw,
        ):
            return HandlingOutcome(handled=True)

        chat = Chat(event)
        prepared = await prepare_repeater_reply(
            event,
            chat,
            plain_body=repeater_context.plain_body,
            sharding_active=repeater_context.sharding_active,
        )
        if event.is_tome() or prepared.bundle is None:
            return HandlingOutcome(handled=False, fallback_to_legacy=True)
        capture_action = build_repeater_capture_and_learn_action(event, chat)
        if prepared.fanout_gate is not None and prepared.fanout_gate.won:
            fanout_outcome = build_repeater_fanout_outcome(event, prepared.fanout_gate.bot_ids, prepared.bundle)
            return replace(
                fanout_outcome,
                deferred_actions=(capture_action,) + fanout_outcome.deferred_actions,
            )

        llm_outcome = None
        if capabilities.llm_enabled:
            llm_outcome = await try_build_repeater_llm_select_outcome(
                event,
                plain_body=repeater_context.plain_body,
                bundle=prepared.bundle,
                capabilities=capabilities,
            )
            if llm_outcome is None:
                return HandlingOutcome(handled=False, fallback_to_legacy=True)

        if llm_outcome is not None:
            return replace(llm_outcome, deferred_actions=(capture_action,) + llm_outcome.deferred_actions)

        answers = await chat.answer_from_bundle(prepared.bundle)
        if answers is None:
            return HandlingOutcome(handled=True, deferred_actions=(capture_action,))

        from pallas.core.foundation.config import BotConfig
        from pallas.core.platform.ingress.hotpath_metrics import record_reply_local_dispatched

        await BotConfig(int(event.self_id), int(event.group_id)).refresh_cooldown("repeat")
        record_reply_local_dispatched()
        local_outcome = build_repeater_local_reply_outcome(int(event.self_id), int(event.group_id), answers)
        return replace(local_outcome, deferred_actions=(capture_action,) + local_outcome.deferred_actions)

    async def handle(self, context: MessageContext, *, bot: Bot, event: Event) -> HandlingOutcome:
        if not self.accepts(context):
            return HandlingOutcome(handled=False, fallback_to_legacy=True)
        return await self.build_fanout_plan(context, bot=bot, event=event)
