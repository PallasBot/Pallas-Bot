"""离线库内 Bot 账号应能从协议/缓存补全 nickname。"""

from __future__ import annotations

from packages.pb_webui.social_api import (
    _fill_bot_profile_nicknames_for_accounts,
    _merge_protocol_snap_display_names,
)


def test_merge_protocol_snap_fills_offline_display_name(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.core.foundation.db.pallas_console_data.pallas_protocol_snapshot",
        lambda: {
            "accounts": [
                {"qq": "10001", "display_name": "小牛"},
                {"id": "10002", "nickname": "外置牛"},
            ]
        },
    )
    out: dict = {"10001": {"nickname": "", "user_id": 10001}}
    _merge_protocol_snap_display_names(out)
    assert out["10001"]["nickname"] == "小牛"
    assert out["10002"]["nickname"] == "外置牛"
    assert out["10002"].get("online") is False


def test_fill_db_accounts_uses_cached_login_nickname(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.product.persona.self_identity.resolve_cached_login_nickname",
        lambda bot_id: {10001: "库内牛", 10002: ""}.get(int(bot_id), ""),
    )
    out: dict = {}
    _fill_bot_profile_nicknames_for_accounts(out, [10001, 10002, 0])
    assert out["10001"]["nickname"] == "库内牛"
    assert "10002" not in out


def test_fill_db_accounts_keeps_existing_nickname(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.product.persona.self_identity.resolve_cached_login_nickname",
        lambda bot_id: "覆盖我",
    )
    out = {"10001": {"nickname": "已有", "user_id": 10001}}
    _fill_bot_profile_nicknames_for_accounts(out, [10001])
    assert out["10001"]["nickname"] == "已有"
