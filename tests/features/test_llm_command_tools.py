from __future__ import annotations

from types import SimpleNamespace

import pytest

from pallas.product.llm.tools.bootstrap import reset_llm_tools_bootstrap_for_tests
from pallas.product.llm.tools.command_invoke import (
    LLM_COMMAND_EVENT_CONTEXT_ATTR,
    CommandTemplateError,
    append_source_segments_to_message,
    build_synthetic_group_event,
    dispatch_group_command_text,
    render_command_template,
    serialize_event_source_segments,
    source_segments_for_command,
)
from pallas.product.llm.tools.context import ToolInvokeContext
from pallas.product.llm.tools.declare import llm_command_tool_row
from pallas.product.llm.tools.metadata import parse_llm_command_tool_decl
from pallas.product.llm.tools.plugin_bootstrap import build_command_tool_spec, register_plugin_command_tools
from pallas.product.llm.tools.registry import clear_tool_registry, tool_openai_schemas


@pytest.fixture(autouse=True)
def reset_tools() -> None:
    reset_llm_tools_bootstrap_for_tests()
    yield
    reset_llm_tools_bootstrap_for_tests()


def test_render_command_template() -> None:
    text = render_command_template("牛牛画画 {prompt}", {"prompt": "一只猫"})
    assert text == "牛牛画画 一只猫"


def test_serialize_event_source_segments_keeps_at_image_and_self() -> None:
    from nonebot.adapters.onebot.v11 import Message, MessageSegment

    event = SimpleNamespace(
        original_message=Message([
            MessageSegment.at(3879348674),
            MessageSegment.text("做个摸"),
            MessageSegment.at(12345),
            MessageSegment.image("https://example.com/a.png"),
            MessageSegment.text("自己"),
        ]),
        get_message=lambda: Message("stripped"),
        self_id=3879348674,
        user_id=3023094357,
    )
    segments = serialize_event_source_segments(event, bot_id=3879348674)
    assert segments[0] == {"type": "at", "qq": "12345"}
    assert segments[1]["type"] == "image"
    assert segments[1].get("url") == "https://example.com/a.png"
    assert segments[2] == {"type": "text", "text": "自己"}


def test_serialize_event_source_segments_drops_leading_wake_bot_at() -> None:
    from nonebot.adapters.onebot.v11 import Message, MessageSegment

    event = SimpleNamespace(
        original_message=Message([
            MessageSegment.at(3879348674),
            MessageSegment.text("做个摸表情"),
        ]),
        self_id=3879348674,
        user_id=3023094357,
    )
    segments = serialize_event_source_segments(event, bot_id=3879348674)
    assert segments == []


def test_serialize_event_source_segments_keeps_trailing_bot_at() -> None:
    """句末 @bot 表示用牛牛头像做表情，不能当唤醒丢掉。"""
    from nonebot.adapters.onebot.v11 import Message, MessageSegment

    event = SimpleNamespace(
        original_message=Message([
            MessageSegment.text("做个滚表情"),
            MessageSegment.at(3879348674),
        ]),
        self_id=3879348674,
        user_id=3023094357,
    )
    segments = serialize_event_source_segments(event, bot_id=3879348674)
    assert segments == [{"type": "at", "qq": "3879348674"}]


def test_serialize_event_source_segments_keeps_target_drops_leading_bot() -> None:
    from nonebot.adapters.onebot.v11 import Message, MessageSegment

    event = SimpleNamespace(
        original_message=Message([
            MessageSegment.at(3879348674),
            MessageSegment.text("做个摸"),
            MessageSegment.at(3023094357),
            MessageSegment.text("的表情"),
        ]),
        self_id=3879348674,
        user_id=3023094357,
    )
    segments = serialize_event_source_segments(event, bot_id=3879348674)
    assert segments == [{"type": "at", "qq": "3023094357"}]


def test_build_synthetic_group_event_appends_source_segments() -> None:
    event = build_synthetic_group_event(
        bot_id=1,
        group_id=2,
        user_id=3,
        text="牛牛表情推荐 摸",
        source_segments=[{"type": "at", "qq": "12345"}],
    )
    types = [seg.type for seg in event.message]
    assert "text" in types
    assert "at" in types
    assert any(seg.type == "at" and str(seg.data.get("qq")) == "12345" for seg in event.message)
    assert event.original_message is not None


