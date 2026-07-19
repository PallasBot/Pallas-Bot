from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi import FastAPI
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
    def fake_list_group_feedback_entries(*, group_id: int, limit: int = 20):
        assert group_id == 123
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
                eligible_for_writeback=False,
            )
        ]

    monkeypatch.setattr(
        mod,
        "list_group_feedback_entries",
        fake_list_group_feedback_entries,
        raising=False,
    )

    client = _build_client(monkeypatch)
    response = client.get(
        "/pallas/api/llm/repeater-feedback",
        params={"group_id": 123, "limit": 20},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["items"][0]["request_id"] == "req-1"
    assert payload["data"]["items"][0]["reply_text"] == "少来。"
    assert payload["data"]["limit"] == 20


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
        mod,
        "group_feedback_bias_snapshot",
        fake_group_feedback_bias_snapshot,
        raising=False,
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


def test_llm_repeater_feedback_promotion_candidates_api(monkeypatch) -> None:
    from pallas.product.llm.kernel.feedback_models import PromotionCandidate

    def fake_list_promotion_candidates(*, group_id: int, limit: int = 20, include_resolved: bool = False):
        assert group_id == 123
        assert limit == 20
        assert include_resolved is False
        return [
            PromotionCandidate(
                candidate_id="cand-1",
                group_id=123,
                trigger_text="你又来这套",
                reply_text="少来。",
                support_count=2,
                last_seen_at=1718700001,
                behavior_scene="banter",
                source_request_id="req-2",
            )
        ]

    monkeypatch.setattr(
        mod,
        "list_promotion_candidates",
        fake_list_promotion_candidates,
        raising=False,
    )

    client = _build_client(monkeypatch)
    response = client.get(
        "/pallas/api/llm/repeater-feedback/promotion-candidates",
        params={"group_id": 123, "limit": 20},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["items"][0]["candidate_id"] == "cand-1"
    assert payload["data"]["items"][0]["reply_text"] == "少来。"


def test_llm_repeater_feedback_promotion_candidates_resolve_api(monkeypatch) -> None:
    from pallas.product.llm.kernel.feedback_models import PromotionCandidate

    async def fake_resolve_promotion_candidate(candidate_id: str, *, action: str, reason: str = ""):
        assert candidate_id == "cand-1"
        assert action == "promote"
        return PromotionCandidate(
            candidate_id="cand-1",
            group_id=123,
            trigger_text="你又来这套",
            reply_text="少来。",
            support_count=2,
            promoted=True,
            writeback_status="written",
        )

    monkeypatch.setattr(
        mod,
        "resolve_promotion_candidate_with_writeback",
        AsyncMock(side_effect=fake_resolve_promotion_candidate),
        raising=False,
    )

    client = _build_client(monkeypatch)
    response = client.post(
        "/pallas/api/llm/repeater-feedback/promotion-candidates/resolve",
        json={"candidate_id": "cand-1", "action": "promote"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["promoted"] is True
    assert payload["data"]["writeback_status"] == "written"


def test_llm_repeater_feedback_manage_api(monkeypatch) -> None:
    def fake_set_feedback_entry_eligibility(*, entry_id: str = "", request_id: str = "", eligible_for_bias: bool):
        assert request_id == "req-1"
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

    monkeypatch.setattr(mod, "set_feedback_entry_eligibility", fake_set_feedback_entry_eligibility, raising=False)

    client = _build_client(monkeypatch)
    response = client.post(
        "/pallas/api/llm/repeater-feedback/manage",
        json={"request_id": "req-1", "action": "invalidate"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["eligible_for_bias"] is False


def test_llm_repeater_feedback_manage_correct_api(monkeypatch) -> None:
    def fake_find_feedback_entry(*, entry_id: str = "", request_id: str = ""):
        assert request_id == "req-1"
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

    monkeypatch.setattr(mod, "find_feedback_entry", fake_find_feedback_entry, raising=False)
    monkeypatch.setattr(mod, "set_feedback_entry_correction", fake_set_feedback_entry_correction, raising=False)

    client = _build_client(monkeypatch)
    response = client.post(
        "/pallas/api/llm/repeater-feedback/manage",
        json={"request_id": "req-1", "action": "correct", "corrected_reply_text": "别闹"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["corrected_reply_text"] == "别闹"
