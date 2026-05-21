import os

from pydantic import BaseModel, Field

from src.common.config import dotenv as ed
from src.common.webui.plugin_config import config_from_env


def test_repo_env_raw_value_prefers_dotenv_over_environ(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=from_file\n", encoding="utf-8")
    monkeypatch.setattr(ed, "repo_env_path", lambda: env_file)
    os.environ["FOO"] = "from_environ"
    try:
        assert ed.repo_env_raw_value("FOO") == "from_file"
    finally:
        os.environ.pop("FOO", None)


def test_upsert_env_dotenv_items_updates_environ(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(ed, "repo_env_path", lambda: env_file)
    os.environ.pop("BAR", None)
    ed.upsert_env_dotenv_items({"BAR": "2"})
    assert "BAR=2" in env_file.read_text(encoding="utf-8")
    assert os.environ.get("BAR") == "2"
    os.environ.pop("BAR", None)


def test_config_from_env_reads_dotenv_after_environ_stale(tmp_path, monkeypatch):
    class Cfg(BaseModel):
        answer_threshold: int = Field(default=3)

    env_file = tmp_path / ".env"
    env_file.write_text("ANSWER_THRESHOLD=2\n", encoding="utf-8")
    monkeypatch.setattr(ed, "repo_env_path", lambda: env_file)
    monkeypatch.setattr(ed, "repo_layered_dotenv_files_exist", lambda: True)
    os.environ["ANSWER_THRESHOLD"] = "3"
    try:
        cfg = config_from_env(Cfg)
        assert cfg.answer_threshold == 2
    finally:
        os.environ.pop("ANSWER_THRESHOLD", None)
