from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from packages.pb_webui import extended_api as mod
from packages.pb_webui.config import Config
from pallas.product.llm.repeater_feedback import LlmRepeaterFeedbackEntry


def _build_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(mod, "_check_pallas_write_token", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_require_pallas_token_configured", lambda *a, **k: None)
    monkeypatch.setattr(mod, "ensure_console_metrics_hooks", lambda: None)
    app = FastAPI()
    mod.register_extended_api(app, api_base="/pallas/api", plugin_config=Config())
    return TestClient(app)


def test_llm_repeater_feedback_api_returns_recent_entries(monkeypatch) -> None:
    def fake_list_group_feedback_entries(*, group_id: int, bot_id: int, limit: int = 20):
        assert group_id == 123
        assert bot_id == 10001
        assert limit == 20
        return [
            LlmRepeaterFeedbackEntry(
                entry_id="req-1",
                created_at=1718700001,
                bot_id=10001,
                group_id=123,
                user_id=30003,
                request_id="req-1",
                user_text="你又来这套",
                reply_text="少来。",
                behavior_scene="banter",
                behavior_actions=["follow_joke_once"],
                llm_route="plain_llm_chat",
                source_tags=[],
                eligible_for_bias=True,
            )
        ]

    monkeypatch.setattr(
        "packages.pb_webui.llm_product_api.list_group_feedback_entries",
        fake_list_group_feedback_entries,
    )

    client = _build_client(monkeypatch)
    response = client.get(
        "/pallas/api/llm/repeater-feedback",
        params={"group_id": 123, "bot_id": 10001, "limit": 20},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["items"][0]["request_id"] == "req-1"
    assert payload["data"]["items"][0]["reply_text"] == "少来。"
    assert payload["data"]["limit"] == 20


def test_llm_repeater_feedback_api_rejects_missing_bot_scope(monkeypatch) -> None:
    client = _build_client(monkeypatch)

    for params, missing_scope in (
        ({"group_id": 123}, "bot_id"),
        ({"bot_id": 10001}, "group_id"),
    ):
        response = client.get("/pallas/api/llm/repeater-feedback", params=params)

        assert response.status_code in {400, 422}
        assert response.json()["detail"][0]["loc"] == ["query", missing_scope]


def test_llm_repeater_feedback_api_passes_bot_scope(monkeypatch) -> None:
    calls: list[tuple[int, int | None, int]] = []

    def fake_list_group_feedback_entries(*, group_id: int, bot_id: int | None = None, limit: int = 20):
        calls.append((group_id, bot_id, limit))
        return []

    monkeypatch.setattr(
        "packages.pb_webui.llm_product_api.list_group_feedback_entries",
        fake_list_group_feedback_entries,
    )
    client = _build_client(monkeypatch)

    response = client.get("/pallas/api/llm/repeater-feedback", params={"group_id": 123, "bot_id": 10001})

    assert response.status_code == 200, response.text
    assert calls == [(123, 10001, 20)]


def test_llm_repeater_feedback_api_keeps_same_group_bots_isolated(monkeypatch) -> None:
    entries = {
        10001: [{"entry_id": "bot-1", "bot_id": 10001}],
        10002: [{"entry_id": "bot-2", "bot_id": 10002}],
    }

    def fake_list_group_feedback_entries(*, group_id: int, bot_id: int, limit: int = 20):
        assert group_id == 123
        return entries[bot_id][:limit]

    monkeypatch.setattr(
        "packages.pb_webui.llm_product_api.list_group_feedback_entries",
        fake_list_group_feedback_entries,
    )
    client = _build_client(monkeypatch)

    first = client.get("/pallas/api/llm/repeater-feedback", params={"group_id": 123, "bot_id": 10001})
    second = client.get("/pallas/api/llm/repeater-feedback", params={"group_id": 123, "bot_id": 10002})

    assert [item["bot_id"] for item in first.json()["data"]["items"]] == [10001]
    assert [item["bot_id"] for item in second.json()["data"]["items"]] == [10002]


def test_llm_repeater_feedback_summary_api_returns_group_snapshot(monkeypatch) -> None:
    def fake_group_feedback_bias_snapshot(*, group_id: int, limit: int = 40):
        assert group_id == 123
        assert limit == 40
        return {
            "count": 3,
            "top_replies": ["少来。", "行啊。"],
            "scenes": ["banter", "group_threading"],
        }

    monkeypatch.setattr(
        "packages.pb_webui.llm_product_api.group_feedback_bias_snapshot",
        fake_group_feedback_bias_snapshot,
    )

    client = _build_client(monkeypatch)
    response = client.get(
        "/pallas/api/llm/repeater-feedback/summary",
        params={"group_id": 123, "limit": 40},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["count"] == 3
    assert payload["data"]["top_replies"] == ["少来。", "行啊。"]
    assert payload["data"]["scenes"] == ["banter", "group_threading"]


def test_llm_repeater_feedback_manage_api(monkeypatch) -> None:
    def fake_set_feedback_entry_eligibility(
        *, entry_id: str = "", request_id: str = "", bot_id: int, group_id: int, eligible_for_bias: bool
    ):
        assert request_id == "req-1"
        assert (bot_id, group_id) == (10001, 123)
        assert eligible_for_bias is False
        return LlmRepeaterFeedbackEntry(
            entry_id="req-1",
            created_at=1718700001,
            bot_id=10001,
            group_id=123,
            user_id=30003,
            request_id="req-1",
            user_text="你又来这套",
            reply_text="少来。",
            eligible_for_bias=False,
        )

    monkeypatch.setattr(
        "packages.pb_webui.llm_product_api.set_feedback_entry_eligibility",
        fake_set_feedback_entry_eligibility,
    )

    client = _build_client(monkeypatch)
    response = client.post(
        "/pallas/api/llm/repeater-feedback/manage",
        json={"request_id": "req-1", "action": "invalidate", "bot_id": 10001, "group_id": 123},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["eligible_for_bias"] is False


def test_llm_repeater_feedback_manage_rejects_missing_scope_for_every_action(monkeypatch) -> None:
    client = _build_client(monkeypatch)
    for action in ("invalidate", "restore", "delete", "correct", "clear_correction"):
        response = client.post(
            "/pallas/api/llm/repeater-feedback/manage",
            json={"request_id": "req-1", "action": action},
        )
        assert response.status_code == 400, (action, response.text)
        assert "bot_id 和 group_id" in response.json()["detail"]


def test_llm_repeater_feedback_manage_delete_uses_scope(monkeypatch) -> None:
    calls: list[tuple[str, int, int]] = []

    def fake_delete_feedback_entry(*, entry_id: str = "", request_id: str = "", bot_id: int, group_id: int) -> bool:
        calls.append((entry_id or request_id, bot_id, group_id))
        return True

    monkeypatch.setattr(
        "packages.pb_webui.llm_product_api.delete_feedback_entry",
        fake_delete_feedback_entry,
    )
    client = _build_client(monkeypatch)

    response = client.post(
        "/pallas/api/llm/repeater-feedback/manage",
        json={"entry_id": "shared-entry", "action": "delete", "bot_id": "10001", "group_id": "123"},
    )
    partial = client.post(
        "/pallas/api/llm/repeater-feedback/manage",
        json={"entry_id": "shared-entry", "action": "delete", "bot_id": "10001"},
    )

    assert response.status_code == 200, response.text
    assert partial.status_code == 400, partial.text
    assert calls == [("shared-entry", 10001, 123)]


def test_llm_repeater_feedback_manage_correct_api(monkeypatch) -> None:
    def fake_find_feedback_entry(*, entry_id: str = "", request_id: str = "", bot_id: int, group_id: int):
        assert request_id == "req-1"
        assert (bot_id, group_id) == (10001, 123)
        return LlmRepeaterFeedbackEntry(
            entry_id="req-1",
            created_at=1718700001,
            bot_id=10001,
            group_id=123,
            user_id=30003,
            request_id="req-1",
            user_text="你又来这套",
            reply_text="少来。",
        )

    def fake_set_feedback_entry_correction(**kwargs):
        assert kwargs["corrected_reply_text"] == "别闹"
        assert (kwargs["bot_id"], kwargs["group_id"]) == (10001, 123)
        return LlmRepeaterFeedbackEntry(
            entry_id="req-1",
            created_at=1718700001,
            bot_id=10001,
            group_id=123,
            user_id=30003,
            request_id="req-1",
            user_text="你又来这套",
            reply_text="少来。",
            corrected_reply_text="别闹",
            corrected_at=1718700002,
            eligible_for_bias=True,
        )

    monkeypatch.setattr("packages.pb_webui.llm_product_api.find_feedback_entry", fake_find_feedback_entry)
    monkeypatch.setattr(
        "packages.pb_webui.llm_product_api.set_feedback_entry_correction",
        fake_set_feedback_entry_correction,
    )

    client = _build_client(monkeypatch)
    response = client.post(
        "/pallas/api/llm/repeater-feedback/manage",
        json={
            "request_id": "req-1",
            "action": "correct",
            "corrected_reply_text": "别闹",
            "bot_id": 10001,
            "group_id": 123,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["corrected_reply_text"] == "别闹"


def test_injection_governance_get_returns_requested_scope(monkeypatch) -> None:
    thread_calls: list[str] = []

    def fake_list_injection_governance_status(*, bot_id: int, group_id: int):
        assert (bot_id, group_id) == (10001, 123)
        return "ok", {"bot_id": bot_id, "group_id": group_id, "outcomes": ["outcome-1"]}

    async def fake_to_thread(function, /, *args, **kwargs):
        thread_calls.append(function.__name__)
        return function(*args, **kwargs)

    monkeypatch.setattr(
        "packages.pb_webui.llm_product_api.list_injection_governance_status",
        fake_list_injection_governance_status,
    )
    monkeypatch.setattr("packages.pb_webui.llm_product_api.asyncio.to_thread", fake_to_thread)

    response = _build_client(monkeypatch).get(
        "/pallas/api/llm/repeater-feedback/governance",
        params={"bot_id": 10001, "group_id": 123},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "ok": True,
        "data": {"bot_id": 10001, "group_id": 123, "outcomes": ["outcome-1"]},
    }
    assert thread_calls == ["fake_list_injection_governance_status"]


def test_injection_governance_get_rejects_missing_or_invalid_scope(monkeypatch) -> None:
    client = _build_client(monkeypatch)

    assert client.get("/pallas/api/llm/repeater-feedback/governance", params={"group_id": 123}).status_code == 400
    assert (
        client.get(
            "/pallas/api/llm/repeater-feedback/governance",
            params={"bot_id": "bad", "group_id": 123},
        ).status_code
        == 400
    )


def test_injection_governance_get_returns_500_for_ledger_read_failure(monkeypatch) -> None:
    def fail_read(path):
        raise OSError("ledger read failed")

    monkeypatch.setattr(
        "pallas.product.llm.injection_feedback._iter_outcomes",
        fail_read,
    )

    response = _build_client(monkeypatch).get(
        "/pallas/api/llm/repeater-feedback/governance",
        params={"bot_id": 10001, "group_id": 123},
    )

    assert response.status_code == 500


def test_injection_governance_get_missing_ledger_is_empty_without_storage_mutation(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))

    response = _build_client(monkeypatch).get(
        "/pallas/api/llm/repeater-feedback/governance",
        params={"bot_id": 10001, "group_id": 123},
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["outcomes"] == []
    assert not (tmp_path / "llm_repeater_feedback").exists()


def test_injection_governance_manage_requires_action_specific_id(monkeypatch) -> None:
    client = _build_client(monkeypatch)
    scope = {"bot_id": "10001", "group_id": "123"}

    for action, key in (
        ("undo_outcome", "outcome_id"),
        ("restore_semantic", "outcome_id"),
    ):
        response = client.post(
            "/pallas/api/llm/repeater-feedback/governance/manage",
            json={"action": action, **scope},
        )
        assert response.status_code == 400, response.text
        assert key in response.json()["detail"]


def test_injection_governance_manage_undo_uses_exact_scope(monkeypatch) -> None:
    calls: list[tuple[str, int, int]] = []

    def fake_undo_negative_outcome_status(*, outcome_id: str, bot_id: int, group_id: int) -> str:
        calls.append((outcome_id, bot_id, group_id))
        return "undone" if outcome_id == "outcome-1" else "missing"

    monkeypatch.setattr(
        "packages.pb_webui.llm_product_api.undo_negative_outcome_status",
        fake_undo_negative_outcome_status,
    )
    client = _build_client(monkeypatch)

    missing = client.post(
        "/pallas/api/llm/repeater-feedback/governance/manage",
        json={"action": "undo_outcome", "outcome_id": "foreign", "bot_id": "10001", "group_id": "123"},
    )
    restored = client.post(
        "/pallas/api/llm/repeater-feedback/governance/manage",
        json={"action": "undo_outcome", "outcome_id": "outcome-1", "bot_id": "10001", "group_id": "123"},
    )

    assert missing.status_code == 404
    assert restored.status_code == 200, restored.text
    assert restored.json()["data"] == {"undone": True, "outcome_id": "outcome-1"}
    assert calls == [("foreign", 10001, 123), ("outcome-1", 10001, 123)]


def test_injection_governance_manage_restore_semantic_undoes_scoped_outcome(monkeypatch) -> None:
    calls: list[tuple[str, int, int]] = []

    def fake_undo_negative_outcome_status(*, outcome_id: str, bot_id: int, group_id: int) -> str:
        calls.append((outcome_id, bot_id, group_id))
        return "undone"

    monkeypatch.setattr(
        "packages.pb_webui.llm_product_api.undo_negative_outcome_status",
        fake_undo_negative_outcome_status,
    )

    response = _build_client(monkeypatch).post(
        "/pallas/api/llm/repeater-feedback/governance/manage",
        json={
            "action": "restore_semantic",
            "outcome_id": "outcome-1",
            "bot_id": "10001",
            "group_id": "123",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"] == {
        "undone": True,
        "outcome_id": "outcome-1",
        "semantic_restored": True,
    }
    assert calls == [("outcome-1", 10001, 123)]


def test_injection_governance_restore_semantic_validates_optional_source_example(monkeypatch) -> None:
    undo_calls: list[dict[str, int | str]] = []
    monkeypatch.setattr(
        "packages.pb_webui.llm_product_api.list_injection_governance_status",
        lambda **kwargs: (
            "ok",
            {"outcomes": [{"outcome_id": "outcome-1", "decisions": [{"source_id": "semantic-example-1"}]}]},
        ),
    )
    monkeypatch.setattr(
        "packages.pb_webui.llm_product_api.undo_negative_outcome_status",
        lambda **kwargs: undo_calls.append(kwargs) or True,
    )

    response = _build_client(monkeypatch).post(
        "/pallas/api/llm/repeater-feedback/governance/manage",
        json={
            "action": "restore_semantic",
            "outcome_id": "outcome-1",
            "source_example_id": "foreign-example",
            "bot_id": "10001",
            "group_id": "123",
        },
    )

    assert response.status_code == 404
    assert undo_calls == []


def test_injection_governance_restore_semantic_accepts_matching_source_example(monkeypatch) -> None:
    governance_calls: list[tuple[int, int]] = []
    undo_calls: list[tuple[str, int, int]] = []

    def fake_list_injection_governance_status(*, bot_id: int, group_id: int):
        governance_calls.append((bot_id, group_id))
        return "ok", {"outcomes": [{"outcome_id": "outcome-1", "decisions": [{"source_id": "semantic-example-1"}]}]}

    def fake_undo_negative_outcome_status(*, outcome_id: str, bot_id: int, group_id: int) -> str:
        undo_calls.append((outcome_id, bot_id, group_id))
        return "undone"

    monkeypatch.setattr(
        "packages.pb_webui.llm_product_api.list_injection_governance_status",
        fake_list_injection_governance_status,
    )
    monkeypatch.setattr(
        "packages.pb_webui.llm_product_api.undo_negative_outcome_status",
        fake_undo_negative_outcome_status,
    )

    response = _build_client(monkeypatch).post(
        "/pallas/api/llm/repeater-feedback/governance/manage",
        json={
            "action": "restore_semantic",
            "outcome_id": "outcome-1",
            "source_example_id": "semantic-example-1",
            "bot_id": "10001",
            "group_id": "123",
        },
    )

    assert response.status_code == 200, response.text
    assert governance_calls == [(10001, 123)]
    assert undo_calls == [("outcome-1", 10001, 123)]


def test_injection_governance_manage_returns_500_for_ledger_storage_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        "packages.pb_webui.llm_product_api.undo_negative_outcome_status",
        lambda **kwargs: "storage_error",
    )

    response = _build_client(monkeypatch).post(
        "/pallas/api/llm/repeater-feedback/governance/manage",
        json={"action": "undo_outcome", "outcome_id": "outcome-1", "bot_id": "10001", "group_id": "123"},
    )

    assert response.status_code == 500


def test_injection_governance_manage_checks_write_token(monkeypatch) -> None:
    from packages.pb_webui import llm_product_api

    checked: list[bool] = []
    monkeypatch.setattr(
        llm_product_api,
        "check_pallas_write_token",
        lambda *args, **kwargs: checked.append(True),
    )
    monkeypatch.setattr(
        llm_product_api,
        "undo_negative_outcome_status",
        lambda **kwargs: "undone",
    )

    response = _build_client(monkeypatch).post(
        "/pallas/api/llm/repeater-feedback/governance/manage",
        json={"action": "undo_outcome", "outcome_id": "outcome-1", "bot_id": "10001", "group_id": "123"},
    )

    assert response.status_code == 200, response.text
    assert checked == [True]


def test_injection_governance_manage_rejects_invalid_write_token_before_undo(monkeypatch) -> None:
    from packages.pb_webui import llm_product_api

    undo_called = False

    def deny(*args, **kwargs) -> None:
        raise HTTPException(status_code=403, detail="invalid write token")

    def fake_undo(**kwargs) -> bool:
        nonlocal undo_called
        undo_called = True
        return True

    monkeypatch.setattr(llm_product_api, "check_pallas_write_token", deny)
    monkeypatch.setattr(llm_product_api, "undo_negative_outcome_status", fake_undo)

    response = _build_client(monkeypatch).post(
        "/pallas/api/llm/repeater-feedback/governance/manage",
        json={"action": "undo_outcome", "outcome_id": "outcome-1", "bot_id": "10001", "group_id": "123"},
    )

    assert response.status_code == 403
    assert undo_called is False
