"""AI Runtime supervisor：托管路径、pid 探活、ctl 封装。"""

from __future__ import annotations

from pallas.console.cli import ai_ops, ai_supervisor


def test_resolve_prefers_managed_over_sibling(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("PALLAS_AI_ROOT", raising=False)
    managed = tmp_path / "managed"
    sibling = tmp_path / "sibling"
    for root in (managed, sibling):
        (root / "scripts").mkdir(parents=True)
        (root / "scripts" / "ai_bootstrap.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(ai_ops, "managed_ai_root", lambda: managed.resolve())
    monkeypatch.setattr(ai_ops, "sibling_ai_root", lambda: sibling.resolve())
    assert ai_ops.resolve_ai_repo_root() == managed.resolve()


def test_resolve_falls_back_to_sibling(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("PALLAS_AI_ROOT", raising=False)
    managed = tmp_path / "managed"
    sibling = tmp_path / "sibling"
    (sibling / "scripts").mkdir(parents=True)
    (sibling / "scripts" / "ai_bootstrap.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(ai_ops, "managed_ai_root", lambda: managed.resolve())
    monkeypatch.setattr(ai_ops, "sibling_ai_root", lambda: sibling.resolve())
    assert ai_ops.resolve_ai_repo_root() == sibling.resolve()


def test_is_managed_by_path_or_marker(tmp_path) -> None:
    root = tmp_path / "ai"
    root.mkdir()
    assert ai_supervisor.is_managed_ai_root(root) is False
    ai_supervisor.mark_ai_root_managed(root)
    assert ai_supervisor.is_managed_ai_root(root) is True
    assert (root / ".pallas-managed").is_file()


def test_ai_runtime_status_reads_pidfiles(tmp_path, monkeypatch) -> None:
    root = tmp_path / "ai"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "ctl.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (root / "logs").mkdir()
    (root / "logs" / "api.pid").write_text("1\n", encoding="utf-8")
    (root / "logs" / "llm.pid").write_text("1\n", encoding="utf-8")
    monkeypatch.setattr(ai_supervisor, "_pid_alive", lambda pid: pid == 1)
    monkeypatch.setattr(
        ai_supervisor,
        "probe_ai_health_sync",
        lambda **_: {
            "ok": True,
            "url": "http://127.0.0.1:9099/health",
            "status_code": 200,
            "body_preview": "{}",
            "error": None,
        },
    )
    st = ai_supervisor.ai_runtime_status(ai_root=root)
    assert st["can_manage"] is True
    assert st["running"] is True
    assert st["services"]["api"]["running"] is True
    assert st["services"]["llm"]["running"] is True
    assert st["health"]["ok"] is True


def test_start_ai_runtime_calls_ctl(tmp_path, monkeypatch) -> None:
    root = tmp_path / "ai"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "ctl.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    calls: list[tuple[str, ...]] = []

    def fake_ctl(ai_root, *args: str, timeout_sec: float = 120.0):  # noqa: ANN001
        assert ai_root == root
        calls.append(args)
        return 0, f"ok {' '.join(args)}"

    monkeypatch.setattr(ai_supervisor, "run_ctl", fake_ctl)
    monkeypatch.setattr(
        ai_supervisor,
        "ai_runtime_status",
        lambda **_: {"running": True, "can_manage": True},
    )
    out = ai_supervisor.start_ai_runtime(ai_root=root, with_media=False)
    assert out["ok"] is True
    assert calls == [("start", "llm"), ("start", "api")]
    with_media = ai_supervisor.start_ai_runtime(ai_root=root, with_media=True)
    assert with_media["ok"] is True
    assert calls[-1] == ("start", "all")
