"""Pallas-Bot WebUI console API: common-config routes."""

import asyncio
from datetime import date as _date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Header, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from packages.pb_webui.console_openapi_models import (
    PluginConfigData as _PluginConfigData,
)
from packages.pb_webui.console_openapi_models import (
    PluginConfigRawData as _PluginConfigRawData,
)
from packages.pb_webui.console_openapi_models import (
    _ApiOkResponse,
)
from pallas.product.llm.ops_api import BehaviorPattern, BehaviorScene, ensure_default_behavior_patterns
from pallas.product.persona.account_profile import AccountPersonaProfile

from .ai_extension_api import ai_extension_http_json
from .config import Config
from .console_read_cache import cached_read
from .extended_common import (
    check_pallas_write_token,
)


class _CommonConfigSectionPatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[str, Any] = Field(default_factory=dict)


CommonConfigSectionPatchBody = _CommonConfigSectionPatchBody


def _runtime_ext():
    from packages.pb_webui import extended_api

    return extended_api


class _LlmHealthProviderRow(BaseModel):
    id: str
    kind: str = ""
    enabled: bool = False
    configured: bool = False
    reachable: bool | None = None
    health_state: str | None = None
    circuit_state: str | None = None


class _LlmHealthSummaryData(BaseModel):
    health_state: str | None = None
    degraded_state: str | None = None
    circuit_state: str | None = None
    recent_failure_class: str | None = None
    consecutive_failures: int | None = None
    provider_status: list[_LlmHealthProviderRow] = Field(default_factory=list)


class _LlmImageHealthData(BaseModel):
    circuit_state: str | None = None
    consecutive_failures: int | None = None
    recent_failure_class: str | None = None
    health_state: str | None = None
    degraded_state: str | None = None


class _LlmTtsHealthData(BaseModel):
    capability: str | None = None
    health_state: str | None = None
    degraded_state: str | None = None
    circuit_state: str | None = None
    celery_enabled: bool | None = None


class _LlmMediaTaskCapabilityRow(BaseModel):
    capability: str
    queue_depth: int = 0
    active_tasks: int = 0
    health_state: str | None = None


class _LlmMediaTasksHealthData(BaseModel):
    queue_depth: int = 0
    active_tasks: int = 0
    total_tasks: int = 0
    health_state: str | None = None
    degraded_state: str | None = None
    circuit_state: str | None = None
    recent_failure_class: str | None = None
    capabilities: list[_LlmMediaTaskCapabilityRow] = Field(default_factory=list)


class _AiServiceHealthProbeData(BaseModel):
    """媒体扩展（AI Runtime）探活；与聊天 Provider 健康分离。"""

    ok: bool
    url: str = ""
    status_code: int | None = None
    error: str = ""


class _LlmRuntimeOverviewHealthData(BaseModel):
    # ok / url / status_code / error：内核 LLM Provider（聊天）
    ok: bool
    url: str = ""
    status_code: int | None = None
    error: str = ""
    llm_runtime_detail: str | None = None
    llm_health: _LlmHealthSummaryData | None = None
    llm_circuit: dict[str, Any] | None = None
    image_health: _LlmImageHealthData | None = None
    # 画画插件已装时多为 plugin_runtime；未装为 null（旧版可能为 ai_service_runtime）
    draw_runtime_mode: str | None = None
    tts_health: _LlmTtsHealthData | None = None
    media_tasks: _LlmMediaTasksHealthData | None = None
    # 唱歌 / 可选 AI 绘图运行时等媒体侧
    ai_service: _AiServiceHealthProbeData | None = None
    submit_gate: dict[str, Any] | None = None


class _LlmRuntimeOverviewData(BaseModel):
    health: _LlmRuntimeOverviewHealthData
    model_admin: dict[str, Any] = Field(default_factory=dict)
    task_stats: dict[str, Any] = Field(default_factory=dict)
    conversation_kernel: dict[str, Any] = Field(default_factory=dict)
    task_routing_preview: dict[str, Any] = Field(default_factory=dict)


class _ServiceProbeResultData(BaseModel):
    category: str
    site: str
    ok: bool
    latency_ms: int | None = None
    status_code: int | None = None
    error: str | None = None
    runtime_state: str | None = None
    runtime_detail: str | None = None
    capability_id: str | None = None
    capability_group: str | None = None
    runtime_type: str | None = None
    failure_class: str | None = None
    health_state: str | None = None
    circuit_state: str | None = None
    consecutive_failures: int | None = None
    recent_failure_class: str | None = None
    queue_load_hint: str | None = None


class _ServiceGatewaysConnectivityCheckData(BaseModel):
    lines: list[str] = Field(default_factory=list)
    results: list[_ServiceProbeResultData] = Field(default_factory=list)


class _LlmEmbeddingStatusData(BaseModel):
    embedding_provider: str = ""
    embedding_kind: str = ""
    embedding_model: str = ""
    resolved_model: str = ""
    semantic_available: bool = False
    embedding_fallback: bool = False
    embedding_error: str | None = None
    available_providers: list[str] = Field(default_factory=list)
    local_dependency_ready: bool = False
    local_default_model: str | None = None
    remote_default_model: str | None = None
    endpoint_configured: bool = False
    trigger_cache_count: int = 0
    trigger_cache_model: str | None = None
    probe_ok: bool | None = None
    probe_dims: int | None = None
    probe_ms: float | None = None


