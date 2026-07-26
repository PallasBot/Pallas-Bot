from __future__ import annotations

import httpx
import pytest

from pallas.product.llm.current_turn_decision import (
    CurrentTurnAction,
    CurrentTurnDecisionInput,
    decide_current_turn,
    decide_current_turn_with_model,
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
        CurrentTurnDecisionInput(text="继续说", is_to_me=True),
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
