import asyncio
import random
import time
from collections import defaultdict
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nonebot import get_bots, logger
from nonebot.adapters.onebot.v11 import Message

from pallas.core.foundation.config import BotConfig
from pallas.core.foundation.db import Answer
from pallas.core.foundation.db.context_repo_access import context_repo
from pallas.core.foundation.db.pool_budget import is_pg_pool_timeout_error, pg_pool_under_pressure
from pallas.core.platform.shard import context as shard_ctx
from pallas.core.platform.shard.repeater_ingress_metrics import record_repeater_reply_selection
from pallas.product.llm.kernel.memory_governance import can_apply_feedback_bias
from pallas.product.llm.repeater_feedback import group_feedback_bias_snapshot
from pallas.product.persona.model import ResolvedPersona
from pallas.product.persona.scorer import freshness_multiplier, message_weight_multiplier

from .ban_manager import BanManager
from .config import get_repeater_config
from .opportunity_trace import append_repeater_opportunity_trace
from .topic_utils import filtered_recent_topics

if TYPE_CHECKING:
    from .model import ChatData


plugin_config = get_repeater_config()


@dataclass(frozen=True)
class ReplyBundle:
    """一次 context 检索结果；fanout 时各牛从 message_pool 轻量随机，不再重复查库。"""

    answer_list: list[str]
    answer_keywords: str
    message_pool: list[str]
    reply_mode: str = "normal"
    reply_source: str = "same_group"
    recent_hit: bool = False
    repeat_hit: bool = False
    pick_path: str = "default"


