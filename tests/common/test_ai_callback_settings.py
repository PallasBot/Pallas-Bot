"""AI Runtime CALLBACK_* 读写与探活。"""

from __future__ import annotations

from pallas.console.cli import ai_callback_settings as cbs


def test_set_and_read_callback_env(tmp_path) -> None:
    root = tmp_path / "ai"
    root.mkdir()
    (root / ".env").write_text("FOO=1\nCALLBACK_PORT=8080\n", encoding="utf-8")
    cbs.write_callback_settings(root, host="127.0.0.1", port=8088)
    host, port = cbs.read_callback_settings(root)
    assert host == "127.0.0.1"
    assert port == 8088
    text = (root / ".env").read_text(encoding="utf-8")
    assert "CALLBACK_HOST=127.0.0.1" in text
    assert "CALLBACK_PORT=8088" in text
    assert "FOO=1" in text


def test_hosts_loopback_compatible() -> None:
    assert cbs.hosts_loopback_compatible("localhost", "127.0.0.1")
    assert not cbs.hosts_loopback_compatible("pallasbot", "127.0.0.1")


def test_is_callback_aligned() -> None:
    assert cbs.is_callback_aligned(
        "localhost",
        8088,
        expected_host="127.0.0.1",
        expected_port=8088,
    )
    assert (
        cbs.is_callback_aligned(
            "127.0.0.1",
            8080,
            expected_host="127.0.0.1",
            expected_port=8088,
        )
        is False
    )
    assert cbs.is_callback_aligned(None, 8088, expected_host="127.0.0.1", expected_port=8088) is None


def test_build_callback_status_reads_env(tmp_path, monkeypatch) -> None:
    root = tmp_path / "ai"
    root.mkdir()
    (root / ".env").write_text("CALLBACK_HOST=127.0.0.1\nCALLBACK_PORT=8080\n", encoding="utf-8")
    monkeypatch.setattr(cbs, "default_bot_callback_host", lambda: "127.0.0.1")
    monkeypatch.setattr(cbs, "default_bot_callback_port", lambda: 8088)
    monkeypatch.setattr(
        cbs,
        "probe_bot_callback_target",
        lambda host, port, timeout_sec=2.0: {
            "ok": False,
            "url": f"http://{host}:{port}/pallas/api/health",
            "status_code": None,
            "error": "refused",
        },
    )
    st = cbs.build_callback_status(ai_root=root)
    assert st["can_edit"] is True
    assert st["port"] == 8080
    assert st["aligned"] is False
    assert st["probe"]["ok"] is False


def test_apply_callback_align(tmp_path, monkeypatch) -> None:
    root = tmp_path / "ai"
    root.mkdir()
    (root / ".env").write_text("CALLBACK_HOST=127.0.0.1\nCALLBACK_PORT=8080\n", encoding="utf-8")
    monkeypatch.setattr(cbs, "default_bot_callback_host", lambda: "127.0.0.1")
    monkeypatch.setattr(cbs, "default_bot_callback_port", lambda: 8088)
    monkeypatch.setattr(cbs, "resolve_ai_repo_root", lambda: root)
    monkeypatch.setattr(
        cbs,
        "probe_bot_callback_target",
        lambda *a, **k: {"ok": True, "url": "u", "status_code": 200, "error": None},
    )

    class _Sup:
        @staticmethod
        def ai_runtime_status(*, ai_root=None):
            return {"running": True, "ai_root": str(ai_root or root)}

        @staticmethod
        def run_ctl(ai_root, *args, timeout_sec=120.0):
            return 0, "restarted"

    import pallas.console.cli.ai_supervisor as sup

    monkeypatch.setattr(sup, "ai_runtime_status", _Sup.ai_runtime_status)
    monkeypatch.setattr(sup, "run_ctl", _Sup.run_ctl)

    out = cbs.apply_callback_settings(ai_root=root, align=True, restart_media=True)
    assert out["ok"] is True
    assert cbs.read_callback_settings(root) == ("127.0.0.1", 8088)
    assert out["callback"]["aligned"] is True
