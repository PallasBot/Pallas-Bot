from __future__ import annotations

import pytest

from src.platform.ingress.unified_pass import (
    mark_unified_ingress_once_won,
    reset_unified_ingress_once_pass_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_unified_ingress_pass() -> None:
    reset_unified_ingress_once_pass_for_tests()


@pytest.mark.asyncio
async def test_command_cross_bot_claim_trusts_ingress_when_sharded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.plugins.help import event_preprocessor

    async def _memory_claim(*_args, **_kwargs) -> bool:
        raise AssertionError("shard mode should not use in-process memory claim")

    monkeypatch.setattr(event_preprocessor, "is_plugin_command_plaintext", lambda text: text == "牛牛MAA状态")
    monkeypatch.setattr("src.platform.ingress.fanout_bypass.ingress_fanout_bypasses_claim", lambda _text: False)
    monkeypatch.setattr(event_preprocessor.shard_ctx, "sharding_active", lambda: True)
    monkeypatch.setattr(event_preprocessor, "try_claim_cross_bot_message_memory", _memory_claim)

    won = await event_preprocessor.command_cross_bot_claim_won(
        bot_id=111,
        group_id=12345,
        user_id=999,
        plain_text="牛牛MAA状态",
        message_time=100,
    )

    assert won is True


@pytest.mark.asyncio
async def test_command_cross_bot_claim_trusts_ingress_for_dream_when_sharded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.plugins.help import event_preprocessor

    async def _memory_claim(*_args, **_kwargs) -> bool:
        raise AssertionError("shard mode should not use in-process memory claim")

    monkeypatch.setattr(event_preprocessor, "is_plugin_command_plaintext", lambda text: text == "牛牛做梦")
    monkeypatch.setattr("src.platform.ingress.fanout_bypass.ingress_fanout_bypasses_claim", lambda _text: False)
    monkeypatch.setattr(event_preprocessor.shard_ctx, "sharding_active", lambda: True)
    monkeypatch.setattr(event_preprocessor, "try_claim_cross_bot_message_memory", _memory_claim)

    won = await event_preprocessor.command_cross_bot_claim_won(
        bot_id=111,
        group_id=12345,
        user_id=999,
        plain_text="牛牛做梦",
        message_time=100,
    )

    assert won is True


@pytest.mark.asyncio
async def test_command_cross_bot_claim_uses_memory_claim_for_maa_status_when_unified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.plugins.help import event_preprocessor

    called: list[tuple[str, int, int, str, int, int]] = []

    async def _memory_claim(
        plugin: str,
        group_id: int,
        user_id: int,
        message_body: str,
        message_time: int,
        bot_id: int,
        *,
        use_plaintext: bool = True,
        include_message_time: bool = False,
    ) -> bool:
        assert use_plaintext is True
        assert include_message_time is True
        called.append((plugin, group_id, user_id, message_body, message_time, bot_id))
        return True

    monkeypatch.setattr(event_preprocessor, "is_plugin_command_plaintext", lambda text: text == "牛牛MAA状态")
    monkeypatch.setattr("src.platform.ingress.fanout_bypass.ingress_fanout_bypasses_claim", lambda _text: False)
    monkeypatch.setattr(event_preprocessor.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr(event_preprocessor, "try_claim_cross_bot_message_memory", _memory_claim)

    won = await event_preprocessor.command_cross_bot_claim_won(
        bot_id=111,
        group_id=12345,
        user_id=999,
        plain_text="牛牛MAA状态",
        message_time=100,
    )

    assert won is True
    assert called == [("command_ingress", 12345, 999, "牛牛MAA状态", 100, 111)]


@pytest.mark.asyncio
async def test_command_cross_bot_claim_trusts_unified_ingress_once_won(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.plugins.help import event_preprocessor

    async def _memory_claim(*_args, **_kwargs) -> bool:
        raise AssertionError("unified ingress pass should skip memory claim")

    monkeypatch.setattr(event_preprocessor, "is_plugin_command_plaintext", lambda text: text == "牛牛帮助")
    monkeypatch.setattr("src.platform.ingress.fanout_bypass.ingress_fanout_bypasses_claim", lambda _text: False)
    monkeypatch.setattr(event_preprocessor.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr(event_preprocessor, "try_claim_cross_bot_message_memory", _memory_claim)

    mark_unified_ingress_once_won(
        type(
            "E",
            (),
            {"group_id": 12345, "user_id": 999, "time": 100, "raw_message": "牛牛帮助", "get_plaintext": lambda self: "牛牛帮助"},
        )(),
        body="牛牛帮助",
    )

    won = await event_preprocessor.command_cross_bot_claim_won(
        bot_id=222,
        group_id=12345,
        user_id=999,
        plain_text="牛牛帮助",
        message_time=100,
    )

    assert won is True


@pytest.mark.asyncio
async def test_command_cross_bot_claim_allows_only_one_bot(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.platform.multi_bot import dedup as dedup_mod
    from src.plugins.help import event_preprocessor

    dedup_mod._cross_bot_claim_owners.clear()
    monkeypatch.setattr(event_preprocessor, "is_plugin_command_plaintext", lambda text: text == "牛牛帮助")
    monkeypatch.setattr(event_preprocessor.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr(
        "src.platform.ingress.fanout_bypass.ingress_fanout_bypasses_claim",
        lambda _text: False,
    )

    first = await event_preprocessor.command_cross_bot_claim_won(
        bot_id=111,
        group_id=12345,
        user_id=999,
        plain_text="牛牛帮助",
        message_time=100,
    )
    second = await event_preprocessor.command_cross_bot_claim_won(
        bot_id=222,
        group_id=12345,
        user_id=999,
        plain_text="牛牛帮助",
        message_time=100,
    )
    again = await event_preprocessor.command_cross_bot_claim_won(
        bot_id=111,
        group_id=12345,
        user_id=999,
        plain_text="牛牛帮助",
        message_time=100,
    )

    assert first is True
    assert second is False
    assert again is True


@pytest.mark.asyncio
async def test_command_cross_bot_claim_skips_non_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.platform.multi_bot import dedup as dedup_mod
    from src.plugins.help import event_preprocessor

    dedup_mod._cross_bot_claim_owners.clear()
    monkeypatch.setattr(event_preprocessor, "is_plugin_command_plaintext", lambda _text: False)

    first = await event_preprocessor.command_cross_bot_claim_won(
        bot_id=111,
        group_id=12345,
        user_id=999,
        plain_text="普通聊天",
        message_time=100,
    )
    second = await event_preprocessor.command_cross_bot_claim_won(
        bot_id=222,
        group_id=12345,
        user_id=999,
        plain_text="普通聊天",
        message_time=100,
    )

    assert first is True
    assert second is True


@pytest.mark.asyncio
async def test_command_cross_bot_claim_skips_ingress_fanout_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.platform.multi_bot import dedup as dedup_mod
    from src.plugins.help import event_preprocessor

    dedup_mod._cross_bot_claim_owners.clear()
    monkeypatch.setattr(event_preprocessor, "is_plugin_command_plaintext", lambda text: text == "牛牛赞我")
    monkeypatch.setattr(
        "src.platform.ingress.fanout_bypass.ingress_fanout_bypasses_claim",
        lambda text: text == "牛牛赞我",
    )

    first = await event_preprocessor.command_cross_bot_claim_won(
        bot_id=923722427,
        group_id=626266902,
        user_id=3023094357,
        plain_text="牛牛赞我",
        message_time=1780135241,
    )
    second = await event_preprocessor.command_cross_bot_claim_won(
        bot_id=3879348674,
        group_id=626266902,
        user_id=3023094357,
        plain_text="牛牛赞我",
        message_time=1780135241,
    )

    assert first is True
    assert second is True


@pytest.mark.asyncio
async def test_check_plugin_enabled_skips_claim_for_help_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.plugins.help import event_preprocessor

    called = False

    async def fake_claim(**_kwargs) -> bool:
        nonlocal called
        called = True
        return True

    monkeypatch.setattr(event_preprocessor, "command_cross_bot_claim_won", fake_claim)

    matcher = type("M", (), {"plugin_name": "src.plugins.help"})()
    bot = type("B", (), {"self_id": "123"})()
    event = type(
        "E",
        (),
        {
            "group_id": 1,
            "user_id": 2,
            "time": 3,
            "message_id": 4,
            "get_plaintext": lambda self: "牛牛帮助",
        },
    )()

    await event_preprocessor.check_plugin_enabled(matcher, bot, event)

    assert called is False
