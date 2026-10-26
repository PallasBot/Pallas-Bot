"""maim-message 0.6.8 loopback-only protocol probe.

Run from its isolated environment, for example:
    /tmp/opencode/maim068/venv/bin/python tools/experiments/maibot_spike/message_protocol.py

The probe uses synthetic data and demonstrates the message package only; it is
not a MaiBot product integration or a QQ delivery test.

The observed exit timeout is consistent with maim-message 0.6.8's
``LogQueueProcessor._process_batch`` awaiting ``asyncio.to_thread(self._queue.get)``
(``maim_message/log_queue.py:293``): ``stop()`` at line 338 cancels the
coroutine but cannot interrupt its blocking queue read in the default executor.
The parent test reports failure if the process does not exit naturally; this
probe does not force process exit or patch the dependency.
"""

from __future__ import annotations

import asyncio
import json
import socket
import sys
import threading
import time


def _port_on_loopback() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _assert_identity(message, *, message_id: str, text: str) -> None:
    info = message.message_info
    sender = getattr(info, "sender_info", None)
    group = getattr(info, "group_info", None) or (sender.group_info if sender else None)
    user = getattr(info, "user_info", None) or (sender.user_info if sender else None)
    assert info.message_id == message_id
    assert info.additional_config == {"account_id": "synthetic-account", "scope": "probe"}
    assert group.group_id == "synthetic-group"
    assert user.user_id == "synthetic-user"
    assert message.message_segment.type == "text"
    assert message.message_segment.data == text


