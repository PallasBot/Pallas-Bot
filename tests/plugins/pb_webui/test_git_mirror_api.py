from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
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


def test_git_mirror_info_returns_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.console.webui.git_mirror_api.git_mirror_info_payload",
        lambda: {
            "preferred_id": "github",
            "custom_proxy_prefix": "",
            "available_mirrors": [{"id": "github", "label": "GitHub（默认）", "type": "default"}],
            "plugins": [],
        },
    )

    client = _build_client(monkeypatch)
    response = client.get("/pallas/api/git-mirror/info")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["preferred_id"] == "github"
    assert payload["data"]["plugins"] == []


def test_git_mirror_preferred_saves_and_returns_info(monkeypatch, tmp_path) -> None:
    from pallas.core.shared.utils import git_mirror as gm

    webui_path = tmp_path / "webui.json"
    webui_path.write_text('{"env":{}}\n', encoding="utf-8")
    monkeypatch.setattr(gm, "repo_webui_settings_path", lambda: webui_path)
    monkeypatch.setattr("pallas.core.shared.utils.git_mirror.list_community_plugin_git_info", list)

    client = _build_client(monkeypatch)
    response = client.put(
        "/pallas/api/git-mirror/preferred",
        json={"preferred_id": "ghproxy-vip", "custom_proxy_prefix": ""},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["preferred_id"] == "ghproxy-vip"
    assert gm.load_git_mirror_config()["preferred_id"] == "ghproxy-vip"


def test_git_mirror_preferred_rejects_invalid_custom_prefix(monkeypatch) -> None:
    client = _build_client(monkeypatch)
    response = client.put(
        "/pallas/api/git-mirror/preferred",
        json={"preferred_id": "custom", "custom_proxy_prefix": "https://127.0.0.1/"},
    )

    assert response.status_code == 400


def test_git_mirror_apply_community_returns_summary(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.console.webui.git_mirror_api.apply_mirror_to_community_plugins",
        lambda mirror=None: {
            "results": [{"id": "demo", "success": True, "message": "ok"}],
            "summary": {"total": 1, "success_count": 1, "fail_count": 0},
        },
    )

    client = _build_client(monkeypatch)
    response = client.post("/pallas/api/git-mirror/apply-community")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["data"]["summary"]["success_count"] == 1


def test_git_mirror_apply_plugin_with_preferred_id(monkeypatch) -> None:
    from pallas.core.shared.utils.git_mirror import BUILTIN_MIRRORS

    captured: dict[str, str] = {}

    def fake_apply(plugin_id: str, mirror=None):
        captured["plugin_id"] = plugin_id
        captured["mirror_id"] = mirror.id if mirror is not None else ""
        return {"id": plugin_id, "success": True, "message": "done", "remote_url": "https://example.test/a/b.git"}

    monkeypatch.setattr("pallas.console.webui.git_mirror_api.apply_mirror_to_plugin", fake_apply)
    monkeypatch.setattr(
        "pallas.core.shared.utils.git_mirror.load_git_mirror_config",
        lambda: {"preferred_id": "github", "custom_proxy_prefix": ""},
    )
    ghproxy = next(m for m in BUILTIN_MIRRORS if m.id == "ghproxy-vip")
    monkeypatch.setattr(
        "pallas.core.shared.utils.git_mirror.mirror_by_id",
        lambda mirror_id: ghproxy if mirror_id == "ghproxy-vip" else BUILTIN_MIRRORS[0],
    )

    client = _build_client(monkeypatch)
    response = client.post(
        "/pallas/api/git-mirror/apply-plugin/demo_plugin",
        json={"preferred_id": "ghproxy-vip"},
    )

    assert response.status_code == 200, response.text
    assert captured["plugin_id"] == "demo_plugin"
    assert captured["mirror_id"] == "ghproxy-vip"


@pytest.mark.asyncio
async def test_git_mirror_probe_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.console.webui.git_mirror_api.probe_preferred_mirror",
        AsyncMock(return_value={"ok": True, "mirror_id": "github"}),
    )

    client = _build_client(monkeypatch)
    response = client.post("/pallas/api/git-mirror/probe")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["data"]["ok"] is True
    assert payload["data"]["mirror_id"] == "github"
