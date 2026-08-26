from __future__ import annotations

from pallas.product.llm.provider_client import (
    messages_to_responses_payload,
    parse_responses_message,
    tools_for_responses_api,
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


def test_messages_to_responses_payload_converts_vision_content() -> None:
    payload = messages_to_responses_payload(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "这是什么？"},
                    {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                    {"type": "input_text", "text": "补充问题"},
                    {"type": "input_image", "image_url": "https://example.com/b.png", "detail": "high"},
                ],
            }
        ],
        model="deepseek-v4-flash-vision-exp",
        options={},
        tools=None,
    )
    assert payload["input"] == [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "这是什么？"},
                {
                    "type": "input_image",
                    "image_url": "https://example.com/a.png",
                    "detail": "auto",
                },
                {
                    "type": "input_image",
                    "image_url": "data:image/png;base64,abc",
                    "detail": "auto",
                },
                {"type": "input_text", "text": "补充问题"},
                {"type": "input_image", "image_url": "https://example.com/b.png", "detail": "high"},
            ],
        }
    ]


def test_tools_for_responses_api_flattens_chat_schema() -> None:
    flat = tools_for_responses_api([
        {
            "type": "function",
            "function": {
                "name": "search",
                "description": "搜一下",
                "parameters": {
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                    "required": ["q"],
                },
            },
        }
    ])
    assert flat == [
        {
            "type": "function",
            "name": "search",
            "description": "搜一下",
            "parameters": {
                "type": "object",
                "properties": {"q": {"type": "string"}},
                "required": ["q"],
            },
            "strict": False,
        }
    ]


def test_messages_to_responses_payload_flattens_tools() -> None:
    payload = messages_to_responses_payload(
        [{"role": "user", "content": "查一下"}],
        model="deepseek-v4-flash",
        options={"model_effort": "high"},
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "demo",
                    "description": "demo",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )
    assert payload["tools"][0]["name"] == "demo"
    assert "function" not in payload["tools"][0]
    assert payload["tools"][0]["strict"] is False
    assert payload["reasoning"] == {"effort": "high"}


def test_messages_to_responses_payload_echoes_reasoning_before_tool_calls() -> None:
    payload = messages_to_responses_payload(
        [
            {"role": "user", "content": "天气"},
            {
                "role": "assistant",
                "content": "",
                "reasoning_content": "先查天气",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": '{"city":"HZ"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "晴"},
        ],
        model="deepseek-v4-flash",
        options={"model_effort": "high"},
        tools=None,
    )
    types = [item.get("type") or item.get("role") for item in payload["input"]]
    assert types == ["user", "reasoning", "function_call", "function_call_output"]
    assert payload["input"][1]["content"][0]["text"] == "先查天气"


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


def test_parse_responses_message_reasoning() -> None:
    message = parse_responses_message({
        "output": [
            {
                "type": "reasoning",
                "content": [{"type": "reasoning_text", "text": "想一想"}],
            },
            {
                "type": "function_call",
                "call_id": "call_1",
                "name": "demo",
                "arguments": "{}",
            },
        ]
    })
    assert message["reasoning_content"] == "想一想"
    assert message["tool_calls"][0]["id"] == "call_1"
