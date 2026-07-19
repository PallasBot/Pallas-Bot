from __future__ import annotations

import pallas.core.foundation.db.pool_diagnostics as pool_diagnostics


def test_pg_session_caller_hint_entry_avoids_inspect_stack(monkeypatch) -> None:
    def _boom():
        raise AssertionError("inspect.stack should not be used on the fast path")

    monkeypatch.setattr(pool_diagnostics.inspect, "stack", _boom)

    def wrapper() -> str:
        return pool_diagnostics.pg_session_caller_hint_entry()

    hint = wrapper()

    assert hint.startswith("wrapper@common/test_pool_diagnostics.py:")


def test_pg_session_caller_hint_entry_falls_back_to_inspect_stack(monkeypatch) -> None:
    monkeypatch.setattr(pool_diagnostics.sys, "_getframe", None, raising=False)

    class _FrameInfo:
        filename = "/tmp/site-packages/pkg.py"
        function = "ignored"
        lineno = 1

    class _WantedFrame:
        filename = "/root/Projects/Bots/Pallas-Bot/tests/common/test_pool_diagnostics.py"
        function = "fallback_wrapper"
        lineno = 27

    monkeypatch.setattr(pool_diagnostics.inspect, "stack", lambda: [None, None, _FrameInfo(), _WantedFrame()])

    assert pool_diagnostics.pg_session_caller_hint_entry() == "fallback_wrapper@common/test_pool_diagnostics.py:27"


def test_pool_diag_tick_notable_only_when_anomaly() -> None:
    base = {
        "under_pressure": False,
        "idle_in_tx": 0,
        "slow_sessions": 0,
        "remote_skipped_pressure": 0,
        "remote_skipped_busy": 0,
        "mirror_skip": 0,
        "learn_pool_wait": 0,
    }
    assert pool_diagnostics.pool_diag_tick_notable(**base) is False
    assert pool_diagnostics.pool_diag_tick_notable(**{**base, "under_pressure": True}) is True
    assert pool_diagnostics.pool_diag_tick_notable(**{**base, "remote_skipped_busy": 3}) is True


def test_pool_diag_tick_sec_default(monkeypatch) -> None:
    monkeypatch.delenv("PG_POOL_DIAG_TICK_SEC", raising=False)
    monkeypatch.setattr(pool_diagnostics, "repo_env_raw_value", lambda _k: None)
    assert pool_diagnostics.pool_diag_tick_sec() == 300.0
