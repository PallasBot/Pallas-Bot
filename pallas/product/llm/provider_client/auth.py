"""Provider 请求头与 API Key 相关辅助。"""

from __future__ import annotations

from typing import Any

from pallas.product.llm import provider_client as _repo


def auth_headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    key = str(api_key or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def anthropic_auth_headers(api_key: str) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "anthropic-version": _repo.ANTHROPIC_VERSION,
    }
    key = str(api_key or "").strip()
    if key:
        headers["x-api-key"] = key
    return headers


def endpoint_api_keys(endpoint: Any, *, fallback: str = "") -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for item in getattr(endpoint, "api_keys", ()) or ():
        key = str(item or "").strip()
        if key and key not in seen:
            keys.append(key)
            seen.add(key)
    if keys:
        return keys
    primary = str(getattr(endpoint, "api_key", "") or "").strip() or str(fallback or "").strip()
    return [primary] if primary else [""]
