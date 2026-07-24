from __future__ import annotations

from pallas.product.llm.provider_client import (
    messages_to_responses_payload,
    parse_responses_message,
)


def test_messages_to_responses_payload_basic() -> None:
    payload = messages_to_responses_payload(
        [
            {"role": "system", "content": "你是助手"},
            {"role": "user", "content": "你好"},
        ],
        model="gpt-4.1",
        options={},
        tools=None,
    )
    assert payload["model"] == "gpt-4.1"
    assert payload["instructions"] == "你是助手"
    assert payload["input"] == [{"role": "user", "content": "你好"}]


def test_parse_responses_message_text_and_tools() -> None:
    message = parse_responses_message({
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "收到"}],
            },
            {
                "type": "function_call",
                "call_id": "call_1",
                "name": "search",
                "arguments": '{"q":"x"}',
            },
        ]
    })
    assert message["content"] == "收到"
    assert message["tool_calls"][0]["function"]["name"] == "search"
