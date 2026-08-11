from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.pb_webui import api as api_mod
from packages.pb_webui import extended_api as mod
from packages.pb_webui.config import Config
from tools.export_pb_webui_openapi import export_console_openapi


def _build_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(mod, "_check_pallas_write_token", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_require_pallas_token_configured", lambda *a, **k: None)
    monkeypatch.setattr(mod, "ensure_console_metrics_hooks", lambda: None)
    app = FastAPI()
    mod.register_extended_api(app, api_base="/pallas/api", plugin_config=Config())
    return TestClient(app)


def test_auth_setup_status_public(monkeypatch) -> None:
    monkeypatch.setattr(
        mod,
        "console_setup_status",
        lambda: {
            "auth_configured": True,
            "setup_completed": False,
            "default_password_active": True,
            "requires_setup": True,
            "first_completed_at": None,
            "updated_at": None,
        },
    )
    client = _build_client(monkeypatch)
    response = client.get("/pallas/api/auth/setup-status")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["requires_setup"] is True
    assert payload["data"]["default_password_active"] is True


def test_console_openapi_json_filters_non_console_routes(monkeypatch) -> None:
    monkeypatch.setattr(mod, "ensure_console_metrics_hooks", lambda: None)
    app = FastAPI()

    @app.get("/hello")
    async def _hello() -> dict[str, str]:
        return {"ok": "yes"}

    api_mod.register_api(app, api_base="/pallas/api")
    mod.register_extended_api(app, api_base="/pallas/api", plugin_config=Config())
    client = TestClient(app)

    response = client.get("/pallas/api/openapi.json")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "/pallas/api/health" in payload["paths"]
    assert "/pallas/api/system" in payload["paths"]
    assert "/hello" not in payload["paths"]
    assert "/pallas/api/openapi.json" not in payload["paths"]
    assert payload["servers"] == [{"url": "/pallas/api"}]


def test_export_console_openapi_matches_console_prefix(monkeypatch) -> None:
    monkeypatch.setattr(mod, "ensure_console_metrics_hooks", lambda: None)
    payload = export_console_openapi(api_base="/pallas/api")
    assert "/pallas/api/health" in payload["paths"]
    assert "/pallas/api/system" in payload["paths"]
    assert all(path.startswith("/pallas/api/") for path in payload["paths"])
    assert payload["servers"] == [{"url": "/pallas/api"}]

    setup_schema = payload["paths"]["/pallas/api/auth/setup-status"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    gateways_schema = payload["paths"]["/pallas/api/common-config/service_gateways/connectivity-check"]["post"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]
    providers_schema = payload["paths"]["/pallas/api/common-config/llm/providers"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    provider_test_schema = payload["paths"]["/pallas/api/common-config/llm/providers/{provider_id}/test"]["post"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]
    runtime_schema = payload["paths"]["/pallas/api/common-config/llm/runtime-overview"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    extension_test_schema = payload["paths"]["/pallas/api/ai-extension/test"]["post"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    password_schema = payload["paths"]["/pallas/api/security/console-login"]["post"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]

    assert setup_schema["$ref"].endswith("_ApiOkResponse__ConsoleSetupStatusData_")
    assert gateways_schema["$ref"].endswith("_ApiOkResponse__ServiceGatewaysConnectivityCheckData_")
    assert providers_schema["$ref"].endswith("_ApiOkResponse__LlmProvidersConfigData_")
    assert provider_test_schema["$ref"].endswith("_ApiOkResponse__LlmProviderTestData_")
    assert runtime_schema["$ref"].endswith("_ApiOkResponse__LlmRuntimeOverviewData_")
    assert extension_test_schema["$ref"].endswith("_ApiOkResponse__AiExtensionTestData_")
    assert password_schema["$ref"].endswith("_ApiOkResponse__ConsoleLoginChangeData_")
    sing_defaults_schema = payload["paths"]["/pallas/api/common-config/llm/media-models/sing/defaults"]["put"][
        "requestBody"
    ]["content"]["application/json"]["schema"]
    assert sing_defaults_schema["$ref"].endswith("_LlmSingDefaultsBody")
    sing_defaults_name = sing_defaults_schema["$ref"].removeprefix("#/components/schemas/")
    sing_defaults_properties = payload["components"]["schemas"][sing_defaults_name]["properties"]
    song_cache_days_schema = sing_defaults_properties["song_cache_days"]["anyOf"][0]
    song_cache_size_schema = sing_defaults_properties["song_cache_size"]["anyOf"][0]
    assert song_cache_days_schema == {"type": "integer", "maximum": 3650.0, "minimum": 1.0}
    assert song_cache_size_schema == {"type": "integer", "maximum": 10000.0, "minimum": 0.0}
    sing_defaults_response_schema = payload["paths"]["/pallas/api/common-config/llm/media-models/sing/defaults"]["put"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]
    assert sing_defaults_response_schema["$ref"].endswith("_ApiOkResponse__LlmSingDefaultsData_")
    sing_defaults_response_name = sing_defaults_response_schema["$ref"].removeprefix("#/components/schemas/")
    sing_defaults_response_properties = payload["components"]["schemas"][sing_defaults_response_name]["properties"]
    sing_defaults_data_schema = sing_defaults_response_properties["data"]["$ref"]
    sing_defaults_data_name = sing_defaults_data_schema.removeprefix("#/components/schemas/")
    sing_defaults_data_properties = payload["components"]["schemas"][sing_defaults_data_name]["properties"]
    assert sing_defaults_data_properties["default_speaker"]["type"] == "string"
    assert sing_defaults_data_properties["preferred_backend"]["type"] == "string"
    assert sing_defaults_data_properties["speaker_backends"]["type"] == "object"
    assert sing_defaults_data_properties["song_cache_days"]["type"] == "integer"
    assert sing_defaults_data_properties["song_cache_days"]["minimum"] == 1.0
    assert sing_defaults_data_properties["song_cache_days"]["maximum"] == 3650.0
    assert sing_defaults_data_properties["song_cache_size"]["type"] == "integer"
    assert sing_defaults_data_properties["song_cache_size"]["minimum"] == 0.0
    assert sing_defaults_data_properties["song_cache_size"]["maximum"] == 10000.0
    assert sing_defaults_data_properties["writable"]["anyOf"][0]["type"] == "boolean"
    assert "/pallas/api/common-config/llm/wizard/status" not in payload["paths"]

    local_routing_tasks = payload["components"]["schemas"]["_LlmLocalRoutingTaskModelsBody"]["properties"]
    assert set(local_routing_tasks) == {"llm_chat", "drunk"}

    wave2_paths = (
        "/pallas/api/shard-observability",
        "/pallas/api/ingress-dispatch",
        "/pallas/api/logs",
        "/pallas/api/plugins/{plugin_name}/governance",
        "/pallas/api/plugins/{plugin_name}/config",
    )
    for path in wave2_paths:
        assert path in payload["paths"], path
    shard_schema = payload["paths"]["/pallas/api/shard-observability"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    ingress_schema = payload["paths"]["/pallas/api/ingress-dispatch"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    logs_schema = payload["paths"]["/pallas/api/logs"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    governance_schema = payload["paths"]["/pallas/api/plugins/{plugin_name}/governance"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    config_schema = payload["paths"]["/pallas/api/plugins/{plugin_name}/config"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert shard_schema["$ref"].endswith("_ApiOkResponse_ShardObservabilityData_")
    assert ingress_schema["$ref"].endswith("_ApiOkResponse_IngressDispatchData_")
    assert logs_schema["$ref"].endswith("_ApiOkResponse_LogsData_")
    assert governance_schema["$ref"].endswith("_ApiOkResponse_PluginGovernanceData_")
    assert config_schema["$ref"].endswith("_ApiOkResponse_PluginConfigData_")


def test_llm_runtime_overview_returns_aggregated_fields(monkeypatch) -> None:
    async def fake_provider(*, timeout_sec: float = 0.0):
        _ = timeout_sec
        return {
            "ok": True,
            "configured": True,
            "url": "http://127.0.0.1:11434/v1/models",
            "status_code": 200,
            "error": "",
        }

    async def fake_health(*, timeout_sec: float = 0.0):
        _ = timeout_sec
        return {
            "ok": True,
            "url": "http://127.0.0.1:9099/health",
            "status_code": 200,
            "error": "",
            "body": {
                "image": {
                    "health_state": "healthy",
                    "degraded_state": "normal",
                    "backends": [{"circuit_state": "closed", "consecutive_failures": 0}],
                },
                "tts": {
                    "capability": "tts",
                    "health_state": "healthy",
                    "degraded_state": "normal",
                    "circuit_state": "closed",
                    "celery_enabled": False,
                },
                "media_tasks": {
                    "queue_depth": 1,
                    "active_tasks": 2,
                    "total_tasks": 3,
                    "health_state": "healthy",
                },
            },
        }

    async def fake_model_admin(*, timeout_sec: float = 0.0):
        _ = timeout_sec
        return {"model": "qwen", "ai_reachable": True, "provider_mode": "hybrid", "error": ""}

    async def fake_task_stats(*, timeout_sec: float = 0.0):
        _ = timeout_sec
        return {"bot": {"day_key": "2026-06-24"}, "ai": {}, "ai_reachable": True}

    monkeypatch.setattr("pallas.product.llm.ops_api.probe_llm_provider", fake_provider)
    monkeypatch.setattr("pallas.product.llm.ops_api.probe_ai_service_health", fake_health)
    monkeypatch.setattr("pallas.product.llm.ops_api.fetch_model_admin_status", fake_model_admin)
    monkeypatch.setattr("pallas.product.llm.ops_api.fetch_llm_task_stats", fake_task_stats)

    class _Gate:
        allowed = True
        status = ""

    monkeypatch.setattr(
        "pallas.product.llm.ops_api.assess_llm_kernel_submit_gate",
        lambda cfg=None: _Gate(),
    )

    async def fake_task_routing_preview():
        return {
            "llm_chat": {
                "primary_model": "qwen",
                "fallback_count": 1,
                "chain": [
                    {"task": "llm_chat", "resolved_model": "qwen", "source": "config", "fallback_models": ["fb"]},
                    {"task": "llm_chat", "resolved_model": "fb", "source": "fallback", "fallback_models": []},
                ],
            }
        }

    monkeypatch.setattr(
        "pallas.product.llm.ops_api.build_task_routing_preview",
        fake_task_routing_preview,
    )
    monkeypatch.setattr(
        mod,
        "build_conversation_kernel_status",
        lambda: {"feature_level": "full_conversation_kernel"},
    )

    client = _build_client(monkeypatch)
    response = client.get("/pallas/api/common-config/llm/runtime-overview")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    data = payload["data"]
    assert data["health"]["ok"] is True
    assert data["health"]["url"] == "http://127.0.0.1:11434/v1/models"
    assert data["health"]["llm_health"]["health_state"] == "healthy"
    assert data["health"]["llm_runtime_detail"] == "内核 Provider 可达"
    assert data["health"]["ai_service"]["ok"] is True
    assert data["health"]["ai_service"]["url"] == "http://127.0.0.1:9099/health"
    assert data["health"]["image_health"]["circuit_state"] == "closed"
    assert "draw_runtime_mode" in data["health"]
    assert data["health"]["draw_runtime_mode"] in (None, "plugin_runtime", "ai_service_runtime")
    assert data["health"]["media_tasks"]["queue_depth"] == 1
    assert data["model_admin"]["model"] == "qwen"
    assert data["task_stats"]["ai_reachable"] is True
    assert data["conversation_kernel"]["feature_level"] == "full_conversation_kernel"
    assert data["health"]["submit_gate"]["allowed"] is True
    assert data["task_routing_preview"]["llm_chat"]["primary_model"] == "qwen"


def test_ai_extension_test_returns_payload_without_validation_error(monkeypatch) -> None:
    import urllib.request

    class _FakeHTTPResponse:
        status = 200

        def read(self) -> bytes:
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(
        mod,
        "_load_ai_extension_config",
        lambda: {
            "base_url": "http://127.0.0.1:9099",
            "api_prefix": "/api",
            "token": "",
            "health_paths": ["/health"],
        },
    )
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: _FakeHTTPResponse())

    client = _build_client(monkeypatch)
    response = client.post("/pallas/api/ai-extension/test")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert "status_code" in payload["data"]
    assert "tried_urls" in payload["data"]


async def _fake_probe_provider(provider_id: str, *, cfg=None, timeout_sec: float = 15.0):
    _ = (provider_id, cfg, timeout_sec)
    return {"provider_id": "local", "reachable": True, "latency_ms": 26.4, "error": ""}


def test_llm_providers_put_ignores_readonly_metadata(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_save(document, **kwargs):
        _ = kwargs
        captured["document"] = document
        return {"providers_file": "/tmp/providers.toml", "provider_status": [], "task_routing": {}}

    monkeypatch.setattr("pallas.product.llm.ops_api.save_providers_config", fake_save)
    client = _build_client(monkeypatch)
    response = client.put(
        "/pallas/api/common-config/llm/providers",
        json={
            "providers": [],
            "routing": {"chain_fallback": [], "tasks": {}},
            "providers_file": "/tmp/x",
            "file_exists": True,
        },
    )
    assert response.status_code == 200, response.text
    assert captured["document"] == {"providers": [], "routing": {"chain_fallback": [], "tasks": {}}}


def test_llm_provider_test_accepts_float_latency(monkeypatch) -> None:
    monkeypatch.setattr("pallas.product.llm.ops_api.probe_provider", _fake_probe_provider)
    client = _build_client(monkeypatch)
    response = client.post("/pallas/api/common-config/llm/providers/local/test")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["reachable"] is True
    assert payload["data"]["latency_ms"] == 26.4
