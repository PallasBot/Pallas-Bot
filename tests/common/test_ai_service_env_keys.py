from __future__ import annotations

import json

from pallas.core.foundation.config.ai_service_env import is_misplaced_ai_env_key
from pallas.core.foundation.config.repo_settings import (
    apply_repo_settings_to_environ,
    purge_misplaced_ai_env_keys_from_webui,
    upsert_repo_settings_items,
)


def test_upsert_repo_settings_skips_ai_runtime_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "pallas.core.foundation.config.repo_settings.repo_webui_settings_path",
        lambda: tmp_path / "webui.json",
    )
    upsert_repo_settings_items({
        "LLM_CHAT_ENABLED": "true",
        "LLM_NUM_GPU": "12",
        "OLLAMA_CHAT_ENDPOINT": "/api/ollama/chat",
    })
    data = json.loads((tmp_path / "webui.json").read_text(encoding="utf-8"))
    env = data["env"]
    assert env["LLM_CHAT_ENABLED"] == "true"
    assert "LLM_NUM_GPU" not in env
    assert "OLLAMA_CHAT_ENDPOINT" not in env


def test_apply_repo_settings_skips_ai_runtime_keys(tmp_path, monkeypatch):
    webui = tmp_path / "webui.json"
    webui.write_text(
        json.dumps({
            "env": {
                "LLM_CHAT_ENABLED": "true",
                "LLM_NUM_GPU": "12",
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "pallas.core.foundation.config.repo_settings.repo_webui_settings_path",
        lambda: webui,
    )
    monkeypatch.delenv("LLM_NUM_GPU", raising=False)
    monkeypatch.delenv("LLM_CHAT_ENABLED", raising=False)
    apply_repo_settings_to_environ()
    assert "LLM_NUM_GPU" not in __import__("os").environ
    assert __import__("os").environ.get("LLM_CHAT_ENABLED") == "true"


def test_purge_misplaced_ai_env_keys_from_webui(tmp_path, monkeypatch):
    webui = tmp_path / "webui.json"
    webui.write_text(
        json.dumps({
            "env": {
                "LLM_CHAT_ENABLED": "true",
                "LLM_NUM_GPU": "12",
                "OLLAMA_MODEL_ENDPOINT": "/api/ollama/model",
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "pallas.core.foundation.config.repo_settings.repo_webui_settings_path",
        lambda: webui,
    )
    removed = purge_misplaced_ai_env_keys_from_webui()
    assert set(removed) == {"LLM_NUM_GPU", "OLLAMA_MODEL_ENDPOINT"}
    data = json.loads(webui.read_text(encoding="utf-8"))
    assert "LLM_NUM_GPU" not in data["env"]
    assert data["env"]["LLM_CHAT_ENABLED"] == "true"


def test_is_misplaced_ai_env_key():
    assert is_misplaced_ai_env_key("LLM_NUM_GPU")
    assert is_misplaced_ai_env_key("ollama_num_gpu")
    assert not is_misplaced_ai_env_key("LLM_CHAT_ENABLED")
