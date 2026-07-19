"""控制台 OpenAPI response_model（codegen 第二波）。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiOkResponse[T](BaseModel):
    ok: Literal[True] = True
    data: T
    error: None = None


class ApiErrResponse(BaseModel):
    ok: Literal[False] = False
    error: str = ""
    data: Any = None


class ConsoleSetupStatusData(BaseModel):
    auth_configured: bool
    setup_completed: bool
    default_password_active: bool
    requires_setup: bool
    first_completed_at: str | None = None
    updated_at: str | None = None


class ConsoleLoginChangeData(BaseModel):
    message: str


class LlmWizardCheckRow(BaseModel):
    id: str
    label: str
    ok: bool
    detail: str = ""


class LlmWizardStatusData(BaseModel):
    ai_reachable: bool
    health_url: str = ""
    model: str = ""
    provider_mode: str = ""
    llm_chat_enabled: bool
    llm_tools_enabled: bool = False
    providers_configured: int = 0
    providers_reachable: int = 0
    checks: list[LlmWizardCheckRow] = Field(default_factory=list)
    next_step: str = ""


class LlmHealthProviderRow(BaseModel):
    id: str
    kind: str = ""
    enabled: bool = False
    configured: bool = False
    reachable: bool | None = None
    health_state: str | None = None
    circuit_state: str | None = None


class LlmHealthSummaryData(BaseModel):
    health_state: str | None = None
    degraded_state: str | None = None
    circuit_state: str | None = None
    recent_failure_class: str | None = None
    consecutive_failures: int | None = None
    provider_status: list[LlmHealthProviderRow] = Field(default_factory=list)


class LlmImageHealthData(BaseModel):
    circuit_state: str | None = None
    consecutive_failures: int | None = None
    recent_failure_class: str | None = None
    health_state: str | None = None
    degraded_state: str | None = None


class LlmTtsHealthData(BaseModel):
    capability: str | None = None
    health_state: str | None = None
    degraded_state: str | None = None
    circuit_state: str | None = None
    celery_enabled: bool | None = None


class LlmMediaTaskCapabilityRow(BaseModel):
    capability: str
    queue_depth: int = 0
    active_tasks: int = 0
    health_state: str | None = None


class LlmMediaTasksHealthData(BaseModel):
    queue_depth: int = 0
    active_tasks: int = 0
    total_tasks: int = 0
    health_state: str | None = None
    degraded_state: str | None = None
    circuit_state: str | None = None
    recent_failure_class: str | None = None
    capabilities: list[LlmMediaTaskCapabilityRow] = Field(default_factory=list)


class LlmRuntimeOverviewHealthData(BaseModel):
    ok: bool
    url: str = ""
    status_code: int | None = None
    error: str = ""
    llm_runtime_detail: str | None = None
    llm_health: LlmHealthSummaryData | None = None
    llm_circuit: dict[str, Any] | None = None
    image_health: LlmImageHealthData | None = None
    tts_health: LlmTtsHealthData | None = None
    media_tasks: LlmMediaTasksHealthData | None = None
    submit_gate: dict[str, Any] | None = None


class LlmRuntimeOverviewData(BaseModel):
    health: LlmRuntimeOverviewHealthData
    model_admin: dict[str, Any] = Field(default_factory=dict)
    task_stats: dict[str, Any] = Field(default_factory=dict)
    conversation_kernel: dict[str, Any] = Field(default_factory=dict)
    task_routing_preview: dict[str, Any] = Field(default_factory=dict)


class LlmProviderTestData(BaseModel):
    ok: bool
    provider_id: str = ""
    model: str = ""
    latency_ms: float | None = None
    error: str = ""
    detail: str = ""


class LlmProvidersConfigData(BaseModel):
    model_config = ConfigDict(extra="allow")

    providers: list[dict[str, Any]] = Field(default_factory=list)
    routing: dict[str, Any] = Field(default_factory=dict)
    provider_status: list[dict[str, Any]] = Field(default_factory=list)


class ServiceGatewaysConnectivityCheckData(BaseModel):
    ok: bool
    results: list[dict[str, Any]] = Field(default_factory=list)
    lines: list[str] = Field(default_factory=list)


class AiExtensionTestData(BaseModel):
    model_config = ConfigDict(extra="allow")

    ok: bool
    status_code: int | None = None
    health_url: str = ""
    tried_urls: list[str] = Field(default_factory=list)
    error: str | None = None
    media_tasks: dict[str, Any] | None = None
    llm_detail: str | None = None
    image_circuit: dict[str, Any] | None = None
    llm_health: dict[str, Any] | None = None
    tts_health: dict[str, Any] | None = None


class LogEntryData(BaseModel):
    id: int
    time: str = ""
    level: str = "info"
    scope: str = ""
    message: str = ""


class LogsData(BaseModel):
    lines: list[str] = Field(default_factory=list)
    entries: list[LogEntryData] = Field(default_factory=list)
    max: int = 0
    scope: str | None = None
    source: str | None = None
    sharded_logs: bool = False
    log_sources: list[str] = Field(default_factory=list)


class PluginGovernanceRuntimeData(BaseModel):
    global_disable: bool = False
    help_hidden: bool = False
    global_disable_protected: bool = False
    help_ignored: bool = False


class PluginGovernanceData(BaseModel):
    plugin: str
    title: str = ""
    commands: list[dict[str, Any]] = Field(default_factory=list)
    menu_items: list[dict[str, Any]] = Field(default_factory=list)
    runtime: PluginGovernanceRuntimeData
    perm_ui_filtered: dict[str, Any] = Field(default_factory=dict)
    limits_ui_filtered: dict[str, Any] = Field(default_factory=dict)
    blocked_user_ids: list[int] = Field(default_factory=list)
    reload_policy: str | None = None
    activation_policy: str | None = None


class PluginGovernanceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_permission_overrides: dict[str, str] = Field(default_factory=dict)
    command_limit_overrides: dict[str, int] = Field(default_factory=dict)
    global_disable: bool = False
    help_hidden: bool = False
    blocked_user_ids: list[int] = Field(default_factory=list)


class PluginConfigData(BaseModel):
    """插件 / 通用配置表单载荷。须声明 field_groups 等扩展键，否则 GET 的 response_model 会剥掉分组。"""

    model_config = ConfigDict(extra="allow")

    plugin: str
    module: str = ""
    fields: list[dict[str, Any]] = Field(default_factory=list)
    unexpected_keys: list[dict[str, str]] = Field(default_factory=list)
    field_groups: list[dict[str, Any]] = Field(default_factory=list)
    hot_reload: bool | None = None
    gateway_editor: bool | None = None
    supports_connectivity_check: bool | None = None
    llm_model_admin: bool | None = None
    dev_mode_hot_reload: bool | None = None
    command_perm_ui: dict[str, Any] | None = None
    command_limits_ui: dict[str, Any] | None = None


class PluginConfigRawData(BaseModel):
    toml: str = ""


class ShardObservabilityData(BaseModel):
    model_config = ConfigDict(extra="allow")

    sharded: bool = False
    ingress_cluster: dict[str, Any] | None = None
    ingress_process: dict[str, Any] | None = None
    repeater_ingress_cluster: dict[str, Any] | None = None
    repeater_ingress_process: dict[str, Any] | None = None
    coord_pending_live: dict[str, Any] | None = None
    workers: list[dict[str, Any]] = Field(default_factory=list)
    pg_pool: dict[str, Any] | None = None


class IngressDispatchData(BaseModel):
    model_config = ConfigDict(extra="allow")

    sharded: bool = False
    workers: list[dict[str, Any]] = Field(default_factory=list)
