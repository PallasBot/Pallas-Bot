from __future__ import annotations

from pallas.product.llm.structured_reply import (
    normalize_model_reply,
    validate_reply_chars,
)


def test_normalize_extracts_json_reply_field() -> None:
    raw = '{"reasoning": "旁观", "intent": "chat", "reply": "行吧那就这样", "mem": ""}'
    assert normalize_model_reply(raw) == "行吧那就这样"


def test_normalize_pass_becomes_empty() -> None:
    assert normalize_model_reply('{"reply": "PASS"}') == ""
    assert normalize_model_reply("PASS") == ""
    assert normalize_model_reply("PASS.") == ""


def test_normalize_fenced_json() -> None:
    raw = '```json\n{"reply": "草，这也行"}\n```'
    assert normalize_model_reply(raw) == "草，这也行"


def test_normalize_malformed_json_object_fail_closed() -> None:
    assert normalize_model_reply('{"reply": "半截') == ""
    assert normalize_model_reply("{not json") == ""


def test_normalize_plain_chat_passthrough() -> None:
    assert normalize_model_reply("在的，咋了") == "在的，咋了"


def test_normalize_rejects_reasoning_prefix_leak() -> None:
    assert normalize_model_reply("意图：先安抚再提问\n然后说你好") == ""
    assert normalize_model_reply("thinking: stay calm") == ""


def test_validate_reply_chars_allows_normal_zh() -> None:
    ok, _reason = validate_reply_chars("在的，咋了？")
    assert ok is True


def test_validate_reply_chars_rejects_xml_json_tokens() -> None:
    ok, reason = validate_reply_chars("你好 <reply>hi</reply>")
    assert ok is False
    assert "bad token" in reason

    ok2, _ = validate_reply_chars('答：{"a":1}')
    assert ok2 is False


def test_validate_reply_chars_rejects_empty_and_no_cjk() -> None:
    ok, reason = validate_reply_chars("")
    assert ok is False
    assert reason == "empty"

    ok2, reason2 = validate_reply_chars("|||")
    assert ok2 is False
