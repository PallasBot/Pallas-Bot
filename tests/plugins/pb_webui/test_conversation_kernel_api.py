from __future__ import annotations

from types import SimpleNamespace

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


def test_conversation_kernel_status_api_returns_rollout_flags(monkeypatch) -> None:
    def fake_status():
        return {
            "feature_level": "kernel_v1",
            "llm_chat_enabled": True,
            "feedback_bias_active": False,
            "runtime_state_summary_active": True,
            "memory_policy": {
                "read_session": True,
                "runtime_state_summary_enabled": True,
            },
        }

    monkeypatch.setattr(
        mod,
        "build_conversation_kernel_status",
        fake_status,
        raising=False,
    )

    client = _build_client(monkeypatch)
    response = client.get("/pallas/api/llm/conversation-kernel/status")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["feature_level"] == "kernel_v1"
    assert payload["data"]["feedback_bias_active"] is False
    assert payload["data"]["runtime_state_summary_active"] is True


def test_conversation_kernel_traces_api_filters_decision_rows(monkeypatch) -> None:
    def fake_traces(*, group_id, bot_id, kind, limit):
        assert group_id == 123
        assert bot_id is None
        assert kind == "decision"
        assert limit == 10
        return [
            {
                "kind": "conversation_decision_trace",
                "group_id": 123,
                "action": "reply",
            }
        ]

    monkeypatch.setattr(
        mod,
        "list_recent_conversation_traces",
        fake_traces,
        raising=False,
    )

    client = _build_client(monkeypatch)
    response = client.get(
        "/pallas/api/llm/conversation-kernel/traces",
        params={"group_id": 123, "kind": "decision", "limit": 10},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["items"][0]["action"] == "reply"
    assert payload["data"]["limit"] == 10


def test_conversation_kernel_memory_api_returns_entries(monkeypatch) -> None:
    async def fake_list_memory_entries(bot_id, group_id, query, limit):
        assert bot_id == 10001
        assert group_id == 123
        assert query == "银灰"
        assert limit == 20
        return [{"id": 1, "bot_id": 10001, "group_id": 123, "content": "银灰是我推", "source": "teach"}]

    monkeypatch.setattr(mod, "list_memory_entries", fake_list_memory_entries, raising=False)

    client = _build_client(monkeypatch)
    response = client.get(
        "/pallas/api/llm/conversation-kernel/memory",
        params={"bot_id": 10001, "group_id": 123, "query": "银灰", "limit": 20},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["items"][0]["content"] == "银灰是我推"
    assert payload["data"]["count"] == 1


def test_conversation_kernel_knowledge_sources_api_returns_items(monkeypatch) -> None:
    class _Decl:
        title = "Bot FAQ"
        description = "常见问答"
        scope = SimpleNamespace(value="global")
        retrieval_mode = SimpleNamespace(value="prompt_inject")
        default = True
        chunks = [1, 2]

    monkeypatch.setattr(
        mod,
        "list_active_knowledge_sources",
        lambda: [
            SimpleNamespace(
                source_id="pallas.bot_faq",
                decl=_Decl(),
                origin=SimpleNamespace(value="builtin"),
                plugin_name="pallas",
                plugin_title="Pallas",
            )
        ],
        raising=False,
    )

    client = _build_client(monkeypatch)
    response = client.get("/pallas/api/llm/conversation-kernel/knowledge-sources")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["items"][0]["source_id"] == "pallas.bot_faq"
    assert payload["data"]["items"][0]["chunk_count"] == 2