async def _run_loopback() -> None:
    try:
        import maim_message
        import maim_message.client as maim_client
        import maim_message.message as maim_api
        import maim_message.server as maim_server
    except ModuleNotFoundError as exc:
        if exc.name == "maim_message":
            print(
                "maim-message is missing; install maim-message==0.6.8 in an isolated venv, "
                "then run this script with that venv's Python (see its module docstring).",
                file=sys.stderr,
            )
            raise SystemExit(2) from exc
        raise

    if maim_message.__version__ != "0.6.8":
        raise RuntimeError(f"expected maim-message==0.6.8, found {maim_message.__version__}")

    legacy = maim_message.MessageBase(
        message_info=maim_message.BaseMessageInfo(
            platform="qq",
            message_id="synthetic-message-id",
            time=1_800_000_000.0,
            group_info=maim_message.GroupInfo(platform="qq", group_id="synthetic-group"),
            user_info=maim_message.UserInfo(platform="qq", user_id="synthetic-user"),
            additional_config={"account_id": "synthetic-account", "scope": "probe"},
        ),
        message_segment=maim_message.Seg(type="text", data="synthetic inbound text"),
    )
    legacy = maim_message.MessageBase.from_dict(json.loads(json.dumps(legacy.to_dict(), ensure_ascii=False)))
    api = maim_message.MessageConverter.to_api_receive(legacy, api_key="synthetic-account")
    api = maim_api.APIMessageBase.from_dict(json.loads(json.dumps(api.to_dict(), ensure_ascii=False)))
    legacy_back = maim_message.MessageConverter.from_api_receive(api)
    _assert_identity(legacy_back, message_id="synthetic-message-id", text="synthetic inbound text")
    assert api.message_info.sender_info.group_info.group_id == "synthetic-group"
    assert api.message_info.sender_info.user_info.user_id == "synthetic-user"
    print("Legacy -> API -> Legacy serialization: PASS")

    host = "127.0.0.1"
    port = _port_on_loopback()
    inbound = asyncio.Event()
    outbound = asyncio.Event()
    received_by_server: dict[str, object] = {}
    received_by_client: dict[str, object] = {}

    async def authenticate(metadata: dict) -> bool:
        return metadata.get("api_key") == "synthetic-account"

    async def extract_account(metadata: dict) -> str:
        return str(metadata.get("api_key") or "")

    async def server_on_message(message, _metadata: dict) -> None:
        print("server on_message callback", flush=True)
        received_by_server["payload"] = message.to_dict()
        received_by_server["message"] = message
        inbound.set()

    async def client_on_message(message, _metadata: dict) -> None:
        print("client on_message callback", flush=True)
        received_by_client["payload"] = message.to_dict()
        received_by_client["message"] = message
        outbound.set()

    server = maim_server.WebSocketServer(
        maim_server.ServerConfig(
            host=host,
            port=port,
            path="/ws",
            on_auth=authenticate,
            on_auth_extract_user=extract_account,
            on_message=server_on_message,
            enable_message_cache=False,
            enable_connection_log=False,
            enable_message_log=False,
        )
    )
    client = maim_client.WebSocketClient(
        maim_client.ClientConfig(
            url=f"ws://{host}:{port}/ws",
            api_key="synthetic-account",
            platform="qq",
            on_message=client_on_message,
            auto_reconnect=False,
            enable_message_cache=False,
            enable_connection_log=False,
            enable_message_log=False,
        )
    )
    server_attempted = False
    client_attempted = False
    try:
        server_attempted = True
        await asyncio.wait_for(server.start(), timeout=8)
        client_attempted = True
        await asyncio.wait_for(client.start(), timeout=8)
        assert await asyncio.wait_for(client.connect(), timeout=12), "client could not connect to loopback server"

        client_sent = await asyncio.wait_for(client.send_message(api), timeout=5)
        assert client_sent is True
        print("client send result:", json.dumps(client_sent))
        await asyncio.wait_for(inbound.wait(), timeout=5)
        received = received_by_server["message"]
        _assert_identity(received, message_id="synthetic-message-id", text="synthetic inbound text")
        assert received.get_api_key() == "synthetic-account"
        assert received.get_platform() == "qq"

        reply = maim_api.APIMessageBase(
            message_info=maim_api.BaseMessageInfo(
                platform="qq",
                message_id="synthetic-reply-id",
                time=time.time(),
                receiver_info=maim_api.ReceiverInfo(
                    group_info=maim_api.GroupInfo(platform="qq", group_id="synthetic-group"),
                    user_info=maim_api.UserInfo(platform="qq", user_id="synthetic-user"),
                ),
                additional_config={"account_id": "synthetic-account", "scope": "probe"},
            ),
            message_segment=maim_api.Seg(type="text", data="synthetic outbound text"),
            message_dim=maim_api.MessageDim(api_key="synthetic-account", platform="qq"),
        )
        send_results = await asyncio.wait_for(server.send_message(reply), timeout=5)
        assert send_results, f"server send returned no connection results: {send_results}"
        assert all(send_results.values()), f"server send failed: {send_results}"
        await asyncio.wait_for(outbound.wait(), timeout=5)
        response = received_by_client["message"]
        assert response.message_info.message_id == "synthetic-reply-id"
        assert response.message_info.additional_config == {"account_id": "synthetic-account", "scope": "probe"}
        assert response.message_info.receiver_info.group_info.group_id == "synthetic-group"
        assert response.message_info.receiver_info.user_info.user_id == "synthetic-user"
        assert response.message_segment.data == "synthetic outbound text"
        assert response.get_api_key() == "synthetic-account"
        assert response.get_platform() == "qq"

        print("client -> server payload:", json.dumps(received_by_server["payload"], ensure_ascii=False))
        print("server -> client payload:", json.dumps(received_by_client["payload"], ensure_ascii=False))
        print("server send results:", json.dumps(send_results, ensure_ascii=False))
    finally:
        try:
            if client_attempted:
                await asyncio.wait_for(client.stop(), timeout=10)
        finally:
            if server_attempted:
                await asyncio.wait_for(server.stop(), timeout=10)
        current = asyncio.current_task()
        pending = [task.get_name() for task in asyncio.all_tasks() if task is not current and not task.done()]
        threads = [(thread.name, thread.daemon) for thread in threading.enumerate()]
        print(f"shutdown snapshot: pending_tasks={pending}, threads={threads}", flush=True)


def main() -> None:
    try:
        asyncio.run(_run_loopback())
    except BaseException as exc:
        print(f"PROTOCOL PROBE FAILED: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        raise
    print("PROTOCOL PROBE PASSED; not a MaiBot product integration or a QQ delivery test.")


if __name__ == "__main__":
    main()
