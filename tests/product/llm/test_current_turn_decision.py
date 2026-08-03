from __future__ import annotations

import httpx
import pytest

from pallas.product.llm.current_turn_decision import (
    CurrentTurnAction,
    CurrentTurnDecisionInput,
    CurrentTurnSocialAction,
    build_current_turn_decision_prompt,
    decide_current_turn,
    decide_current_turn_with_model,
    resolve_reply_target,
    should_read_persistent_memory_for_turn,
)


def test_default_current_turn_decision_preserves_reply_behavior() -> None:
    result = decide_current_turn(
        CurrentTurnDecisionInput(text="这个怎么弄？", is_to_me=True),
        model_enabled=False,
    )

    assert result.action == CurrentTurnAction.REPLY
    assert result.trace.source == "rule"
    assert result.trace.reason == "default_reply"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ('{"action":"REPLY"}', CurrentTurnAction.REPLY),
        ('{"action":"PASS"}', CurrentTurnAction.PASS),
        ('{"action":"FOLLOW_UP"}', CurrentTurnAction.FOLLOW_UP),
    ],
)
def test_model_current_turn_decision_accepts_each_non_tool_action(
    payload: str,
    expected: CurrentTurnAction,
) -> None:
    result = decide_current_turn(
        CurrentTurnDecisionInput(text="好吧", is_to_me=True),
        model_enabled=True,
        model_response=payload,
    )

    assert result.action == expected
    assert result.trace.source == "model"
    assert result.trace.action == expected


def test_model_current_turn_tool_decision_requires_existing_tool_permission() -> None:
    result = decide_current_turn(
        CurrentTurnDecisionInput(text="帮我搜一下天气", is_to_me=True, tools_permitted=False),
        model_enabled=True,
        model_response='{"action":"TOOL"}',
    )

    assert result.action == CurrentTurnAction.REPLY
    assert result.trace.source == "fallback"
    assert result.trace.reason == "tool_not_permitted"


def test_model_current_turn_tool_decision_uses_permitted_tools() -> None:
    result = decide_current_turn(
        CurrentTurnDecisionInput(text="帮我搜一下天气", is_to_me=True, tools_permitted=True),
        model_enabled=True,
        model_response='{"action":"TOOL"}',
    )

    assert result.action == CurrentTurnAction.TOOL
    assert result.trace.source == "model"


def test_model_current_turn_keeps_a_social_action_separate_from_reply_routing() -> None:
    result = decide_current_turn(
        CurrentTurnDecisionInput(
            text="你是不是只会哞哞叫？",
            is_to_me=True,
            recent_bot_reply_count=2,
            has_multi_party_overlap=True,
        ),
        model_enabled=True,
        model_response='{"action":"REPLY","social_action":"JOKE"}',
    )

    assert result.action is CurrentTurnAction.REPLY
    assert result.social_action.value == "JOKE"
    assert result.trace.social_action.value == "JOKE"


@pytest.mark.parametrize("text", ["没绷住", "我又改输出了，唉", "就是骂你"])
def test_model_current_turn_passes_low_value_acknowledgements(text: str) -> None:
    result = decide_current_turn(
        CurrentTurnDecisionInput(text=text, is_to_me=True),
        model_enabled=True,
        model_response='{"action":"REPLY","social_action":"ACK"}',
    )

    assert result.action is CurrentTurnAction.PASS
    assert result.social_action is CurrentTurnSocialAction.ACK
    assert result.trace.reason == "low_value_ack_pass"


def test_model_current_turn_passes_low_value_joke_without_reply_obligation() -> None:
    result = decide_current_turn(
        CurrentTurnDecisionInput(text="就是骂你", is_to_me=True),
        model_enabled=True,
        model_response='{"action":"REPLY","social_action":"JOKE"}',
    )

    assert result.action is CurrentTurnAction.PASS
    assert result.social_action is CurrentTurnSocialAction.JOKE
    assert result.trace.reason == "low_value_joke_pass"


def test_model_current_turn_keeps_playful_question_replyable() -> None:
    result = decide_current_turn(
        CurrentTurnDecisionInput(text="你是不是只会哞哞叫", is_to_me=True),
        model_enabled=True,
        model_response='{"action":"REPLY","social_action":"JOKE"}',
    )

    assert result.action is CurrentTurnAction.REPLY


