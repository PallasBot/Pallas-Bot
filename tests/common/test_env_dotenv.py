import json
import os

from pydantic import BaseModel, Field

from src.common.config import dotenv as ed
from src.common.config import repo_settings as rs
from src.common.webui.plugin_config import config_from_env


def test_repo_env_raw_value_prefers_disk_over_environ(tmp_path, monkeypatch):
    webui = tmp_path / "webui.json"
    webui.write_text(json.dumps({"env": {"FOO": "from_file"}}), encoding="utf-8")
    monkeypatch.setattr(rs, "repo_webui_settings_path", lambda: webui)
    monkeypatch.setattr(rs, "repo_config_path", lambda: tmp_path / "missing.toml")
    monkeypatch.setattr(rs, "repo_env_path", lambda: tmp_path / "missing.env")
    monkeypatch.setattr(rs, "_REPO_ROOT", tmp_path)
    os.environ["FOO"] = "from_environ"
    try:
        assert ed.repo_env_raw_value("FOO") == "from_file"
    finally:
        os.environ.pop("FOO", None)


def test_upsert_env_dotenv_items_updates_webui_and_environ(tmp_path, monkeypatch):
    webui = tmp_path / "webui.json"
    monkeypatch.setattr(rs, "repo_webui_settings_path", lambda: webui)
    os.environ.pop("BAR", None)
    ed.upsert_env_dotenv_items({"BAR": "2"})
    data = json.loads(webui.read_text(encoding="utf-8"))
    assert data["env"]["BAR"] == "2"
    assert os.environ.get("BAR") == "2"
    os.environ.pop("BAR", None)


def test_config_from_env_reads_disk_after_environ_stale(tmp_path, monkeypatch):
    class Cfg(BaseModel):
        answer_threshold: int = Field(default=3)

    webui = tmp_path / "webui.json"
    webui.write_text(json.dumps({"env": {"ANSWER_THRESHOLD": "2"}}), encoding="utf-8")
    monkeypatch.setattr(rs, "repo_webui_settings_path", lambda: webui)
    monkeypatch.setattr(rs, "repo_config_path", lambda: tmp_path / "missing.toml")
    monkeypatch.setattr(rs, "repo_env_path", lambda: tmp_path / "missing.env")
    monkeypatch.setattr(rs, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(ed, "repo_settings_files_exist", lambda: True)
    os.environ["ANSWER_THRESHOLD"] = "3"
    try:
        cfg = config_from_env(Cfg)
        assert cfg.answer_threshold == 2
    finally:
        os.environ.pop("ANSWER_THRESHOLD", None)
