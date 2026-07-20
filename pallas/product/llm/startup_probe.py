from __future__ import annotations

from typing import Any

from nonebot import get_driver, logger

from pallas.core.foundation.startup_report import register_startup_fact, register_startup_warning

_hook_installed = False
_ai_service_reachable: bool | None = None
_llm_provider_ready: bool | None = None
MIN_AI_API_VERSION = (4, 0, 0)


def llm_ai_service_reachable() -> bool | None:
    """启动探针结果；None 表示尚未探测。"""
    return _ai_service_reachable


def llm_provider_ready() -> bool | None:
    """内核 Provider 配置/探活结果；None 表示尚未探测。"""
    return _llm_provider_ready


def parse_api_version(raw: str | None) -> tuple[int, ...] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    parts: list[int] = []
    for segment in text.split("."):
        chunk = ""
        for ch in segment:
            if ch.isdigit():
                chunk += ch
            else:
                break
        if not chunk:
            break
        parts.append(int(chunk))
    return tuple(parts) if parts else None


def ai_api_version_compatible(raw: str | None, *, minimum: tuple[int, ...] = MIN_AI_API_VERSION) -> bool:
    parsed = parse_api_version(raw)
    if parsed is None:
        return True
    return parsed >= minimum


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
            "error": "llm_base_url or llm_model missing",
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
        global _ai_service_reachable, _llm_provider_ready
        from pallas.core.platform.bot_runtime.roles import is_sharded_worker

        if is_sharded_worker():
            return

        from pallas.product.llm.config import get_llm_config, is_llm_bot_kernel_runtime

        cfg = get_llm_config()
        from pallas.product.llm.legacy_guard import log_legacy_chat_config_warnings

        log_legacy_chat_config_warnings(cfg)
        flags = []
        if cfg.llm_chat_enabled:
            flags.append("LLM_CHAT")
        if cfg.llm_fallback_enabled:
            flags.append("FALLBACK")
        if cfg.llm_polish_lite_enabled:
            flags.append("POLISH_LITE")
        if cfg.llm_select_enabled:
            flags.append("SELECT")
        if cfg.llm_polish_enabled:
            flags.append("POLISH")
        flag_text = ",".join(flags) if flags else "off"
        llm_switches_on = (
            cfg.llm_chat_enabled
            or cfg.llm_fallback_enabled
            or cfg.llm_polish_enabled
            or cfg.llm_select_enabled
            or cfg.llm_polish_lite_enabled
        )

        if is_llm_bot_kernel_runtime(cfg):
            _ai_service_reachable = None
            result = await probe_llm_provider()
            _llm_provider_ready = bool(result.get("ok"))
            from packages.help.plugin_availability import invalidate_plugin_help_availability_cache

            invalidate_plugin_help_availability_cache()
            model = str(cfg.llm_model or "").strip() or "?"
            if result.get("ok"):
                register_startup_fact(
                    "llm",
                    f"kernel ok model={model} switches={flag_text}",
                )
                return
            if not result.get("configured"):
                if llm_switches_on:
                    register_startup_warning(
                        "llm",
                        f"provider_not_configured switches={flag_text}",
                    )
                    logger.warning("[LLM] 内核模式未配置 Provider（LLM_BASE_URL + LLM_MODEL） switches={}", flag_text)
                else:
                    logger.debug("[LLM] 内核模式未配置 Provider（开关均为关）")
                return
            if llm_switches_on:
                register_startup_warning(
                    "llm",
                    f"provider_unreachable err={result.get('error') or 'unknown'} switches={flag_text}",
                )
                logger.warning(
                    "[LLM] Provider 不可达 {} err={} switches={}",
                    result.get("url") or "",
                    result.get("error") or "unknown",
                    flag_text,
                )
            else:
                logger.debug("[LLM] Provider 无响应（开关均为关）")
            return

        result = await probe_ai_service_health()
        _ai_service_reachable = bool(result.get("ok"))
        from packages.help.plugin_availability import invalidate_plugin_help_availability_cache

        invalidate_plugin_help_availability_cache()
        url = result.get("url", "")
        if result.get("ok"):
            body = result.get("body")
            version = ""
            provider_mode = ""
            if isinstance(body, dict):
                version = str(body.get("version") or body.get("api_version") or "").strip()
                llm_info = body.get("llm")
                if isinstance(llm_info, dict):
                    provider_mode = str(llm_info.get("provider_mode") or "").strip()
            if version and provider_mode:
                if not ai_api_version_compatible(version):
                    register_startup_warning(
                        "llm",
                        f"version<{MIN_AI_API_VERSION[0]}.{MIN_AI_API_VERSION[1]}.{MIN_AI_API_VERSION[2]}",
                    )
                    logger.warning(
                        "[LLM] v={} 低于最低 {}.{}.{}, 部分 4.0 API 可能不可用",
                        version,
                        MIN_AI_API_VERSION[0],
                        MIN_AI_API_VERSION[1],
                        MIN_AI_API_VERSION[2],
                    )
                register_startup_fact(
                    "llm",
                    f"ok v={version} provider={provider_mode} switches={flag_text}",
                )
            elif version:
                if not ai_api_version_compatible(version):
                    register_startup_warning(
                        "llm",
                        f"version<{MIN_AI_API_VERSION[0]}.{MIN_AI_API_VERSION[1]}.{MIN_AI_API_VERSION[2]}",
                    )
                    logger.warning(
                        "[LLM] v={} 低于最低 {}.{}.{}",
                        version,
                        MIN_AI_API_VERSION[0],
                        MIN_AI_API_VERSION[1],
                        MIN_AI_API_VERSION[2],
                    )
                register_startup_fact("llm", f"ok v={version} switches={flag_text}")
            else:
                register_startup_fact("llm", f"ok switches={flag_text}")
            return

        if llm_switches_on:
            register_startup_warning(
                "llm",
                f"unreachable err={result.get('error') or 'unknown'} switches={flag_text}",
            )
            logger.warning(
                "[LLM] 不可达 {} err={} switches={}",
                url,
                result.get("error") or "unknown",
                flag_text,
            )
        else:
            logger.debug("[LLM] 无响应 {}（开关均为关）", url)
