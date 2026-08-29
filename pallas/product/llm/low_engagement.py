"""低投入表达出口：PASS 时可选投一条极短 soft 气泡。

形态约束（见 specs/2026-08-22-low-engagement-exit-design.md）：
接住上一句的极短表达（单字/短吐槽/曲解/表情），≤12 字、无问句/祈使、
不堆叠语气词；不经 LLM 生成（本地取句）。默认乖巧，不学怼人腔。
"""

from __future__ import annotations

import random
import re
from re import Pattern

_QUESTION_OR_IMPERATIVE_TAIL_RE: Pattern[str] = re.compile(r"[？?！!。.]|[吗呢嘛吧呀]+$")
_CQ_CODE_RE = re.compile(r"\[CQ:")
_MAX_SAYING_CHARS = 12
_EMOJI_FALLBACK_POOL = ["😄😄😄", "哈哈哈哈", "（（", "（", "www"]

# 情绪触发词：命中则优先走「梗型跳脱」池
_EMOTION_TRIGGER_KEYWORDS = (
    "难绷",
    "绷",
    "破防",
    "麻了",
    "emo",
    "玉玉",
    "崩溃",
    "想死",
    "哭",
    "太惨",
    "无聊",
    "好烦",
    "烦死",
    "累",
    "心累",
    "焦虑",
    "离谱",
    "裂开",
    "烦",
    "气死",
    "要死",
    "好气",
)

# 情绪场景的「单句冷转移/跳脱」——来自真实语料提炼（干净、不攻击、跨群可复用）
_EMOTION_TANGENT_POOL = [
    "阴完了",
    "没绷住",
    "我有点累",
    "困了",
    "休息会",
    "看完释怀了",
    "不知道为什么",
    "我有个问题",
    "离大谱",
    "这也进",
]

_GENTLE_POOL = [
    "哈哈",
    "嗯嗯",
    "确实",
    "不意外",
    "这个没事",
    "难绷",
    "那没事了",
    "神了",
    "还真是",
    "可以可以",
    "笑死我了",
    "好的",
    "哦哦",
    "嗐",
    "乐了",
    "不赖",
]

_last_used_cache: dict[int, str] = {}


def _is_gentle_short_saying(saying: str) -> bool:
    text = str(saying or "").strip()
    if not text:
        return False
    if len(text) > _MAX_SAYING_CHARS:
        return False
    if _CQ_CODE_RE.search(text):
        return False
    if _QUESTION_OR_IMPERATIVE_TAIL_RE.search(text):
        return False
    return True


def _is_emotion_turn(trigger_text: str) -> bool:
    return any(kw in trigger_text for kw in _EMOTION_TRIGGER_KEYWORDS)


def pick_emotion_tangent_saying(rng: random.Random | None = None) -> str:
    """情绪场景：单句冷转移池取一句（不经 LLM）。"""
    rng = rng or random
    candidates = [*_EMOTION_TANGENT_POOL, *_EMOJI_FALLBACK_POOL]
    last = _last_used_cache.get(-1)
    filtered = [item for item in candidates if item != last] or candidates
    choice = str(rng.choice(filtered))
    _last_used_cache[-1] = choice
    return choice


def list_gentle_short_sayings(group_id: int, *, limit: int = 16) -> list[str]:
    """Return this group's local gentle short-saying pool (capped)."""
    pool = [item for item in _GENTLE_POOL if _is_gentle_short_saying(item)]
    seen: set[str] = set()
    unique: list[str] = []
    for saying in pool:
        if saying in seen:
            continue
        seen.add(saying)
        unique.append(saying)
    return unique[: max(1, int(limit))]


def pick_low_engagement_saying(group_id: int, rng: random.Random | None = None) -> str:
    """Pick a low-engagement phrase, avoiding immediate repeats for the same group."""
    rng = rng or random
    candidates = list_gentle_short_sayings(group_id) + [*_EMOTION_TANGENT_POOL, *_EMOJI_FALLBACK_POOL]
    if not candidates:
        return "哈哈"
    last = _last_used_cache.get(int(group_id))
    filtered = [item for item in candidates if item != last] or candidates
    choice = str(rng.choice(filtered))
    _last_used_cache[int(group_id)] = choice
    return choice


def clear_low_engagement_last_used() -> None:
    _last_used_cache.clear()


def low_engagement_emit_probability(recent_bot_reply_count: int) -> float:
    """返回给定「群被忽略度」的补泡概率；Bot 越久没说话越可能补一根气泡。"""
    count = max(0, int(recent_bot_reply_count))
    if count == 0:
        return 0.35
    if count <= 2:
        return 0.20
    if count <= 4:
        return 0.10
    return 0.05


def should_emit_low_engagement(recent_bot_reply_count: int, rng: random.Random | None = None) -> bool:
    rng = rng or random
    return rng.random() < low_engagement_emit_probability(recent_bot_reply_count)


async def dispatch_low_engagement(
    *,
    bot_id: int,
    group_id: int,
    user_id: int,
    recent_bot_reply_count: int,
    send_message: object,
    rng: random.Random | None = None,
    trigger_text: str = "",
) -> bool:
    """PASS 分支的落地：掷一次概率，命中则取句并发送；否则真静默。

    分场景取句：触发文本带情绪词时优先从「梗型跳脱」池取（单句冷转移，真实语料
    支持的主流接法）；其余仍走通用 soft 句池。Returns whether a low-engagement
    bubble was delivered.
    """
    if not should_emit_low_engagement(recent_bot_reply_count, rng=rng):
        return False
    saying = (
        pick_emotion_tangent_saying(rng=rng)
        if _is_emotion_turn(str(trigger_text or ""))
        else pick_low_engagement_saying(int(group_id), rng=rng)
    )
    await send_message(saying)
    try:
        from pallas.core.platform.ai_callback.task_types import LLM_CHAT_TASK_TYPE
        from pallas.product.llm.task_metrics import record_bot_llm_task

        record_bot_llm_task(LLM_CHAT_TASK_TYPE, "low_engagement_emit")
    except Exception:
        pass
    try:
        from packages.repeater.opportunity_trace import append_conversation_decision_trace

        append_conversation_decision_trace({
            "group_id": int(group_id),
            "bot_id": int(bot_id or 0),
            "kind": "low_engagement_emit",
            "user_id": int(user_id or 0),
            "saying": saying,
        })
    except Exception:
        pass
    return True


def can_bubble_low_engagement_on_necessity_skip(
    *,
    text: str,
    bot_id: int | None = None,
    recent_bot_reply_count: int = 0,
) -> bool:
    """necessity gate 判 skip 时，判定是否值得走低投入冒泡而非直接静默。

    复用 reply_necessity 的硬静默原语：noise/spam/incomplete/bystander 任一命中即
    真静默（spec 边界「该静默的仍然静默」）；其余低价值社交短消息（low_social /
    short_reaction 扣分项）可冒泡。
    """
    from pallas.product.llm.reply_necessity import (
        is_bystander_plain_text,
        is_high_frequency_short_reaction,
        is_incomplete_utterance,
        is_low_value_social_turn,
        is_noise_fragment,
        looks_like_spam_or_promo,
    )

    plain = str(text or "").strip()
    if not plain:
        return False
    if is_high_frequency_short_reaction(plain):
        return True
    if is_noise_fragment(plain):
        return False
    if looks_like_spam_or_promo(plain):
        return False
    if is_incomplete_utterance(plain):
        return False
    if is_bystander_plain_text(plain, bot_id=bot_id):
        return False
    return is_low_value_social_turn(plain)