class _LlmEmbeddingProbeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(default="ping", max_length=200)


class _LlmSingDefaultsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_speaker: str | None = Field(default=None, max_length=64)
    preferred_backend: str | None = Field(default=None, max_length=64)
    speaker_backends: dict[str, str] | None = None
    song_cache_days: StrictInt | None = Field(default=None, ge=1, le=3650)
    song_cache_size: StrictInt | None = Field(default=None, ge=0, le=10000)


class _LlmSingDefaultsData(BaseModel):
    default_speaker: str
    preferred_backend: str
    speaker_backends: dict[str, str]
    song_cache_days: int = Field(ge=1, le=3650)
    song_cache_size: int = Field(ge=0, le=10000)
    writable: bool | None = None


class _PersonaObserveBotRow(BaseModel):
    account: int
    group_style_enabled: bool = True
    account_profile: AccountPersonaProfile
    base: dict[str, Any]
    base_hints: list[str] = Field(default_factory=list)
    resolved: dict[str, Any] | None = None
    resolved_hints: list[str] = Field(default_factory=list)


class _PersonaObserveData(BaseModel):
    group_id: int | None = None
    group_style_snapshot: dict[str, Any] | None = None
    affect_refine: dict[str, Any] | None = None
    affect_triggers: list[dict[str, Any]] = Field(default_factory=list)
    bots: list[_PersonaObserveBotRow] = Field(default_factory=list)


class _CommunityConnectivityProbeRow(BaseModel):
    url: str
    ok: bool
    latency_ms: int | None = None
    http_status: int | None = None
    error: str | None = None


class _CommunityConnectivityReporting(BaseModel):
    enabled: bool = True
    endpoint: str = ""
    active_heartbeat_endpoint: str | None = None
    deployment_id: str | None = None
    last_heartbeat_ok_unix: int | None = None
    last_primary_probe_unix: int | None = None


class _CommunityConnectivitySummary(BaseModel):
    any_ok: bool = False
    hint: str = ""


class _CommunityConnectivityCheckData(BaseModel):
    probes: list[_CommunityConnectivityProbeRow]
    reporting: _CommunityConnectivityReporting
    summary: _CommunityConnectivitySummary


class _LlmModelPricingRowData(BaseModel):
    """模型单价：币种见 routing.cost_currency；单位为「每百万 tokens」。"""

    price_in: float = 0.0
    price_out: float = 0.0
    cache_price_in: float = 0.0
    cache_price_out: float = 0.0


class _LlmProviderConfigRowData(BaseModel):
    id: str
    kind: str
    base_url: str = ""
    api_key: str = ""
    api_keys: list[str] = Field(default_factory=list)
    api_key_hints: list[str] = Field(default_factory=list)
    api_key_env: str = ""
    api_key_set: bool = False
    api_keys_count: int = 0
    default_model: str = ""
    models: list[dict[str, Any]] = Field(default_factory=list)
    enabled: bool = False
    task_models: dict[str, str] = Field(default_factory=dict)
    capabilities: list[str] = Field(default_factory=list)
    model_effort: str = ""
    request_method: str = "chat_completions"
    model_pricing: dict[str, _LlmModelPricingRowData] = Field(default_factory=dict)


class _LlmProvidersRoutingData(BaseModel):
    chain_fallback: list[str] = Field(default_factory=list)
    tasks: dict[str, str] = Field(default_factory=dict)
    tier_backups: dict[str, str] = Field(default_factory=dict)
    tier_backup_models: dict[str, str] = Field(default_factory=dict)
    task_backups: dict[str, str] = Field(default_factory=dict)
    task_backup_models: dict[str, str] = Field(default_factory=dict)
    route_source: str = ""
    cost_currency: str = ""


class _LlmProvidersConfigData(BaseModel):
    providers: list[_LlmProviderConfigRowData] = Field(default_factory=list)
    routing: _LlmProvidersRoutingData = Field(default_factory=_LlmProvidersRoutingData)
    providers_file: str = ""
    file_exists: bool = False


class _LlmProviderTestData(BaseModel):
    provider_id: str
    reachable: bool
    latency_ms: float | None = None
    error: str | None = None
    status: int | None = None
    enabled: bool | None = None


class _AiExtensionTestData(BaseModel):
    ok: bool
    status_code: int | None = None
    health_url: str = ""
    tried_urls: list[str] = Field(default_factory=list)
    error: str | None = None
    media_tasks: _LlmMediaTasksHealthData | None = None
    llm_detail: str | None = None
    image_circuit: _LlmImageHealthData | None = None
    llm_health: _LlmHealthSummaryData | None = None
    tts_health: _LlmTtsHealthData | None = None


class _AuthLoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=512)


class _ChangeConsoleLoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_password: str = Field(min_length=1, max_length=256)


class _RequestActionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    self_id: int = Field(ge=1)
    kind: Literal["friend", "group"]
    action: Literal["approve", "reject"] = "approve"
    source: Literal["pending", "doubt"] = "pending"
    user_id: int | None = Field(default=None, ge=1)
    group_id: int | None = Field(default=None, ge=1)


class _RequestBatchFriendRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    self_id: int = Field(ge=1)
    user_id: int = Field(ge=1)
    source: Literal["pending", "doubt"] = "pending"


