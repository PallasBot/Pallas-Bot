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
        if event.is_tome() or prepared.bundle is None or prepared.fanout_gate is None or not prepared.fanout_gate.won:
            return HandlingOutcome(handled=False, fallback_to_legacy=True)

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

    async def handle(self, context: MessageContext, *, bot: Bot, event: Event) -> HandlingOutcome:
        if not self.accepts(context):
            return HandlingOutcome(handled=False, fallback_to_legacy=True)
        return await self.build_fanout_plan(context, bot=bot, event=event)
