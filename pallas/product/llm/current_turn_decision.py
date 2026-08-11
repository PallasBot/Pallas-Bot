"""Current-turn conversation decision contract."""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from pallas.product.llm.inference_params import task_token_budget
from pallas.product.llm.reply_necessity import has_reply_obligation, is_low_value_social_turn


class CurrentTurnAction(StrEnum):
    REPLY = "REPLY"
    PASS = "PASS"
    TOOL = "TOOL"
    FOLLOW_UP = "FOLLOW_UP"


class CurrentTurnSocialAction(StrEnum):
    ACK = "ACK"
    AFFECTION = "AFFECTION"
    JOKE = "JOKE"
    STANCE = "STANCE"
    ANSWER = "ANSWER"
    ASK_ONE = "ASK_ONE"


class CurrentTurnDeliveryStyle(StrEnum):
    PLAIN = "PLAIN"
    QUOTE = "QUOTE"
    MENTION = "MENTION"


ReplyTarget = Literal["fact", "emotion", "short_tease", "answer", "silent"]


class ReplyTargetCandidate(BaseModel):
    """A recent group message the current turn may quote."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    message_id: int = Field(gt=0)
    sender_id: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=160)
    is_current: bool = False


def current_turn_field(decision: object, name: str, default: Any = None) -> Any:
    """Read a decision field from either the validated model or a mapping."""
    if isinstance(decision, Mapping):
        return decision.get(name, default)
    return getattr(decision, name, default)


def normalize_current_turn_action(decision: object) -> CurrentTurnAction:
    raw = current_turn_field(decision, "action", CurrentTurnAction.REPLY)
    value = str(getattr(raw, "value", raw) or "").strip().upper()
    try:
        return CurrentTurnAction(value)
    except ValueError:
        return CurrentTurnAction.REPLY


def normalize_current_turn_social_action(decision: object) -> CurrentTurnSocialAction:
    raw = current_turn_field(decision, "social_action", CurrentTurnSocialAction.ANSWER)
    value = str(getattr(raw, "value", raw) or "").strip().upper()
    try:
        return CurrentTurnSocialAction(value)
    except ValueError:
        return CurrentTurnSocialAction.ANSWER


def current_turn_decision_is_known(decision: object) -> bool:
    raw_action = current_turn_field(decision, "action")
    raw_social_action = current_turn_field(decision, "social_action")
    action = str(getattr(raw_action, "value", raw_action) or "")
    social_action = str(getattr(raw_social_action, "value", raw_social_action) or "")
    return action.strip().upper() in CurrentTurnAction._value2member_map_ and (
        social_action.strip().upper() in CurrentTurnSocialAction._value2member_map_
    )


class CurrentTurnDecisionInput(BaseModel):
    """Only current-turn, non-identifying fields may enter this decision."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    text: str = Field(max_length=4000)
    is_to_me: bool = False
    is_explicitly_addressed: bool = False
    tools_permitted: bool = False
    required_tool_intent: bool = False
    recent_bot_reply_count: int = Field(default=0, ge=0, le=6)
    has_multi_party_overlap: bool = False
    reply_candidates: list[ReplyTargetCandidate] = Field(default_factory=list, max_length=6)


