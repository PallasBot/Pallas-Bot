from __future__ import annotations

import httpx
import pytest

from pallas.product.llm.current_turn_decision import (
    CurrentTurnAction,
    CurrentTurnDecisionInput,
    CurrentTurnDeliveryStyle,
    CurrentTurnSocialAction,
    ReplyTargetCandidate,
    build_current_turn_decision_prompt,
    build_reply_target_instruction,
    decide_current_turn,
    decide_current_turn_with_model,
    resolve_reply_target,
    should_include_recent_pair_for_turn,
    should_read_persistent_memory_for_turn,
)


def test_default_current_turn_decision_preserves_reply_behavior() -> None:
    result = decide_current_turn(
        CurrentTurnDecisionInput(text="这个怎么弄？", is_to_me=True),
        model_enabled=False,
    )

    assert result.action == CurrentTurnAction.REPLY
    assert result.trace.source == "rule"
    assert result.trace.reason == "rule_reply_obligation"


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


def test_required_tool_intent_bypasses_current_turn_model() -> None:
    result = decide_current_turn(
        CurrentTurnDecisionInput(
            text="牛牛赞我",
            is_to_me=True,
            tools_permitted=True,
            required_tool_intent=True,
        ),
        model_enabled=True,
        model_response='{"action":"REPLY","social_action":"ACK"}',
    )

    assert result.action is CurrentTurnAction.TOOL
    assert result.trace.source == "rule"
    assert result.trace.reason == "required_tool_intent"


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


def test_model_current_turn_allows_quote_for_a_direct_reply() -> None:
    result = decide_current_turn(
        CurrentTurnDecisionInput(text="这个怎么弄？", is_to_me=True),
        model_enabled=True,
        model_response='{"action":"REPLY","delivery_style":"QUOTE"}',
    )

    assert result.delivery_style is CurrentTurnDeliveryStyle.QUOTE


def test_model_current_turn_selects_an_offered_reply_target() -> None:
    result = decide_current_turn(
        CurrentTurnDecisionInput(
            text="这个怎么弄？",
            is_to_me=True,
            reply_candidates=[
                ReplyTargetCandidate(message_id=101, sender_id=7, text="前面的配置报错了", is_current=False),
                ReplyTargetCandidate(message_id=102, sender_id=8, text="这个怎么弄？", is_current=True),
            ],
        ),
        model_enabled=True,
        model_response='{"action":"REPLY","reply_message_id":101}',
    )

    assert result.reply_message_id == 101
    assert result.delivery_style is CurrentTurnDeliveryStyle.QUOTE


def test_model_current_turn_drops_unknown_reply_target() -> None:
    result = decide_current_turn(
        CurrentTurnDecisionInput(
            text="这个怎么弄？",
            is_to_me=True,
            reply_candidates=[ReplyTargetCandidate(message_id=102, sender_id=8, text="这个怎么弄？", is_current=True)],
        ),
        model_enabled=True,
        model_response='{"action":"REPLY","reply_message_id":999}',
    )

    assert result.reply_message_id is None
    assert result.delivery_style is CurrentTurnDeliveryStyle.PLAIN


