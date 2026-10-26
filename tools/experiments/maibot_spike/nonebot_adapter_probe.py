"""Replay an explicit upstream checkout with fake bots and no network.

The upstream package initializer starts a network thread. This probe loads only
its original submodules, so it does not validate plugin loading or lifecycle.
Successful fact checks do not mean the observed routing gaps are acceptable.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
from importlib.metadata import version
from pathlib import Path
from types import ModuleType
from unittest.mock import patch


class FakeBot:
    def __init__(self, self_id: str):
        self.self_id = self_id
        self.sent = []

    async def get_group_info(self, **_kwargs):
        return {"group_name": "synthetic group"}

    async def send_msg(self, **kwargs):
        self.sent.append(kwargs)
        return {"message_id": 123456}


class FakeTransport:
    connected = True

    def __init__(self):
        self.messages = []
        self.echo_calls = []

    async def send_message(self, message):
        self.messages.append(message)
        return True

    async def send_custom_message(self, *args, **kwargs):
        self.echo_calls.append((args, kwargs))


async def replay(source: Path) -> dict:
    import maim_message as maim
    from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message

    package_name = "nonebot_plugin_maibot_adapters"
    package = ModuleType(package_name)
    package.__path__ = [str(source)]
    sys.modules[package_name] = package
    with patch("nonebot.get_plugin_config", side_effect=lambda cls: cls(allow_group_list=[42])):
        router = importlib.import_module(f"{package_name}.router")
        adapter = importlib.import_module(f"{package_name}.bot")

    transport = FakeTransport()
    router.router.client = transport
    bots = {key: FakeBot(key) for key in ("100", "200")}
    event = GroupMessageEvent.model_validate({
        "time": 1800000000,
        "self_id": 100,
        "post_type": "message",
        "message_type": "group",
        "sub_type": "normal",
        "message_id": 123,
        "group_id": 42,
        "user_id": 7,
        "message": "synthetic text",
        "raw_message": "synthetic text",
        "font": 0,
        "sender": {"user_id": 7, "nickname": "synthetic user", "role": "member"},
    })
    try:
        await adapter.chat_bot.handle_message(event, bots["100"])
        assert len(transport.messages) == 1
        received = maim.MessageConverter.from_api_receive(transport.messages[0])
        assert str(received.message_info.group_info.group_id) == "42"
        assert str(received.message_info.user_info.user_id) == "7"
        assert str(received.message_info.message_id) == "123"
        assert received.message_segment.data == "synthetic text"
        metadata = received.message_info.additional_config or {}
        account_present = bool(metadata.get("account_id") or getattr(transport.messages[0], "account_id", None))

        await adapter.chat_bot.handle_message(event.model_copy(update={"group_id": 43}), bots["100"])
        blocked = len(transport.messages) == 1
        assert blocked, "adapter whitelist did not reject the other group"
        command = event.model_copy(update={"message": Message("/status"), "raw_message": "/status"})
        await adapter.chat_bot.handle_message(command, bots["100"])
        forwarded = transport.messages[-1].message_segment.data == "/status"

        requested = []

        def select_bot(self_id=None):
            requested.append(self_id)
            return bots[self_id or "100"]

        reply = maim.MessageBase(
            message_info=maim.BaseMessageInfo(
                platform="nonebot-qq",
                message_id="synthetic-reply",
                time=1800000001,
                group_info=maim.GroupInfo(platform="nonebot-qq", group_id="42"),
                user_info=maim.UserInfo(platform="nonebot-qq", user_id="7"),
                additional_config={"account_id": "200"},
            ),
            message_segment=maim.Seg(type="text", data="synthetic reply"),
        )
        with patch.object(router, "get_bot", side_effect=select_bot):
            outcome = await router.message_handler(maim.MessageConverter.to_api_send(reply, api_key="synthetic-key"))
        assert outcome == {"status": "success"}, outcome
        actual_bot = next(key for key, bot in bots.items() if bot.sent)
        return {
            "maim_message": version("maim-message"),
            "text_conversion": True,
            "whitelist_blocks_other_group": blocked,
            "command_forwarded": forwarded,
            "inbound_carries_account_id": account_present,
            "target_bot": "200",
            "actual_bot": actual_bot,
            "requested_bot_ids": requested,
            "echo_calls": len(transport.echo_calls),
            "network_tested": False,
            "plugin_lifecycle_tested": False,
        }
    finally:
        await adapter.chat_bot.client.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    source = parser.parse_args().checkout.resolve() / "nonebot_plugin_maibot_adapters"
    if not (source / "router.py").is_file():
        parser.error("an explicit upstream adapter checkout is required")
    report = asyncio.run(replay(source))
    print("ADAPTER_REPLAY_RESULT=" + json.dumps(report))
