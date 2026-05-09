from __future__ import annotations

import json

from src.plugins.pallas_protocol.config_manager import AccountConfigManager


def test_sync_onebot_sets_placeholder_only_when_no_url_anywhere(tmp_path) -> None:
    """账号与 onebot 均无 url 时才写占位 ws。"""
    ad = tmp_path / "inst"
    cfg_dir = ad / "config"
    cfg_dir.mkdir(parents=True)
    onebot = cfg_dir / "onebot11_123456.json"
    onebot.write_text(
        json.dumps({"network": {"websocketClients": [{"name": "x"}]}}, ensure_ascii=False),
        encoding="utf-8",
    )
    mgr = AccountConfigManager()
    account: dict = {
        "account_data_dir": str(ad),
        "qq": "123456",
        "ws_url": "",
        "ws_name": "pallas",
        "ws_token": "",
    }
    mgr.sync_onebot(account, lambda a: "123456")
    data = json.loads(onebot.read_text(encoding="utf-8"))
    url = data["network"]["websocketClients"][0]["url"]
    assert url == "ws://127.0.0.1:8088/onebot/v11/ws"


def test_sync_onebot_keeps_existing_url_when_account_ws_empty(tmp_path) -> None:
    """账号 ws_url 为空且 onebot 已有可达 url 时不应改成 127.0.0.1。"""
    ad = tmp_path / "inst2"
    cfg_dir = ad / "config"
    cfg_dir.mkdir(parents=True)
    keep = "ws://172.17.0.1:9999/onebot/v11/ws"
    onebot = cfg_dir / "onebot11_123456.json"
    onebot.write_text(
        json.dumps(
            {"network": {"websocketClients": [{"url": keep, "name": "x"}]}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    mgr = AccountConfigManager()
    account: dict = {
        "account_data_dir": str(ad),
        "qq": "123456",
        "ws_url": "",
        "ws_name": "pallas",
        "ws_token": "",
    }
    mgr.sync_onebot(account, lambda a: "123456")
    data = json.loads(onebot.read_text(encoding="utf-8"))
    assert data["network"]["websocketClients"][0]["url"] == keep
