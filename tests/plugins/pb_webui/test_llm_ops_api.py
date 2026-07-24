from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.pb_webui import extended_api as mod
from packages.pb_webui.config import Config


def _build_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(mod, "_check_pallas_write_token", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_require_pallas_token_configured", lambda *a, **k: None)
    monkeypatch.setattr(mod, "ensure_console_metrics_hooks", lambda: None)
    app = FastAPI()
    mod.register_extended_api(app, api_base="/pallas/api", plugin_config=Config())
    return TestClient(app)


def test_llm_history_stats_and_clear(monkeypatch) -> None:
    async def fake_stats(*, bot_id=None, group_id=None, limit=200):
        return {"available": True, "session_count": 2, "turn_total": 9}

    async def fake_clear(*, bot_id, group_id, user_id=None):
        return {"scope": "user", "bot_id": bot_id, "group_id": group_id, "user_id": user_id, "deleted": 3}

    monkeypatch.setattr("pallas.product.llm.session_ops.build_llm_history_stats", fake_stats)
    monkeypatch.setattr("pallas.product.llm.session_ops.clear_llm_history_session", fake_clear)

    client = _build_client(monkeypatch)
    stats = client.get("/pallas/api/common-config/llm/history/stats", params={"bot_id": 1})
    assert stats.status_code == 200, stats.text
    assert stats.json()["data"]["session_count"] == 2

    cleared = client.post(
        "/pallas/api/common-config/llm/history/session/clear",
        json={"bot_id": 1, "group_id": 2, "user_id": 3},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["data"]["deleted"] == 3


def test_llm_history_inject_and_compact(monkeypatch) -> None:
    async def fake_inject(**kwargs):
        return {"ok": True, **kwargs}

    async def fake_compact(**kwargs):
        return {"ok": True, "keep_messages": 16, **{k: kwargs[k] for k in ("bot_id", "group_id", "user_id")}}

    monkeypatch.setattr("pallas.product.llm.session_ops.inject_llm_history_message", fake_inject)
    monkeypatch.setattr("pallas.product.llm.session_ops.compact_llm_history_session", fake_compact)

    client = _build_client(monkeypatch)
    injected = client.post(
        "/pallas/api/common-config/llm/history/session/inject",
        json={"bot_id": 1, "group_id": 0, "user_id": 9, "content": "hello", "role": "user"},
    )
    assert injected.status_code == 200, injected.text
    assert injected.json()["data"]["ok"] is True

    compacted = client.post(
        "/pallas/api/common-config/llm/history/session/compact",
        json={"bot_id": 1, "group_id": 0, "user_id": 9, "summary": "聊过天气"},
    )
    assert compacted.status_code == 200, compacted.text
    assert compacted.json()["data"]["ok"] is True


def test_memory_ops_retrieve_clear_lifecycle(monkeypatch, tmp_path) -> None:
    async def fake_preview(bot_id, group_id, query, *, cfg=None):
        return {"query": query, "hits": [{"id": 7, "content": "银灰是我推"}], "prompt_text": "x", "hit_count": 1}

    async def fake_clear(*, bot_id, group_id=None, dry_run=False):
        return {"deleted": 4, "dry_run": dry_run, "bot_id": bot_id, "group_id": group_id}

    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("pallas.product.llm.memory.ops.preview_memory_retrieve", fake_preview)
    monkeypatch.setattr("pallas.product.llm.memory.ops.clear_memory_entries", fake_clear)

    client = _build_client(monkeypatch)
    retrieved = client.post(
        "/pallas/api/llm/conversation-kernel/memory/retrieve",
        json={"bot_id": 1, "group_id": 2, "query": "银灰"},
    )
    assert retrieved.status_code == 200, retrieved.text
    assert retrieved.json()["data"]["hit_count"] == 1

    cleared = client.post(
        "/pallas/api/llm/conversation-kernel/memory/clear",
        json={"bot_id": 1, "group_id": 2, "dry_run": True},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["data"]["deleted"] == 4

    life = client.post(
        "/pallas/api/llm/conversation-kernel/memory/lifecycle",
        json={"id": 7, "action": "reinforce", "entity_tags": ["银灰"]},
    )
    assert life.status_code == 200, life.text
    assert life.json()["data"]["weight"] >= 1.0


def test_memory_preferences_and_mid_term(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))

    async def fake_mid(*, bot_id, group_id=None, user_id=None, limit=50):
        return [{"bot_id": bot_id, "group_id": 0, "user_id": 1, "summary": "聊过猫", "created_at": 1}]

    monkeypatch.setattr("pallas.product.llm.memory.mid_term.list_mid_term_summaries", fake_mid)

    client = _build_client(monkeypatch)
    created = client.post(
        "/pallas/api/llm/conversation-kernel/memory/preferences",
        json={"bot_id": 1, "group_id": 0, "rule": "少提考试", "polarity": "dont"},
    )
    assert created.status_code == 200, created.text
    pref_id = created.json()["data"]["id"]

    listed = client.get("/pallas/api/llm/conversation-kernel/memory/preferences", params={"bot_id": 1})
    assert listed.status_code == 200, listed.text
    assert listed.json()["data"]["count"] == 1

    deleted = client.post(
        "/pallas/api/llm/conversation-kernel/memory/preferences/delete",
        json={"id": pref_id},
    )
    assert deleted.status_code == 200, deleted.text

    mid = client.get("/pallas/api/llm/conversation-kernel/mid-term", params={"bot_id": 1})
    assert mid.status_code == 200, mid.text
    assert mid.json()["data"]["items"][0]["summary"] == "聊过猫"


def test_session_memory_config_subset_get(monkeypatch) -> None:
    from pallas.product.llm.ops_config import LlmMemoryOpsConfig, LlmSessionOpsConfig

    monkeypatch.setattr(
        "pallas.product.llm.ops_config.get_llm_session_ops_config",
        lambda: LlmSessionOpsConfig(llm_session_user_window=22),
    )
    monkeypatch.setattr(
        "pallas.product.llm.ops_config.get_llm_memory_ops_config",
        lambda: LlmMemoryOpsConfig(llm_memory_rag_top_k=5),
    )
    client = _build_client(monkeypatch)
    session = client.get("/pallas/api/common-config/llm/session")
    assert session.status_code == 200, session.text
    assert session.json()["data"]["llm_session_user_window"] == 22

    memory = client.get("/pallas/api/common-config/llm/memory")
    assert memory.status_code == 200, memory.text
    assert memory.json()["data"]["llm_memory_rag_top_k"] == 5
