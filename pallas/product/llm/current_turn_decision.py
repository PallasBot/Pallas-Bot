"""Current-turn conversation decision contract."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class CurrentTurnAction(StrEnum):
    REPLY = "REPLY"
    PASS = "PASS"
    TOOL = "TOOL"
    FOLLOW_UP = "FOLLOW_UP"


class CurrentTurnDecisionInput(BaseModel):
    """Only current-turn, non-identifying fields may enter this decision."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    text: str = Field(max_length=4000)
    is_to_me: bool = False
    tools_permitted: bool = False


class CurrentTurnModelResponse(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    action: CurrentTurnAction


class CurrentTurnDecisionTrace(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    action: CurrentTurnAction
    source: str
    reason: str


class CurrentTurnDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: CurrentTurnAction
    trace: CurrentTurnDecisionTrace


def build_current_turn_decision_prompt(turn: CurrentTurnDecisionInput) -> str:
    """Build the compact classifier prompt without conversation history."""
    tool_option = "TOOL is available" if turn.tools_permitted else "TOOL is unavailable"
    addressed = "directly addressed to the bot" if turn.is_to_me else "not directly addressed to the bot"
    return (
        "Classify only this current message. Reply with JSON only: "
        '{"action":"REPLY|PASS|TOOL|FOLLOW_UP"}. '
        f"The message is {addressed}; {tool_option}. "
        f"Message: {turn.text}"
    )


def decide_current_turn(
    turn: CurrentTurnDecisionInput,
    *,
    model_enabled: bool,
    model_response: str | None = None,
) -> CurrentTurnDecision:
    """Choose a validated current-turn action, with a reply-safe fallback."""
    if not model_enabled:
        return _decision(CurrentTurnAction.REPLY, source="rule", reason="default_reply")
    try:
        parsed = CurrentTurnModelResponse.model_validate_json(str(model_response or ""))
    except (ValidationError, ValueError):
        return _decision(CurrentTurnAction.REPLY, source="fallback", reason="invalid_model_response")
    if parsed.action is CurrentTurnAction.TOOL and not turn.tools_permitted:
        return _decision(CurrentTurnAction.REPLY, source="fallback", reason="tool_not_permitted")
    return _decision(parsed.action, source="model", reason="model_action")


async def decide_current_turn_with_model(
    turn: CurrentTurnDecisionInput,
    *,
    enabled: bool,
) -> CurrentTurnDecision:
    """Use the turn-decision task route only when the explicit feature flag is enabled."""
    if not enabled:
        return decide_current_turn(turn, model_enabled=False)
    from pallas.product.llm.provider_client import complete_chat_message

    try:
        message = await complete_chat_message(
            [
                {
                    "role": "system",
                    "content": (
                        "Return only a JSON object with action. Allowed actions: REPLY, PASS, TOOL, FOLLOW_UP."
                    ),
                },
                {"role": "user", "content": build_current_turn_decision_prompt(turn)},
            ],
            model="",
            options={"temperature": 0, "max_tokens": 24},
            task="turn_decision",
        )
    except Exception:
        return _decision(CurrentTurnAction.REPLY, source="fallback", reason="model_request_failed")
    content = str(message.get("content") or "") if isinstance(message, dict) else ""
    return decide_current_turn(turn, model_enabled=True, model_response=content)


def _decision(action: CurrentTurnAction, *, source: str, reason: str) -> CurrentTurnDecision:
    return CurrentTurnDecision(
        action=action,
        trace=CurrentTurnDecisionTrace(action=action, source=source, reason=reason),
    )