def test_rule_current_turn_quotes_a_candidate_reply_to(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.llm import reply_target_candidates

    monkeypatch.setattr(reply_target_candidates, "should_emit_quote", lambda *a, **k: True)
    result = decide_current_turn(
        CurrentTurnDecisionInput(
            text="哈哈哈哈",
            group_id=778901,
            is_to_me=False,
            reply_candidates=[
                ReplyTargetCandidate(message_id=1001, sender_id=5, text="这个怎么弄？", is_current=False),
            ],
            reply_to_message_id=1001,
        ),
        model_enabled=False,
    )

    assert result.action is CurrentTurnAction.REPLY
    assert result.delivery_style is CurrentTurnDeliveryStyle.QUOTE
    assert result.reply_message_id == 1001
    assert result.trace.source == "rule"
    assert result.trace.reason == "rule_reply_quote"


def test_rule_current_turn_ignores_quote_for_unknown_reply_to() -> None:
    result = decide_current_turn(
        CurrentTurnDecisionInput(
            text="哈哈哈哈",
            group_id=778902,
            is_to_me=False,
            reply_candidates=[
                ReplyTargetCandidate(message_id=1001, sender_id=5, text="这个怎么弄？", is_current=False)
            ],
            reply_to_message_id=9999,
        ),
        model_enabled=False,
    )

    assert result.delivery_style is CurrentTurnDeliveryStyle.PLAIN
    assert result.reply_message_id is None


def test_rule_current_turn_respects_quote_cooldown_within_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.llm import reply_target_candidates

    calls = 0

    def first_emit(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return calls == 1

    monkeypatch.setattr(reply_target_candidates, "should_emit_quote", first_emit)
    first = decide_current_turn(
        CurrentTurnDecisionInput(
            text="哈哈哈哈",
            group_id=778903,
            is_to_me=False,
            reply_candidates=[ReplyTargetCandidate(message_id=1001, sender_id=5, text="这条", is_current=False)],
            reply_to_message_id=1001,
        ),
        model_enabled=False,
    )
    second = decide_current_turn(
        CurrentTurnDecisionInput(
            text="哈哈哈哈",
            group_id=778903,
            is_to_me=False,
            reply_candidates=[ReplyTargetCandidate(message_id=1001, sender_id=5, text="这条", is_current=False)],
            reply_to_message_id=1001,
        ),
        model_enabled=False,
    )

    assert first.delivery_style is CurrentTurnDeliveryStyle.QUOTE
    assert second.delivery_style is CurrentTurnDeliveryStyle.PLAIN


def test_model_current_turn_downgrades_mention_without_multi_party_overlap() -> None:
    result = decide_current_turn(
        CurrentTurnDecisionInput(text="你怎么看？", is_to_me=True, has_multi_party_overlap=False),
        model_enabled=True,
        model_response='{"action":"REPLY","delivery_style":"MENTION"}',
    )

    assert result.delivery_style is CurrentTurnDeliveryStyle.PLAIN
    assert result.trace.reason == "mention_without_multi_party_overlap"


def test_current_turn_prompt_distinguishes_short_vent_from_explicit_opinion() -> None:
    prompt = build_current_turn_decision_prompt(CurrentTurnDecisionInput(text="我又改需求了，烦", is_to_me=True))

    assert "ACK is for a short vent" in prompt
    assert "STANCE is only for an explicit request for an opinion" in prompt
    assert "QUOTE only when directly answering the current message" in prompt


def test_current_turn_prompt_forbids_ack_when_replying_to_bot_candidate() -> None:
    turn = CurrentTurnDecisionInput(
        text="真的吗",
        is_to_me=False,
        reply_candidates=[
            ReplyTargetCandidate(message_id=1803128195, sender_id=10001, text="这又是什么缩写"),
        ],
    )
    prompt = build_current_turn_decision_prompt(turn)

    assert "If the message replies to one of the reply candidates" in prompt
    assert "must not be ACK" in prompt


def test_short_social_turns_still_read_persistent_memory() -> None:
    assert should_read_persistent_memory_for_turn(
        "我又改输出了，烦",
        CurrentTurnSocialAction.ANSWER,
    )
    assert should_read_persistent_memory_for_turn(
        "我又改输出了，烦",
        CurrentTurnSocialAction.ACK,
    )
    assert should_read_persistent_memory_for_turn(
        "真的吗",
        CurrentTurnSocialAction.ACK,
    )
    assert should_read_persistent_memory_for_turn(
        "刚才那个输出怎么改的？",
        CurrentTurnSocialAction.ANSWER,
    )


def test_recent_pair_trigger_surface_unchanged_after_history_always_on() -> None:
    # 显式寻址 + 近期 assistant 回复 + 短社交 → 仍带 recent_pair
    assert should_include_recent_pair_for_turn(
        "继续讲",
        CurrentTurnSocialAction.ACK,
        explicitly_addressed=True,
        has_recent_assistant_turn=True,
    )
    # 非显式寻址 → False
    assert not should_include_recent_pair_for_turn(
        "继续讲",
        CurrentTurnSocialAction.ACK,
        explicitly_addressed=False,
        has_recent_assistant_turn=True,
    )
    # 无近期 assistant 回复 → False
    assert not should_include_recent_pair_for_turn(
        "继续讲",
        CurrentTurnSocialAction.ACK,
        explicitly_addressed=True,
        has_recent_assistant_turn=False,
    )
    # 问句（非短社交）→ False
    assert not should_include_recent_pair_for_turn(
        "刚才那个输出怎么改的？",
        CurrentTurnSocialAction.ANSWER,
        explicitly_addressed=True,
        has_recent_assistant_turn=True,
    )


def test_reply_target_keeps_short_social_generation_on_the_current_turn() -> None:
    assert (
        resolve_reply_target(
            "我又改需求了，烦",
            action=CurrentTurnAction.REPLY,
            social_action=CurrentTurnSocialAction.ACK,
        )
        == "emotion"
    )
    assert (
        resolve_reply_target(
            "牛牛你还在吗",
            action=CurrentTurnAction.REPLY,
            social_action=CurrentTurnSocialAction.ACK,
        )
        == "fact"
    )
    assert (
        resolve_reply_target(
            "这也能改？",
            action=CurrentTurnAction.REPLY,
            social_action=CurrentTurnSocialAction.ACK,
        )
        == "fact"
    )
    assert (
        resolve_reply_target(
            "这个怎么改？",
            action=CurrentTurnAction.REPLY,
            social_action=CurrentTurnSocialAction.ANSWER,
        )
        == "answer"
    )
    assert (
        resolve_reply_target(
            "你是不是只会哞哞叫",
            action=CurrentTurnAction.REPLY,
            social_action=CurrentTurnSocialAction.JOKE,
        )
        == "short_tease"
    )
    assert (
        resolve_reply_target(
            "就是骂你",
            action=CurrentTurnAction.PASS,
            social_action=CurrentTurnSocialAction.JOKE,
        )
        == "silent"
    )


def test_answer_reply_target_keeps_relationship_replies_in_current_context() -> None:
    instruction = build_reply_target_instruction("answer")

    assert "情感或关系确认" in instruction
    assert "当前熟悉程度" in instruction
    assert "不补出背景设定、爱好或新安排" in instruction
    assert "不以礼貌反问收尾" in instruction


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
        "delivery_style": "PLAIN",
        "source": "rule",
        "reason": "rule_reply_obligation",
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
async def test_explicit_direct_chat_uses_current_turn_model(monkeypatch) -> None:
    async def request_model(*args: object, **kwargs: object) -> dict[str, str]:
        return {"content": '{"action":"REPLY"}'}

    monkeypatch.setattr("pallas.product.llm.provider_client.complete_chat_message", request_model)

    result = await decide_current_turn_with_model(
        CurrentTurnDecisionInput(text="吃饭了吗", is_to_me=True),
        enabled=True,
    )

    assert result.action is CurrentTurnAction.REPLY
    assert result.trace.source == "model"


@pytest.mark.asyncio
async def test_explicit_direct_chat_uses_current_turn_model_for_quote_delivery(monkeypatch) -> None:
    async def request_model(*args: object, **kwargs: object) -> dict[str, str]:
        return {"content": '{"action":"REPLY","delivery_style":"QUOTE"}'}

    monkeypatch.setattr("pallas.product.llm.provider_client.complete_chat_message", request_model)

    result = await decide_current_turn_with_model(
        CurrentTurnDecisionInput(text="群里聊啥呢", is_to_me=True),
        enabled=True,
    )

    assert result.delivery_style is CurrentTurnDeliveryStyle.QUOTE
    assert result.trace.source == "model"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "turn",
    [
        CurrentTurnDecisionInput(text="帮我找个表情", is_to_me=True, tools_permitted=True),
        CurrentTurnDecisionInput(text="最近怎么样", is_explicitly_addressed=True),
        CurrentTurnDecisionInput(text="你觉得呢", is_to_me=True, has_multi_party_overlap=True),
    ],
)
async def test_complex_turns_keep_current_turn_model(monkeypatch, turn: CurrentTurnDecisionInput) -> None:
    requested = False

    async def request_model(*args: object, **kwargs: object) -> dict[str, str]:
        nonlocal requested
        requested = True
        return {"content": '{"action":"REPLY"}'}

    monkeypatch.setattr("pallas.product.llm.provider_client.complete_chat_message", request_model)

    await decide_current_turn_with_model(turn, enabled=True)

    assert requested is True


@pytest.mark.asyncio
async def test_enabled_current_turn_decision_uses_task_routing_without_legacy_model(monkeypatch) -> None:
    received: dict[str, object] = {}

    async def request_model(*args: object, **kwargs: object) -> dict[str, str]:
        received.update(kwargs)
        return {"content": '{"action":"PASS"}'}

    monkeypatch.setattr("pallas.product.llm.provider_client.complete_chat_message", request_model)

    result = await decide_current_turn_with_model(
        CurrentTurnDecisionInput(text="不用回复", is_to_me=True, has_multi_party_overlap=True),
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
    save_providers_document({
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
    })
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
        CurrentTurnDecisionInput(text="不用回复", is_to_me=True, has_multi_party_overlap=True),
        enabled=True,
    )

    assert result.action is CurrentTurnAction.PASS
    assert attempted == [
        ("https://primary.example.com/v1", "decision-primary"),
        ("https://backup.example.com/v1", "decision-backup"),
    ]
