"""Pure current-turn policy resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pallas.product.llm.current_turn_decision import (
    CurrentTurnAction,
    CurrentTurnSocialAction,
    current_turn_decision_is_known,
    current_turn_field,
    normalize_current_turn_action,
    normalize_current_turn_social_action,
    resolve_reply_target,
)
from pallas.product.llm.scene_style import (
    normalize_scene_label,
    scene_allows_affection,
    scene_allows_teasing,
    scene_seriousness,
)

if TYPE_CHECKING:
    from pallas.product.llm.kernel.models import ConversationScene


@dataclass(frozen=True)
class TurnPolicy:
    reply_target: str
    seriousness: str
    social_action: str
    allow_teasing: bool
    allow_affection: bool
    needs_tool: bool
    needs_grounding: bool


def resolve_turn_policy(
    decision: object,
    scene: ConversationScene | str | None,
    tools_enabled: bool,
) -> TurnPolicy:
    action = normalize_current_turn_action(decision)
    social_action = normalize_current_turn_social_action(decision)
    scene_label = normalize_scene_label(scene)
    decision_known = current_turn_decision_is_known(decision)
    seriousness = scene_seriousness(scene) if decision_known else "serious"
    needs_tool = tools_enabled and action is CurrentTurnAction.TOOL

    explicit_target = str(current_turn_field(decision, "reply_target", "") or "").strip().lower()
    if explicit_target not in {"fact", "emotion", "short_tease", "answer", "silent"}:
        explicit_target = ""
    if action is CurrentTurnAction.PASS:
        reply_target = "silent"
    elif explicit_target:
        reply_target = explicit_target
    elif scene_label == "venting" or social_action is CurrentTurnSocialAction.AFFECTION:
        reply_target = "emotion"
    else:
        reply_target = resolve_reply_target("", action=action, social_action=social_action)
    if not decision_known or (scene_label == "unknown" and reply_target == "short_tease"):
        reply_target = "answer"

    needs_grounding = (
        not decision_known or needs_tool or action is CurrentTurnAction.TOOL or scene_label in {"light_help", "unknown"}
    )
    return TurnPolicy(
        reply_target=reply_target,
        seriousness=seriousness,
        social_action=social_action.value,
        allow_teasing=decision_known and scene_allows_teasing(scene),
        allow_affection=decision_known and scene_allows_affection(scene),
        needs_tool=needs_tool,
        needs_grounding=needs_grounding,
    )
