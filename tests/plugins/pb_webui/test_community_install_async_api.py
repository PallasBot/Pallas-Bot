"""社区插件 install-async API。"""

from __future__ import annotations

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


def test_community_install_async_returns_job(monkeypatch) -> None:
    async def fake_resolve(body):
        return "demo-plugin", "https://github.com/example/demo.git", "main"

    async def fake_create(package: str, action: str):
        from pallas.console.webui.extension_install_progress import ExtensionInstallJob

        return ExtensionInstallJob(job_id="job-demo", package=package, action=action)

    async def fake_run(job, runner):
        _ = runner
        job.push("done", "ok", result={"message": "ok"})

    monkeypatch.setattr(mod, "_resolve_community_plugin_target", fake_resolve)
    monkeypatch.setattr(
        "pallas.console.webui.extension_install_progress.create_extension_install_job",
        fake_create,
    )
    monkeypatch.setattr(
        "pallas.console.webui.extension_install_progress.run_extension_install_job",
        fake_run,
    )

    client = _build_client(monkeypatch)
    response = client.post(
        "/pallas/api/plugins/community-plugins/install-async",
        json={"plugin_id": "demo-plugin", "repository_url": "https://github.com/example/demo.git"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["job_id"] == "job-demo"
    assert payload["data"]["package"] == "demo-plugin"


def test_install_job_stream_alias_route(monkeypatch) -> None:
    async def fake_iter(job_id: str):
        yield 'data: {"type":"complete","phase":"done","message":"ok"}\n\n'

    monkeypatch.setattr(
        "pallas.console.webui.extension_install_progress.iter_extension_install_job_sse",
        fake_iter,
    )
    client = _build_client(monkeypatch)
    with client.stream("GET", "/pallas/api/plugins/install-jobs/job-demo/stream") as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())
    assert "complete" in body
