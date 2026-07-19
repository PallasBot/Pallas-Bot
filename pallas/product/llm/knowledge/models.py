"""通用知识源契约模型。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

KNOWLEDGE_CONTRACT_VERSION = 1


class KnowledgeRetrievalMode(StrEnum):
    PROMPT_INJECT = "prompt_inject"
    METADATA_ONLY = "metadata_only"
    TOOL_ONLY = "tool_only"


class KnowledgeSourceScope(StrEnum):
    GLOBAL = "global"
    GROUP = "group"
    USER = "user"


class KnowledgeChunkDecl(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(default="", max_length=120)
    content: str = Field(min_length=1)
    keywords: str = Field(default="")


class KnowledgeSourceDecl(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(default="")
    retrieval_mode: KnowledgeRetrievalMode = KnowledgeRetrievalMode.PROMPT_INJECT
    scope: KnowledgeSourceScope = KnowledgeSourceScope.GLOBAL
    default: bool = True
    top_k: int = Field(default=3, ge=1, le=8)
    max_chunk_len: int = Field(default=400, ge=64, le=2000)
    chunks: list[KnowledgeChunkDecl] = Field(default_factory=list)


class RetrievedKnowledgeChunk(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source_id: str
    title: str
    content: str
    score: int = 0


class KnowledgeInjectionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    system_prompt: str
    trace: dict[str, Any] = Field(default_factory=dict)