class _RequestBatchGroupRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    self_id: int = Field(ge=1)
    user_id: int = Field(ge=1)
    group_id: int = Field(ge=1)


class _LlmModelSwitchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1, max_length=200)
    pull: bool = True


class _LlmModelNumGpuBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    num_gpu: int = Field(ge=0, le=999)


class _LlmModelPricingRowBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price_in: float = Field(default=0.0, ge=0)
    price_out: float = Field(default=0.0, ge=0)
    cache_price_in: float = Field(default=0.0, ge=0)
    cache_price_out: float = Field(default=0.0, ge=0)


class _LlmProviderRowBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    kind: str = Field(default="remote")
    base_url: str = ""
    api_key: str = ""
    api_keys: list[str] = Field(default_factory=list)
    api_key_env: str = ""
    clear_api_keys: bool = False
    default_model: str = ""
    models: list[dict[str, Any]] = Field(default_factory=list)
    enabled: bool = True
    task_models: dict[str, str] = Field(default_factory=dict)
    capabilities: list[str] = Field(default_factory=list)
    model_effort: str = ""
    request_method: str = "chat_completions"
    model_pricing: dict[str, _LlmModelPricingRowBody] = Field(default_factory=dict)


class _LlmProvidersRoutingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chain_fallback: list[str] = Field(default_factory=list)
    tasks: dict[str, str] = Field(default_factory=dict)
    tier_backups: dict[str, str] = Field(default_factory=dict)
    tier_backup_models: dict[str, str] = Field(default_factory=dict)
    task_backups: dict[str, str] = Field(default_factory=dict)
    task_backup_models: dict[str, str] = Field(default_factory=dict)
    route_source: str = ""
    cost_currency: str = ""


class _LlmProvidersDocumentBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    providers: list[_LlmProviderRowBody] = Field(default_factory=list)
    routing: _LlmProvidersRoutingBody = Field(default_factory=_LlmProvidersRoutingBody)


class _LlmProviderModelsDiscoverBody(BaseModel):
    """Bot 直连发现模型：由控制台传入草稿凭证，不经 AI Runtime。"""

    model_config = ConfigDict(extra="forbid")

    base_url: str = ""
    api_key: str = ""
    api_key_env: str = ""
    kind: str = ""
    request_method: str = ""


class _LlmProviderRenameBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_id: str = Field(min_length=1, max_length=200)


class _LlmLocalRoutingModelsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    simple: str = ""
    medium: str = ""
    complex: str = ""
    vision: str = ""


class _LlmLocalRoutingTaskModelsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm_chat: str = ""
    drunk: str = ""
    affect_refine: str = ""
    turn_decision: str = ""


class _LlmLocalRoutingConfigBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm_model: str = Field(default="", max_length=200)
    local_multi_model_enabled: bool = False
    moe_models: _LlmLocalRoutingModelsBody = Field(default_factory=_LlmLocalRoutingModelsBody)
    task_models: _LlmLocalRoutingTaskModelsBody = Field(default_factory=_LlmLocalRoutingTaskModelsBody)
    env_file: str = ""


class _PluginConfigRawBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    toml: str = ""


class LlmReplayRunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str = "mock_tools"


PluginConfigRawBody = _PluginConfigRawBody
LlmModelSwitchBody = _LlmModelSwitchBody
LlmModelNumGpuBody = _LlmModelNumGpuBody
LlmLocalRoutingConfigBody = _LlmLocalRoutingConfigBody
LlmProvidersDocumentBody = _LlmProvidersDocumentBody
LlmProviderRowBody = _LlmProviderRowBody
LlmProviderModelsDiscoverBody = _LlmProviderModelsDiscoverBody
LlmProviderRenameBody = _LlmProviderRenameBody


