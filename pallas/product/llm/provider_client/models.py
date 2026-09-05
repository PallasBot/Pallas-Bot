"""Provider 模型列表拉取 / 解析 / 探测。"""

from __future__ import annotations

from typing import Any

import httpx

from pallas.product.llm import provider_client as _repo


def parse_openai_models_payload(payload: Any) -> list[str]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return []
    out: list[str] = []
    for item in data:
        mid = item.get("id") if isinstance(item, dict) else None
        if isinstance(mid, str) and mid.strip():
            out.append(mid.strip())
    return out


def parse_ollama_tags_payload(payload: Any) -> list[str]:
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return []
    out: list[str] = []
    for item in models:
        name = item.get("name") if isinstance(item, dict) else None
        if isinstance(name, str) and name.strip():
            out.append(name.strip())
    return out


async def list_openai_compatible_models(
    base_url: str,
    api_key: str = "",
    *,
    timeout_sec: float = 15.0,
    request_method: str | None = None,
) -> list[str]:
    method = _repo.resolve_request_method(request_method, base_url)
    if method == "anthropic_messages":
        return await _repo.list_anthropic_models(base_url, api_key, timeout_sec=timeout_sec)
    url = _repo.models_url(base_url)
    headers = _repo.auth_headers(api_key)
    try:
        client = await _repo.get_llm_shared_httpx_client()
        response = await client.get(url, headers=headers, timeout=httpx.Timeout(timeout_sec))
    except Exception as exc:
        raise _repo.LlmProviderError(_repo.format_provider_transport_error(exc, url=url)) from exc
    if response.status_code != 200:
        raise _repo.raise_provider_http_error(response)
    try:
        payload = response.json()
    except Exception as exc:
        raise _repo.LlmProviderError("invalid models response") from exc
    return _repo.parse_openai_models_payload(payload)


async def list_anthropic_models(
    base_url: str,
    api_key: str = "",
    *,
    timeout_sec: float = 15.0,
) -> list[str]:
    url = _repo.anthropic_models_url(base_url)
    headers = _repo.anthropic_auth_headers(api_key)
    try:
        client = await _repo.get_llm_shared_httpx_client()
        response = await client.get(url, headers=headers, timeout=httpx.Timeout(timeout_sec))
    except Exception as exc:
        raise _repo.LlmProviderError(_repo.format_provider_transport_error(exc, url=url)) from exc
    if response.status_code != 200:
        raise _repo.raise_provider_http_error(response)
    try:
        payload = response.json()
    except Exception as exc:
        raise _repo.LlmProviderError("invalid anthropic models response") from exc
    return _repo.parse_openai_models_payload(payload)


async def list_ollama_tag_models(
    base_url: str,
    *,
    timeout_sec: float = 15.0,
) -> list[str]:
    url = _repo.ollama_tags_url(base_url)
    try:
        client = await _repo.get_llm_shared_httpx_client()
        response = await client.get(url, timeout=httpx.Timeout(timeout_sec))
    except Exception as exc:
        raise _repo.LlmProviderError(_repo.format_provider_transport_error(exc, url=url)) from exc
    if response.status_code != 200:
        raise _repo.raise_provider_http_error(response)
    try:
        payload = response.json()
    except Exception as exc:
        raise _repo.LlmProviderError("invalid ollama tags response") from exc
    return _repo.parse_ollama_tags_payload(payload)


async def probe_provider_models(*, timeout_sec: float = 3.0, cfg: _repo.LlmConfig | None = None) -> dict[str, Any]:
    c = cfg or _repo.get_llm_config()
    base = str(c.llm_base_url or "").strip()
    key = str(c.llm_api_key or "").strip()
    if not base:
        from pallas.product.llm.providers_store import resolve_endpoint_for_task

        endpoint = resolve_endpoint_for_task("llm_chat")
        if endpoint is not None:
            base = endpoint.base_url
            key = key or endpoint.api_key
    try:
        url = _repo.models_url(base)
    except _repo.LlmProviderError as exc:
        return {"ok": False, "url": "", "error": str(exc)}
    headers = _repo.auth_headers(key)
    try:
        client = await _repo.get_llm_shared_httpx_client()
        response = await client.get(url, headers=headers, timeout=httpx.Timeout(timeout_sec))
    except Exception as exc:
        return {"ok": False, "url": url, "error": str(exc)}
    ok = response.status_code == 200
    return {
        "ok": ok,
        "url": url,
        "status_code": response.status_code,
        "error": "" if ok else f"HTTP {response.status_code}",
    }
