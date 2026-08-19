from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call

import pytest
from nonebot.exception import ActionFailed

from packages.drink import handlers, service


def event() -> SimpleNamespace:
    return SimpleNamespace(self_id=1, group_id=2)


def config(*, drunkenness: int = 1, dreaming: bool = False) -> MagicMock:
    value = MagicMock()
    value.drink = AsyncMock()
    value.drunkenness = AsyncMock(return_value=drunkenness)
    value.sleep = AsyncMock()
    value.is_dreaming = AsyncMock(return_value=dreaming)
    value.fully_sober_up_now = AsyncMock()
    value.stop_dream = AsyncMock()
    value.sober_up = AsyncMock(return_value=True)
    value.is_sleep = AsyncMock(return_value=False)
    return value


@pytest.mark.asyncio
async def test_drink_returns_without_side_effects_during_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    bot_config = config()
    monkeypatch.setattr(service, "is_command_cooldown_ready", AsyncMock(return_value=False))
    monkeypatch.setattr(service, "refresh_command_cooldown", AsyncMock())
    monkeypatch.setattr(service, "BotConfig", MagicMock(return_value=bot_config))
    send = AsyncMock()

    await service.drink(event(), send)

    service.refresh_command_cooldown.assert_not_awaited()
    bot_config.drink.assert_not_awaited()
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_drink_refreshes_before_mutating_state_and_sends_normal_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    bot_config = config(drunkenness=10)
    bot_config.drink.side_effect = lambda: order.append("drink")
    refresh = AsyncMock(side_effect=lambda *_args: order.append("refresh"))
    monkeypatch.setattr(service, "is_command_cooldown_ready", AsyncMock(return_value=True))
    monkeypatch.setattr(service, "refresh_command_cooldown", refresh)
    monkeypatch.setattr(service, "BotConfig", MagicMock(return_value=bot_config))
    monkeypatch.setattr(service.random, "randint", lambda *_args: 60)
    monkeypatch.setattr(service.random, "random", lambda: 0.5)
    monkeypatch.setattr(service, "now", lambda: datetime(2026, 8, 10, 12, 0, 0))
    add_job = MagicMock()
    monkeypatch.setattr(service.scheduler, "add_job", add_job)
    send = AsyncMock()

    await service.drink(event(), send)

    assert order == ["refresh", "drink"]
    refresh.assert_awaited_once()
    send.assert_awaited_once_with("呀，博士。你今天走起路来，怎么看着摇摇晃晃的？")
    add_job.assert_called_once_with(
        service.sober_up_later,
        trigger="date",
        run_date=datetime(2026, 8, 10, 12, 1, 0),
        args=(1, 2),
    )


@pytest.mark.asyncio
async def test_drink_logs_domain_narrative_after_state_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    bot_config = config(drunkenness=10)
    log_info = MagicMock()
    monkeypatch.setattr(service, "is_command_cooldown_ready", AsyncMock(return_value=True))
    monkeypatch.setattr(service, "refresh_command_cooldown", AsyncMock())
    monkeypatch.setattr(service, "BotConfig", MagicMock(return_value=bot_config))
    monkeypatch.setattr(service.random, "randint", lambda *_args: 60)
    monkeypatch.setattr(service.random, "random", lambda: 0.5)
    monkeypatch.setattr(service.scheduler, "add_job", MagicMock())
    monkeypatch.setattr(service.logger, "info", log_info)

    await service.drink(event(), AsyncMock())

    assert log_info.call_args_list[0].args == ("[Drink] Bot [1] started drinking in group [2], sober up after [60s]",)


