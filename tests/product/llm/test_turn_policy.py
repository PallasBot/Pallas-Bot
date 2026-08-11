from __future__ import annotations

import pytest

from pallas.product.llm.current_turn_decision import (
    CurrentTurnAction,
    CurrentTurnDecisionInput,
    CurrentTurnSocialAction,
    build_current_turn_decision_prompt,
    decide_current_turn,
)
from pallas.product.llm.kernel.models import ConversationScene
from pallas.product.llm.turn_policy import resolve_turn_policy


@pytest.mark.parametrize(
    ("scene", "social_action", "reply_target", "allow_teasing", "allow_affection", "seriousness"),
    [
        ("banter", CurrentTurnSocialAction.JOKE, "short_tease", True, True, "casual"),
        ("smalltalk", CurrentTurnSocialAction.ANSWER, "answer", True, True, "casual"),
        ("venting", CurrentTurnSocialAction.ACK, "emotion", False, True, "serious"),
        ("provocation", CurrentTurnSocialAction.STANCE, "answer", False, False, "conflict"),
    ],
)
def test_resolve_turn_policy_covers_social_and_serious_scenes(
    scene: str,
    social_action: CurrentTurnSocialAction,
    reply_target: str,
    allow_teasing: bool,
    allow_affection: bool,
    seriousness: str,
) -> None:
    policy = resolve_turn_policy(
        {"action": CurrentTurnAction.REPLY, "social_action": social_action},
        scene,
        tools_enabled=False,
    )

    assert policy.reply_target == reply_target
    assert policy.seriousness == seriousness
    assert policy.allow_teasing is allow_teasing
    assert policy.allow_affection is allow_affection
    assert policy.needs_tool is False


@pytest.mark.parametrize("text", ["牛牛真可爱", "牛牛贴贴嘛"])
def test_affection_decision_reaches_turn_policy_from_real_classifier_contract(text: str) -> None:
    turn = CurrentTurnDecisionInput(text=text, is_to_me=True)
    prompt = build_current_turn_decision_prompt(turn)
    decision = decide_current_turn(
        turn,
        model_enabled=True,
        model_response='{"action":"REPLY","social_action":"AFFECTION","delivery_style":"PLAIN"}',
    )
    policy = resolve_turn_policy(decision, ConversationScene.SMALLTALK, tools_enabled=False)

    assert "AFFECTION" in prompt
    assert decision.action is CurrentTurnAction.REPLY
    assert decision.social_action is CurrentTurnSocialAction.AFFECTION
    assert decision.trace.source == "model"
    assert policy.reply_target == "emotion"
    assert policy.social_action == "AFFECTION"
    assert policy.allow_affection is True


def test_tool_turn_has_task_priority_and_grounding() -> None:
    policy = resolve_turn_policy(
        {"action": "TOOL", "social_action": "ANSWER", "reply_target": "answer"},
        "light_help",
        tools_enabled=True,
    )

    assert policy.reply_target == "answer"
    assert policy.seriousness == "serious"
    assert policy.needs_tool is True
    assert policy.needs_grounding is True
    assert policy.allow_teasing is False


def test_pass_action_always_resolves_to_silent_target() -> None:
    policy = resolve_turn_policy(
        {"action": "PASS", "social_action": "ACK", "reply_target": "answer"},
        ConversationScene.SMALLTALK,
        tools_enabled=False,
    )

    assert policy.reply_target == "silent"
    assert policy.needs_tool is False


@pytest.mark.parametrize(
    ("decision", "scene"),
    [
        (
            {"action": "DANCE", "social_action": "FLIRT", "reply_target": "short_tease"},
            ConversationScene.SMALLTALK,
        ),
        ({"action": "REPLY", "social_action": "ANSWER"}, "future_scene"),
    ],
)
def test_unknown_inputs_fall_back_to_conservative_policy(
    decision: object,
    scene: ConversationScene | str,
) -> None:
    policy = resolve_turn_policy(decision, scene, tools_enabled=False)

    assert policy.reply_target == "answer"
    assert policy.seriousness == "serious"
    assert policy.social_action == "ANSWER"
    assert policy.allow_teasing is False
    assert policy.allow_affection is False
    assert policy.needs_tool is False
    assert policy.needs_grounding is True


def test_unknown_scene_suppresses_teasing_target_from_known_decision() -> None:
    policy = resolve_turn_policy(
        {"action": "REPLY", "social_action": "JOKE"},
        "future_scene",
        tools_enabled=False,
    )

    assert policy.reply_target == "answer"
    assert policy.social_action == "JOKE"
    assert policy.allow_teasing is False
    assert policy.needs_grounding is True


def test_tool_action_with_tools_disabled_keeps_grounding_without_tool_execution() -> None:
    policy = resolve_turn_policy(
        {"action": "TOOL", "social_action": "ANSWER"},
        ConversationScene.LIGHT_HELP,
        tools_enabled=False,
    )

    assert policy.needs_tool is False
    assert policy.needs_grounding is True


def test_reply_action_does_not_need_tool_just_because_tools_are_enabled() -> None:
    policy = resolve_turn_policy(
        {"action": "REPLY", "social_action": "ANSWER"},
        ConversationScene.SMALLTALK,
        tools_enabled=True,
    )

    assert policy.needs_tool is False
    assert policy.needs_grounding is False
