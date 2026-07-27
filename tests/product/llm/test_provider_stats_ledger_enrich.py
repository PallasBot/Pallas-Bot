"""账本补全提供方调用统计；落盘 day_key 过期时回写日汇总。"""

from __future__ import annotations

from pallas.product.llm.model_admin import _enrich_ai_snapshot_from_ledger
from pallas.product.llm.provider_request_metrics import (
    clear_llm_provider_request_metrics_for_tests,
    llm_provider_request_metrics_snapshot,
)
from pallas.product.llm.usage_ledger import append_usage_record, aggregate_day_from_ledger


def test_ledger_breakdown_tracks_request_count(tmp_path, monkeypatch) -> None:
    root = tmp_path / "llm_usage"
    monkeypatch.setattr("pallas.product.llm.usage_ledger.usage_ledger_dir", lambda: root)
    append_usage_record(
        task="llm_chat",
        provider="ds",
        model="m",
        prompt_tokens=1,
        completion_tokens=1,
        day_key="2026-07-27",
    )
    append_usage_record(
        task="llm_chat",
        provider="ds",
        model="m",
        prompt_tokens=1,
        completion_tokens=1,
        day_key="2026-07-27",
    )
    append_usage_record(
        task="llm_chat",
        provider="packy",
        model="m2",
        prompt_tokens=1,
        completion_tokens=1,
        day_key="2026-07-27",
    )
    bucket = aggregate_day_from_ledger("2026-07-27")
    assert bucket is not None
    assert bucket["by_provider"]["ds"]["requests"] == 2
    assert bucket["by_provider"]["packy"]["requests"] == 1


def test_enrich_ai_fills_missing_provider_stats_from_ledger(tmp_path, monkeypatch) -> None:
    root = tmp_path / "llm_usage"
    monkeypatch.setattr("pallas.product.llm.usage_ledger.usage_ledger_dir", lambda: root)
    append_usage_record(
        task="llm_chat",
        provider="ds",
        model="deepseek-v4-flash",
        prompt_tokens=10,
        completion_tokens=2,
        day_key="2026-07-27",
    )
    append_usage_record(
        task="llm_chat",
        provider="packy",
        model="x",
        prompt_tokens=3,
        completion_tokens=1,
        day_key="2026-07-27",
    )
    live = {
        "source": "bot",
        "day_key": "2026-07-27",
        "tokens": {
            "prompt_tokens": 3,
            "completion_tokens": 1,
            "total_tokens": 4,
            "by_provider": {"packy": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4}},
        },
        "provider_stats": {
            "packy": {
                "requests": 1,
                "succeeded": 1,
                "failed": 0,
                "total_latency_ms": 100,
                "avg_latency_ms": 100.0,
            }
        },
        "model_stats": {},
    }
    out = _enrich_ai_snapshot_from_ledger(live, day_key="2026-07-27")
    assert out is not None
    assert "ds" in out["provider_stats"]
    assert out["provider_stats"]["ds"]["requests"] == 1
    assert out["provider_stats"]["packy"]["requests"] == 1
    assert "deepseek-v4-flash" in out["model_stats"]


def test_stale_provider_stats_file_salvaged_to_daily(tmp_path, monkeypatch) -> None:
    clear_llm_provider_request_metrics_for_tests()
    stats_path = tmp_path / "llm_provider_request_stats.json"
    monkeypatch.setattr(
        "pallas.product.llm.provider_request_metrics.stats_file_path",
        lambda: stats_path,
    )
    monkeypatch.setattr(
        "pallas.product.llm.provider_request_metrics.today_key",
        lambda: "2026-07-27",
    )
    written: list[tuple[str, str, dict]] = []

    def fake_write(day: str, side: str, snapshot: dict) -> None:
        written.append((day, side, snapshot))

    monkeypatch.setattr(
        "pallas.product.llm.llm_daily_stats_store.write_day_side",
        fake_write,
    )
    stats_path.write_text(
        __import__("json").dumps(
            {
                "v": 1,
                "day_key": "2026-07-25",
                "provider_stats": {
                    "ds": {
                        "requests": 10,
                        "succeeded": 9,
                        "failed": 1,
                        "total_latency_ms": 1000,
                    }
                },
                "model_stats": {},
                "failure_counts": {},
            }
        ),
        encoding="utf-8",
    )
    import pallas.product.llm.provider_request_metrics as prm

    with prm._lock:
        prm._day_key = "2026-07-27"
        prm._hydrated = False
        prm._by_provider.clear()
        prm._by_model.clear()
        prm._failure_counts.clear()

    snap = llm_provider_request_metrics_snapshot(include_persisted=True)
    assert "ds" not in (snap.get("provider_stats") or {})
    assert written
    assert written[0][0] == "2026-07-25"
    assert written[0][2]["provider_stats"]["ds"]["requests"] == 10