def test_build_synthetic_group_event_keeps_original_media_after_message_mutation() -> None:
    event = build_synthetic_group_event(
        bot_id=1,
        group_id=2,
        user_id=3,
        text="牛牛表情推荐 摸",
        source_segments=[{"type": "at", "qq": "12345"}],
    )

    event.message.pop()

    assert any(seg.type == "at" and str(seg.data.get("qq")) == "12345" for seg in event.original_message)


def test_tool_invoke_context_reads_source_segments() -> None:
    ctx = ToolInvokeContext.from_payload({
        "bot_id": 1,
        "group_id": 2,
        "user_id": 3,
        "command_source_segments": [{"type": "at", "qq": "9"}],
    })
    assert ctx is not None
    assert ctx.source_segments == ({"type": "at", "qq": "9"},)


def test_append_source_segments_to_message() -> None:
    from nonebot.adapters.onebot.v11 import Message

    message = append_source_segments_to_message(
        Message("hello"),
        [{"type": "at", "qq": "42"}, {"type": "text", "text": "自己"}],
    )
    assert [seg.type for seg in message] == ["text", "at", "text"]


def test_source_segments_for_command_only_adds_self_for_media() -> None:
    assert source_segments_for_command((), mode="none") == ()
    assert source_segments_for_command((), mode="media") == ({"type": "text", "text": "自己"},)
    segments = ({"type": "at", "qq": "42"},)
    assert source_segments_for_command(segments, mode="none") == ()
    assert source_segments_for_command(segments, mode="media") == segments


def test_source_segments_for_command_uses_sender_at_when_media_is_missing() -> None:
    assert source_segments_for_command((), mode="media", sender_id=12345) == ({"type": "at", "qq": "12345"},)


@pytest.mark.asyncio
async def test_dispatch_group_command_text_reports_source_segment_types(monkeypatch) -> None:
    from pallas.product.llm.tools import command_invoke

    async def allow(*_args, **_kwargs) -> bool:
        return True

    dispatched_events = []

    async def handle(_bot, event) -> None:
        dispatched_events.append(event)
        return None

    monkeypatch.setattr(command_invoke, "get_bot", lambda _bot_id: SimpleNamespace())
    monkeypatch.setattr(command_invoke, "satisfies_command_permission", allow)
    monkeypatch.setattr(command_invoke.nb_message, "handle_event", handle)

    result = await dispatch_group_command_text(
        ToolInvokeContext(bot_id=1, group_id=2, user_id=12345),
        command_id="memes.recommend",
        command_text="牛牛表情推荐 摸",
        source_segments_mode="media",
    )

    assert result["source_segment_count"] == 1
    assert result["source_segment_types"] == ["at"]
    assert getattr(dispatched_events[0], LLM_COMMAND_EVENT_CONTEXT_ATTR) == {
        "command_id": "memes.recommend",
        "source_segment_types": ["at"],
    }


def test_source_segments_for_command_uses_sender_when_only_wake_bot_is_present() -> None:
    segments = ({"type": "at", "qq": "3879348674"},)
    assert source_segments_for_command(segments, mode="media", bot_id=3879348674) == ({"type": "text", "text": "自己"},)


def test_source_segments_for_command_keeps_an_explicit_subject() -> None:
    segments = (
        {"type": "at", "qq": "3879348674"},
        {"type": "at", "qq": "3023094357"},
    )
    assert source_segments_for_command(segments, mode="media", bot_id=3879348674) == (
        {"type": "at", "qq": "3023094357"},
    )


