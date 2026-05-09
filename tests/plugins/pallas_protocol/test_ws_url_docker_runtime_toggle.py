from __future__ import annotations

import sys

import pytest

from src.plugins.pallas_protocol.linux_docker import apply_docker_runtime_toggle_to_ws_url


@pytest.fixture
def linux_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")


def test_toggle_no_change_when_mode_unchanged(linux_platform: None) -> None:
    assert (
        apply_docker_runtime_toggle_to_ws_url(
            "ws://127.0.0.1:8088/w",
            prev_docker_runtime=False,
            now_docker_runtime=False,
            config=object(),
        )
        is None
    )


def test_shell_to_docker_rewrites_localhost_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows 上 ``napcat_linux_docker`` 也可为真；切换时应把 127 等改写为 Docker Desktop 侧主机。"""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        "src.plugins.pallas_protocol.linux_docker.resolve_docker_onebot_host_from_config",
        lambda _c: "host.docker.internal",
    )
    out = apply_docker_runtime_toggle_to_ws_url(
        "ws://127.0.0.1:8088/onebot/v11/ws",
        prev_docker_runtime=False,
        now_docker_runtime=True,
        config=object(),
    )
    assert out == "ws://host.docker.internal:8088/onebot/v11/ws"


def test_shell_to_docker_rewrites_localhost(linux_platform: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.plugins.pallas_protocol.linux_docker.resolve_docker_onebot_host_from_config",
        lambda _c: "172.17.0.1",
    )
    out = apply_docker_runtime_toggle_to_ws_url(
        "ws://127.0.0.1:8088/onebot/v11/ws",
        prev_docker_runtime=False,
        now_docker_runtime=True,
        config=object(),
    )
    assert out == "ws://172.17.0.1:8088/onebot/v11/ws"


def test_docker_to_shell_rewrites_host_docker_internal_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        "src.plugins.pallas_protocol.linux_docker.resolve_docker_onebot_host_from_config",
        lambda _c: "host.docker.internal",
    )
    monkeypatch.setattr(
        "src.plugins.pallas_protocol.config.resolve_onebot_ws_settings",
        lambda _c: ("ws://127.0.0.1:9999/ignored", "pallas", ""),
    )
    out = apply_docker_runtime_toggle_to_ws_url(
        "ws://host.docker.internal:8088/onebot/v11/ws",
        prev_docker_runtime=True,
        now_docker_runtime=False,
        config=object(),
    )
    assert out == "ws://127.0.0.1:8088/onebot/v11/ws"


def test_docker_to_shell_rewrites_gateway_host(linux_platform: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.plugins.pallas_protocol.linux_docker.resolve_docker_onebot_host_from_config",
        lambda _c: "172.17.0.1",
    )
    monkeypatch.setattr(
        "src.plugins.pallas_protocol.config.resolve_onebot_ws_settings",
        lambda _c: ("ws://127.0.0.1:9999/ignored", "pallas", ""),
    )
    out = apply_docker_runtime_toggle_to_ws_url(
        "ws://172.17.0.1:8088/onebot/v11/ws",
        prev_docker_runtime=True,
        now_docker_runtime=False,
        config=object(),
    )
    assert out == "ws://127.0.0.1:8088/onebot/v11/ws"


def test_docker_to_shell_keeps_custom_lan_ip(linux_platform: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.plugins.pallas_protocol.linux_docker.resolve_docker_onebot_host_from_config",
        lambda _c: "172.17.0.1",
    )
    monkeypatch.setattr(
        "src.plugins.pallas_protocol.config.resolve_onebot_ws_settings",
        lambda _c: ("ws://127.0.0.1:8088/x", "pallas", ""),
    )
    assert (
        apply_docker_runtime_toggle_to_ws_url(
            "ws://192.168.50.10:8088/onebot/v11/ws",
            prev_docker_runtime=True,
            now_docker_runtime=False,
            config=object(),
        )
        is None
    )
