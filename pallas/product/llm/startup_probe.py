from __future__ import annotations

from typing import Any

from nonebot import get_driver, logger

from pallas.core.foundation.startup_report import register_startup_fact, register_startup_warning

_hook_installed = False
_llm_provider_ready: bool | None = None


def llm_provider_ready() -> bool | None:
    """内核 Provider 配置/探活结果；None 表示尚未探测。"""
    return _llm_provider_ready


def build_llm_startup_fact(cfg: Any, endpoint: Any | None) -> str:
    provider = str(getattr(endpoint, "provider_id", "") or "").strip()
    model = str(getattr(endpoint, "model", "") or "").strip() or str(getattr(cfg, "llm_model", "") or "").strip()
    chat_state = "enabled" if bool(getattr(cfg, "llm_chat_enabled", False)) else "disabled"
    parts = ["ok"]
    if provider:
        parts.append(f"provider={provider}")
    if model:
        parts.append(f"model={model}")
    parts.append(f"chat={chat_state}")
    return " ".join(parts)


async def probe_ai_service_health(*, timeout_sec: float = 5.0) -> dict[str, Any]:
    from pallas.core.shared.utils import HTTPXClient
    from pallas.product.llm.config import get_llm_config, llm_server_base_url

    cfg = get_llm_config()
    base = llm_server_base_url(cfg).rstrip("/")
    url = f"{base}/health"
    try:
        response = await HTTPXClient.get(url, timeout=timeout_sec)
    except Exception as exc:
        return {
            "ok": False,
            "url": url,
            "status_code": None,
            "body": None,
            "error": str(exc),
        }
    if response is None:
        return {
            "ok": False,
            "url": url,
            "status_code": None,
            "body": None,
            "error": "HTTP request failed",
        }
    body: Any = None
    try:
        body = response.json()
    except Exception:
        body = (response.text or "")[:200]
    status_ok = 200 <= response.status_code < 300
    payload_ok = isinstance(body, dict) and str(body.get("status", "")).lower() in ("ok", "healthy")
    if isinstance(body, dict):
        from pallas.core.shared.ai_health_cache import update_ai_health_cache

        update_ai_health_cache(body)
    return {
        "ok": status_ok and (payload_ok or body is None),
        "url": url,
        "status_code": response.status_code,
        "body": body,
        "error": "" if status_ok else f"HTTP {response.status_code}",
    }


async def probe_llm_provider(*, timeout_sec: float = 3.0) -> dict[str, Any]:
    from pallas.product.llm.config import get_llm_config, llm_provider_configured
    from pallas.product.llm.provider_client import probe_provider_models

    cfg = get_llm_config()
    if not llm_provider_configured(cfg):
        return {
            "ok": False,
            "configured": False,
            "url": "",
            "error": "llm provider missing (configure 接入 Provider or LLM_BASE_URL + LLM_MODEL)",
        }
    result = await probe_provider_models(timeout_sec=timeout_sec, cfg=cfg)
    result["configured"] = True
    return result


def install_llm_startup_probe() -> None:
    global _hook_installed
    if _hook_installed:
        return
    try:
        driver = get_driver()
    except ValueError:
        return
    _hook_installed = True

    @driver.on_startup
    async def _llm_probe_ai_service_on_startup() -> None:
        global _llm_provider_ready
        from pallas.core.platform.bot_runtime.roles import is_sharded_worker

        if is_sharded_worker():
            return

        from pallas.product.llm.config import get_llm_config

        cfg = get_llm_config()
        from pallas.product.llm.legacy_guard import log_legacy_chat_config_warnings

        log_legacy_chat_config_warnings(cfg)
        llm_switches_on = (
            cfg.llm_chat_enabled or cfg.llm_fallback_enabled or cfg.llm_polish_enabled or cfg.llm_polish_lite_enabled
        )

        result = await probe_llm_provider()
        _llm_provider_ready = bool(result.get("ok"))
        from packages.help.plugin_availability import invalidate_plugin_help_availability_cache

        invalidate_plugin_help_availability_cache()
        from pallas.product.llm.providers_store import resolve_endpoint_for_task

        endpoint = resolve_endpoint_for_task("llm_chat")
        startup_fact = build_llm_startup_fact(cfg, endpoint)
        if result.get("ok"):
            register_startup_fact("llm", startup_fact)
            return
        if not result.get("configured"):
            if llm_switches_on:
                register_startup_warning(
                    "llm",
                    "provider_not_configured",
                )
                logger.warning(
                    "[LLM] Provider is not configured. Configure it in the console or set LLM_BASE_URL and LLM_MODEL.",
                )
            else:
                logger.debug("[LLM] 内核模式未配置 Provider（开关均为关）")
            return
        if llm_switches_on:
            register_startup_warning(
                "llm",
                f"provider_unreachable err={result.get('error') or 'unknown'}",
            )
            logger.warning(
                "[LLM] Provider is unreachable: {}. Error: {}.",
                result.get("url") or "",
                result.get("error") or "unknown",
            )
        else:
            logger.debug("[LLM] Provider 无响应（开关均为关）")