def test_sanitize_meme_tool_argument_strips_self_and_noise() -> None:
    from pallas.product.llm.tools.plugin_bootstrap import (
        prepare_command_tool_arguments,
        sanitize_meme_tool_argument,
    )

    assert sanitize_meme_tool_argument("吃自己") == "吃"
    assert sanitize_meme_tool_argument("自己自己") == ""
    assert sanitize_meme_tool_argument("牛牛表情搜索 牛牛自己") == ""
    assert sanitize_meme_tool_argument("摸") == "摸"
    prepared = prepare_command_tool_arguments(
        "memes.recommend",
        {"intent": "吃自己"},
    )
    assert prepared["intent"] == "吃"
    prepared_search = prepare_command_tool_arguments(
        "memes.search",
        {"keyword": "牛牛自己"},
    )
    assert prepared_search["keyword"] == ""
    from pallas.product.llm.tools.plugin_bootstrap import command_tool_arguments_ready

    assert command_tool_arguments_ready("memes.search", prepared_search) == "empty_meme_keyword"
    assert command_tool_arguments_ready("memes.recommend", prepared) is None


def test_sing_tool_rejects_placeholder_song_args() -> None:
    from pallas.product.llm.tools.plugin_bootstrap import command_tool_arguments_ready

    assert command_tool_arguments_ready("sing.sing", {"song": ""}) == "placeholder_sing_song"
    assert command_tool_arguments_ready("sing.sing", {"song": "牛牛唱歌"}) == "placeholder_sing_song"
    assert command_tool_arguments_ready("sing.sing", {"song": "随机"}) == "placeholder_sing_song"
    assert command_tool_arguments_ready("sing.sing", {"song": "随便"}) == "placeholder_sing_song"
    assert command_tool_arguments_ready("sing.request_song", {"song": "牛牛唱歌"}) == ("placeholder_sing_song")
    assert command_tool_arguments_ready("sing.sing", {"song": "夜曲"}) is None
    assert command_tool_arguments_ready("sing.request_song", {"song": "夜曲"}) is None


def test_memes_list_search_do_not_auto_media(monkeypatch) -> None:
    decl_search = parse_llm_command_tool_decl(
        llm_command_tool_row(
            name="memes.search",
            command_id="memes.search",
            description="搜",
            parameters={
                "type": "object",
                "properties": {"keyword": {"type": "string"}},
                "required": ["keyword"],
            },
            command_template="牛牛表情搜索 {keyword}",
            source_segments="none",
        )
    )
    decl_recommend = parse_llm_command_tool_decl(
        llm_command_tool_row(
            name="memes.recommend",
            command_id="memes.recommend",
            description="荐",
            parameters={
                "type": "object",
                "properties": {"intent": {"type": "string"}},
                "required": ["intent"],
            },
            command_template="牛牛表情推荐 {intent}",
            source_segments="none",
        )
    )
    assert decl_search is not None
    assert decl_recommend is not None

    captured: list[str] = []

    async def fake_dispatch(ctx, *, command_id, command_text, source_segments_mode="none"):
        captured.append(source_segments_mode)
        return {"ok": True, "dispatched": True}

    monkeypatch.setattr(
        "pallas.product.llm.tools.plugin_bootstrap.dispatch_group_command_text",
        fake_dispatch,
    )
    import asyncio

    search_spec = build_command_tool_spec(decl_search, plugin_name="memes", plugin_title="表情")
    recommend_spec = build_command_tool_spec(decl_recommend, plugin_name="memes", plugin_title="表情")
    ctx = ToolInvokeContext.from_payload({"bot_id": 1, "group_id": 2, "user_id": 3})
    assert ctx is not None
    asyncio.run(search_spec.handler({"keyword": "吃"}, ctx))
    asyncio.run(recommend_spec.handler({"intent": "吃"}, ctx))
    assert captured == ["none", "media"]


def test_render_command_template_missing_field() -> None:
    with pytest.raises(CommandTemplateError):
        render_command_template("牛牛画画 {prompt}", {})


def test_parse_llm_command_tool_decl() -> None:
    raw = llm_command_tool_row(
        name="draw.image",
        command_id="draw.draw",
        description="生图",
        parameters={"type": "object", "properties": {}},
        command_template="牛牛画画 {prompt}",
    )
    decl = parse_llm_command_tool_decl(raw)
    assert decl is not None
    assert decl.name == "draw.image"


