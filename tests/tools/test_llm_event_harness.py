from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from urllib.request import urlopen

import nonebot
import pytest
from nonebot.adapters.onebot.v11 import Adapter

from tools.llm_event_harness import (
    EventFixture,
    FakeBot,
    LocalImageServer,
    build_group_message_payload,
    load_event_fixtures,
    run_event_case,
)


def test_build_group_message_payload_uses_real_onebot_segments() -> None:
    payload = build_group_message_payload(
        text="看这个",
        images=["https://example.test/a.png", "https://example.test/b.png"],
        to_me=True,
        bot_id="10001",
        group_id=20002,
        user_id=30003,
        message_id=40004,
        sender_nickname="tester",
        sender_role="admin",
    )

    assert [segment["type"] for segment in payload["message"]] == ["at", "text", "image", "image"]
    assert payload["message"][0]["data"]["qq"] == "10001"
    assert payload["message"][2]["data"]["url"] == "https://example.test/a.png"
    assert payload["sender"] == {"user_id": 30003, "nickname": "tester", "role": "admin"}
    assert payload["self_id"] == "10001"
    assert payload["group_id"] == 20002


def test_load_event_fixtures_supports_wrapped_and_bare_payloads(tmp_path) -> None:
    wrapped = build_group_message_payload(
        text="wrapped",
        images=[],
        to_me=False,
        bot_id="10001",
        group_id=20002,
        user_id=30003,
        message_id=40004,
        sender_nickname="tester",
        sender_role="member",
    )
    bare = build_group_message_payload(
        text="bare",
        images=[],
        to_me=False,
        bot_id="10001",
        group_id=20002,
        user_id=30003,
        message_id=40005,
        sender_nickname="tester",
        sender_role="member",
    )
    path = tmp_path / "events.jsonl"
    path.write_text(
        "\n".join([
            json.dumps({"name": "wrapped-case", "event": wrapped}),
            json.dumps(bare),
        ]),
        encoding="utf-8",
    )

    fixtures = load_event_fixtures(path)

    assert [fixture.name for fixture in fixtures] == ["wrapped-case", "case-2"]
    assert fixtures[0].event == wrapped
    assert fixtures[1].event == bare


@pytest.mark.asyncio
async def test_fake_bot_only_allows_group_delivery() -> None:
    adapter = Adapter(nonebot.get_driver())
    bot = FakeBot(adapter, "10001")

    result = await bot.call_api("send_group_msg", group_id=20002, message="hello")

    assert result["message_id"]
    assert bot.calls == [{"action": "send_group_msg", "params": {"group_id": 20002, "message": "hello"}}]
    assert bot.last_message == "hello"
    assert bot.reply_text() == "hello"

    with pytest.raises(RuntimeError, match="FakeBot rejected API: send_private_msg"):
        await bot.call_api("send_private_msg", user_id=30003, message="no")


def test_local_image_server_serves_only_registered_files(tmp_path) -> None:
    image = tmp_path / "sample.png"
    image.write_bytes(b"fake-image")

    with LocalImageServer([image]) as server:
        with urlopen(server.url_for(image)) as response:
            assert response.read() == b"fake-image"

    with pytest.raises(RuntimeError, match="not running"):
        server.url_for(image)


@pytest.mark.asyncio
async def test_run_event_case_timeout_resets_context_and_keeps_unrelated_task() -> None:
    payload = build_group_message_payload(
        text="hello",
        images=[],
        to_me=True,
        bot_id="10001",
        group_id=20002,
        user_id=30003,
        message_id=40004,
        sender_nickname="tester",
        sender_role="member",
    )
    adapter = Adapter(nonebot.get_driver())
    seen: list[tuple[object, object]] = []

    async def dispatch(bot, event) -> None:
        seen.append((bot, event))
        from pallas.product.llm.persona_context import llm_chat_prompt_override

        assert nonebot.get_bot("10001") is bot
        assert llm_chat_prompt_override.get() == "variant prompt"
        await asyncio.sleep(0.2)

    unrelated_task = asyncio.create_task(asyncio.sleep(0.2))
    try:
        result = await run_event_case(
            EventFixture("timeout-case", payload),
            prompt="variant prompt",
            provider="test-provider",
            model="test-model",
            temperature=0.7,
            timeout=0.01,
            runtime=SimpleNamespace(adapter=adapter, dispatch=dispatch),
        )
    finally:
        unrelated_task.cancel()
        await asyncio.gather(unrelated_task, return_exceptions=True)

    assert result.status == "timeout"
    assert result.error
    assert seen
    from pallas.product.llm.persona_context import llm_chat_prompt_override

    assert llm_chat_prompt_override.get() is None
