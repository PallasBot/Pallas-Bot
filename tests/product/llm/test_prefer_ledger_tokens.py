"""当日 token 优先账本：重启后实时快照缺提供方时仍能还原。"""

from __future__ import annotations

from pallas.product.llm.model_admin import _prefer_ledger_tokens_on_ai
from pallas.product.llm.usage_ledger import append_usage_record


def test_prefer_ledger_tokens_keeps_ds_after_incomplete_live(tmp_path, monkeypatch) -> None:
    root = tmp_path / "llm_usage"
    monkeypatch.setattr(
        "pallas.product.llm.usage_ledger.usage_ledger_dir",
        lambda: root,
    )
    # 2026-07-27 10:00 local
    ts_hour = 1785117600.0
    append_usage_record(
        task="llm_chat",
        provider="ds",
        model="m",
        prompt_tokens=100,
        completion_tokens=20,
        day_key="2026-07-27",
        ts=ts_hour,
    )
    append_usage_record(
        task="llm_chat",
        provider="packy",
        model="m2",
        prompt_tokens=10,
        completion_tokens=5,
        day_key="2026-07-27",
        ts=ts_hour,
    )
    live = {
        "source": "bot",
        "day_key": "2026-07-27",
        "tokens": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "by_provider": {
                "packy": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
            "by_hour": {"17": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
        },
        "gates": {"proceed": 3, "skip": 0, "defer": 0},
    }
    out = _prefer_ledger_tokens_on_ai(live, day_key="2026-07-27")
    assert out is not None
    tokens = out["tokens"]
    assert tokens["source"] == "ledger"
    assert tokens["prompt_tokens"] == 110
    assert tokens["completion_tokens"] == 25
    assert set(tokens["by_provider"]) == {"ds", "packy"}
    assert tokens["by_provider"]["ds"]["total_tokens"] == 120
    # 账本按 ts 重建小时桶（覆盖重启后残缺的实时 by_hour）
    assert tokens["by_hour"]["10"]["total_tokens"] == 135
    assert "17" not in tokens["by_hour"]
    assert out["gates"]["proceed"] == 3


def test_prefer_ledger_tokens_noop_without_ledger() -> None:
    live = {
        "source": "bot",
        "tokens": {
            "prompt_tokens": 1,
            "completion_tokens": 2,
            "total_tokens": 3,
            "by_provider": {"local": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}},
        },
    }
    out = _prefer_ledger_tokens_on_ai(live, day_key="2099-01-01")
    assert out is live or out == live
    assert out["tokens"]["by_provider"] == {"local": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}}
