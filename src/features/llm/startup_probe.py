from __future__ import annotations

from typing import Any

from nonebot import get_driver, logger

_hook_installed = False


async def probe_ai_service_health(*, timeout_sec: float = 5.0) -> dict[str, Any]:
    from src.features.llm.config import get_llm_config, llm_server_base_url
    from src.shared.utils import HTTPXClient

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
    return {
        "ok": status_ok and (payload_ok or body is None),
        "url": url,
        "status_code": response.status_code,
        "body": body,
        "error": "" if status_ok else f"HTTP {response.status_code}",
    }


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
        from src.platform.bot_runtime.roles import is_sharded_worker

        if is_sharded_worker():
            return

        from src.features.llm.config import get_llm_config

        cfg = get_llm_config()
        flags = []
        if cfg.llm_chat_enabled:
            flags.append("LLM_CHAT")
        if cfg.llm_fallback_enabled:
            flags.append("FALLBACK")
        if cfg.llm_polish_enabled:
            flags.append("POLISH")
        flag_text = ",".join(flags) if flags else "off"

        result = await probe_ai_service_health()
        url = result.get("url", "")
        if result.get("ok"):
            body = result.get("body")
            version = ""
            if isinstance(body, dict):
                version = str(body.get("version") or body.get("api_version") or "").strip()
            if version:
                logger.info("llm: AI 服务可达 {} version={} switches={}", url, version, flag_text)
            else:
                logger.info("llm: AI 服务可达 {} switches={}", url, flag_text)
            return

        if cfg.llm_chat_enabled or cfg.llm_fallback_enabled or cfg.llm_polish_enabled:
            logger.warning(
                "llm: AI 服务不可达 {} error={}，但已开启 {}",
                url,
                result.get("error") or "unknown",
                flag_text,
            )
        else:
            logger.debug("llm: AI 服务未响应 {}（LLM 开关均为关）", url)
