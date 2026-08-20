"""console_login 长期 API Key：签发 / 校验 / 吊销 / 列表。"""

from pallas.console.webui.console_login import (
    API_KEY_PREFIX,
    issue_api_key,
    list_api_keys,
    revoke_api_key,
    verify_api_key,
)


def test_issue_and_verify_api_key(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("pallas.console.webui.console_login.console_auth_dir", lambda: tmp_path)

    secret, key_id = issue_api_key(label="agent-a")
    assert secret.startswith(API_KEY_PREFIX)
    assert key_id

    assert verify_api_key(secret) is True
    assert verify_api_key("wrong") is False
    assert verify_api_key(f"{API_KEY_PREFIX}xxxyyy") is False

    rows = list_api_keys()
    assert rows
    assert rows[0]["id"] == key_id
    assert rows[0]["label"] == "agent-a"
    assert "hash" not in rows[0]
    assert "secret" not in rows[0]


def test_revoke_api_key(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("pallas.console.webui.console_login.console_auth_dir", lambda: tmp_path)

    secret, key_id = issue_api_key()
    assert revoke_api_key(key_id) is True
    assert verify_api_key(secret) is False
    assert revoke_api_key(key_id) is False


def test_verify_api_key_updates_last_used(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("pallas.console.webui.console_login.console_auth_dir", lambda: tmp_path)

    secret, _ = issue_api_key()
    assert verify_api_key(secret) is True
    rows = list_api_keys()
    assert rows[0]["last_used_at"]
