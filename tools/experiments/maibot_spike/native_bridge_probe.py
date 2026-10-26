"""Protocol self-check for the original bridge against the real legacy server.

Run with the isolated environment's Python:

    /tmp/opencode/maim068/venv/bin/python tools/experiments/maibot_spike/native_bridge_probe.py

It loads the real maim-message 0.6.8 Legacy ``MessageServer`` (no library
client, no MaiBot main program) and drives the original aiohttp bridge with
synthetic data only. It does not prove QQ delivery or a product integration.
"""

from __future__ import annotations

import asyncio
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "pallas" / "product" / "agent_bridge"))

from transport import BridgeScope, MaiBotBridge  # noqa: E402

EXPECTED_MAIM_VERSION = "0.6.8"
PLATFORM = "pallas-probe"
BOT_ID = 10001
GROUP_ID = 700001
USER_ID = 20002
ACTUAL_ID = 555000111


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def main() -> None:
    import maim_message
    from maim_message import BaseMessageInfo, GroupInfo, MessageBase, MessageServer, Seg, UserInfo

    if maim_message.__version__ != EXPECTED_MAIM_VERSION:
        raise RuntimeError(f"expected maim-message=={EXPECTED_MAIM_VERSION}, found {maim_message.__version__}")

    inbound_seen: dict = {}
    echo_seen: dict = {}

    def on_standard(message: dict) -> None:
        inbound_seen.update(message)

    def on_echo(message: dict) -> None:
        echo_seen.update(message)

    port = free_port()
    url = f"ws://127.0.0.1:{port}/ws"
    server = MessageServer(host="127.0.0.1", port=port, enable_token=False, path="/ws")
    server.register_message_handler(on_standard)
    server.register_custom_message_handler("message_id_echo", on_echo)
    server_task = asyncio.create_task(server.run(), name="maim-legacy-server")
    bridge: MaiBotBridge | None = None
    try:
        for _ in range(100):
            await asyncio.sleep(0.05)
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                continue

        replies: list[tuple[int, int, str]] = []

        async def send_reply(bot_id: int, group_id: int, text: str) -> int:
            replies.append((bot_id, group_id, text))
            return ACTUAL_ID

        scope = BridgeScope(enabled=True, bot_id=BOT_ID, allowed_group_ids=frozenset({GROUP_ID}), platform=PLATFORM)
        bridge = MaiBotBridge(scope, send_reply)
        await bridge.connect(url)
        await asyncio.sleep(0.3)

        event = {
            "time": int(time.time()),
            "self_id": BOT_ID,
            "post_type": "message",
            "message_type": "group",
            "sub_type": "normal",
            "message_id": 90001,
            "group_id": GROUP_ID,
            "user_id": USER_ID,
            "message": "synthetic inbound text",
            "raw_message": "synthetic inbound text",
            "font": 0,
            "sender": {"user_id": USER_ID, "nickname": "synthetic user", "role": "member"},
        }
        await bridge.forward_event(event, command_traffic=False)
        await asyncio.sleep(0.3)
        assert inbound_seen.get("message_segment", {}).get("data") == "synthetic inbound text", inbound_seen
        assert inbound_seen["message_info"]["additional_config"]["account_id"] == str(BOT_ID), inbound_seen
        assert inbound_seen["message_info"]["group_info"]["group_id"] == str(GROUP_ID), inbound_seen

        outbound = MessageBase(
            message_info=BaseMessageInfo(
                platform=PLATFORM,
                message_id="synthetic-outbound-1",
                time=time.time(),
                group_info=GroupInfo(platform=PLATFORM, group_id=str(GROUP_ID)),
                user_info=UserInfo(platform=PLATFORM, user_id=str(USER_ID)),
            ),
            message_segment=Seg(type="text", data="synthetic outbound reply"),
        )
        assert await server.send_message(outbound) is True
        for _ in range(100):
            await asyncio.sleep(0.05)
            if echo_seen:
                break
        assert replies == [(BOT_ID, GROUP_ID, "synthetic outbound reply")], replies
        assert echo_seen.get("message_type_name") == "message_id_echo", echo_seen
        content = echo_seen.get("content", {})
        assert content.get("echo") == "synthetic-outbound-1", content
        assert content.get("actual_id") == str(ACTUAL_ID), content
    finally:
        if bridge is not None:
            await bridge.close()
        await server.stop()
        await asyncio.wait_for(server_task, timeout=5)
    print("NATIVE_BRIDGE_PROBE=PASS; MaiBot main program was NOT started")


if __name__ == "__main__":
    asyncio.run(main())
