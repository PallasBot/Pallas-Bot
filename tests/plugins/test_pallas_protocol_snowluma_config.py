"""SnowLuma 扁平 OneBot 写入。"""

from pathlib import Path

from src.plugins.pallas_protocol.config_manager import AccountConfigManager
from src.plugins.pallas_protocol.snowluma_config import (
    extract_snowluma_webui_temp_password_from_log_lines,
    read_snowluma_runtime_webui_password,
    resolve_snowluma_webui_temp_password,
    sync_snowluma_onebot,
    sync_snowluma_runtime_json,
    update_snowluma_account_configs,
)


def test_sync_snowluma_onebot_flat_ws_client(tmp_path: Path) -> None:
    cfg = AccountConfigManager()
    account = {
        "account_data_dir": str(tmp_path),
        "qq": "3023094357",
        "ws_url": "ws://127.0.0.1:8088/onebot/v11/ws",
        "ws_name": "pallas",
        "ws_token": "tok",
    }

    def rq(a: dict) -> str:
        return str(a.get("qq", ""))

    sync_snowluma_onebot(cfg, account, rq)
    p = tmp_path / "config" / "onebot_3023094357.json"
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert '"wsClients"' in text
    assert "websocketClients" not in text
    assert "onebot/v11/ws" in text


def test_sync_snowluma_runtime_writes_webui_port(tmp_path: Path) -> None:
    account = {"account_data_dir": str(tmp_path), "qq": "30111222", "webui_port": 9155}
    sync_snowluma_runtime_json(account, webui_port_fallback_min=8000)
    data = (tmp_path / "config" / "runtime.json").read_text(encoding="utf-8")
    assert "9155" in data
    assert "webuiPort" in data


def test_update_snowluma_runtime_under_docker_keeps_host_webui_port(tmp_path: Path) -> None:
    cfg = AccountConfigManager()
    account = {
        "account_data_dir": str(tmp_path),
        "qq": "30111222",
        "webui_port": 6100,
        "snowluma_linux_docker": True,
    }

    def rq(a: dict) -> str:
        return str(a.get("qq", ""))

    update_snowluma_account_configs(cfg, account, {"runtime": {"webuiPort": 5099}}, rq)
    assert account["webui_port"] == 6100
    written = (tmp_path / "config" / "runtime.json").read_text(encoding="utf-8")
    assert "5099" in written


def test_update_snowluma_runtime_syncs_webui_port_when_not_docker(tmp_path: Path) -> None:
    cfg = AccountConfigManager()
    account = {"account_data_dir": str(tmp_path), "qq": "30111222", "webui_port": 6100}

    def rq(a: dict) -> str:
        return str(a.get("qq", ""))

    update_snowluma_account_configs(cfg, account, {"runtime": {"webuiPort": 7123}}, rq)
    assert account["webui_port"] == 7123


def test_read_snowluma_runtime_webui_password(tmp_path: Path) -> None:
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "runtime.json").write_text('{"webuiPort": 9000, "webuiPassword": "secret123"}', encoding="utf-8")
    assert read_snowluma_runtime_webui_password({"account_data_dir": str(tmp_path)}) == "secret123"


def test_extract_snowluma_webui_temp_password_from_logs() -> None:
    lines = [
        "12:34:56 INFO  [WebUI] 临时密码: a1b2c3d4e5f67890",
    ]
    assert extract_snowluma_webui_temp_password_from_log_lines(lines) == "a1b2c3d4e5f67890"


def test_extract_snowluma_initial_credentials_log_line() -> None:
    lines = [
        "20:18:13 INFO  [WebUI] initial credentials: user=admin password=eb99457d973c7764",
    ]
    assert extract_snowluma_webui_temp_password_from_log_lines(lines) == "eb99457d973c7764"


def test_extract_snowluma_prefers_latest_temp_password() -> None:
    lines = [
        "临时密码: 1111111111111111",
        "临时密码: 2222222222222222",
    ]
    assert extract_snowluma_webui_temp_password_from_log_lines(lines) == "2222222222222222"


def test_resolve_snowluma_prefers_logs_over_runtime_json(tmp_path: Path) -> None:
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "runtime.json").write_text('{"webuiPassword": "fromfile"}', encoding="utf-8")
    acc = {"account_data_dir": str(tmp_path)}
    logs = ["临时密码: deadbeefcafebabe"]
    assert resolve_snowluma_webui_temp_password(acc, logs) == "deadbeefcafebabe"


def test_resolve_snowluma_ignores_runtime_json_plaintext(tmp_path: Path) -> None:
    """SnowLuma 官方不在 runtime.json 存 WebUI 明文；解析仅依赖日志。"""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "runtime.json").write_text('{"webuiPassword": "onlyfile"}', encoding="utf-8")
    acc = {"account_data_dir": str(tmp_path)}
    assert resolve_snowluma_webui_temp_password(acc, []) is None