class Responder:
    """回复决策模块，负责根据上下文检索候选回答并选择最终回复"""

    NON_PLAIN_CORPUS_SKIP_LEN = 256
    SHORT_PLAIN_SKIP_LEN = 2
    EMPTY_KEYWORDS_PLAIN_SKIP_LEN = 4
    ANSWER_THRESHOLD = plugin_config.answer_threshold
    ANSWER_THRESHOLD_WEIGHTS = plugin_config.answer_threshold_weights
    TOPICS_SIZE = plugin_config.topics_size
    TOPICS_IMPORTANCE = plugin_config.topics_importance
    CROSS_GROUP_THRESHOLD = plugin_config.cross_group_threshold
    REPEAT_THRESHOLD = plugin_config.repeat_threshold
    DUPLICATE_REPLY = plugin_config.duplicate_reply

    SPLIT_PROBABILITY = plugin_config.split_probability

    SAVE_RESERVED_SIZE = plugin_config.save_reserved_size
    GOD_ACTIVITY_THRESHOLD = 0.6
    GHOST_ACTIVITY_THRESHOLD = 0.45
    GHOST_PICK_ACTIVITY_THRESHOLD = 0.72
    # 神鬼是偶发风味：大多数回复仍走 normal，符合人格条件时也只按概率「入戏」，
    # 避免在活跃群里几乎必进特殊模式而显得整天在复读/无厘头。
    GOD_MODE_PROBABILITY = 0.3
    GHOST_MODE_PROBABILITY = 0.3

    ANSWER_THRESHOLD_CHOICE_LIST = list(
        range(ANSWER_THRESHOLD - len(ANSWER_THRESHOLD_WEIGHTS) + 1, ANSWER_THRESHOLD + 1)
    )
    BLACKLIST_FLAG = 114514
    REPLY_FLAG = "[PallasBot: Reply]"
    FEEDBACK_BIAS_LIMIT = 40
    FEEDBACK_BIAS_MAX_MULTIPLIER = 1.08
    FEEDBACK_BIAS_MATCHED_MULTIPLIER = 1.18
    FEEDBACK_BIAS_PARTIAL_MULTIPLIER = 1.05
    FEEDBACK_BIAS_MIN_COUNT = 2
    FEEDBACK_BIAS_MATCHED_MIN_COUNT = 1

    @staticmethod
    def _repeat_ignore_user_ids() -> set[int]:
        from pallas.core.platform.multi_bot.fleet import get_catalog_bot_ids

        if shard_ctx.sharding_active():
            ids = set(get_catalog_bot_ids())
        else:
            ids = {int(b.self_id) for b in get_bots().values()}
        ids.update(plugin_config.repeat_ignore_user_ids)
        return ids

    @staticmethod
    def _group_activity_score(group_msgs: list) -> float:
        if not group_msgs:
            return 0.0
        human_msgs = Responder._human_messages_for_repeat(group_msgs)
        if not human_msgs:
            return 0.0
        recent = human_msgs[-12:]
        unique_users = {int(uid) for msg in recent if (uid := getattr(msg, "user_id", None)) is not None}
        activity = min(len(recent), 12) / 12.0
        diversity = min(len(unique_users), 5) / 5.0
        return round(activity * 0.7 + diversity * 0.3, 3)

    @staticmethod
    def _choose_reply_mode(persona, *, group_activity: float, to_me: bool) -> str:
        if to_me:
            return "normal"
        chaos = float(getattr(persona, "chaos_bias", 0.0) or 0.0)
        reply_bias = float(getattr(persona, "reply_bias", 1.0) or 1.0)
        warmth = float(getattr(persona, "warmth", 0.0) or 0.0)
        assertiveness = float(getattr(persona, "assertiveness", 0.0) or 0.0)
        if chaos >= 0.72 and group_activity >= Responder.GHOST_ACTIVITY_THRESHOLD:
            return "ghost"
        if (
            chaos <= 0.18
            and group_activity >= Responder.GOD_ACTIVITY_THRESHOLD
            and (reply_bias >= 1.0 or warmth >= 0.08 or assertiveness >= 0.08)
        ):
            return "god"
        return "normal"

    @staticmethod
    def _roll_active_mode(mode: str) -> str:
        """符合人格条件后再掷一次骰子决定是否真的入戏，让神鬼时有时无。"""
        if mode == "god":
            return "god" if random.random() < Responder.GOD_MODE_PROBABILITY else "normal"
        if mode == "ghost":
            return "ghost" if random.random() < Responder.GHOST_MODE_PROBABILITY else "normal"
        return mode

    @staticmethod
    def _sample_mode_multiplier(text: str, *, mode: str, recent_message: list[str], persona) -> float:
        plain = (text or "").strip()
        if not plain:
            return 0.05
        length = len(plain)
        chaos = float(getattr(persona, "chaos_bias", 0.0) or 0.0)
        bluntness = float(getattr(persona, "bluntness", 0.0) or 0.0)
        warmth = float(getattr(persona, "warmth", 0.0) or 0.0)
        assertiveness = float(getattr(persona, "assertiveness", 0.0) or 0.0)
        recent_hits = recent_message.count(plain)
        if mode == "god":
            # 神＝挑「贴切、像样」的语料，不再因为某句正在群里刷就加权跟读。
            multiplier = 1.0
            if length <= 18:
                multiplier *= 1.08
            if warmth > 0:
                multiplier *= 1.0 + min(warmth, 0.4) * 0.18
            if assertiveness > 0:
                multiplier *= 1.0 + min(assertiveness, 0.4) * 0.12
            return max(0.05, multiplier)
        if mode == "ghost":
            multiplier = 1.0 + chaos * 0.35
            if length <= 8:
                multiplier *= 1.35 + chaos * 0.35
            elif length >= 20:
                multiplier *= max(0.7, 1.0 - chaos * 0.3)
            if recent_hits == 0:
                multiplier *= 1.08
            if bluntness > 0:
                multiplier *= 1.0 + min(bluntness, 0.5) * 0.2
            return max(0.05, multiplier)
        return 1.0

    @staticmethod
    def _ghost_candidate_rank(text: str) -> tuple[int, int, int]:
        plain = (text or "").strip()
        if not plain:
            return (-1, -99, -99)
        short_bonus = 2 if len(plain) <= 8 else (1 if len(plain) <= 14 else 0)
        odd_markers = ("寄", "草", "笑死", "有点", "这什么", "怎么个事", "什么鬼")
        odd_bonus = sum(1 for token in odd_markers if token in plain)
        punct_bonus = sum(1 for token in ("?", "？", "!", "！", "~", "…") if token in plain)
        return (short_bonus + odd_bonus + punct_bonus, -len(plain), odd_bonus)

    @staticmethod
    def _collect_mode_candidate_pool(
        answer: Answer,
        *,
        mode: str,
        recent_message: list[str],
    ) -> list[str]:
        base_pool: list[str] = []
        for sample in answer.messages:
            text = sample.removeprefix("牛牛").strip()
            if text and text not in base_pool:
                base_pool.append(text)
        if mode == "god":
            # 神不跟读群里此刻在刷的原话；优先挑短而干净、未在刷屏的语料。
            live = {str(text or "").strip() for text in recent_message if str(text or "").strip()}
            fresh = [text for text in base_pool if text not in live]
            return fresh or base_pool
        if mode == "ghost":
            return sorted(base_pool, key=Responder._ghost_candidate_rank, reverse=True)
        return base_pool

    @staticmethod
    def _answer_weight_for_mode(
        answer: Answer,
        persona,
        *,
        recent_sent: list[str],
        recent_message: list[str],
        affect_triggers,
        mode: str,
        feedback_snapshot: dict | None = None,
    ) -> float:
        from pallas.product.persona.scorer import (
            answer_popularity_multiplier,
            freshness_multiplier,
            message_weight_multiplier,
        )

        base = min(answer.count, 10) + answer._topical * Responder.TOPICS_IMPORTANCE
        if mode != "ghost":
            base *= answer_popularity_multiplier(answer.count, persona)
        elif answer.count >= 4:
            base *= max(0.75, 1.0 - min(answer.count, 10) * 0.04)
        mults = []
        for sample in answer.messages:
            text = sample.removeprefix("牛牛")
            sample_weight = (
                message_weight_multiplier(text, persona, affect_triggers=affect_triggers)
                * freshness_multiplier(text, recent_sent, persona=persona)
                * Responder._sample_mode_multiplier(
                    text,
                    mode=mode,
                    recent_message=recent_message,
                    persona=persona,
                )
                * Responder._feedback_bias_multiplier(
                    text,
                    feedback_snapshot=feedback_snapshot,
                )
            )
            mults.append(sample_weight)
        factor = max(mults) if mults else 1.0
        if mode == "god":
            factor *= 1.18
        elif mode == "ghost":
            factor *= 1.12
        return max(0.05, base * factor)

    @staticmethod
    def _feedback_bias_multiplier(
        text: str,
        *,
        feedback_snapshot: dict | None,
    ) -> float:
        from pallas.product.llm.feedback_learning import feedback_bias_multiplier_for_text

        return feedback_bias_multiplier_for_text(
            text,
            feedback_snapshot=feedback_snapshot,
            max_multiplier=Responder.FEEDBACK_BIAS_MATCHED_MULTIPLIER,
            matched_multiplier=Responder.FEEDBACK_BIAS_MATCHED_MULTIPLIER,
            semantic_multiplier=1.12,
            top_multiplier=Responder.FEEDBACK_BIAS_MAX_MULTIPLIER,
            partial_multiplier=Responder.FEEDBACK_BIAS_PARTIAL_MULTIPLIER,
            penalty_multiplier=0.45,
            min_count=Responder.FEEDBACK_BIAS_MIN_COUNT,
            matched_min_count=Responder.FEEDBACK_BIAS_MATCHED_MIN_COUNT,
        )

    @staticmethod
    def _pick_answer_text(
        answer: Answer,
        *,
        mode: str,
        recent_message: list[str],
        recent_sent: list[str],
        group_activity: float,
        persona,
    ) -> tuple[str, str]:
        pool = Responder._collect_mode_candidate_pool(answer, mode=mode, recent_message=recent_message)
        if not pool:
            pool = [sample.removeprefix("牛牛").strip() for sample in answer.messages if sample.strip()]
        if not pool:
            return "", "default"
        # 硬约束：最近 DUPLICATE_REPLY 条说过的一律排除，宁可不接也不复读自己。
        fresh = [text for text in pool if text not in recent_sent]
        if not fresh:
            return "", "default"
        if mode == "god":
            return fresh[0], "god_pool"
        if mode == "ghost":
            chaos = float(getattr(persona, "chaos_bias", 0.0) or 0.0)
            if group_activity >= Responder.GHOST_PICK_ACTIVITY_THRESHOLD and chaos >= 0.72:
                return fresh[0], "ghost_pool"
        return random.choice(fresh), "default"

    @staticmethod
    def _human_messages_for_repeat(group_msgs: list) -> list:
        ignore = Responder._repeat_ignore_user_ids()
        return [m for m in group_msgs if (uid := getattr(m, "user_id", None)) is None or uid not in ignore]

    @staticmethod
    def evaluate_llm_candidate_text(
        text: str,
        *,
        base_score: float,
        min_score: float,
        recent_sent: list[str] | None = None,
        persona: ResolvedPersona | None = None,
        affect_triggers: list[dict] | None = None,
        reply_mode: str = "normal",
    ) -> tuple[bool, float]:
        plain = str(text or "").strip()
        if not plain:
            return False, 0.0
        score = max(0.0, float(base_score))
        if persona is not None:
            score *= message_weight_multiplier(plain, persona, affect_triggers=affect_triggers)
            score *= freshness_multiplier(plain, recent_sent or [], persona=persona)
        mode = str(reply_mode or "normal").strip().lower()
        try:
            from pallas.product.llm.kernel.models import normalize_conversation_mode
            from pallas.product.persona.affect_kernel import (
                affect_contract_to_constraints,
                build_persona_affect_contract,
            )

            contract = build_persona_affect_contract(persona, mode=normalize_conversation_mode(mode))
            constraints = affect_contract_to_constraints(contract)
            if constraints.max_length and len(plain) > constraints.max_length:
                score *= 0.85
            if constraints.min_length and len(plain) < constraints.min_length:
                score *= 0.9
        except Exception:
            pass
        if mode == "ghost":
            if len(plain) <= 8:
                score *= 1.12
            if "？" in plain or "!" in plain or "！" in plain or "?" in plain:
                score *= 1.08
        elif mode == "god":
            if len(plain) > 18:
                score *= 0.92
            if recent_sent and plain in recent_sent:
                score *= 0.85
        if recent_sent and plain in recent_sent:
            score *= 0.3
        return score >= float(min_score), score

    @staticmethod
    def should_skip_context_lookup(chat_data: "ChatData", keywords: str) -> bool:
        if getattr(chat_data, "is_plain_text", False):
            if getattr(chat_data, "to_me", False):
                return False
            plain = str(getattr(chat_data, "plain_text", "") or "").strip()
            if shard_ctx.sharding_active():
                return not plain
            keywords_len = int(getattr(chat_data, "keywords_len", 0) or 0)
            if keywords_len == 0:
                return 0 < len(plain) <= Responder.EMPTY_KEYWORDS_PLAIN_SKIP_LEN
            if keywords_len == 1:
                return 0 < len(plain) <= Responder.SHORT_PLAIN_SKIP_LEN
            return False
        plain = str(getattr(chat_data, "plain_text", "") or "").strip()
        # 纯 CQ / 媒体消息没有可复用的语义，直接跳过语料 miss。
        if not plain:
            return True
        if getattr(chat_data, "keywords_len", 0) != 0:
            return False
        return len(keywords) >= Responder.NON_PLAIN_CORPUS_SKIP_LEN

    @staticmethod
    async def answer(
        chat_data: "ChatData",
        config: BotConfig,
        reply_dict,
        reply_lock,
        recent_topics,
        topics_lock,
    ) -> AsyncGenerator[Message, None] | None:
        """
        回复这句话，可能会分多次回复，也可能不回复
        """
        # 不回复太短的对话，大部分是“？”、“草”
        if chat_data.is_plain_text and len(chat_data.plain_text) < 2:
            if not shard_ctx.sharding_active():
                return None

        from .message_store import MessageStore

        bundle = await Responder.find_reply_bundle(
            chat_data, config, reply_dict, MessageStore._message_dict, recent_topics
        )
        if not bundle:
            return None

        return await Responder.answer_from_bundle(
            bundle,
            chat_data,
            config,
            reply_dict,
            reply_lock,
            recent_topics,
            topics_lock,
        )

    @staticmethod
    async def answer_from_bundle(
        bundle: ReplyBundle,
        chat_data: "ChatData",
        config: BotConfig,
        reply_dict,
        reply_lock,
        recent_topics,
        topics_lock,
        *,
        plan: tuple[list[str], str] | None = None,
    ) -> AsyncGenerator[Message, None] | None:
        answer_list, answer_keywords = plan if plan is not None else (bundle.answer_list, bundle.answer_keywords)
        if not answer_list:
            return None

        group_id = chat_data.group_id
        bot_id = chat_data.bot_id
        group_bot_replies = reply_dict[group_id][bot_id]

        raw_message = chat_data.raw_message
        keywords = chat_data.keywords
        from .reply_record_sync import publish_reply_record

        async with reply_lock:
            group_bot_replies.append({
                "time": int(time.time()),
                "pre_raw_message": raw_message,
                "pre_keywords": keywords,
                "reply": Responder.REPLY_FLAG,
                "reply_keywords": Responder.REPLY_FLAG,
            })

        async def yield_results(results: tuple[list[str], str]) -> AsyncGenerator[Message, None]:
            answer_list, answer_keywords = results
            group_bot_replies = reply_dict[group_id][bot_id]
            try:
                for item in answer_list:
                    async with reply_lock:
                        group_bot_replies.append({
                            "time": int(time.time()),
                            "pre_raw_message": raw_message,
                            "pre_keywords": keywords,
                            "reply": item,
                            "reply_keywords": answer_keywords,
                        })
                        publish_reply_record(group_id, bot_id, group_bot_replies[-1])
                    if "[CQ:" not in item:
                        async with topics_lock:
                            recent_topics[group_id] += filtered_recent_topics(answer_keywords.split(" "))
                    async with topics_lock:
                        recent_topics[group_id] += filtered_recent_topics(chat_data._keywords_list)
                    yield Message(item)
            finally:
                async with reply_lock:
                    reply_dict[group_id][bot_id][:] = reply_dict[group_id][bot_id][-Responder.SAVE_RESERVED_SIZE :]

        return yield_results((answer_list, answer_keywords))

    @staticmethod
    async def find_reply_bundle(
        chat_data: "ChatData",
        config: BotConfig,
        reply_dict,
        message_dict,
        recent_topics,
    ) -> ReplyBundle | None:
        found = await Responder._context_find_with_pool(chat_data, config, reply_dict, message_dict, recent_topics)
        if not found:
            return None
        return found

    @staticmethod
    async def _context_find(
        chat_data: "ChatData",
        config: BotConfig,
        reply_dict,
        message_dict,
        recent_topics,
    ) -> tuple[list[str], str] | None:
        found = await Responder._context_find_with_pool(chat_data, config, reply_dict, message_dict, recent_topics)
        if not found:
            return None
        return found.answer_list, found.answer_keywords

    @staticmethod
    async def reply_post_proc(
        raw_message: str, new_msg: str, bot_id: int, group_id: int, reply_dict, reply_lock
    ) -> bool:
        """
        对 bot 回复的消息进行后处理，将缓存替换为处理后的消息
        """

        if raw_message == new_msg:
            return True

        async with reply_lock:
            reply_data = reply_dict[group_id][bot_id][::-1]
            for item in reply_data:
                if item["reply"] == raw_message:
                    item["reply"] = new_msg
                    from .reply_record_sync import publish_reply_record

                    publish_reply_record(group_id, bot_id, item)
                    return True
        return False

    @staticmethod
    async def _context_find_with_pool(
        chat_data: "ChatData",
        config: BotConfig,
        reply_dict,
        message_dict,
        recent_topics,
    ) -> ReplyBundle | None:
        group_id = chat_data.group_id
        raw_message = chat_data.raw_message
        bot_id = chat_data.bot_id
        group_msgs = message_dict.get(group_id, [])

        # 复读！
        rt = Responder.REPEAT_THRESHOLD
        if rt >= 2 and group_id in message_dict:
            human_msgs = Responder._human_messages_for_repeat(group_msgs)
            tail = rt - 1
            if len(human_msgs) >= tail and all(item.raw_message == raw_message for item in human_msgs[-tail:]):
                # 到这里说明当前群里是在复读
                group_bot_replies = reply_dict[group_id][bot_id]
                if len(group_bot_replies) and group_bot_replies[-1]["reply"] != raw_message:
                    keywords = chat_data.keywords
                    return ReplyBundle(
                        answer_list=[raw_message],
                        answer_keywords=keywords,
                        message_pool=[raw_message],
                        reply_mode="normal",
                        reply_source="same_group",
                        recent_hit=True,
                        repeat_hit=True,
                        pick_path="default",
                    )
                else:
                    # 复读过一次就不再回复这句话了
                    return None

        plain_text = str(getattr(chat_data, "plain_text", "") or "").strip()
        if not getattr(chat_data, "is_plain_text", False) and not plain_text:
            return None

        keywords = chat_data.keywords
        if not keywords:
            return None
        if Responder.should_skip_context_lookup(chat_data, keywords):
            logger.debug(
                "repeater.skip_context_lookup group_id={} bot_id={} raw_len={} kw_len={}",
                group_id,
                bot_id,
                len(raw_message),
                len(keywords),
            )
            return None

        if pg_pool_under_pressure(threshold=0.55):
            logger.debug(
                "repeater.skip_reply_context pg_pool_pressure group_id={} bot_id={} kw_len={}",
                group_id,
                bot_id,
                len(keywords),
            )
            return None

        find_reply = getattr(context_repo, "find_by_keywords_for_reply", None)
        try:
            if callable(find_reply):
                context = await find_reply(keywords)
            else:
                context = await context_repo.find_by_keywords(keywords)
        except Exception as exc:
            if is_pg_pool_timeout_error(exc):
                logger.debug(
                    "repeater.skip_reply_context db_timeout group_id={} bot_id={} kw_len={}",
                    group_id,
                    bot_id,
                    len(keywords),
                )
                return None
            raise

        if not context:
            return None

        from pallas.product.persona import resolve_persona_for_message
        from pallas.product.persona.loader import load_affect_triggers
        from pallas.product.persona.scorer import scaled_answer_threshold

        from .activity_gate import group_has_hosted_activity

        persona = await resolve_persona_for_message(
            bot_id,
            group_id,
            str(getattr(chat_data, "plain_text", "") or chat_data.raw_message or ""),
        )
        affect_triggers = await load_affect_triggers(group_id)
        in_hosted_activity = group_has_hosted_activity(group_id) and not chat_data.to_me
        group_activity = Responder._group_activity_score(group_msgs)
        reply_mode = Responder._roll_active_mode(
            Responder._choose_reply_mode(
                persona,
                group_activity=group_activity,
                to_me=chat_data.to_me,
            )
        )

        is_drunk = await config.drunkenness() > 0

        if is_drunk:
            answer_count_threshold = 1
        else:
            answer_count_threshold = random.choices(
                Responder.ANSWER_THRESHOLD_CHOICE_LIST, weights=Responder.ANSWER_THRESHOLD_WEIGHTS
            )[0]
            from .model import ChatData

            if chat_data.keywords_len == ChatData._keywords_size:
                answer_count_threshold -= 1

        answer_count_threshold = scaled_answer_threshold(
            answer_count_threshold,
            persona,
            in_hosted_activity=in_hosted_activity,
        )

        if chat_data.to_me:
            cross_group_threshold = 1
        else:
            cross_group_threshold = Responder.CROSS_GROUP_THRESHOLD

        ban_keywords = await BanManager.find_ban_keywords(context=context, group_id=group_id)

        candidate_answers: dict[str, Answer] = {}
        other_group_cache = {}
        answers_count = defaultdict(int)
        recent_replies = [r["reply_keywords"] for r in reply_dict[group_id][bot_id][-Responder.DUPLICATE_REPLY :]]
        recent_message = [m.raw_message for m in message_dict[group_id][-Responder.DUPLICATE_REPLY :]]
        recent_sent = [
            str(r.get("reply") or "")
            for r in reply_dict[group_id][bot_id][-Responder.DUPLICATE_REPLY :]
            if r.get("reply") and r["reply"] != Responder.REPLY_FLAG
        ]
        feedback_snapshot = None
        trigger_text = str(getattr(chat_data, "plain_text", "") or chat_data.raw_message or "").strip()
        behavior_scene = ""
        try:
            from pallas.product.llm.behavior import classify_behavior_scene

            recent_texts = [str(getattr(item, "raw_message", "") or "") for item in group_msgs[-5:]]
            recent_users = {int(getattr(item, "user_id", 0) or 0) for item in group_msgs[-5:]}
            behavior_scene = str(
                classify_behavior_scene(
                    user_text=trigger_text,
                    recent_texts=recent_texts,
                    has_multi_party_overlap=len(recent_users) > 2,
                ).value
            )
        except Exception as exc:
            logger.warning("repeater.behavior_scene_failed group_id={}: {}", group_id, exc)
        if can_apply_feedback_bias():
            try:
                feedback_snapshot = await asyncio.to_thread(
                    group_feedback_bias_snapshot,
                    group_id=group_id,
                    limit=Responder.FEEDBACK_BIAS_LIMIT,
                    user_text=trigger_text,
                    behavior_scene=behavior_scene,
                )
            except Exception as exc:
                logger.warning("repeater.llm_feedback_bias_snapshot_failed group_id={}: {}", group_id, exc)

        def candidate_append(dst: dict[str, Answer], answer: Answer):
            answer_key = answer.keywords
            if "[CQ:" not in answer_key:
                topics = recent_topics[group_id]
                for key in answer_key.split(" "):
                    if key in topics:
                        answer._topical += topics.count(key)

            if answer_key not in dst:
                dst[answer_key] = answer
            else:
                pre_answer = dst[answer_key]
                pre_answer.count += answer.count
                pre_answer.messages += answer.messages

        for answer in context.answers:
            count = answer.count
            if not is_drunk and count < answer_count_threshold:
                continue

            answer_key = answer.keywords
            if answer_key in ban_keywords or answer_key in recent_replies or answer_key == keywords:
                continue

            if not answer.messages:
                continue

            sample_msg = answer.messages[0]
            if chat_data.is_image and "[CQ:" not in sample_msg:
                # 图片消息不回复纯文本。图片经常是表情包，后面的纯文本啥都有，很乱
                continue
            if sample_msg.startswith("牛牛"):
                if not chat_data.to_me or len(sample_msg) <= 6:
                    # 这种一般是学反过来的，比如有人教“牛牛你好”——“你好”
                    # 然后下次有人发“你好”，突然回个“牛牛你好”，有点莫名其妙的
                    continue
            if sample_msg.startswith("[CQ:xml"):
                continue
            if "\n" in sample_msg:
                continue
            if count < 3 and sample_msg in recent_message:  # 别人刚发的就重复，显得很笨
                continue

            if answer.group_id == group_id:
                candidate_append(candidate_answers, answer)
            # 别的群的 at, 忽略
            elif "[CQ:at,qq=" in sample_msg:
                continue
            elif is_drunk and count > answer_count_threshold:
                candidate_append(candidate_answers, answer)
            else:  # 有这么 N 个群都有相同的回复，就作为全局回复
                answers_count[answer_key] += 1
                cur_count = answers_count[answer_key]
                if cur_count < cross_group_threshold:  # 没达到阈值前，先缓存
                    candidate_append(other_group_cache, answer)
                elif cur_count == cross_group_threshold:  # 刚达到阈值时，将缓存加入
                    if cur_count > 1:
                        candidate_append(candidate_answers, other_group_cache[answer_key])
                    candidate_append(candidate_answers, answer)
                else:  # 超过阈值后，加入
                    candidate_append(candidate_answers, answer)

        if not candidate_answers:
            return None

        message_pool: list[str] = []
        for answer in candidate_answers.values():
            for sample in answer.messages:
                text = sample.removeprefix("牛牛")
                if text and text not in message_pool:
                    message_pool.append(text)

        weights = [
            Responder._answer_weight_for_mode(
                answer,
                persona,
                recent_sent=recent_sent,
                recent_message=recent_message,
                affect_triggers=affect_triggers,
                mode=reply_mode,
                feedback_snapshot=feedback_snapshot,
            )
            for answer in candidate_answers.values()
        ]
        final_answer = random.choices(list(candidate_answers.values()), weights=weights)[0]
        answer_str, pick_path = Responder._pick_answer_text(
            final_answer,
            mode=reply_mode,
            recent_message=recent_message,
            recent_sent=recent_sent,
            group_activity=group_activity,
            persona=persona,
        )
        if not answer_str:
            return None
        answer_keywords = final_answer.keywords
        reply_source = "same_group" if int(final_answer.group_id) == int(group_id) else "cross_group"
        recent_hit = answer_str in recent_message
        repeat_hit = answer_str in recent_sent

        plan = Responder._plan_from_answer_text(answer_str, answer_keywords)
        if plan is None:
            return None
        if not message_pool:
            message_pool = list(plan[0])
        record_repeater_reply_selection(
            mode=reply_mode,
            source=reply_source,
            recent_hit=recent_hit,
            repeat_hit=repeat_hit,
            pick_path=pick_path,
        )
        append_repeater_opportunity_trace({
            "kind": "repeater_reply_bundle",
            "group_id": int(group_id),
            "bot_id": int(bot_id),
            "reply_mode": str(reply_mode or "normal"),
            "reply_source": str(reply_source or "same_group"),
            "pick_path": str(pick_path or "default"),
            "group_activity": float(group_activity),
            "candidate_answer_count": len(candidate_answers),
            "message_pool_size": len(message_pool),
            "recent_hit": bool(recent_hit),
            "repeat_hit": bool(repeat_hit),
            "keywords": str(answer_keywords or "")[:120],
            "answer_preview": str(answer_str or "")[:80],
            "behavior_scene": behavior_scene,
            "feedback_bias_multiplier": float(
                Responder._feedback_bias_multiplier(answer_str, feedback_snapshot=feedback_snapshot)
            ),
        })
        return ReplyBundle(
            answer_list=plan[0],
            answer_keywords=plan[1],
            message_pool=message_pool,
            reply_mode=reply_mode,
            reply_source=reply_source,
            recent_hit=recent_hit,
            repeat_hit=repeat_hit,
            pick_path=pick_path,
        )

    @staticmethod
    def _plan_from_answer_text(answer_str: str, answer_keywords: str) -> tuple[list[str], str] | None:
        if not answer_str:
            return None
        if (
            0 < answer_str.count("，") <= 3
            and "[CQ:" not in answer_str
            and random.random() < Responder.SPLIT_PROBABILITY
        ):
            return (answer_str.split("，"), answer_keywords)
        return ([answer_str], answer_keywords)

    @staticmethod
    def pick_fanout_plan(bundle: ReplyBundle, bot_id: int) -> tuple[list[str], str]:
        """各牛从共享候选池选句，按 bot_id 稳定分化，避免齐声。"""
        pool = bundle.message_pool
        if len(pool) <= 1:
            return bundle.answer_list, bundle.answer_keywords
        rng = random.Random(int(bot_id) ^ hash(bundle.answer_keywords))
        text = rng.choice(pool)
        plan = Responder._plan_from_answer_text(text, bundle.answer_keywords)
        if plan is None:
            return bundle.answer_list, bundle.answer_keywords
        return plan
