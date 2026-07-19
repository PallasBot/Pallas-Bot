"""AI Runtime 安装状态、受控 clone、连接写回。"""

from __future__ import annotations

import json

import pytest

from pallas.console.cli import ai_install
from pallas.console.webui import ai_install_writeback as writeback


def test_ai_install_status_shape(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("PALLAS_AI_ROOT", str(tmp_path / "missing"))
    monkeypatch.setattr(ai_install, "resolve_ai_repo_root", lambda: None)
    st = ai_install.ai_install_status()
    assert st["detected"] is False
    assert st["git_url"].endswith("Pallas-Bot-AI.git")
    assert "docker-compose.llm.yml" in st["docker_hint"]
    assert "docker-compose.full.yml" in st["docker_hint"]
    assert "--profile ai" not in st["docker_hint"]
    assert st["clone_target"] == str((tmp_path / "missing").resolve())


def test_clone_ai_repo_rejects_foreign_path(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    allowed = tmp_path / "Pallas-Bot-AI"
    monkeypatch.setattr(ai_install, "default_ai_clone_target", lambda: allowed.resolve())
    with pytest.raises(ValueError, match="受控路径"):
        ai_install.clone_ai_repo(target=tmp_path / "other")


def test_clone_ai_repo_rejects_existing(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    allowed = tmp_path / "Pallas-Bot-AI"
    allowed.mkdir()
    (allowed / "scripts").mkdir()
    (allowed / "scripts" / "ai_bootstrap.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(ai_install, "default_ai_clone_target", lambda: allowed.resolve())
    with pytest.raises(FileExistsError):
        ai_install.clone_ai_repo()


def test_writeback_ai_extension_creates_missing_file(tmp_path) -> None:
    path = tmp_path / "ai_extension.json"
    assert writeback.writeback_ai_extension_if_empty(path=path) is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["base_url"] == "http://127.0.0.1:9099"
    assert data["api_prefix"] == "/api"


def test_writeback_ai_extension_fills_empty_base_url(tmp_path) -> None:
    path = tmp_path / "ai_extension.json"
    path.write_text(
        json.dumps({"base_url": "", "token": "keep-me", "api_prefix": "/api"}, ensure_ascii=False),
        encoding="utf-8",
    )
    assert writeback.writeback_ai_extension_if_empty(path=path) is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["base_url"] == "http://127.0.0.1:9099"
    assert data["token"] == "keep-me"


def test_writeback_ai_extension_preserves_custom_base_url(tmp_path) -> None:
    path = tmp_path / "ai_extension.json"
    path.write_text(
        json.dumps({"base_url": "http://10.0.0.2:9199", "token": "x"}, ensure_ascii=False),
        encoding="utf-8",
    )
    assert writeback.writeback_ai_extension_if_empty(path=path) is False
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["base_url"] == "http://10.0.0.2:9199"


def test_writeback_ai_server_only_when_both_missing(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    webui = tmp_path / "webui.json"
    webui.write_text(json.dumps({"env": {}}, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        "pallas.core.foundation.config.repo_settings.repo_webui_settings_path",
        lambda: webui,
    )
    # clear cache that may have loaded other paths
    from pallas.core.foundation.config.repo_settings import clear_merged_repo_settings_cache

    clear_merged_repo_settings_cache()
    assert writeback.writeback_ai_server_if_missing() is True
    env = json.loads(webui.read_text(encoding="utf-8"))["env"]
    assert env["AI_SERVER_HOST"] == "127.0.0.1"
    assert env["AI_SERVER_PORT"] == "9099"

    assert writeback.writeback_ai_server_if_missing() is False


def test_writeback_ai_server_skips_when_any_key_exists(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    webui = tmp_path / "webui.json"
    webui.write_text(
        json.dumps({"env": {"AI_SERVER_HOST": "10.0.0.9"}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "pallas.core.foundation.config.repo_settings.repo_webui_settings_path",
        lambda: webui,
    )
    from pallas.core.foundation.config.repo_settings import clear_merged_repo_settings_cache

    clear_merged_repo_settings_cache()
    assert writeback.writeback_ai_server_if_missing() is False
    env = json.loads(webui.read_text(encoding="utf-8"))["env"]
    assert env == {"AI_SERVER_HOST": "10.0.0.9"}


def test_apply_ai_install_connection_writeback(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    ext = tmp_path / "ai_extension.json"
    webui = tmp_path / "webui.json"
    webui.write_text(json.dumps({"env": {}}, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        "pallas.core.foundation.config.repo_settings.repo_webui_settings_path",
        lambda: webui,
    )
    from pallas.core.foundation.config.repo_settings import clear_merged_repo_settings_cache

    clear_merged_repo_settings_cache()
    flags = writeback.apply_ai_install_connection_writeback(extension_path=ext)
    assert flags == {"wrote_ai_extension": True, "wrote_ai_server": True}
    assert ext.is_file()


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("http://127.0.0.1:9099", ("127.0.0.1", "9099")),
        ("https://ai.example.com", ("ai.example.com", "443")),
        ("http://pallasbot-ai", ("pallasbot-ai", "9099")),
        ("10.0.0.2:9199", ("10.0.0.2", "9199")),
        ("", None),
    ],
)
def test_parse_ai_server_from_base_url(base_url: str, expected: tuple[str, str] | None) -> None:
    assert writeback.parse_ai_server_from_base_url(base_url) == expected


def test_sync_ai_server_from_extension_base_url(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    webui = tmp_path / "webui.json"
    webui.write_text(json.dumps({"env": {}}, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        "pallas.core.foundation.config.repo_settings.repo_webui_settings_path",
        lambda: webui,
    )
    from pallas.core.foundation.config.repo_settings import clear_merged_repo_settings_cache

    clear_merged_repo_settings_cache()
    assert writeback.sync_ai_server_from_extension_base_url("http://pallasbot-ai:9099") is True
    env = json.loads(webui.read_text(encoding="utf-8"))["env"]
    assert env["AI_SERVER_HOST"] == "pallasbot-ai"
    assert env["AI_SERVER_PORT"] == "9099"


def test_sync_extension_base_url_from_ai_server_preserves_token(tmp_path) -> None:
    path = tmp_path / "ai_extension.json"
    path.write_text(
        json.dumps(
            {
                "base_url": "http://127.0.0.1:9099",
                "token": "keep",
                "api_prefix": "/api",
                "health_paths": ["/health"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert writeback.sync_extension_base_url_from_ai_server("pallasbot-ai", 9099, path=path) is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["base_url"] == "http://pallasbot-ai:9099"
    assert data["token"] == "keep"
    assert writeback.sync_extension_base_url_from_ai_server("pallasbot-ai", 9099, path=path) is False
