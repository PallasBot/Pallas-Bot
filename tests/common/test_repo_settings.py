import json
import os
from pathlib import Path

import pytest

from pallas.core.foundation.config import repo_settings as rs


@pytest.fixture(autouse=True)
def clear_repo_settings_cache():
    rs.clear_merged_repo_settings_cache()
    yield
    rs.clear_merged_repo_settings_cache()


def test_merged_prefers_webui_over_legacy_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    legacy = tmp_path / ".env"
    legacy.write_text("FOO=from_dotenv\n", encoding="utf-8")
    webui = tmp_path / "webui.json"
    webui.write_text(json.dumps({"env": {"FOO": "from_webui"}}), encoding="utf-8")
    monkeypatch.setattr(rs, "repo_config_path", lambda: tmp_path / "missing.toml")
    monkeypatch.setattr(rs, "repo_webui_settings_path", lambda: webui)
    monkeypatch.setattr(rs, "repo_env_path", lambda: legacy)
    monkeypatch.setattr(rs, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(rs, "nonebot_repo_dotenv_environment", lambda: "prod")
    assert rs.merged_repo_settings_upper()["FOO"] == "from_webui"


def test_merged_prefers_webui_over_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "pallas.toml"
    cfg.write_text('[env]\nFOO = "from_toml"\n', encoding="utf-8")
    webui = tmp_path / "webui.json"
    webui.write_text(json.dumps({"env": {"FOO": "from_webui"}}), encoding="utf-8")
    monkeypatch.setattr(rs, "repo_config_path", lambda: cfg)
    monkeypatch.setattr(rs, "repo_webui_settings_path", lambda: webui)
    monkeypatch.setattr(rs, "repo_env_path", lambda: tmp_path / "missing.env")
    monkeypatch.setattr(rs, "_REPO_ROOT", tmp_path)
    assert rs.merged_repo_settings_upper()["FOO"] == "from_webui"


def test_repo_env_raw_value_prefers_disk_over_environ(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    webui = tmp_path / "webui.json"
    webui.write_text(json.dumps({"env": {"FOO": "from_file"}}), encoding="utf-8")
    monkeypatch.setattr(rs, "repo_webui_settings_path", lambda: webui)
    monkeypatch.setattr(rs, "repo_config_path", lambda: tmp_path / "missing.toml")
    monkeypatch.setattr(rs, "repo_env_path", lambda: tmp_path / "missing.env")
    monkeypatch.setattr(rs, "_REPO_ROOT", tmp_path)
    os.environ["FOO"] = "from_environ"
    try:
        assert rs.repo_env_raw_value("FOO") == "from_file"
    finally:
        os.environ.pop("FOO", None)


def test_upsert_writes_webui_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    webui = tmp_path / "webui.json"
    monkeypatch.setattr(rs, "repo_webui_settings_path", lambda: webui)
    os.environ.pop("BAR", None)
    rs.upsert_repo_settings_items({"BAR": "2"})
    data = json.loads(webui.read_text(encoding="utf-8"))
    assert data["env"]["BAR"] == "2"
    assert os.environ.get("BAR") == "2"
    assert rs.repo_env_raw_value("BAR") == "2"
    os.environ.pop("BAR", None)


def test_merged_repo_settings_cache_by_disk_revision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    webui = tmp_path / "webui.json"
    webui.write_text(json.dumps({"env": {"FOO": "v1"}}), encoding="utf-8")
    monkeypatch.setattr(rs, "repo_webui_settings_path", lambda: webui)
    monkeypatch.setattr(rs, "repo_config_path", lambda: tmp_path / "missing.toml")
    monkeypatch.setattr(rs, "repo_env_path", lambda: tmp_path / "missing.env")
    monkeypatch.setattr(rs, "_REPO_ROOT", tmp_path)
    rs.clear_merged_repo_settings_cache()
    first = rs.merged_repo_settings_upper()
    second = rs.merged_repo_settings_upper()
    assert first is second
    webui.write_text(json.dumps({"env": {"FOO": "v2_extra"}}), encoding="utf-8")
    third = rs.merged_repo_settings_upper()
    assert third is not first
    assert third["FOO"] == "v2_extra"


def test_bootstrap_flatten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "pallas.toml"
    cfg.write_text(
        """
[bootstrap]
host = "127.0.0.1"
port = 9000

[bootstrap.mongo]
host = "mongo.internal"
db = "MyDb"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(rs, "repo_config_path", lambda: cfg)
    monkeypatch.setattr(rs, "repo_webui_settings_path", lambda: tmp_path / "w.json")
    monkeypatch.setattr(rs, "repo_env_path", lambda: tmp_path / "e.env")
    monkeypatch.setattr(rs, "_REPO_ROOT", tmp_path)
    merged = rs.merged_repo_settings_upper()
    assert merged["HOST"] == "127.0.0.1"
    assert merged["PORT"] == "9000"
    assert merged["MONGO_HOST"] == "mongo.internal"
    assert merged["MONGO_DB"] == "MyDb"


def test_get_invalidates_cache_when_webui_json_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import BaseModel, Field

    from pallas.console.webui.plugin_config import install_hot_reload_config

    class Cfg(BaseModel):
        flag: bool = Field(default=False)

    webui = tmp_path / "webui.json"
    webui.write_text('{"env": {"FLAG": "false"}}', encoding="utf-8")
    monkeypatch.setattr(rs, "repo_webui_settings_path", lambda: webui)
    monkeypatch.setattr(rs, "repo_config_path", lambda: tmp_path / "missing.toml")
    monkeypatch.setattr(rs, "repo_env_path", lambda: tmp_path / "missing.env")
    monkeypatch.setattr(rs, "_REPO_ROOT", tmp_path)

    handle = install_hot_reload_config(Cfg, config_module="test.shard_reload")
    assert handle.get().flag is False
    webui.write_text('{"env": {"FLAG": "true"}}', encoding="utf-8")
    import time

    time.sleep(0.05)
    assert handle.get().flag is True


def test_apply_repo_settings_does_not_override_environ(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "pallas.toml"
    cfg.write_text('[bootstrap]\nhost = "10.0.0.1"\n', encoding="utf-8")
    monkeypatch.setattr(rs, "repo_config_path", lambda: cfg)
    monkeypatch.setattr(rs, "repo_webui_settings_path", lambda: tmp_path / "w.json")
    monkeypatch.setattr(rs, "repo_env_path", lambda: tmp_path / "e.env")
    monkeypatch.setattr(rs, "_REPO_ROOT", tmp_path)
    os.environ["HOST"] = "docker-host"
    try:
        rs.apply_repo_settings_to_environ()
        assert os.environ["HOST"] == "docker-host"
    finally:
        os.environ.pop("HOST", None)
