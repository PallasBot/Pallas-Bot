"""跨仓 tool contract：Bot 持有 canonical 定义，AI 消费 transport 快照。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ToolCapability(StrEnum):
    READ_ONLY = "read_only"
    SIDE_EFFECTING = "side_effecting"
    REQUIRES_GROUP_CONTEXT = "requires_group_context"
    EXTERNAL_NETWORK = "external_network"
    BACKGROUND_TASK = "background_task"
    REQUIRES_APPROVAL = "requires_approval"
    PROACTIVE_SEND = "proactive_send"


class ToolAuditInfo(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    command_id: str | None = None
    plugin_name: str | None = None
    provider_name: str | None = None
    mcp_server_id: str | None = None


class ToolCatalogEntry(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    name: str
    description: str
    parameters: dict
    source: str
    domains: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    audit: ToolAuditInfo = Field(default_factory=ToolAuditInfo)
    estimated_duration_ms: int = 0
    cost_hint: str = ""
    approval_required: bool = False
    background_ok: bool = False
    display_mode: str = "default"


class ArtifactRef(BaseModel):
    artifact_id: str = ""
    kind: str = "text"
    uri: str = ""
    title: str = ""


class TaskContract(BaseModel):
    task_id: str = ""
    name: str = ""
    status: str = "pending"
    group_id: int | None = None
    user_id: int | None = None
    deadline: int | None = None
    artifacts: list[ArtifactRef] = Field(default_factory=list)


class SubAgentContract(BaseModel):
    run_id: str = ""
    task_id: str = ""
    tools: list[str] = Field(default_factory=list)
    budget: int = 3
    deadline: int | None = None
    status: str = "planned"


class ProactiveDeliveryContract(BaseModel):
    group_id: int
    user_id: int | None = None
    text: str
    source: str = "task"
    metadata: dict = Field(default_factory=dict)


class ToolCatalogSelection(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    tools_enabled: bool = False
    selective_enabled: bool = False
    inferred_domains: list[str] = Field(default_factory=list)
    schema_count: int = 0
    selection_source: str = ""
    soft_recall_confidence: int = 0
    soft_recall_candidates: list[dict] = Field(default_factory=list)
    ask_before_call: bool = False
    missing_required_params: dict[str, list[str]] = Field(default_factory=dict)
    inventory_intent: bool = False


class ToolCatalogSnapshot(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    version: str = "tool_catalog/v1"
    tools: list[ToolCatalogEntry] = Field(default_factory=list)
    selection: ToolCatalogSelection = Field(default_factory=ToolCatalogSelection)


class ToolResultEnvelope(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    ok: bool
    result: dict | None = None
    error: str = ""
    source: str = ""
    audit: ToolAuditInfo = Field(default_factory=ToolAuditInfo)
