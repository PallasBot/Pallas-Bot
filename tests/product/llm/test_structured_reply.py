from __future__ import annotations

from pallas.product.llm.models import StructuredChatReply
from pallas.product.llm.output_filter import resolve_output_filtered_chat_reply
from pallas.product.llm.structured_reply import (
    normalize_model_reply,
    parse_structured_reply,
    validate_reply_chars,
)


def test_normalize_extracts_json_reply_field() -> None:
    raw = '{"reasoning": "旁观", "intent": "chat", "reply": "行吧那就这样", "mem": ""}'
    assert normalize_model_reply(raw) == "行吧那就这样"


def test_normalize_accepts_json_only_reply_segments() -> None:
    raw = '{"reply_segments":["先这样吧","回头再说"]}'
    assert normalize_model_reply(raw) == "先这样吧\n回头再说"


def test_parse_structured_reply_keeps_one_to_three_segments_and_logical_text() -> None:
    reply = parse_structured_reply(
        '{"reply_segments":["第一句","第二句","第三句"],"intent":"CHAT","mem":"记一下","sticker":"send"}'
    )

    assert reply.reply_segments == ("第一句", "第二句", "第三句")
    assert reply.logical_text == "第一句\n第二句\n第三句"
    assert reply.intent == "chat"
    assert reply.mem == "记一下"
    assert reply.sticker_intent == "send"


def test_parse_structured_reply_normalizes_sticker_label_intent() -> None:
    reply = parse_structured_reply('{"reply":"好呀","sticker":{"emotion":"开心","action":"挥手","tone":"可爱"}}')

    assert reply.sticker_intent == "emotion:开心 action:挥手 tone:可爱"


def test_parse_structured_reply_merges_tail_after_three_segments() -> None:
    reply = parse_structured_reply('{"reply_segments":["一","二","三","四"]}')

    assert reply.reply_segments == ("一", "二", "三\n四")
    assert reply.logical_text == "一\n二\n三\n四"


def test_parse_structured_reply_rejects_invalid_or_empty_segments() -> None:
    assert parse_structured_reply('{"reply_segments":["一", ""]}').reply_segments == ()
    assert parse_structured_reply('{"reply_segments":["一", 2]}').reply_segments == ()
    assert parse_structured_reply('{"reply_segments":[]}').reply_segments == ()
    assert parse_structured_reply('{"reply_segments":"一"}').reply_segments == ()
    assert parse_structured_reply('{"reply_segments":["你好 <reply>" ]}').reply_segments == ()


def test_old_reply_is_always_one_segment() -> None:
    reply = parse_structured_reply('{"reply":"第一句\\n第二句","reply_segments":["不应","使用"]}')

    assert reply.reply_segments == ("第一句\n第二句",)


def test_parse_structured_reply_rejects_non_text_legacy_reply() -> None:
    assert parse_structured_reply('{"reply": ["不应接受"]}').reply_segments == ()


def test_parse_structured_reply_pass_has_no_segments() -> None:
    assert parse_structured_reply('{"reply_segments":["PASS"]}').reply_segments == ()


def test_parse_structured_reply_accepts_bare_json_array_as_segments() -> None:
    reply = parse_structured_reply('["早呀", "今天也来得挺早"]')

    assert reply.reply_segments == ("早呀", "今天也来得挺早")

    assert parse_structured_reply('["PASS"]').reply_segments == ()
    assert parse_structured_reply('["一", "二", "三", "四"]').reply_segments == ("一", "二", "三\n四")


def test_output_filter_removes_empty_segments_after_stage_cleanup() -> None:
    task = {"task_type": "llm_chat"}
    reply = StructuredChatReply(reply_segments=("（笑）", "在的，咋了"))

    assert resolve_output_filtered_chat_reply(task, reply).reply_segments == ("在的，咋了",)


def test_output_filter_keeps_direct_candidate_as_one_literal_segment() -> None:
    task = {"task_type": "llm_chat"}
    direct = StructuredChatReply.single("PASS")

    assert resolve_output_filtered_chat_reply(task, direct).reply_segments == ("PASS",)


def test_output_filter_drops_individually_filler_segment(monkeypatch) -> None:
    monkeypatch.setattr("pallas.product.llm.output_filter.output_filter_enabled", lambda: True)
    task = {"task_type": "llm_chat"}
    reply = StructuredChatReply(reply_segments=("还行吧", "你呢"))

    assert resolve_output_filtered_chat_reply(task, reply).reply_segments == ("你呢",)


def test_output_filter_blocks_phrase_split_between_segments(monkeypatch) -> None:
    monkeypatch.setattr("pallas.product.llm.output_filter.output_filter_enabled", lambda: True)
    monkeypatch.setattr(
        "pallas.product.llm.output_filter.phrases_for_profile",
        lambda _profile, tier: ("危险组合",) if tier == "hard_block" else (),
    )
    task = {"task_type": "llm_chat"}
    reply = StructuredChatReply(reply_segments=("危险", "组合"))

    assert resolve_output_filtered_chat_reply(task, reply).reply_segments == ()


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


def test_validate_reply_chars_allows_standalone_question_mark() -> None:
    ok, _reason = validate_reply_chars("？")
    assert ok is True


def test_validate_reply_chars_allows_cjk_ellipsis() -> None:
    ok, _reason = validate_reply_chars("我看看……快十点了？")
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