def test_model_current_turn_keeps_addressed_question_replyable_when_model_passes() -> None:
    result = decide_current_turn(
        CurrentTurnDecisionInput(text="你还在吗", is_explicitly_addressed=True),
        model_enabled=True,
        model_response='{"action":"PASS","social_action":"ACK"}',
    )

    assert result.action is CurrentTurnAction.REPLY
    assert result.social_action is CurrentTurnSocialAction.ANSWER
    assert result.trace.reason == "addressed_obligation_reply"


def test_model_current_turn_keeps_ambient_question_passable() -> None:
    result = decide_current_turn(
        CurrentTurnDecisionInput(text="你还在吗"),
        model_enabled=True,
        model_response='{"action":"PASS","social_action":"ACK"}',
    )

    assert result.action is CurrentTurnAction.PASS


@pytest.mark.parametrize("text", ["你还在吗", "快回我", "你怎么看"])
def test_model_current_turn_keeps_reply_for_acknowledgements_with_a_reply_obligation(text: str) -> None:
    result = decide_current_turn(
        CurrentTurnDecisionInput(text=text, is_to_me=True),
        model_enabled=True,
        model_response='{"action":"REPLY","social_action":"ACK"}',
    )

    assert result.action is CurrentTurnAction.REPLY


def test_legacy_current_turn_response_defaults_to_answer_social_action() -> None:
    result = decide_current_turn(
        CurrentTurnDecisionInput(text="这个怎么弄？", is_to_me=True),
        model_enabled=True,
        model_response='{"action":"REPLY"}',
    )

    assert result.social_action.value == "ANSWER"


def test_current_turn_prompt_distinguishes_short_vent_from_explicit_opinion() -> None:
    prompt = build_current_turn_decision_prompt(CurrentTurnDecisionInput(text="我又改需求了，烦", is_to_me=True))

    assert "ACK is for a short vent" in prompt
    assert "STANCE is only for an explicit request for an opinion" in prompt


def test_short_vent_does_not_read_persistent_memory_even_when_model_calls_it_an_answer() -> None:
    assert not should_read_persistent_memory_for_turn(
        "我又改输出了，烦",
        CurrentTurnSocialAction.ANSWER,
    )
    assert should_read_persistent_memory_for_turn(
        "刚才那个输出怎么改的？",
        CurrentTurnSocialAction.ANSWER,
    )


def test_reply_target_keeps_short_social_generation_on_the_current_turn() -> None:
    assert resolve_reply_target(
        "我又改需求了，烦",
        action=CurrentTurnAction.REPLY,
        social_action=CurrentTurnSocialAction.ACK,
    ) == "emotion"
    assert resolve_reply_target(
        "牛牛你还在吗",
        action=CurrentTurnAction.REPLY,
        social_action=CurrentTurnSocialAction.ACK,
    ) == "fact"
    assert resolve_reply_target(
        "这也能改？",
        action=CurrentTurnAction.REPLY,
        social_action=CurrentTurnSocialAction.ACK,
    ) == "fact"
    assert resolve_reply_target(
        "这个怎么改？",
        action=CurrentTurnAction.REPLY,
        social_action=CurrentTurnSocialAction.ANSWER,
    ) == "answer"
    assert resolve_reply_target(
        "你是不是只会哞哞叫",
        action=CurrentTurnAction.REPLY,
        social_action=CurrentTurnSocialAction.JOKE,
    ) == "short_tease"
    assert resolve_reply_target(
        "就是骂你",
        action=CurrentTurnAction.PASS,
        social_action=CurrentTurnSocialAction.JOKE,
    ) == "silent"


def test_reply_target_is_only_attached_to_the_current_generation_prompt() -> None:
    from pallas.product.llm.kernel_runner import system_prompt_with_reply_target

    prompt = system_prompt_with_reply_target(
        "base persona",
        {"reply_target": "short_tease"},
    )

    assert prompt == (
        "base persona\n\n【本轮回复目标】\n"
        "只围绕当前句开一个短玩笑，不引入角色背景、动作描写、邀约或新话题。"
    )
    assert system_prompt_with_reply_target("base persona", {}) == "base persona"


@pytest.mark.parametrize("payload", ['{"action":"UNKNOWN"}', '{"action":"PASS"', "PASS", '{"action":"PASS","extra":1}'])
def test_malformed_model_response_falls_back_to_default_reply(payload: str) -> None:
    result = decide_current_turn(
        CurrentTurnDecisionInput(text="在吗", is_to_me=True),
        model_enabled=True,
        model_response=payload,
    )

    assert result.action == CurrentTurnAction.REPLY
    assert result.trace.source == "fallback"
    assert result.trace.reason == "invalid_model_response"


