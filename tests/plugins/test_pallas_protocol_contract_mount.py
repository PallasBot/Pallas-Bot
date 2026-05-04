"""协议管理页默认挂载路径（与账号 protocol_backend 解耦）。"""

from src.plugins.pallas_protocol.contract import (
    DEFAULT_PROTOCOL_WEB_MOUNT_SLUG,
    protocol_web_mount_path,
    resolve_public_mount_path,
)


def test_default_web_mount_uses_console_slug() -> None:
    assert DEFAULT_PROTOCOL_WEB_MOUNT_SLUG == "console"
    assert protocol_web_mount_path(implementation_slug="") == "/protocol/console"
    assert resolve_public_mount_path(path_override="", implementation_slug="") == "/protocol/console"


def test_custom_slug_override() -> None:
    assert protocol_web_mount_path(implementation_slug="napcat") == "/protocol/napcat"
