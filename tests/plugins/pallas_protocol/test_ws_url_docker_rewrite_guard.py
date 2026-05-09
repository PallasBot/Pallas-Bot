from __future__ import annotations

import pytest

from src.plugins.pallas_protocol.linux_docker import is_plain_ws_url, ws_url_host_should_rewrite_for_docker_bridge


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("", False),
        ("wss://127.0.0.1:8088/ws", False),
        ("ws://127.0.0.1:8088/onebot/v11/ws", True),
        ("ws://localhost:8088/ws", True),
        ("ws://host.docker.internal:8088/ws", True),
        ("ws://[::1]:8088/ws", True),
        ("ws://192.168.1.10:8088/ws", False),
        ("ws://10.0.0.5:8088/ws", False),
        ("ws://172.17.0.1:8088/ws", False),
        ("ws://nonebot:8088/ws", True),
    ],
)
def test_ws_url_host_should_rewrite_for_docker_bridge(url: str, expected: bool) -> None:
    assert ws_url_host_should_rewrite_for_docker_bridge(url) is expected


def test_is_plain_ws_url_scheme_only() -> None:
    assert is_plain_ws_url("ws://127.0.0.1:8088/x") is True
    assert is_plain_ws_url("wss://127.0.0.1:8088/x") is False
    assert is_plain_ws_url("") is False