def test_current_turn_trace_is_compact_and_uses_safe_fields_only() -> None:
    result = decide_current_turn(
        CurrentTurnDecisionInput(text="在吗", is_to_me=True, tools_permitted=True),
        model_enabled=False,
    )

    assert result.trace.model_dump(mode="json") == {
        "action": "REPLY",
        "social_action": "ANSWER",
        "source": "rule",
        "reason": "default_reply",
    }


@pytest.mark.asyncio
async def test_disabled_current_turn_decision_does_not_request_a_model(monkeypatch) -> None:
    requested = False

    async def request_model(*args: object, **kwargs: object) -> dict[str, str]:
        nonlocal requested
        requested = True
        return {"content": '{"action":"PASS"}'}

    monkeypatch.setattr("pallas.product.llm.provider_client.complete_chat_message", request_model)

    result = await decide_current_turn_with_model(
        CurrentTurnDecisionInput(text="在吗", is_to_me=True),
        enabled=False,
    )

    assert requested is False
    assert result.action is CurrentTurnAction.REPLY


@pytest.mark.asyncio
async def test_enabled_current_turn_decision_uses_task_routing_without_legacy_model(monkeypatch) -> None:
    received: dict[str, object] = {}

    async def request_model(*args: object, **kwargs: object) -> dict[str, str]:
        received.update(kwargs)
        return {"content": '{"action":"PASS"}'}

    monkeypatch.setattr("pallas.product.llm.provider_client.complete_chat_message", request_model)

    result = await decide_current_turn_with_model(
        CurrentTurnDecisionInput(text="不用回复", is_to_me=True),
        enabled=True,
    )

    assert result.action is CurrentTurnAction.PASS
    assert received["task"] == "turn_decision"
    assert received["model"] == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("transport_failure", [False, True], ids=["provider_error", "connect_error"])
async def test_current_turn_decision_retries_configured_task_backup(
    monkeypatch,
    tmp_path,
    transport_failure: bool,
) -> None:
    from pallas.product.llm.config import LlmConfig
    from pallas.product.llm.provider_client import LlmProviderError
    from pallas.product.llm.providers_store import clear_providers_store_cache, save_providers_document

    store = tmp_path / "llm_providers.json"
    monkeypatch.setattr("pallas.product.llm.providers_store.providers_store_path", lambda: store)
    monkeypatch.setattr("pallas.product.llm.providers_store._read_ai_providers_toml", lambda: None)
    clear_providers_store_cache()
    save_providers_document(
        {
            "providers": [
                {
                    "id": "primary",
                    "kind": "remote",
                    "base_url": "https://primary.example.com/v1",
                    "api_key": "sk-primary",
                    "default_model": "main",
                    "task_models": {"turn_decision": "decision-primary"},
                },
                {
                    "id": "backup",
                    "kind": "remote",
                    "base_url": "https://backup.example.com/v1",
                    "api_key": "sk-backup",
                    "default_model": "fallback",
                },
            ],
            "routing": {
                "chain_fallback": ["primary"],
                "tasks": {"turn_decision": "primary"},
                "task_backups": {"turn_decision": "backup"},
                "task_backup_models": {"turn_decision": "decision-backup"},
            },
        }
    )
    monkeypatch.setattr(
        "pallas.product.llm.provider_client.get_llm_config",
        lambda: LlmConfig(llm_base_url="", llm_model=""),
    )
    attempted: list[tuple[str, str]] = []

    async def post_provider_chat(*args: object, **kwargs: object) -> dict[str, str]:
        attempted.append((str(kwargs["base_url"]), str(kwargs["model"])))
        if len(attempted) == 1:
            if transport_failure:
                raise httpx.ConnectError("primary unavailable")
            raise LlmProviderError("primary unavailable")
        return {"content": '{"action":"PASS"}'}

    monkeypatch.setattr("pallas.product.llm.provider_client._post_provider_chat", post_provider_chat)

    result = await decide_current_turn_with_model(
        CurrentTurnDecisionInput(text="不用回复", is_to_me=True),
        enabled=True,
    )

    assert result.action is CurrentTurnAction.PASS
    assert attempted == [
        ("https://primary.example.com/v1", "decision-primary"),
        ("https://backup.example.com/v1", "decision-backup"),
    ]
