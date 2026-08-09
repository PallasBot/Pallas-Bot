from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pallas.core.platform.message_runtime.models import (
    CrossWorkerAction,
    DeferredAction,
    HandlingOutcome,
    MessageContext,
)

if TYPE_CHECKING:
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

        if resolve_repeater_capabilities(get_llm_config()).llm_enabled:
            return HandlingOutcome(handled=False, fallback_to_legacy=True)

        from packages.repeater.event_gate import build_repeater_event_context
        from packages.repeater.learn_queue import enqueue_repeater_learn
        from packages.repeater.model import Chat
        from packages.repeater.reply_preparation import prepare_repeater_reply
        from pallas.core.shared.utils.media_cache import insert_image
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
        if prepared.fanout_gate is not None and prepared.fanout_gate.won:
            for segment in event.message:
                if segment.type == "image":
                    await insert_image(
                        segment,
                        bot_id=int(event.self_id),
                        group_id=int(event.group_id),
                        message_id=int(event.message_id),
                    )
            await enqueue_repeater_learn(chat, event)
            return build_repeater_fanout_outcome(event, prepared.fanout_gate.bot_ids, prepared.bundle)

        for segment in event.message:
            if segment.type == "image":
                await insert_image(
                    segment,
                    bot_id=int(event.self_id),
                    group_id=int(event.group_id),
                    message_id=int(event.message_id),
                )
        await enqueue_repeater_learn(chat, event)

        answers = await chat.answer_from_bundle(prepared.bundle)
        if answers is None:
            return HandlingOutcome(handled=True)

        from pallas.core.foundation.config import BotConfig
        from pallas.core.platform.ingress.hotpath_metrics import record_reply_local_dispatched

        await BotConfig(int(event.self_id), int(event.group_id)).refresh_cooldown("repeat")
        record_reply_local_dispatched()
        return build_repeater_local_reply_outcome(int(event.self_id), int(event.group_id), answers)

    async def handle(self, context: MessageContext, *, bot: Bot, event: Event) -> HandlingOutcome:
        if not self.accepts(context):
            return HandlingOutcome(handled=False, fallback_to_legacy=True)
        return await self.build_fanout_plan(context, bot=bot, event=event)
