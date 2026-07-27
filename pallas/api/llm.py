"""插件可读的 LLM Provider 凭证解析（转发 product.llm.providers_store）。"""

from __future__ import annotations

from typing import Any

from pallas.product.llm.providers_store import (
    find_provider as _find_provider,
)
from pallas.product.llm.providers_store import (
    resolve_provider_api_key as _resolve_provider_api_key,
)
from pallas.product.llm.providers_store import (
    resolve_provider_api_keys as _resolve_provider_api_keys,
)
from pallas.product.llm.providers_store import (
    resolve_provider_base_url as _resolve_provider_base_url,
)

__all__ = [
    "find_provider",
    "resolve_provider_api_key",
    "resolve_provider_api_keys",
    "resolve_provider_base_url",
]


def find_provider(provider_id: str, *, doc: dict[str, Any] | None = None) -> dict[str, Any] | None:
    return _find_provider(provider_id, doc=doc)


def resolve_provider_api_key(row: dict[str, Any]) -> str:
    return _resolve_provider_api_key(row)


def resolve_provider_api_keys(row: dict[str, Any]) -> list[str]:
    return _resolve_provider_api_keys(row)


def resolve_provider_base_url(row: dict[str, Any]) -> str:
    return _resolve_provider_base_url(row)