@pytest.mark.asyncio
async def test_drink_sleep_branch_persists_sleep_and_keeps_reply_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    bot_config = config(drunkenness=60)
    random_values = iter((0.1, 0.25))
    monkeypatch.setattr(service, "is_command_cooldown_ready", AsyncMock(return_value=True))
    monkeypatch.setattr(service, "refresh_command_cooldown", AsyncMock())
    monkeypatch.setattr(service, "BotConfig", MagicMock(return_value=bot_config))
    monkeypatch.setattr(service.random, "randint", lambda *_args: 120)
    monkeypatch.setattr(service.random, "random", lambda: next(random_values))
    monkeypatch.setattr(service.scheduler, "add_job", MagicMock())
    sleep = AsyncMock()
    monkeypatch.setattr(service.asyncio, "sleep", sleep)
    send = AsyncMock()

    await service.drink(event(), send)

    bot_config.sleep.assert_awaited_once_with(28200)
    assert send.await_args_list == [
        call("呀，博士。你今天走起路来，怎么看着摇…摇……晃…………"),
        call("Zzz……"),
    ]
    sleep.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_drink_ignores_action_failed_but_still_schedules_sober_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "is_command_cooldown_ready", AsyncMock(return_value=True))
    monkeypatch.setattr(service, "refresh_command_cooldown", AsyncMock())
    monkeypatch.setattr(service, "BotConfig", MagicMock(return_value=config()))
    monkeypatch.setattr(service.random, "randint", lambda *_args: 60)
    monkeypatch.setattr(service.random, "random", lambda: 0.5)
    add_job = MagicMock()
    monkeypatch.setattr(service.scheduler, "add_job", add_job)

    await service.drink(event(), AsyncMock(side_effect=ActionFailed("OneBot V11")))

    add_job.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("drunkenness", "dreaming", "expected_calls"),
    [
        (0, False, []),
        (1, False, ["sober", "send"]),
        (0, True, ["stop", "worker", "wake"]),
        (1, True, ["sober", "stop", "worker", "send", "wake"]),
    ],
)
async def test_sober_up_preserves_state_and_reply_order(
    monkeypatch: pytest.MonkeyPatch,
    drunkenness: int,
    dreaming: bool,
    expected_calls: list[str],
) -> None:
    order: list[str] = []
    bot_config = config(drunkenness=drunkenness, dreaming=dreaming)
    bot_config.fully_sober_up_now.side_effect = lambda: order.append("sober")
    bot_config.stop_dream.side_effect = lambda: order.append("stop")
    monkeypatch.setattr(service, "BotConfig", MagicMock(return_value=bot_config))
    monkeypatch.setattr(
        service.dream_coord,
        "stop_dream_worker",
        AsyncMock(side_effect=lambda *_args: order.append("worker")),
    )
    monkeypatch.setattr(
        service.dream_coord,
        "send_dream_wake_text",
        AsyncMock(side_effect=lambda *_args: order.append("wake")),
    )
    send = AsyncMock(side_effect=lambda *_args: order.append("send"))

    await service.sober_up(event(), send)

    assert order == expected_calls


@pytest.mark.asyncio
async def test_sober_up_ignores_action_failed_and_continues_dream_wake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "BotConfig", MagicMock(return_value=config(drunkenness=1, dreaming=True)))
    monkeypatch.setattr(service.dream_coord, "stop_dream_worker", AsyncMock())
    wake = AsyncMock()
    monkeypatch.setattr(service.dream_coord, "send_dream_wake_text", wake)

    await service.sober_up(event(), AsyncMock(side_effect=ActionFailed("OneBot V11")))

    wake.assert_awaited_once_with(1, 2)


@pytest.mark.asyncio
async def test_sober_up_later_sends_only_after_sober_and_not_sleeping(monkeypatch: pytest.MonkeyPatch) -> None:
    bot_config = config()
    monkeypatch.setattr(service, "BotConfig", MagicMock(return_value=bot_config))
    bot = MagicMock()
    bot.call_api = AsyncMock()
    monkeypatch.setattr(service, "get_bot", MagicMock(return_value=bot))

    await service.sober_up_later(1, 2)

    bot.call_api.assert_awaited_once_with(
        "send_group_msg",
        message="呃......咳嗯，下次不能喝、喝这么多了......",
        group_id=2,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("sobered", "sleeping"), [(False, False), (True, True)])
async def test_sober_up_later_stays_silent_when_not_ready(
    monkeypatch: pytest.MonkeyPatch,
    sobered: bool,
    sleeping: bool,
) -> None:
    bot_config = config()
    bot_config.sober_up.return_value = sobered
    bot_config.is_sleep.return_value = sleeping
    monkeypatch.setattr(service, "BotConfig", MagicMock(return_value=bot_config))
    get_bot = MagicMock()
    monkeypatch.setattr(service, "get_bot", get_bot)

    await service.sober_up_later(1, 2)

    get_bot.assert_not_called()


@pytest.mark.asyncio
async def test_legacy_handlers_delegate_to_shared_service(monkeypatch: pytest.MonkeyPatch) -> None:
    drink = AsyncMock()
    sober_up = AsyncMock()
    monkeypatch.setattr(handlers.service, "drink", drink)
    monkeypatch.setattr(handlers.service, "sober_up", sober_up)
    current_event = event()

    await handlers.handle_drink(current_event)
    await handlers.handle_sober_up(current_event)

    drink.assert_awaited_once_with(current_event, handlers.drink_msg.send)
    sober_up.assert_awaited_once_with(current_event, handlers.sober_up_msg.send)
