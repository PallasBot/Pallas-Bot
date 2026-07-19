from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.pb_webui import extended_api as mod
from packages.pb_webui.config import Config
from pallas.product.llm.session_store import LlmChatTurn


def _build_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(mod, "_check_pallas_write_token", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_require_pallas_token_configured", lambda *a, **k: None)
    monkeypatch.setattr(mod, "ensure_console_metrics_hooks", lambda: None)
    app = FastAPI()
    mod.register_extended_api(app, api_base="/pallas/api", plugin_config=Config())
    return TestClient(app)


def test_llm_history_sessions_get(monkeypatch) -> None:
    async def fake_list_sessions(*, bot_id=None, group_id=None, user_id=None, limit=50):
        assert bot_id == 10001
        assert group_id == 20002
        assert user_id is None
        assert limit == 20
        return [
            {
                "session_key": "10001:20002:30003",
                "bot_id": 10001,
                "group_id": 20002,
                "user_id": 30003,
                "turn_count": 6,
                "first_created_at": 1718700000,
                "last_created_at": 1718700123,
                "last_role": "assistant",
                "last_content": "你好，我在。",
            }
        ]

    monkeypatch.setattr(
        "pallas.product.llm.session_store.list_llm_history_sessions",
        fake_list_sessions,
    )

    client = _build_client(monkeypatch)
    response = client.get(
        "/pallas/api/common-config/llm/history/sessions",
        params={"bot_id": 10001, "group_id": 20002, "limit": 20},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["items"][0]["session_key"] == "10001:20002:30003"
    assert payload["data"]["items"][0]["turn_count"] == 6


def test_llm_history_session_detail_get(monkeypatch) -> None:
    async def fake_session_detail(*, bot_id, group_id, user_id, limit=100):
        assert bot_id == 10001
        assert group_id == 20002
        assert user_id == 30003
        assert limit == 12
        return {
            "session": {
                "session_key": "10001:20002:30003",
                "bot_id": 10001,
                "group_id": 20002,
                "user_id": 30003,
                "turn_count": 3,
                "first_created_at": 1718700000,
                "last_created_at": 1718700123,
                "last_role": "assistant",
                "last_content": "你好，我在。",
            },
            "turns": [
                LlmChatTurn(role="user", content="你好", user_id=30003, created_at=1718700000).model_dump(),
                LlmChatTurn(
                    role="assistant", content="你好，我在。", user_id=30003, created_at=1718700002
                ).model_dump(),
            ],
            "behavior_runs": [
                {
                    "request_id": "req-1",
                    "scene": "provocation",
                    "selected_actions": ["light_tease_and_close"],
                    "auto_feedback_payload": {
                        "source": "ambient",
                        "matched_signal": "engaged_token",
                    },
                    "manual_labels": ["像人"],
                }
            ],
        }

    monkeypatch.setattr(
        "pallas.product.llm.session_store.get_llm_history_session_detail",
        fake_session_detail,
    )

    client = _build_client(monkeypatch)
    response = client.get(
        "/pallas/api/common-config/llm/history/session",
        params={"bot_id": 10001, "group_id": 20002, "user_id": 30003, "limit": 12},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["session"]["user_id"] == 30003
    assert payload["data"]["turns"][0]["content"] == "你好"
    assert payload["data"]["behavior_runs"][0]["request_id"] == "req-1"
    assert payload["data"]["behavior_runs"][0]["auto_feedback_payload"]["source"] == "ambient"


def test_llm_behavior_runs_get(monkeypatch) -> None:
    def fake_runs(*, limit):
        assert limit == 20
        return [
            {
                "request_id": "req-1",
                "group_id": 20002,
                "scene": "provocation",
                "final_outcome": "engaged",
                "disabled": False,
            },
            {
                "request_id": "req-2",
                "group_id": 20003,
                "scene": "smalltalk",
                "final_outcome": "ignored",
                "disabled": True,
            },
        ]

    monkeypatch.setattr(mod, "list_behavior_runs", fake_runs)

    client = _build_client(monkeypatch)
    response = client.get(
        "/pallas/api/common-config/llm/behavior/runs",
        params={
            "group_id": 20002,
            "scene": "provocation",
            "final_outcome": "engaged",
            "include_disabled": False,
            "limit": 20,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["count"] == 1
    assert payload["data"]["items"][0]["request_id"] == "req-1"


def test_llm_history_behavior_annotation_post(monkeypatch) -> None:
    async def fake_update(*, request_id, labels, final_outcome=None, disabled=None):
        assert request_id == "req-1"
        assert labels == ["像人", "作为参考保留"]
        assert final_outcome == "engaged"
        assert disabled is False
        return {
            "request_id": "req-1",
            "manual_labels": labels,
            "final_outcome": "engaged",
            "disabled": False,
        }

    monkeypatch.setattr(
        "pallas.product.llm.session_store.update_llm_behavior_annotation",
        fake_update,
    )

    client = _build_client(monkeypatch)
    response = client.post(
        "/pallas/api/common-config/llm/history/behavior/annotate",
        json={
            "request_id": "req-1",
            "labels": ["像人", "作为参考保留"],
            "final_outcome": "engaged",
            "disabled": False,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["request_id"] == "req-1"
    assert payload["data"]["manual_labels"] == ["像人", "作为参考保留"]


def test_llm_runtime_debug_api_returns_snapshot_and_trace(tmp_path, monkeypatch) -> None:
    from pallas.product.llm.runtime_debug import append_request_snapshot, append_runtime_trace

    monkeypatch.setattr(
        "pallas.product.llm.runtime_debug.runtime_debug_dir",
        lambda: tmp_path,
    )
    snapshot_id = append_request_snapshot(
        request_id="req-1",
        task="llm_chat",
        system_prompt="你是牛牛",
        messages=[{"role": "user", "content": "你好"}],
        metadata={"agent_stage_plan": ["plan", "tool_loop", "generate"]},
    )
    append_runtime_trace(
        request_id="req-1",
        trace={"request_snapshot_id": snapshot_id, "version": "agent_trace/v1"},
    )

    client = _build_client(monkeypatch)
    response = client.get("/pallas/api/common-config/llm/runtime-debug/req-1")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["snapshot"]["request_snapshot_id"] == snapshot_id
    assert payload["data"]["trace"]["request_snapshot_id"] == snapshot_id

    replay = client.get("/pallas/api/common-config/llm/runtime-debug/req-1/replay")
    assert replay.status_code == 200, replay.text
    replay_payload = replay.json()
    assert replay_payload["ok"] is True
    assert replay_payload["data"]["request_snapshot_id"] == snapshot_id
    assert replay_payload["data"]["mode"] == "mock_tools"


def test_llm_runtime_replay_run_api_proxies_to_ai_extension(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.product.llm.runtime_debug.build_replay_payload",
        lambda *, request_id, mode="mock_tools": {
            "request_id": request_id,
            "request_snapshot_id": "snap-1",
            "mode": mode,
            "task": "llm_chat",
            "system_prompt": "你是牛牛",
            "messages": [{"role": "user", "content": "查一下银灰"}],
            "agent_stage_plan": ["plan", "tool_loop", "generate"],
            "tool_catalog": {"version": "tool_catalog/v1", "tools": []},
            "metadata_subset": {"task": "llm_chat", "bot_id": 10001, "group_id": 20002, "user_id": 30003},
        },
    )

    async def fake_ai_http_json(*, method, path, body=None):
        assert method == "POST"
        assert path == "/v1/chat/replay"
        assert body["request_id"] == "req-1"
        assert body["mode"] == "mock_tools"
        return {
            "ok": True,
            "status_code": 200,
            "url": "http://ai/api/v1/chat/replay",
            "data": {
                "request_id": "req-1",
                "mode": "mock_tools",
                "task": "llm_chat",
                "reply": "查到了",
                "trace": {"tool_call_count": 1},
                "assistant_message": {"role": "assistant", "content": "查到了"},
            },
            "error": None,
        }

    monkeypatch.setattr(mod, "ai_extension_http_json", fake_ai_http_json)

    client = _build_client(monkeypatch)
    response = client.post(
        "/pallas/api/common-config/llm/runtime-debug/req-1/replay/run",
        json={"mode": "mock_tools"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["reply"] == "查到了"
    assert payload["data"]["trace"]["tool_call_count"] == 1
