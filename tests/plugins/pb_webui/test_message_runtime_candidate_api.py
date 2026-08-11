from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.pb_webui import extended_api as ext
from packages.pb_webui import message_runtime_candidate_api as api
from packages.pb_webui.config import Config


def build_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(ext, "_require_pallas_token_configured", lambda *args, **kwargs: None)
    monkeypatch.setattr(ext, "ensure_console_metrics_hooks", lambda: None)
    app = FastAPI()
    ext.register_extended_api(app, api_base="/pallas/api", plugin_config=Config())
    return TestClient(app)


def test_message_runtime_candidates_combines_memory_snapshots(monkeypatch) -> None:
    monkeypatch.setattr(
        api,
        "dispatch_snapshot",
        lambda: {
            "day_key": "2026-08-10",
            "route_candidates": [{"route_modules": ["drink"], "messages": 14, "matchers_selected": 28}],
        },
    )
    monkeypatch.setattr(
        api,
        "plugin_stats_overview",
        lambda: {
            "bots": [
                {"plugins": [{"name": "drink", "runs": 50, "runs_today": 10, "avg_duration_ms_today": 5.0}]},
                {"plugins": [{"name": "drink", "runs": 50, "runs_today": 18, "avg_duration_ms_today": 10.0}]},
            ]
        },
    )
    monkeypatch.setattr(
        api,
        "route_history_snapshot",
        lambda: {"retention_sec": 604800, "latest_at": 100, "latest": []},
    )

    api.refresh_message_runtime_candidate_report()
    expected = api.candidate_report_snapshot()
    monkeypatch.setattr(api, "candidate_report_snapshot", lambda: expected)
    response = build_client(monkeypatch).get("/pallas/api/message-runtime/candidates")

    assert response.status_code == 200
    body = response.json()
    assert body["candidates"][0]["module"] == "drink"
    assert body["candidates"][0]["runs_today"] == 28
    assert body["candidates"][0]["current_day_duration_ms"] == 230.0
    assert body["candidates"][0]["estimated_matchers_avoided_today"] == 56.0
    assert "self_id" not in response.text


def test_message_runtime_candidates_degrades_to_data_quality(monkeypatch) -> None:
    monkeypatch.setattr(api, "dispatch_snapshot", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(api, "plugin_stats_overview", dict)
    monkeypatch.setattr(api, "route_history_snapshot", dict)

    api.refresh_message_runtime_candidate_report()
    expected = api.candidate_report_snapshot()
    monkeypatch.setattr(api, "candidate_report_snapshot", lambda: expected)
    response = build_client(monkeypatch).get("/pallas/api/message-runtime/candidates")

    assert response.status_code == 200
    assert response.json()["candidates"] == []
    assert "live_snapshot_unavailable" in response.json()["data_quality"]


def test_message_runtime_candidates_do_not_use_previous_day_history(monkeypatch) -> None:
    monkeypatch.setattr(
        api,
        "dispatch_snapshot",
        lambda: {"day_key": "2026-08-11", "route_candidates": []},
    )
    monkeypatch.setattr(api, "plugin_stats_overview", dict)
    monkeypatch.setattr(
        api,
        "route_history_snapshot",
        lambda: {
            "day_key": "2026-08-10",
            "retention_sec": 604800,
            "latest": [{"route_modules": ["drink"], "messages": 14}],
        },
    )

    api.refresh_message_runtime_candidate_report()
    expected = api.candidate_report_snapshot()
    monkeypatch.setattr(api, "candidate_report_snapshot", lambda: expected)
    response = build_client(monkeypatch).get("/pallas/api/message-runtime/candidates")

    assert response.status_code == 200
    assert response.json()["candidates"] == []


def test_message_runtime_candidates_route_only_reads_report_cache(monkeypatch) -> None:
    expected = {
        "day_key": "2026-08-10",
        "generated_at": 123,
        "route_window": {},
        "candidates": [],
        "data_quality": ["cached"],
    }
    monkeypatch.setattr(api, "candidate_report_snapshot", lambda: expected)
    monkeypatch.setattr(api, "dispatch_snapshot", lambda: (_ for _ in ()).throw(AssertionError("unexpected IO")))
    monkeypatch.setattr(api, "plugin_stats_overview", lambda: (_ for _ in ()).throw(AssertionError("unexpected IO")))

    response = build_client(monkeypatch).get("/pallas/api/message-runtime/candidates")

    assert response.status_code == 200
    assert response.json() == expected


def test_sharded_candidate_report_marks_reset_sensitive_totals(monkeypatch) -> None:
    monkeypatch.setattr(api, "plugin_stats_overview", dict)
    monkeypatch.setattr(
        api,
        "route_history_snapshot",
        lambda: {"sharded": True, "today_totals": [], "retention_sec": 604800},
    )

    report = api.build_message_runtime_candidate_report(
        ingress_snapshot={
            "day_key": "2026-08-10",
            "sharded": True,
            "route_candidates": [{"route_modules": ["drink"], "messages": 50}],
        }
    )

    assert report["candidates"][0]["route_messages"] == 50
    assert "sharded_route_totals_reset_sensitive" in report["data_quality"]


def test_plugin_stats_use_canonical_plugin_module_name() -> None:
    rows = api.aggregate_plugin_stats({
        "bots": [
            {
                "plugins": [
                    {
                        "name": "pallas_plugin_sing",
                        "runs": 78,
                        "runs_today": 3,
                        "avg_duration_ms_today": 100.0,
                    }
                ]
            }
        ]
    })

    assert rows == [
        {
            "module": "sing",
            "runs": 78,
            "runs_today": 3,
            "errors": 0,
            "errors_today": 0,
            "duration_ms_today": 300.0,
        }
    ]
