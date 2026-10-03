"""控制台 OpenAPI response_model（codegen 第二波）。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _ApiOkResponse[T](BaseModel):
    ok: Literal[True] = True
    data: T
    error: None = None


class ApiErrResponse(BaseModel):
    ok: Literal[False] = False
    error: str = ""
    data: Any = None


class PluginCatalogMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str | None
    description: str = ""
    usage: str = ""
    extra: Any = None
    type: str = ""


class PluginCatalogRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    nb_plugin_name: str
    module: str
    resolved_plugin_id: str
    resolved_module: str
    metadata: PluginCatalogMetadata | None
    load_role: str
    loaded_in_process: bool
    has_config: bool
    configurable: bool
    help_visible: bool
    help_ignored: bool
    help_hidden: bool
    globally_disabled: bool
    global_disable_protected: bool
    plugin_source: str
    plugin_source_dir: str | None
    plugin_version: str | None
    extra_package: str | None
    uninstallable: bool
    uninstall_kind: str | None
    uninstall_target: str | None
    deps_missing: list[str]
    avatar: str | None
    icon: str | None
    cover: str | None
    catalog_process_role: str
    expected_in_catalog_process: bool


class InstanceBotRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    connection_key: str
    self_id: str
    adapter: str
    connected_at_unix: int | None = None
    ws_port: int | None = None
    shard_id: int | None = None
    nickname: str | None = None
    online: bool | None = None


class AccountPersonaProfileData(BaseModel):
    model_config = ConfigDict(extra="allow")

    energy: float
    warmth: float
    mischief: float
    restraint: float
    source: Literal["derived", "manual", "legacy_migrated"]


class BotConfigPublicData(BaseModel):
    model_config = ConfigDict(extra="allow")

    account: int
    admins: list[int]
    auto_accept_friend: bool
    auto_accept_group: bool
    security: bool
    taken_name: dict[str, int]
    drunk: dict[str, float]
    disabled_plugins: list[str]
    community_roster_show_qq: bool
    persona: dict[str, Any] | None
    account_profile_effective: AccountPersonaProfileData
    group_style_enabled: bool


class ProtocolAccountSnapshot(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | None = None
    qq: str | None = None
    display_name: str | None = None
    webui_port: int | str | None = None
    ws_url: str | None = None


class PallasProtocolSnapshot(BaseModel):
    model_config = ConfigDict(extra="allow")

    plugin: str
    webui_enabled: bool
    webui_path: str
    console_auth_configured: bool
    accounts: list[ProtocolAccountSnapshot]


class ProtocolExtensionStatusData(BaseModel):
    model_config = ConfigDict(extra="allow")

    installed: bool
    package: str
    uv_extra: str | None
    install_cli: str | None
    activation_policy: str | None
    repository_url: str | None


class InstanceBotProfileData(BaseModel):
    model_config = ConfigDict(extra="allow")

    nickname: str | None = None
    user_id: int | None = None
    connection_key: str | None = None
    adapter: str | None = None
    shard_id: int | None = None


class InstancesData(BaseModel):
    model_config = ConfigDict(extra="allow")

    nonebot_bots: list[InstanceBotRow]
    db_bot_configs: list[BotConfigPublicData]
    pallas_protocol: PallasProtocolSnapshot | None
    protocol_extension: ProtocolExtensionStatusData
    bot_profiles: dict[str, InstanceBotProfileData]
    napcat: PallasProtocolSnapshot | None = None


class ConsoleSetupStatusData(BaseModel):
    auth_configured: bool
    setup_completed: bool
    default_password_active: bool
    requires_setup: bool
    first_completed_at: str | None = None
    updated_at: str | None = None


class ConsoleLoginChangeData(BaseModel):
    message: str


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


class AiServiceHealthProbeData(BaseModel):
    ok: bool
    url: str = ""
    status_code: int | None = None
    error: str = ""


class LlmRuntimeOverviewHealthData(BaseModel):
    ok: bool
    url: str = ""
    status_code: int | None = None
    error: str = ""
    llm_runtime_detail: str | None = None
    llm_health: LlmHealthSummaryData | None = None
    llm_circuit: dict[str, Any] | None = None
    image_health: LlmImageHealthData | None = None
    draw_runtime_mode: str | None = None
    tts_health: LlmTtsHealthData | None = None
    media_tasks: LlmMediaTasksHealthData | None = None
    ai_service: AiServiceHealthProbeData | None = None
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
    facet: str | None = None


class LogsData(BaseModel):
    lines: list[str] = Field(default_factory=list)
    entries: list[LogEntryData] = Field(default_factory=list)
    max: int = 0
    scope: str | None = None
    source: str | None = None
    sharded_logs: bool = False
    log_sources: list[str] = Field(default_factory=list)


class PluginGovernanceCommandData(BaseModel):
    model_config = ConfigDict(extra="allow")

    command_id: str
    label: str
    trigger_condition: str | None = None
    default_level: str | None = None
    effective_level: str | None = None
    default_cd_sec: int | None = None
    effective_cd_sec: int | None = None


class PluginGovernanceMenuItemData(BaseModel):
    model_config = ConfigDict(extra="allow")

    func: Any = None
    group: Any = None
    trigger_method: Any = None
    trigger_scene: Any = None
    trigger_condition: Any = None
    brief_des: Any = None
    detail_des: Any = None
    command_permission: Any = None
    command_permissions: Any = None


class PluginGovernanceRuntimeData(BaseModel):
    model_config = ConfigDict(extra="allow")

    global_disable: bool
    global_disable_revision: str
    help_hidden: bool
    global_disable_protected: bool
    help_ignored: bool


class PluginCommandPermLevelData(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    label: str


class PluginCommandPermCommandData(BaseModel):
    model_config = ConfigDict(extra="allow")

    command_id: str
    label: str
    default_level: str
    effective_level: str
    trigger_condition: str | None = None


class PluginCommandPermPluginData(BaseModel):
    model_config = ConfigDict(extra="allow")

    plugin: str
    title: str
    commands: list[PluginCommandPermCommandData]


class PluginCommandPermUiData(BaseModel):
    model_config = ConfigDict(extra="allow")

    levels: list[PluginCommandPermLevelData]
    plugins: list[PluginCommandPermPluginData]


class PluginCommandLimitCommandData(BaseModel):
    model_config = ConfigDict(extra="allow")

    command_id: str
    label: str
    default_cd_sec: int
    effective_cd_sec: int
    trigger_condition: str | None = None


class PluginCommandLimitPluginData(BaseModel):
    model_config = ConfigDict(extra="allow")

    plugin: str
    title: str
    commands: list[PluginCommandLimitCommandData]


class PluginCommandLimitsUiData(BaseModel):
    model_config = ConfigDict(extra="allow")

    plugins: list[PluginCommandLimitPluginData]


class PluginGovernanceData(BaseModel):
    model_config = ConfigDict(extra="allow")

    plugin: str
    title: str
    commands: list[PluginGovernanceCommandData]
    menu_items: list[PluginGovernanceMenuItemData]
    runtime: PluginGovernanceRuntimeData
    perm_ui_filtered: PluginCommandPermUiData
    limits_ui_filtered: PluginCommandLimitsUiData
    blocked_user_ids: list[int]
    reload_policy: str | None
    activation_policy: str | None


class PluginGovernanceUpdateRuntimeData(BaseModel):
    global_disable: bool
    global_disable_revision: str
    help_hidden: bool


class PluginGovernanceUpdateData(BaseModel):
    model_config = ConfigDict(extra="allow")

    plugin: str
    command_permission_overrides: dict[str, str]
    command_limit_overrides: dict[str, int]
    blocked_user_ids: list[int]
    runtime: PluginGovernanceUpdateRuntimeData


class PluginGovernanceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_permission_overrides: dict[str, str] = Field(default_factory=dict)
    command_limit_overrides: dict[str, int] = Field(default_factory=dict)
    global_disable: bool = False
    global_disable_revision: str | None = None
    help_hidden: bool = False
    blocked_user_ids: list[int] = Field(default_factory=list)


class PluginConfigFieldData(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    kind: str
    required: bool
    description: str
    env_key: str
    default: Any
    current: Any
    ui_group: Any = None
    ui_order: Any = None
    ui_hidden: Any = None
    ui_widget: Any = None
    ui_gateway: dict[str, Any] | None = None


class PluginConfigFieldGroupData(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    title: str
    field_names: list[str]


class PluginConfigUnexpectedKeyData(BaseModel):
    env_key: str
    value_preview: str


class PluginConfigData(BaseModel):
    """插件 / 通用配置表单载荷。须声明 field_groups 等扩展键，否则 GET 的 response_model 会剥掉分组。"""

    model_config = ConfigDict(extra="allow")

    plugin: str
    module: str = ""
    fields: list[PluginConfigFieldData]
    unexpected_keys: list[PluginConfigUnexpectedKeyData] = Field(default_factory=list)
    field_groups: list[PluginConfigFieldGroupData] = Field(default_factory=list)
    hot_reload: bool | None = None
    gateway_editor: bool | None = None
    supports_connectivity_check: bool | None = None
    llm_model_admin: bool | None = None
    dev_mode_hot_reload: bool | None = None
    command_perm_ui: PluginCommandPermUiData | None = None
    command_limits_ui: PluginCommandLimitsUiData | None = None


def plugin_config_response(value: dict[str, Any]) -> dict[str, Any]:
    """Keep legacy top-level defaults without serializing open nested rows."""
    return {
        "ok": True,
        "error": None,
        "data": {
            "module": "",
            "fields": [],
            "unexpected_keys": [],
            "field_groups": [],
            "hot_reload": None,
            "gateway_editor": None,
            "supports_connectivity_check": None,
            "llm_model_admin": None,
            "dev_mode_hot_reload": None,
            "command_perm_ui": None,
            "command_limits_ui": None,
            **value,
        },
    }


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


class SystemRestartAvailabilityData(BaseModel):
    model_config = ConfigDict(extra="allow")

    restart_available: bool = False
    deployment_mode: str = ""


class IngressDispatchHotpath(BaseModel):
    model_config = ConfigDict(extra="allow")

    repeater_event_gate_ms_p95: float | None = None
    repeater_scrub_ms_p95: float | None = None
    repeater_prepare_ms_p95: float | None = None
    repeater_answer_ms_p95: float | None = None
    repeater_cooldown_ms_p95: float | None = None


class IngressDispatchConversationScheduler(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    pending: int = 0
    pending_peak: int = 0
    active: int = 0
    active_peak: int = 0
    wait_ms_p95: float | None = None
    run_ms_p95: float | None = None
    passive_repeater_pending: int = 0
    passive_repeater_active: int = 0
    passive_repeater_run_ms_p95: float | None = None
    passive_repeater_active_oldest_ms: float | None = None
    passive_llm_pending: int = 0
    passive_llm_active: int = 0
    passive_llm_run_ms_p95: float | None = None
    passive_llm_active_oldest_ms: float | None = None


class IngressDispatchData(BaseModel):
    model_config = ConfigDict(extra="allow")

    sharded: bool = False
    workers: list[dict[str, Any]] = Field(default_factory=list)
    hotpath: IngressDispatchHotpath = Field(default_factory=IngressDispatchHotpath)
    conversation_scheduler: IngressDispatchConversationScheduler = Field(
        default_factory=IngressDispatchConversationScheduler,
    )


class IngressDispatchHistoryPoint(BaseModel):
    at: int
    ingress_p95_ms: float
    ingress_full_p95_ms: float = 0.0
    scheduler_wait_p95_ms: float
    scheduler_run_p95_ms: float = 0.0
    scheduler_pending: int
    scheduler_active: int
    scheduler_capacity: int
    scheduler_backpressure_waits: int = 0
    scheduler_per_key_backpressure_waits: int = 0
    passive_repeater_pending: int = 0
    passive_repeater_active: int = 0
    passive_llm_pending: int = 0
    passive_llm_active: int = 0
    send_queue_depth: int = 0
    send_queue_capacity: int = 0
    pg_pool_utilization: float = 0.0
    work_pending: int
    work_leased: int
    group_messages: int
    learn_enqueued: int
    learn_persisted: int
    work_completed: int


class IngressDispatchHistoryData(BaseModel):
    retention_sec: int
    bucket_sec: int
    points: list[IngressDispatchHistoryPoint] = Field(default_factory=list)