def register_common_config_router(
    router: APIRouter,
    *,
    x: str,
    plugin_config: Config,
    router_pub: APIRouter | None = None,
) -> None:
    """Register console routes."""

    @router.get(f"{x}/common-config/sections", include_in_schema=True)
    async def _common_config_sections_list() -> JSONResponse:
        from pallas.console.webui.env_sections import list_webui_env_sections

        return JSONResponse({"ok": True, "data": list_webui_env_sections()})

    @router.get(f"{x}/common-config/{{section_id}}", include_in_schema=True)
    async def _common_config_get(section_id: str) -> JSONResponse:
        from pallas.console.webui.env_sections import webui_env_section_payload

        try:
            data = webui_env_section_payload(section_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.put(f"{x}/common-config/{{section_id}}", include_in_schema=True)
    async def _common_config_put(
        section_id: str,
        body: CommonConfigSectionPatchBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.console.webui.env_sections import apply_webui_env_section_patch

        try:
            data = apply_webui_env_section_patch(section_id, dict(body.values or {}))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(
        f"{x}/common-config/{{section_id}}/raw",
        include_in_schema=True,
        response_model=_ApiOkResponse[_PluginConfigRawData],
    )
    async def _common_config_raw_get(section_id: str) -> dict[str, Any]:
        from pallas.console.webui.env_sections import webui_env_section_raw_toml

        try:
            text = webui_env_section_raw_toml(section_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"ok": True, "data": {"toml": text}}

    @router.put(
        f"{x}/common-config/{{section_id}}/raw",
        include_in_schema=True,
        response_model=_ApiOkResponse[_PluginConfigData],
    )
    async def _common_config_raw_put(
        section_id: str,
        body: PluginConfigRawBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> dict[str, Any]:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.console.webui.env_sections import apply_webui_env_section_raw_toml

        try:
            data = apply_webui_env_section_raw_toml(section_id, str(body.toml or ""))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"ok": True, "data": data}

    @router.post(
        f"{x}/common-config/service_gateways/connectivity-check",
        include_in_schema=True,
        response_model=_ApiOkResponse[_ServiceGatewaysConnectivityCheckData],
    )
    async def _service_gateways_connectivity_check(
        body: CommonConfigSectionPatchBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> dict[str, Any]:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.core.shared.service_probe import format_probe_lines
        from pallas.product.service_gateways.collect import probe_all_connectivity_from_draft

        try:
            results = await probe_all_connectivity_from_draft(dict(body.values or {}))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        lines = format_probe_lines(results)
        return {
            "ok": True,
            "data": {
                "lines": lines,
                "results": [r.to_dict() for r in results],
            },
        }

    @router.get(f"{x}/common-config/llm/model-admin", include_in_schema=True)
    async def _llm_model_admin_get() -> JSONResponse:
        from pallas.product.llm.ops_api import fetch_model_admin_status

        try:
            data = await fetch_model_admin_status()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(
        f"{x}/common-config/llm/embedding-status",
        include_in_schema=True,
        response_model=_ApiOkResponse[_LlmEmbeddingStatusData],
    )
    async def _llm_embedding_status_get() -> dict[str, Any]:
        from pallas.product.llm.knowledge.embedding_provider import build_embedding_status

        try:
            data = await asyncio.to_thread(build_embedding_status, probe=False)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return {"ok": True, "data": data}

    @router.post(
        f"{x}/common-config/llm/embedding-status/probe",
        include_in_schema=True,
        response_model=_ApiOkResponse[_LlmEmbeddingStatusData],
    )
    async def _llm_embedding_status_probe(
        body: _LlmEmbeddingProbeBody | None = None,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> dict[str, Any]:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.knowledge.embedding_provider import build_embedding_status

        probe_text = str(getattr(body, "text", None) or "ping")
        try:
            data = await asyncio.to_thread(build_embedding_status, probe=True, probe_text=probe_text)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return {"ok": True, "data": data}

    async def _llm_model_admin_switch(
        body: LlmModelSwitchBody,
        *,
        token: str | None,
        x_pallas_token: str | None,
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import switch_runtime_model

        try:
            data = await switch_runtime_model(body.model, pull=body.pull)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/common-config/llm/model-admin/switch", include_in_schema=True)
    async def _llm_model_admin_switch_post(
        body: LlmModelSwitchBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        return await _llm_model_admin_switch(body, token=token, x_pallas_token=x_pallas_token)

    @router.post(f"{x}/common-config/llm/model-admin", include_in_schema=True)
    async def _llm_model_admin_post(
        body: LlmModelSwitchBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        return await _llm_model_admin_switch(body, token=token, x_pallas_token=x_pallas_token)

    @router.put(f"{x}/common-config/llm/model-admin", include_in_schema=True)
    async def _llm_model_admin_put(
        body: LlmModelSwitchBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        return await _llm_model_admin_switch(body, token=token, x_pallas_token=x_pallas_token)

    @router.post(f"{x}/common-config/llm/model-admin/reload", include_in_schema=True)
    async def _llm_model_admin_reload(
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import reload_runtime_model

        try:
            data = await reload_runtime_model()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/common-config/llm/model-admin/num-gpu", include_in_schema=True)
    async def _llm_model_admin_num_gpu(
        body: LlmModelNumGpuBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import set_runtime_num_gpu

        try:
            data = await set_runtime_num_gpu(body.num_gpu)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/common-config/llm/model-admin/unload", include_in_schema=True)
    async def _llm_model_admin_unload(
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import unload_runtime_model

        try:
            await unload_runtime_model()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": {"status": "ok"}})

    @router.get(
        f"{x}/common-config/llm/providers",
        include_in_schema=True,
        response_model=_ApiOkResponse[_LlmProvidersConfigData],
    )
    async def _llm_providers_get() -> dict[str, Any]:
        from pallas.product.llm.ops_api import fetch_providers_config

        try:
            data = await fetch_providers_config()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return {"ok": True, "data": data}

    @router.get(f"{x}/common-config/llm/local-routing", include_in_schema=True)
    async def _llm_local_routing_get() -> JSONResponse:
        from pallas.product.llm.ops_api import fetch_local_routing_config

        try:
            data = await fetch_local_routing_config()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.put(f"{x}/common-config/llm/local-routing", include_in_schema=True)
    async def _llm_local_routing_put(
        body: LlmLocalRoutingConfigBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import save_local_routing_config

        try:
            data = await save_local_routing_config(body.model_dump())
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.put(f"{x}/common-config/llm/providers", include_in_schema=True)
    async def _llm_providers_put(
        body: LlmProvidersDocumentBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import save_providers_config

        try:
            data = await save_providers_config(body.model_dump(exclude_unset=True))
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.put(f"{x}/common-config/llm/providers/{{provider_id}}", include_in_schema=True)
    async def _llm_provider_upsert_put(
        provider_id: str,
        body: LlmProviderRowBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        """只保存单个提供方，避免整表写回时误擦其他提供方密钥。"""
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import upsert_provider_config

        payload = body.model_dump(exclude_unset=True)
        payload["id"] = str(provider_id or "").strip() or str(payload.get("id") or "").strip()
        if not payload["id"]:
            raise HTTPException(status_code=400, detail="provider id is required")
        try:
            data = await upsert_provider_config(payload)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.put(f"{x}/common-config/llm/providers/{{provider_id}}/rename", include_in_schema=True)
    async def _llm_provider_rename_put(
        provider_id: str,
        body: LlmProviderRenameBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        """改提供方 ID：改行内 id 并同步 routing / 主配置引用。"""
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import rename_provider_config

        try:
            data = await rename_provider_config(provider_id, body.new_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/common-config/llm/providers/{{provider_id}}/models", include_in_schema=True)
    async def _llm_provider_models_get(provider_id: str) -> JSONResponse:
        from pallas.product.llm.ops_api import fetch_provider_models

        try:
            data = await fetch_provider_models(provider_id)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(
        f"{x}/common-config/llm/providers/{{provider_id}}/models",
        include_in_schema=True,
    )
    async def _llm_provider_models_post(
        provider_id: str,
        body: LlmProviderModelsDiscoverBody | None = None,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import fetch_provider_models

        payload = body or _LlmProviderModelsDiscoverBody()
        try:
            data = await fetch_provider_models(
                provider_id,
                base_url=payload.base_url,
                api_key=payload.api_key,
                api_key_env=payload.api_key_env,
                kind=payload.kind,
                request_method=payload.request_method,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(
        f"{x}/common-config/llm/providers/{{provider_id}}/test",
        include_in_schema=True,
        response_model=_ApiOkResponse[_LlmProviderTestData],
    )
    async def _llm_provider_test_post(
        provider_id: str,
        body: LlmProviderModelsDiscoverBody | None = None,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> dict[str, Any]:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import probe_provider

        payload = body or _LlmProviderModelsDiscoverBody()
        try:
            data = await probe_provider(
                provider_id,
                base_url=payload.base_url,
                api_key=payload.api_key,
                api_key_env=payload.api_key_env,
                kind=payload.kind,
                request_method=payload.request_method,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return {"ok": True, "data": data}

    @router.get(f"{x}/common-config/llm/task-stats", include_in_schema=True)
    async def _llm_task_stats_get(
        start: str | None = Query(default=None, description="YYYY-MM-DD，含当日"),
        end: str | None = Query(default=None, description="YYYY-MM-DD，含当日"),
    ) -> JSONResponse:
        from pallas.product.llm.ops_api import fetch_llm_task_stats

        try:
            data = await fetch_llm_task_stats(start=start, end=end)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(
        f"{x}/common-config/llm/usage-ledger/export",
        include_in_schema=True,
    )
    async def _llm_usage_ledger_export(
        start: str = Query(description="YYYY-MM-DD，含当日"),
        end: str = Query(description="YYYY-MM-DD，含当日"),
    ) -> StreamingResponse:
        """导出请求级 usage 账本明细 CSV（llm_usage JSONL 原始记录）。"""
        from pallas.product.llm.usage_ledger import count_ledger_rows, iter_usage_csv_lines

        try:
            start_day = _date.fromisoformat(str(start).strip()[:10]).isoformat()
            end_day = _date.fromisoformat(str(end).strip()[:10]).isoformat()
        except ValueError as e:
            raise HTTPException(status_code=400, detail="start/end 需为 YYYY-MM-DD") from e
        if start_day > end_day:
            start_day, end_day = end_day, start_day
        return StreamingResponse(
            iter_usage_csv_lines(start_day=start_day, end_day=end_day),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": (f'attachment; filename="pallas-ai-usage-detail_{start_day}_{end_day}.csv"'),
                "X-Usage-Rows": str(count_ledger_rows(start_day, end_day)),
            },
        )

    @router.get(
        f"{x}/common-config/llm/media-assets/status",
        include_in_schema=True,
    )
    async def _llm_media_assets_status_get() -> JSONResponse:
        from pallas.product.llm.ops_api import fetch_media_assets_status

        data = await fetch_media_assets_status()
        return JSONResponse({"ok": True, "data": data})

    @router.post(
        f"{x}/common-config/llm/media-assets/download",
        include_in_schema=True,
    )
    async def _llm_media_assets_download_post(body: dict[str, Any] | None = None) -> JSONResponse:
        from pallas.product.llm.ops_api import start_media_assets_download

        assets = None
        if isinstance(body, dict) and isinstance(body.get("assets"), list):
            assets = [str(a) for a in body["assets"]]
        try:
            data = await start_media_assets_download(assets=assets)
        except PermissionError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(
        f"{x}/common-config/llm/media-assets/delete",
        include_in_schema=True,
    )
    async def _llm_media_assets_delete_post(body: dict[str, Any]) -> JSONResponse:
        from pallas.product.llm.ops_api import delete_media_assets

        assets = body.get("assets") if isinstance(body, dict) else None
        if not isinstance(assets, list) or not assets:
            raise HTTPException(status_code=400, detail="assets 不能为空")
        try:
            data = await delete_media_assets(assets=[str(a) for a in assets])
        except PermissionError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(
        f"{x}/common-config/llm/media-assets/download/jobs/active",
        include_in_schema=True,
    )
    async def _llm_media_assets_download_job_active_get() -> JSONResponse:
        from pallas.product.llm.ops_api import fetch_media_assets_download_active

        try:
            data = await fetch_media_assets_download_active()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(
        f"{x}/common-config/llm/media-assets/download/jobs/{{job_id}}",
        include_in_schema=True,
    )
    async def _llm_media_assets_download_job_get(job_id: str) -> JSONResponse:
        from pallas.product.llm.ops_api import fetch_media_assets_download_job

        try:
            data = await fetch_media_assets_download_job(job_id)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(
        f"{x}/common-config/llm/media-models/sing/speakers",
        include_in_schema=True,
    )
    async def _llm_media_models_sing_speakers_get() -> JSONResponse:
        from pallas.product.llm.ops_api import fetch_sing_speakers

        try:
            data = await fetch_sing_speakers()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(
        f"{x}/common-config/llm/media-models/sing/backends",
        include_in_schema=True,
    )
    async def _llm_media_models_sing_backends_get() -> JSONResponse:
        from pallas.product.llm.ops_api import fetch_sing_backends

        try:
            data = await fetch_sing_backends()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(
        f"{x}/common-config/llm/media-models/sing/defaults",
        include_in_schema=True,
    )
    async def _llm_media_models_sing_defaults_get() -> JSONResponse:
        from pallas.product.llm.ops_api import fetch_sing_defaults

        try:
            data = await fetch_sing_defaults()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.put(
        f"{x}/common-config/llm/media-models/sing/defaults",
        include_in_schema=True,
        response_model=_ApiOkResponse[_LlmSingDefaultsData],
        response_model_exclude_none=True,
    )
    async def _llm_media_models_sing_defaults_put(body: _LlmSingDefaultsBody) -> JSONResponse:
        from pallas.product.llm.ops_api import put_sing_defaults

        payload = body.model_dump(exclude_none=True)
        if not payload:
            raise HTTPException(
                status_code=400,
                detail=(
                    "至少提供 default_speaker、preferred_backend、speaker_backends、song_cache_days 或 song_cache_size"
                ),
            )
        try:
            data = await put_sing_defaults(payload)
        except PermissionError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return {"ok": True, "data": data}

    @router.get(
        f"{x}/common-config/llm/media-models/tts/voices",
        include_in_schema=True,
    )
    async def _llm_media_models_tts_voices_get() -> JSONResponse:
        from pallas.product.llm.ops_api import fetch_tts_voices

        try:
            data = await fetch_tts_voices()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(
        f"{x}/common-config/llm/media-models/tts/defaults",
        include_in_schema=True,
    )
    async def _llm_media_models_tts_defaults_get() -> JSONResponse:
        from pallas.product.llm.ops_api import fetch_tts_defaults

        try:
            data = await fetch_tts_defaults()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.put(
        f"{x}/common-config/llm/media-models/tts/defaults",
        include_in_schema=True,
    )
    async def _llm_media_models_tts_defaults_put(body: dict[str, Any]) -> JSONResponse:
        from pallas.product.llm.ops_api import put_tts_defaults

        try:
            data = await put_tts_defaults(body if isinstance(body, dict) else {})
        except PermissionError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(
        f"{x}/common-config/llm/media-models/tts/translator",
        include_in_schema=True,
    )
    async def _llm_media_models_tts_translator_get() -> JSONResponse:
        from pallas.product.llm.ops_api import fetch_tts_translator

        try:
            data = await fetch_tts_translator()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.put(
        f"{x}/common-config/llm/media-models/tts/translator",
        include_in_schema=True,
    )
    async def _llm_media_models_tts_translator_put(body: dict[str, Any]) -> JSONResponse:
        from pallas.product.llm.ops_api import put_tts_translator

        try:
            data = await put_tts_translator(body if isinstance(body, dict) else {})
        except PermissionError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(
        f"{x}/common-config/llm/runtime-overview",
        include_in_schema=True,
        response_model=_ApiOkResponse[_LlmRuntimeOverviewData],
    )
    async def _llm_runtime_overview_get() -> dict[str, Any]:
        from pallas.product.llm.ops_api import (
            assess_llm_kernel_submit_gate,
            build_task_routing_preview,
            fetch_llm_task_stats,
            fetch_model_admin_status,
            image_health_circuit,
            llm_health_from_provider_probe,
            llm_runtime_detail_from_provider_probe,
            parse_media_tasks,
            probe_ai_service_health,
            probe_llm_provider,
            tts_health_summary,
        )

        def _draw_runtime_mode() -> str | None:
            try:
                from pallas.core.platform.plugin_runtime.resolve import import_plugin_submodule

                draw_config = import_plugin_submodule("draw", "config")
                settings = draw_config.active_image_gen_settings()
                # Draw ≥4.1.0 仅插件直连；旧版插件仍可能有 runtime_mode
                mode = str(getattr(settings, "runtime_mode", None) or "plugin_runtime").strip()
                return mode or None
            except Exception:  # noqa: BLE001
                return None

        async def _load() -> dict[str, Any]:
            provider, ai_health, model_admin, task_stats = await asyncio.gather(
                probe_llm_provider(timeout_sec=8.0),
                probe_ai_service_health(timeout_sec=8.0),
                fetch_model_admin_status(timeout_sec=12.0),
                fetch_llm_task_stats(timeout_sec=8.0),
            )
            body = ai_health.get("body") if isinstance(ai_health.get("body"), dict) else None
            provider_ok = bool(provider.get("ok"))
            llm_health = llm_health_from_provider_probe(provider)
            submit_gate = assess_llm_kernel_submit_gate()
            return {
                "health": {
                    "ok": provider_ok,
                    "url": str(provider.get("url") or ""),
                    "status_code": provider.get("status_code"),
                    "error": "" if provider_ok else str(provider.get("error") or ""),
                    "llm_runtime_detail": llm_runtime_detail_from_provider_probe(provider),
                    "llm_health": llm_health,
                    "llm_circuit": {
                        "circuit_state": llm_health.get("circuit_state"),
                        "consecutive_failures": int(llm_health.get("consecutive_failures") or 0),
                        "recent_failure_class": llm_health.get("recent_failure_class"),
                        "health_state": llm_health.get("health_state"),
                        "degraded_state": llm_health.get("degraded_state"),
                    },
                    "image_health": image_health_circuit(body) if body else None,
                    "draw_runtime_mode": _draw_runtime_mode(),
                    "tts_health": tts_health_summary(body) if body else None,
                    "media_tasks": parse_media_tasks(body) if body else None,
                    "ai_service": {
                        "ok": bool(ai_health.get("ok")),
                        "url": str(ai_health.get("url") or ""),
                        "status_code": ai_health.get("status_code"),
                        "error": str(ai_health.get("error") or ""),
                    },
                    "submit_gate": {
                        "allowed": submit_gate.allowed,
                        "status": submit_gate.status or None,
                    },
                },
                "model_admin": model_admin,
                "task_stats": task_stats,
                "conversation_kernel": _runtime_ext().build_conversation_kernel_status(),
                "task_routing_preview": await build_task_routing_preview(),
            }

        data = await cached_read(key="llm-runtime-overview", loader=_load, ttl_sec=2.0, stale_sec=8.0)
        return {"ok": True, "data": data}

    @router.get(f"{x}/common-config/llm/history/sessions", include_in_schema=True)
    async def _llm_history_sessions_get(
        bot_id: int | None = Query(default=None, ge=1, description="Bot QQ；省略则不过滤"),
        group_id: int | None = Query(default=None, ge=0, description="群号；0 表示私聊"),
        user_id: int | None = Query(default=None, ge=1, description="用户 QQ；省略则返回最近会话列表"),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> JSONResponse:
        from pallas.product.llm.ops_api import list_llm_history_sessions

        try:
            rows = await list_llm_history_sessions(
                bot_id=bot_id,
                group_id=group_id,
                user_id=user_id,
                limit=limit,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({
            "ok": True,
            "data": {
                "items": [row.model_dump() if hasattr(row, "model_dump") else row for row in rows],
                "limit": limit,
            },
        })

    @router.get(f"{x}/common-config/llm/history/session", include_in_schema=True)
    async def _llm_history_session_get(
        bot_id: int = Query(..., ge=1, description="Bot QQ"),
        group_id: int | None = Query(default=None, ge=0, description="群号；0 表示私聊"),
        user_id: int = Query(..., ge=1, description="用户 QQ"),
        limit: int = Query(default=100, ge=1, le=200),
    ) -> JSONResponse:
        from pallas.product.llm.ops_api import get_llm_history_session_detail

        try:
            data = await get_llm_history_session_detail(
                bot_id=bot_id,
                group_id=group_id,
                user_id=user_id,
                limit=limit,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if data is None:
            raise HTTPException(status_code=404, detail="未找到该 AI 会话")
        return JSONResponse({"ok": True, "data": data.model_dump() if hasattr(data, "model_dump") else data})

    @router.post(f"{x}/common-config/llm/history/behavior/annotate", include_in_schema=True)
    async def _llm_history_behavior_annotate(body: dict[str, Any]) -> JSONResponse:
        from pallas.product.llm.ops_api import update_llm_behavior_annotation

        request_id = str(body.get("request_id") or "").strip()
        if not request_id:
            raise HTTPException(status_code=400, detail="缺少 request_id")
        try:
            data = await update_llm_behavior_annotation(
                request_id=request_id,
                labels=[str(item).strip() for item in list(body.get("labels") or []) if str(item).strip()],
                final_outcome=str(body.get("final_outcome") or "").strip() or None,
                disabled=body.get("disabled"),
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if data is None:
            raise HTTPException(status_code=404, detail="未找到该 behavior 记录")
        return JSONResponse({"ok": True, "data": data.model_dump() if hasattr(data, "model_dump") else data})

    @router.get(f"{x}/common-config/llm/behavior/patterns", include_in_schema=True)
    async def _llm_behavior_patterns_get(
        group_id: int | None = Query(default=None, ge=1, description="群号；省略则查看全部 pattern"),
        scene: str | None = Query(default=None, description="scene 过滤"),
        include_disabled: bool = Query(default=True, description="是否包含 disabled pattern"),
    ) -> JSONResponse:
        try:
            target_scene = BehaviorScene(str(scene).strip()) if scene else None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"非法 scene: {scene}") from e
        try:
            items = ensure_default_behavior_patterns()
            if target_scene is not None:
                items = [item for item in items if item.scene == target_scene]
            if group_id is not None:
                target_group_id = int(group_id)
                items = [
                    item for item in items if item.scope_group_id is None or int(item.scope_group_id) == target_group_id
                ]
            if not include_disabled:
                items = [item for item in items if not item.disabled]
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({
            "ok": True,
            "data": {
                "items": [item.model_dump(mode="json") for item in items],
                "count": len(items),
            },
        })

    @router.post(f"{x}/common-config/llm/behavior/patterns/upsert", include_in_schema=True)
    async def _llm_behavior_patterns_upsert(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        try:
            data = _runtime_ext().upsert_behavior_pattern(BehaviorPattern.model_validate(body))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data.model_dump(mode="json")})

    @router.post(f"{x}/common-config/llm/behavior/patterns/delete", include_in_schema=True)
    async def _llm_behavior_patterns_delete(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        pattern_id = str(body.get("pattern_id") or "").strip()
        if not pattern_id:
            raise HTTPException(status_code=400, detail="缺少 pattern_id")
        try:
            ok = _runtime_ext().delete_behavior_pattern(pattern_id)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if not ok:
            raise HTTPException(status_code=404, detail="未找到该 behavior pattern")
        return JSONResponse({"ok": True, "data": {"pattern_id": pattern_id}})

    @router.get(f"{x}/common-config/llm/behavior/runs", include_in_schema=True)
    async def _llm_behavior_runs_get(
        group_id: int | None = Query(default=None, ge=1, description="群号"),
        scene: str | None = Query(default=None, description="scene 过滤"),
        final_outcome: str | None = Query(default=None, description="outcome 过滤"),
        include_disabled: bool = Query(default=True, description="是否包含 disabled run"),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> JSONResponse:
        try:
            target_scene = BehaviorScene(str(scene).strip()) if scene else None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"非法 scene: {scene}") from e
        try:
            items = _runtime_ext().list_behavior_runs(limit=limit)
            filtered: list[dict[str, Any]] = []
            for item in items:
                row = item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
                if target_scene is not None and str(row.get("scene") or "") != target_scene.value:
                    continue
                if group_id is not None and int(row.get("group_id") or 0) != int(group_id):
                    continue
                if final_outcome and str(row.get("final_outcome") or "") != str(final_outcome).strip():
                    continue
                if not include_disabled and bool(row.get("disabled")):
                    continue
                filtered.append(row)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": {"items": filtered, "count": len(filtered), "limit": limit}})

    @router.get(f"{x}/common-config/llm/runtime-debug/{{request_id}}", include_in_schema=True)
    async def _llm_runtime_debug_get(request_id: str) -> JSONResponse:
        from pallas.product.llm.ops_api import load_runtime_debug_bundle
        from pallas.product.llm.runtime_debug import build_runtime_debug_webui_view

        rid = str(request_id or "").strip()
        if not rid:
            raise HTTPException(status_code=400, detail="缺少 request_id")
        data = build_runtime_debug_webui_view(load_runtime_debug_bundle(request_id=rid))
        if not data.get("snapshot") and not data.get("trace"):
            raise HTTPException(status_code=404, detail="未找到 runtime debug 记录")
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/common-config/llm/runtime-debug/{{request_id}}/replay", include_in_schema=True)
    async def _llm_runtime_replay_get(
        request_id: str,
        mode: str = Query(default="mock_tools"),
    ) -> JSONResponse:
        from pallas.product.llm.ops_api import build_replay_payload

        rid = str(request_id or "").strip()
        if not rid:
            raise HTTPException(status_code=400, detail="缺少 request_id")
        payload = build_replay_payload(request_id=rid, mode=str(mode or "mock_tools"))
        if payload.get("error") == "snapshot_not_found":
            raise HTTPException(status_code=404, detail="未找到 request snapshot")
        return JSONResponse({"ok": True, "data": payload})

    @router.post(f"{x}/common-config/llm/runtime-debug/{{request_id}}/replay/run", include_in_schema=True)
    async def _llm_runtime_replay_run_post(
        request_id: str,
        body: Annotated[LlmReplayRunBody, Body()],
    ) -> JSONResponse:
        from pallas.product.llm.ops_api import build_replay_payload

        rid = str(request_id or "").strip()
        if not rid:
            raise HTTPException(status_code=400, detail="缺少 request_id")
        payload = build_replay_payload(request_id=rid, mode=str(body.mode or "mock_tools"))
        if payload.get("error") == "snapshot_not_found":
            raise HTTPException(status_code=404, detail="未找到 request snapshot")
        replay_result = await ai_extension_http_json(method="POST", path="/v1/chat/replay", body=payload)
        if not replay_result.get("ok"):
            detail = replay_result.get("error") or replay_result.get("data") or "AI replay failed"
            raise HTTPException(status_code=int(replay_result.get("status_code") or 502), detail=detail)
        return JSONResponse({"ok": True, "data": replay_result.get("data") or {}})

    @router.get(
        f"{x}/common-config/llm/persona-observe",
        include_in_schema=True,
        response_model=_ApiOkResponse[_PersonaObserveData],
    )
    async def _llm_persona_observe_get(
        group_id: int | None = Query(default=None, ge=1, description="群号；省略则仅展示 bot 基线"),
        accounts: str | None = Query(default=None, description="逗号分隔 bot account，省略则全部"),
    ) -> dict[str, Any]:
        from pallas.product.persona.observe import build_persona_observe_payload, parse_observe_accounts

        try:
            data = await build_persona_observe_payload(
                group_id=group_id,
                accounts=parse_observe_accounts(accounts),
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return {"ok": True, "data": data}
