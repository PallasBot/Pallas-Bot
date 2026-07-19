"""Scene-aware behavior primitives for llm_chat."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class BehaviorScene(StrEnum):
    PROVOCATION = "provocation"
    BANTER = "banter"
    SMALLTALK = "smalltalk"
    VENTING = "venting"
    GROUP_THREADING = "group_threading"
    LIGHT_HELP = "light_help"


class BehaviorAction(StrEnum):
    LIGHT_TEASE_AND_CLOSE = "light_tease_and_close"
    ACK_THEN_SHORT_REPLY = "ack_then_short_reply"
    FOLLOW_JOKE_ONCE = "follow_joke_once"
    ACK_EMOTION_NO_LECTURE = "ack_emotion_no_lecture"
    STAY_ON_CURRENT_TOPIC = "stay_on_current_topic"
    AVOID_FORCED_TOPIC_SHIFT = "avoid_forced_topic_shift"
    BRIEF_MULTI_PARTY_ANCHOR = "brief_multi_party_anchor"
    SHORT_HELP_THEN_STOP = "short_help_then_stop"


class BehaviorOutcome(StrEnum):
    ENGAGED = "engaged"
    NEUTRAL = "neutral"
    IGNORED = "ignored"
    AWKWARD = "awkward"
    DERAILED = "derailed"


class BehaviorPattern(BaseModel):
    pattern_id: str
    scene: BehaviorScene
    action: BehaviorAction
    scope_group_id: int | None = None
    success_score: int = 0
    manual_score: int = 0
    disabled: bool = False
    persona_affinity: str = ""
    trigger_features: list[str] = Field(default_factory=list)
    reference_examples: list[str] = Field(default_factory=list)


class BehaviorRun(BaseModel):
    request_id: str
    group_id: int | None = None
    user_id: int | None = None
    bot_id: int | None = None
    created_at: int = 0
    scene: BehaviorScene
    user_text: str = ""
    reply_text: str = ""
    selected_pattern_ids: list[str] = Field(default_factory=list)
    selected_actions: list[BehaviorAction] = Field(default_factory=list)
    behavior_hint_text: str = ""
    final_outcome: BehaviorOutcome | None = None
    score_delta: int = 0
    auto_feedback_payload: dict[str, Any] = Field(default_factory=dict)
    manual_labels: list[str] = Field(default_factory=list)
    disabled: bool = False


_PROVOCATION_TOKENS = ("效忠", "反党", "走资派", "快说", "表态", "忠诚")
_VENTING_TOKENS = ("烦死", "气死", "无语", "沃日", "绷不住", "受不了")
_BANTER_TOKENS = ("哈哈", "乐", "蚌", "绷", "典", "梗")
_HELP_TOKENS = ("怎么", "为啥", "为什么", "咋", "能不能", "可以吗")
_NEGATIVE_OUTCOME_TOKENS = ("答非所问", "没懂", "没看懂", "什么玩意", "你在说啥", "不是这个", "尬", "怪")
_DERAILED_TOKENS = ("跑题", "别转", "扯远", "别岔开", "别拐", "不是在说这个")
_ENGAGED_TOKENS = ("?", "？", "然后", "所以", "笑死", "哈哈", "确实", "行", "草")

_ACTION_HINTS: dict[BehaviorAction, str] = {
    BehaviorAction.LIGHT_TEASE_AND_CLOSE: "这类怪话先接住，轻吐槽一句就收。",
    BehaviorAction.ACK_THEN_SHORT_REPLY: "先接住这句，再短回一句，不要铺开解释。",
    BehaviorAction.FOLLOW_JOKE_ONCE: "顺着梗接一次就好，不要越聊越偏。",
    BehaviorAction.ACK_EMOTION_NO_LECTURE: "先接情绪，不要马上上价值或教育。",
    BehaviorAction.STAY_ON_CURRENT_TOPIC: "只回当前这一句，不要扩成新话题。",
    BehaviorAction.AVOID_FORCED_TOPIC_SHIFT: "别突然拐去别的话题。",
    BehaviorAction.BRIEF_MULTI_PARTY_ANCHOR: "多人插话时只抓一个最该接的锚点。",
    BehaviorAction.SHORT_HELP_THEN_STOP: "给短帮助就收，不强行追问。",
}


def default_behavior_pattern_seeds() -> list[BehaviorPattern]:
    """全局默认行为规则（无群限定）；仅在 patterns.json 不存在时落盘。"""
    return [
        BehaviorPattern(
            pattern_id="seed-provocation-tease",
            scene=BehaviorScene.PROVOCATION,
            action=BehaviorAction.LIGHT_TEASE_AND_CLOSE,
            manual_score=2,
            trigger_features=["provocation", "weird_demand"],
            reference_examples=["快说誓死效忠××", "你表个态"],
        ),
        BehaviorPattern(
            pattern_id="seed-banter-follow-once",
            scene=BehaviorScene.BANTER,
            action=BehaviorAction.FOLLOW_JOKE_ONCE,
            manual_score=2,
            trigger_features=["joke", "meme"],
            reference_examples=["哈哈笑死", "这个梗典"],
        ),
        BehaviorPattern(
            pattern_id="seed-smalltalk-ack-short",
            scene=BehaviorScene.SMALLTALK,
            action=BehaviorAction.ACK_THEN_SHORT_REPLY,
            manual_score=2,
            trigger_features=["chitchat"],
            reference_examples=["今天好闲", "随便聊聊"],
        ),
        BehaviorPattern(
            pattern_id="seed-smalltalk-no-topic-shift",
            scene=BehaviorScene.SMALLTALK,
            action=BehaviorAction.AVOID_FORCED_TOPIC_SHIFT,
            manual_score=1,
            trigger_features=["stay_topic"],
            reference_examples=["就这个事", "别扯远"],
        ),
        BehaviorPattern(
            pattern_id="seed-venting-ack-emotion",
            scene=BehaviorScene.VENTING,
            action=BehaviorAction.ACK_EMOTION_NO_LECTURE,
            manual_score=2,
            trigger_features=["vent", "emotion"],
            reference_examples=["烦死了", "真的绷不住"],
        ),
        BehaviorPattern(
            pattern_id="seed-group-threading-anchor",
            scene=BehaviorScene.GROUP_THREADING,
            action=BehaviorAction.BRIEF_MULTI_PARTY_ANCHOR,
            manual_score=2,
            trigger_features=["multi_party", "overlap"],
            reference_examples=["你们先等等我问牛牛", "A B C 一起插话"],
        ),
        BehaviorPattern(
            pattern_id="seed-group-threading-stay",
            scene=BehaviorScene.GROUP_THREADING,
            action=BehaviorAction.STAY_ON_CURRENT_TOPIC,
            manual_score=1,
            trigger_features=["current_turn"],
            reference_examples=["你先回我这个"],
        ),
        BehaviorPattern(
            pattern_id="seed-light-help-short",
            scene=BehaviorScene.LIGHT_HELP,
            action=BehaviorAction.SHORT_HELP_THEN_STOP,
            manual_score=2,
            trigger_features=["question", "how_to"],
            reference_examples=["这怎么弄", "为啥不行啊"],
        ),
    ]


def classify_behavior_scene(*, user_text: str, recent_texts: list[str], has_multi_party_overlap: bool) -> BehaviorScene:
    text = str(user_text or "").strip()
    if not text:
        return BehaviorScene.SMALLTALK
    if any(token in text for token in _PROVOCATION_TOKENS):
        return BehaviorScene.PROVOCATION
    if has_multi_party_overlap:
        return BehaviorScene.GROUP_THREADING
    if any(token in text for token in _VENTING_TOKENS):
        return BehaviorScene.VENTING
    if any(token in text for token in _HELP_TOKENS) or "?" in text or "？" in text:
        return BehaviorScene.LIGHT_HELP
    if any(token in text for token in _BANTER_TOKENS):
        return BehaviorScene.BANTER
    if (
        recent_texts
        and any("@" in item or "：" in item for item in recent_texts[-3:])
        and len({item[:1] for item in recent_texts[-3:] if item}) >= 2
    ):
        return BehaviorScene.GROUP_THREADING
    return BehaviorScene.SMALLTALK


def select_behavior_patterns(
    *,
    scene: BehaviorScene,
    group_id: int | None,
    patterns: list[BehaviorPattern],
    limit: int = 2,
) -> list[BehaviorPattern]:
    rows = [
        item
        for item in patterns
        if not item.disabled
        and item.scene == scene
        and (item.scope_group_id is None or item.scope_group_id == group_id)
    ]
    rows.sort(
        key=lambda item: (
            0 if group_id is not None and item.scope_group_id == group_id else 1,
            -(int(item.success_score) + int(item.manual_score)),
            item.pattern_id,
        )
    )
    return rows[: max(1, int(limit))]


def build_behavior_hint_text(*, scene: BehaviorScene, actions: list[BehaviorAction]) -> str:
    lines = [_ACTION_HINTS[item] for item in actions if item in _ACTION_HINTS]
    if not lines:
        return ""
    return "【本轮行为参考】\n- " + "\n- ".join(lines[:2])


def default_group_chat_behavior_hint() -> str:
    return "【群聊注意】回复尽量简短；一次只回一个主话题；注意多人互动；不要刻意找话题。"


def map_behavior_outcome_score(outcome: BehaviorOutcome) -> int:
    return {
        BehaviorOutcome.ENGAGED: 2,
        BehaviorOutcome.NEUTRAL: 0,
        BehaviorOutcome.IGNORED: -1,
        BehaviorOutcome.AWKWARD: -2,
        BehaviorOutcome.DERAILED: -3,
    }[outcome]


def infer_behavior_outcome(
    *,
    run: BehaviorRun,
    turns: list[Any],
    ambient_turns: list[Any] | None = None,
    now: int,
    window_sec: int = 90,
) -> BehaviorOutcome | None:
    outcome, _payload = infer_behavior_feedback(
        run=run,
        turns=turns,
        ambient_turns=ambient_turns,
        now=now,
        window_sec=window_sec,
    )
    return outcome


def infer_behavior_feedback(
    *,
    run: BehaviorRun,
    turns: list[Any],
    ambient_turns: list[Any] | None = None,
    now: int,
    window_sec: int = 90,
) -> tuple[BehaviorOutcome | None, dict[str, Any]]:
    if run.final_outcome is not None or int(run.created_at) <= 0:
        return None, {}
    later_user_turns = [
        item
        for item in turns
        if str(getattr(item, "role", "")).strip() == "user"
        and int(getattr(item, "created_at", 0) or 0) > int(run.created_at)
    ]
    ambient_later_turns = [
        item
        for item in list(ambient_turns or [])
        if str(getattr(item, "role", "")).strip() == "user"
        and int(getattr(item, "created_at", 0) or 0) > int(run.created_at)
    ]
    session_later_turn_count = len(later_user_turns)
    later_user_turns.extend(ambient_later_turns)
    if not later_user_turns:
        if int(now) - int(run.created_at) >= max(20, int(window_sec)):
            return BehaviorOutcome.IGNORED, {
                "source": "timeout",
                "matched_signal": "timeout_without_followup",
                "matched_tokens": [],
                "observed_turn_count": 0,
            }
        return None, {}
    later_user_turns.sort(key=lambda item: int(getattr(item, "created_at", 0) or 0))
    window_turns = [
        item
        for item in later_user_turns
        if int(getattr(item, "created_at", 0) or 0) - int(run.created_at) <= max(20, int(window_sec))
    ][:3]
    if not window_turns:
        return BehaviorOutcome.NEUTRAL, {
            "source": "mixed" if ambient_later_turns and session_later_turn_count else "session",
            "matched_signal": "followup_outside_window",
            "matched_tokens": [],
            "observed_turn_count": 0,
        }
    merged = " ".join(str(getattr(item, "content", "") or "").strip() for item in window_turns)
    if ambient_later_turns and session_later_turn_count:
        source = "mixed"
    elif ambient_later_turns:
        source = "ambient"
    else:
        source = "session"
    if any(token in merged for token in _DERAILED_TOKENS):
        matched = [token for token in _DERAILED_TOKENS if token in merged]
        return BehaviorOutcome.DERAILED, {
            "source": source,
            "matched_signal": "derailed_token",
            "matched_tokens": matched,
            "observed_turn_count": len(window_turns),
        }
    if any(token in merged for token in _NEGATIVE_OUTCOME_TOKENS):
        matched = [token for token in _NEGATIVE_OUTCOME_TOKENS if token in merged]
        return BehaviorOutcome.AWKWARD, {
            "source": source,
            "matched_signal": "negative_token",
            "matched_tokens": matched,
            "observed_turn_count": len(window_turns),
        }
    if any(token in merged for token in _ENGAGED_TOKENS):
        matched = [token for token in _ENGAGED_TOKENS if token in merged]
        return BehaviorOutcome.ENGAGED, {
            "source": source,
            "matched_signal": "engaged_token",
            "matched_tokens": matched,
            "observed_turn_count": len(window_turns),
        }
    if ambient_later_turns and not [
        item
        for item in turns
        if str(getattr(item, "role", "")).strip() == "user"
        and int(getattr(item, "created_at", 0) or 0) > int(run.created_at)
    ]:
        return BehaviorOutcome.IGNORED, {
            "source": "ambient",
            "matched_signal": "ambient_continued_without_pickup",
            "matched_tokens": [],
            "observed_turn_count": len(window_turns),
        }
    return BehaviorOutcome.NEUTRAL, {
        "source": source,
        "matched_signal": "default_neutral",
        "matched_tokens": [],
        "observed_turn_count": len(window_turns),
    }