def test_register_plugin_command_tool_schema(monkeypatch) -> None:
    decl = parse_llm_command_tool_decl(
        llm_command_tool_row(
            name="demo.echo",
            command_id="demo.echo",
            description="回声",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            command_template="echo {text}",
        )
    )
    assert decl is not None

    class FakePlugin:
        name = "pallas_plugin_demo"
        metadata = SimpleNamespace(
            name="演示",
            extra={
                "llm_tools": [
                    llm_command_tool_row(
                        name="demo.echo",
                        command_id="demo.echo",
                        description="回声",
                        parameters={
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                        },
                        command_template="echo {text}",
                    )
                ]
            },
        )

    monkeypatch.setattr(
        "nonebot.get_loaded_plugins",
        lambda: [FakePlugin()],
    )
    clear_tool_registry()
    count = register_plugin_command_tools()
    assert count == 1
    schemas = tool_openai_schemas(domains=frozenset({"demo"}))
    names = {item["function"]["name"] for item in schemas}
    assert "demo__echo" in names
    # 短域名 demo 也能命中（即便插件模块名是 pallas_plugin_demo）
    assert tool_openai_schemas(domains=frozenset({"pallas_plugin_demo"}))


def test_build_command_tool_spec_requires_context() -> None:
    decl = parse_llm_command_tool_decl(
        llm_command_tool_row(
            name="demo.echo",
            command_id="demo.echo",
            description="回声",
            parameters={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
            command_template="echo {text}",
        )
    )
    assert decl is not None
    spec = build_command_tool_spec(decl, plugin_name="demo", plugin_title="演示")
    import asyncio

    result = asyncio.run(spec.handler({"text": "hi"}, None))
    assert result["ok"] is False
    assert result["error"] == "missing_invoke_context"


def test_parse_llm_tools_stub_reads_command_tool_row_calls() -> None:
    from pathlib import Path

    from pallas.product.llm.tools.metadata import parse_llm_tools_stub

    decls = parse_llm_tools_stub(Path("packages/drink/__init__.py"))
    names = {item.name for item in decls}
    assert "drink.drink" in names
    assert "drink.sober_up" in names


def test_tool_metadata_prefers_required_for_selective_command_tools(monkeypatch) -> None:
    from pallas.product.llm.tools import registry
    from pallas.product.llm.tools.bootstrap import reset_llm_tools_bootstrap_for_tests

    reset_llm_tools_bootstrap_for_tests()
    monkeypatch.setattr(
        "pallas.product.llm.tools.registry.get_llm_config",
        lambda: type(
            "Cfg",
            (),
            {
                "llm_tools_enabled": True,
                "llm_tools_selective": True,
                "llm_tools_blacklist": [],
                "llm_tools_desc_max_len": 200,
            },
        )(),
    )
    monkeypatch.setattr(
        "pallas.product.llm.tools.registry.get_arknights_kb_config",
        lambda: type("Kb", (), {"arknights_kb_enabled": True})(),
    )
    clear_tool_registry()
    registry.register_tool(
        build_command_tool_spec(
            parse_llm_command_tool_decl(
                llm_command_tool_row(
                    name="drink.drink",
                    command_id="drink.drink",
                    description="喝酒",
                    parameters={"type": "object", "properties": {}},
                    command_template="牛牛喝酒",
                )
            ),
            plugin_name="drink",
            plugin_title="喝酒",
        )
    )
    meta = registry.tool_metadata_for_chat(task="llm_chat", user_text="喝一杯")
    assert meta.get("tools_enabled") is True
    assert meta.get("tool_choice_prefer") == "required"
    names = {item["function"]["name"] for item in meta.get("tool_schemas") or []}
    assert "drink__drink" in names


def test_provider_tool_name_roundtrip() -> None:
    from pallas.product.llm.tools.registry import from_provider_tool_name, to_provider_tool_name

    assert to_provider_tool_name("drink.sober_up") == "drink__sober_up"
    assert to_provider_tool_name("arknights.operator.get") == "arknights__operator__get"
    # 未注册时仍可逆
    assert from_provider_tool_name("drink__sober_up") == "drink.sober_up"