class CurrentTurnModelResponse(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    action: CurrentTurnAction
    social_action: CurrentTurnSocialAction = CurrentTurnSocialAction.ANSWER
    delivery_style: CurrentTurnDeliveryStyle = CurrentTurnDeliveryStyle.PLAIN
    reply_message_id: int | None = Field(default=None, gt=0)


class CurrentTurnDecisionTrace(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    action: CurrentTurnAction
    social_action: CurrentTurnSocialAction
    delivery_style: CurrentTurnDeliveryStyle = CurrentTurnDeliveryStyle.PLAIN
    source: str
    reason: str


class CurrentTurnDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: CurrentTurnAction
    social_action: CurrentTurnSocialAction
    delivery_style: CurrentTurnDeliveryStyle = CurrentTurnDeliveryStyle.PLAIN
    reply_message_id: int | None = None
    trace: CurrentTurnDecisionTrace


_SHORT_SOCIAL_MEMORY_TURN_RE = re.compile(r"(?:烦|唉|累|难受|没绷住|服了|崩溃)[，,。.!！?？~～\s]*$")


def should_pass_low_value_social_turn(text: str) -> bool:
    """Allow short, non-request social turns to end without a generated reply."""
    return is_low_value_social_turn(text)


def should_read_persistent_memory_for_turn(
    text: str,
    social_action: CurrentTurnSocialAction | str,
) -> bool:
    """Keep retrieval out of short social turns without changing reply routing."""
    action = str(getattr(social_action, "value", social_action) or "").strip().upper()
    if action in {
        CurrentTurnSocialAction.ACK.value,
        CurrentTurnSocialAction.AFFECTION.value,
        CurrentTurnSocialAction.JOKE.value,
    }:
        return False
    current = str(text or "").strip()
    return not (len(current) <= 24 and bool(_SHORT_SOCIAL_MEMORY_TURN_RE.search(current)))


def should_include_recent_pair_for_turn(
    text: str,
    social_action: CurrentTurnSocialAction | str,
    *,
    explicitly_addressed: bool,
    has_recent_assistant_turn: bool,
) -> bool:
    """Keep one direct-chat exchange when a short social turn omits context."""
    if not explicitly_addressed or not has_recent_assistant_turn:
        return False
    return not should_read_persistent_memory_for_turn(text, social_action)


def resolve_reply_target(
    text: str,
    *,
    action: CurrentTurnAction | str,
    social_action: CurrentTurnSocialAction | str,
) -> ReplyTarget:
    """Choose a compact, current-turn-only generation target."""
    action_value = str(getattr(action, "value", action) or "").strip().upper()
    social_value = str(getattr(social_action, "value", social_action) or "").strip().upper()
    plain = str(text or "").strip()
    if action_value == CurrentTurnAction.PASS.value:
        return "silent"
    if social_value == CurrentTurnSocialAction.ACK.value:
        if _SHORT_SOCIAL_MEMORY_TURN_RE.search(plain):
            return "emotion"
        return "fact"
    if social_value == CurrentTurnSocialAction.AFFECTION.value:
        return "emotion"
    if social_value == CurrentTurnSocialAction.JOKE.value:
        return "short_tease"
    if has_reply_obligation(plain) or social_value in {
        CurrentTurnSocialAction.ANSWER.value,
        CurrentTurnSocialAction.ASK_ONE.value,
        CurrentTurnSocialAction.STANCE.value,
    }:
        return "answer"
    return "fact"


def build_reply_target_instruction(target: ReplyTarget | str) -> str:
    """Return a per-request guardrail without changing the base persona."""
    instructions = {
        "fact": "只回应当前句明确说到的事，不扩成评价、鼓励、邀约或新话题。",
        "emotion": "只顺手接住当前情绪，一两句即可；不解释、建议或收尾。",
        "short_tease": "只围绕当前句开一个短玩笑，不引入角色背景、动作描写、邀约或新话题。",
        "answer": (
            "直接回答当前问题或请求；情感或关系确认时，先给明确态度，再按当前熟悉程度"
            "自然接一句。角色只影响措辞，不改变话题，不补出背景设定、爱好或新安排；"
            "除非必须澄清，不以礼貌反问收尾。"
        ),
    }
    return instructions.get(str(target or "").strip().lower(), "")


def build_current_turn_decision_prompt(turn: CurrentTurnDecisionInput) -> str:
    """Build the compact classifier prompt without conversation history."""
    tool_option = "TOOL is available" if turn.tools_permitted else "TOOL is unavailable"
    addressed = (
        "directly addressed to the bot"
        if turn.is_to_me or turn.is_explicitly_addressed
        else "not directly addressed to the bot"
    )
    return (
        "Classify this current chat turn. Reply with JSON only: "
        '{"action":"REPLY|PASS|TOOL|FOLLOW_UP",'
        '"social_action":"ACK|AFFECTION|JOKE|STANCE|ANSWER|ASK_ONE",'
        '"delivery_style":"PLAIN|QUOTE|MENTION","reply_message_id":number|null}. '
        "social_action is the visible conversational move, not a writing style. "
        "ACK is for a short vent, acknowledgement, or low-stakes reaction. "
        "AFFECTION is for warmly receiving praise or responding to affectionate, clingy, or cute behavior. "
        "JOKE is for banter or a playful reaction. "
        "For a short ACK or JOKE without a question or request, use PASS. "
        "STANCE is only for an explicit request for an opinion or choice. "
        "ANSWER is for a direct question, and ASK_ONE is only for a necessary clarification. "
        "Use PLAIN by default. QUOTE only when directly answering the current message or an offered reply target. "
        "To quote one offered message, set reply_message_id to its id; never invent an id. "
        "Use MENTION only when multiple people are speaking and a specific person must be singled out; "
        "do not mention someone back just because they mentioned the bot. "
        f"The message is {addressed}; {tool_option}. "
        f"The bot has replied {turn.recent_bot_reply_count} time(s) recently; "
        f"multi-party overlap is {turn.has_multi_party_overlap}. "
        f"Reply candidates: {_format_reply_candidates(turn.reply_candidates)}. "
        f"Message: {turn.text}"
    )


def _format_reply_candidates(candidates: list[ReplyTargetCandidate]) -> str:
    if not candidates:
        return "none"
    return " | ".join(
        f"id={item.message_id};sender={item.sender_id};current={str(item.is_current).lower()};text={item.text}"
        for item in candidates
    )


def decide_current_turn(
    turn: CurrentTurnDecisionInput,
    *,
    model_enabled: bool,
    model_response: str | None = None,
) -> CurrentTurnDecision:
    """Choose a validated current-turn action, with a reply-safe fallback."""
    if turn.required_tool_intent and turn.tools_permitted:
        return _decision(CurrentTurnAction.TOOL, source="rule", reason="required_tool_intent")
    if not model_enabled:
        return _decision(CurrentTurnAction.REPLY, source="rule", reason="default_reply")
    try:
        parsed = CurrentTurnModelResponse.model_validate_json(str(model_response or ""))
    except (ValidationError, ValueError):
        return _decision(CurrentTurnAction.REPLY, source="fallback", reason="invalid_model_response")
    if parsed.action is CurrentTurnAction.TOOL and not turn.tools_permitted:
        return _decision(CurrentTurnAction.REPLY, source="fallback", reason="tool_not_permitted")
    if (
        parsed.action is CurrentTurnAction.PASS
        and (turn.is_to_me or turn.is_explicitly_addressed)
        and has_reply_obligation(turn.text)
    ):
        return _decision(
            CurrentTurnAction.REPLY,
            social_action=CurrentTurnSocialAction.ANSWER,
            source="rule",
            reason="addressed_obligation_reply",
        )
    if (
        parsed.action is CurrentTurnAction.REPLY
        and parsed.social_action in {CurrentTurnSocialAction.ACK, CurrentTurnSocialAction.JOKE}
        and should_pass_low_value_social_turn(turn.text)
    ):
        reason = "low_value_ack_pass" if parsed.social_action is CurrentTurnSocialAction.ACK else "low_value_joke_pass"
        return _decision(
            CurrentTurnAction.PASS,
            social_action=parsed.social_action,
            source="rule",
            reason=reason,
        )
    if parsed.delivery_style is CurrentTurnDeliveryStyle.MENTION and not turn.has_multi_party_overlap:
        return _decision(
            parsed.action,
            social_action=parsed.social_action,
            source="fallback",
            reason="mention_without_multi_party_overlap",
        )
    reply_message_id = _resolve_reply_message_id(parsed.reply_message_id, turn.reply_candidates)
    delivery_style = CurrentTurnDeliveryStyle.QUOTE if reply_message_id is not None else parsed.delivery_style
    return _decision(
        parsed.action,
        social_action=parsed.social_action,
        delivery_style=delivery_style,
        reply_message_id=reply_message_id,
        source="model",
        reason="model_action",
    )


def _resolve_reply_message_id(
    selected_id: int | None,
    candidates: list[ReplyTargetCandidate],
) -> int | None:
    if selected_id is None:
        return None
    candidate_ids = {item.message_id for item in candidates}
    return selected_id if selected_id in candidate_ids else None


async def decide_current_turn_with_model(
    turn: CurrentTurnDecisionInput,
    *,
    enabled: bool,
) -> CurrentTurnDecision:
    """Use the turn-decision task route only when the explicit feature flag is enabled."""
    if turn.required_tool_intent and turn.tools_permitted:
        return decide_current_turn(turn, model_enabled=False)
    if not enabled:
        return decide_current_turn(turn, model_enabled=False)
    from pallas.product.llm.provider_client import complete_chat_message

    try:
        message = await complete_chat_message(
            [
                {
                    "role": "system",
                    "content": (
                        "Return only a JSON object with action, social_action, delivery_style, and reply_message_id. "
                        "Allowed actions: REPLY, PASS, TOOL, FOLLOW_UP. "
                        "Allowed social actions: ACK, AFFECTION, JOKE, STANCE, ANSWER, ASK_ONE. "
                        "Allowed delivery styles: PLAIN, QUOTE, MENTION."
                    ),
                },
                {"role": "user", "content": build_current_turn_decision_prompt(turn)},
            ],
            model="",
            options={"temperature": 0, "max_tokens": task_token_budget("turn_decision")},
            task="turn_decision",
        )
    except Exception:
        return _decision(CurrentTurnAction.REPLY, source="fallback", reason="model_request_failed")
    content = str(message.get("content") or "") if isinstance(message, dict) else ""
    return decide_current_turn(turn, model_enabled=True, model_response=content)


def _decision(
    action: CurrentTurnAction,
    *,
    social_action: CurrentTurnSocialAction | None = None,
    delivery_style: CurrentTurnDeliveryStyle = CurrentTurnDeliveryStyle.PLAIN,
    reply_message_id: int | None = None,
    source: str,
    reason: str,
) -> CurrentTurnDecision:
    if social_action is None:
        social_action = (
            CurrentTurnSocialAction.ASK_ONE if action is CurrentTurnAction.FOLLOW_UP else CurrentTurnSocialAction.ANSWER
        )
    return CurrentTurnDecision(
        action=action,
        social_action=social_action,
        delivery_style=delivery_style,
        reply_message_id=reply_message_id,
        trace=CurrentTurnDecisionTrace(
            action=action,
            social_action=social_action,
            delivery_style=delivery_style,
            source=source,
            reason=reason,
        ),
    )
