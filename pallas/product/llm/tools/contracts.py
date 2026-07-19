"""跨仓 tool contract：Bot 持有 canonical 定义，AI 消费 transport 快照。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ToolCapability(StrEnum):
    READ_ONLY = "read_only"
    SIDE_EFFECTING = "side_effecting"
    REQUIRES_GROUP_CONTEXT = "requires_group_context"


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


class ToolCatalogSelection(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    tools_enabled: bool = False
    selective_enabled: bool = False
    inferred_domains: list[str] = Field(default_factory=list)
    schema_count: int = 0


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
