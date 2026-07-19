from __future__ import annotations

import random
import time
from collections import defaultdict, deque
from functools import cmp_to_key
from typing import TYPE_CHECKING, Any

from nonebot.adapters.onebot.v11 import Message

from pallas.core.foundation.config import BotConfig
from pallas.product.persona import resolve_persona
from pallas.product.persona.model import ResolvedPersona
from pallas.product.persona.scorer import scaled_speak_threshold, speak_keyword_group_weight, speak_message_weight

from .activity_gate import blocks_proactive_speak
from .ban_manager import BanManager
from .message_store import MessageStore
from .model import Chat, ChatData
from .responder import Responder

if TYPE_CHECKING:
    import asyncio

    from pallas.core.foundation.db import Message as MessageModel


class Speaker:
    """主动发言模块，根据群聊活跃度自动触发发言"""

    SPEAK_THRESHOLD = Chat.SPEAK_THRESHOLD
    SPEAK_FLAG = Chat.SPEAK_FLAG
    SPEAK_CONTINUOUSLY_PROBABILITY = Chat.SPEAK_CONTINUOUSLY_PROBABILITY
    SPEAK_POKE_PROBABILITY = Chat.SPEAK_POKE_PROBABILITY
    SPEAK_CONTINUOUSLY_MAX_LEN = Chat.SPEAK_CONTINUOUSLY_MAX_LEN
    DUPLICATE_REPLY = Chat.DUPLICATE_REPLY
    REPLY_FLAG = Chat.REPLY_FLAG

    _recent_speak = defaultdict(lambda: deque(maxlen=Chat.DUPLICATE_REPLY))

    @staticmethod
    def _pick_speak_message(
        persona: ResolvedPersona,
        candidate_pool: list[Any],
        recently: deque[str],
    ) -> Any:
        recent_list = list(recently)
        keyword_groups: defaultdict[str, list[Any]] = defaultdict(list)
        for msg in candidate_pool:
            keyword_groups[msg.keywords].append(msg)

        groups = list(keyword_groups.values())
        group_weights = [speak_keyword_group_weight(group, persona, recent_speaks=recent_list) for group in groups]
        chosen_group = random.choices(groups, weights=group_weights, k=1)[0]

        msg_weights = [
            speak_message_weight(
                str(getattr(msg, "plain_text", None) or getattr(msg, "raw_message", "") or ""),
                persona,
                recent_speaks=recent_list,
            )
            for msg in chosen_group
        ]
        return random.choices(chosen_group, weights=msg_weights, k=1)[0]

    @staticmethod
    async def speak(
        reply_dict: defaultdict,
        reply_lock: asyncio.Lock,
        recent_topics,
        topics_lock: asyncio.Lock,
    ) -> tuple[int, int, list[Message], int | None] | None:
        """
        根据群聊活跃度判断是否主动发言，返回 (bot_id, group_id, 消息列表, 戳一戳目标) 或 None
        """
        basic_msgs_len = 10
        basic_delay = 600

        def group_popularity_cmp(lhs: tuple[int, list[MessageModel]], rhs: tuple[int, list[MessageModel]]) -> int:
            def cmp(a: int | float, b: int | float) -> int:
                return (a > b) - (a < b)

            _, lhs_msgs = lhs
            _, rhs_msgs = rhs

            lhs_len = len(lhs_msgs)
            rhs_len = len(rhs_msgs)

            if lhs_len < basic_msgs_len or rhs_len < basic_msgs_len:
                return cmp(lhs_len, rhs_len)

            lhs_duration = lhs_msgs[-1].time - lhs_msgs[0].time
            rhs_duration = rhs_msgs[-1].time - rhs_msgs[0].time

            if not lhs_duration or not rhs_duration:
                return cmp(lhs_len, rhs_len)

            return cmp(lhs_len / lhs_duration, rhs_len / rhs_duration)

        async with MessageStore._message_lock:
            message_items = list(MessageStore._message_dict.items())
        popularity = sorted(message_items, key=cmp_to_key(group_popularity_cmp))

        cur_time = time.time()
        for group_id, group_msgs in popularity:
            if blocks_proactive_speak(group_id):
                continue

            group_replies = reply_dict[group_id]
            if not len(group_replies) or len(group_msgs) < basic_msgs_len:
                continue

            group_replies_front = list(group_replies.values())[0]
            if not len(group_replies_front) or group_replies_front[-1]["time"] > group_msgs[-1].time:
                continue

            msgs_len = len(group_msgs)
            latest_time = group_msgs[-1].time
            duration = latest_time - group_msgs[0].time
            avg_interval = duration / msgs_len

            candidate_bot_ids = [bid for bid in group_replies.keys() if bid]
            from pallas.core.platform.shard.registry.config import is_sharding_active

            from .shard_opt import local_connected_bot_ids

            if is_sharding_active():
                local_bots = local_connected_bot_ids()
                candidate_bot_ids = [bid for bid in candidate_bot_ids if bid in local_bots]
            if not candidate_bot_ids:
                continue
            speak_bias = 1.0
            activity_persona = None
            for bid in candidate_bot_ids:
                persona = await resolve_persona(bid, group_id)
                speak_bias = max(speak_bias, persona.speak_bias)
                if activity_persona is None:
                    activity_persona = persona

            eff_speak_threshold = scaled_speak_threshold(
                Speaker.SPEAK_THRESHOLD,
                ResolvedPersona(speak_bias=speak_bias),
            )
            from pallas.product.persona.activity_ingress import activity_speak_threshold_multiplier
            from pallas.product.persona.config import persona_activity_ingress_enabled

            if persona_activity_ingress_enabled() and activity_persona is not None:
                eff_speak_threshold *= activity_speak_threshold_multiplier(activity_persona.activity_level)

            if cur_time - latest_time < avg_interval * eff_speak_threshold + basic_delay:
                continue

            async with reply_lock:
                group_replies_front.append({
                    "time": int(cur_time),
                    "pre_raw_message": Speaker.SPEAK_FLAG,
                    "pre_keywords": Speaker.SPEAK_FLAG,
                    "reply": Speaker.SPEAK_FLAG,
                    "reply_keywords": Speaker.SPEAK_FLAG,
                })

            from pallas.core.platform.multi_bot.platform_utils import pick_connected_bot_id

            picked = pick_connected_bot_id(candidate_bot_ids, log_tag="repeater.speak")
            bot_id = picked if picked is not None else random.choice(candidate_bot_ids)

            ban_keywords = await BanManager.find_ban_keywords(context=None, group_id=group_id)

            recently = Speaker._recent_speak[group_id]

            def msg_filter(msg: MessageModel) -> bool:
                cur_raw_message = msg.raw_message
                cur_keywords = msg.keywords
                return (
                    cur_keywords not in ban_keywords  # noqa: B023
                    and cur_raw_message not in recently  # noqa: B023
                    and not cur_raw_message.startswith("牛牛")
                    and not cur_raw_message.startswith("[CQ:xml")
                    and "\n" not in cur_raw_message
                )

            available_messages = list(filter(msg_filter, group_msgs))
            if not available_messages:
                continue

            taken_name = await BotConfig(bot_id, group_id).taken_name()
            pretend_msg = list(filter(lambda msg: msg.user_id == taken_name, available_messages))
            candidate_pool = pretend_msg or available_messages

            speak_persona = await resolve_persona(bot_id, group_id)
            first_message = Speaker._pick_speak_message(speak_persona, candidate_pool, recently)
            speak = first_message.raw_message
            Speaker._recent_speak[group_id].append(speak)

            async with reply_lock:
                group_replies[bot_id].append({
                    "time": int(cur_time),
                    "pre_raw_message": Speaker.SPEAK_FLAG,
                    "pre_keywords": Speaker.SPEAK_FLAG,
                    "reply": speak,
                    "reply_keywords": Speaker.SPEAK_FLAG,
                })
                from .reply_record_sync import publish_reply_record

                publish_reply_record(group_id, bot_id, group_replies[bot_id][-1])

            speak_list = [
                Message(speak),
            ]

            while (
                random.random() < Speaker.SPEAK_CONTINUOUSLY_PROBABILITY
                and len(speak_list) < Speaker.SPEAK_CONTINUOUSLY_MAX_LEN
            ):
                pre_msg = str(speak_list[-1])

                answer_generator = await Responder.answer(
                    ChatData(group_id, 0, pre_msg, pre_msg, int(cur_time), 0),
                    BotConfig(0, group_id),
                    reply_dict,
                    reply_lock,
                    recent_topics,
                    topics_lock,
                )
                if not answer_generator:
                    break

                new_messages = [msg_item async for msg_item in answer_generator]
                if not new_messages:
                    break

                speak_list.extend(new_messages)

            target_id = None
            if random.random() < Speaker.SPEAK_POKE_PROBABILITY:
                target_id = random.choice(group_msgs).user_id

            from pallas.product.llm.proactive_emitter import ProactiveEmitContext, emit_proactive

            await emit_proactive(
                ProactiveEmitContext(
                    source="repeater.speak",
                    group_id=group_id,
                    metadata={"bot_id": bot_id},
                )
            )

            return (bot_id, group_id, speak_list, target_id)

        return None
