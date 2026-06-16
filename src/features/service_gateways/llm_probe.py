"""LLM / Pallas-Bot-AI 服务探测（4.0 内置 provider）。"""

from __future__ import annotations

import time

from src.features.service_gateways.registry import ServiceProbeProvider, register_service_probe_provider
from src.shared.service_probe import ServiceProbeResult

LLM_CATEGORY = "LLM对话"


async def probe_llm_service(*, timeout_sec: float = 15.0, draft_values=None) -> list[ServiceProbeResult]:
    _ = draft_values
    from src.features.llm.config import get_llm_config
    from src.features.llm.startup_probe import probe_ai_service_health

    cfg = get_llm_config()
    if not (cfg.llm_chat_enabled or cfg.llm_fallback_enabled or cfg.llm_polish_enabled):
        return [
            ServiceProbeResult(
                category=LLM_CATEGORY,
                site="健康检查",
                ok=False,
                latency_ms=None,
                status_code=None,
                error="LLM 相关开关均为关",
            ),
        ]

    started = time.perf_counter()
    result = await probe_ai_service_health(timeout_sec=min(timeout_sec, 15.0))
    latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
    url = str(result.get("url") or "LLM 服务")
    status_code = result.get("status_code")
    if result.get("ok"):
        detail = ""
        body = result.get("body")
        if isinstance(body, dict):
            version = str(body.get("version") or body.get("api_version") or "").strip()
            if version:
                detail = f" version={version}"
        return [
            ServiceProbeResult(
                category=LLM_CATEGORY,
                site="健康检查",
                ok=True,
                latency_ms=latency_ms,
                status_code=int(status_code) if status_code is not None else None,
                error=f"{url}{detail}" if detail else None,
            ),
        ]
    err = str(result.get("error") or "unknown")
    return [
        ServiceProbeResult(
            category=LLM_CATEGORY,
            site="健康检查",
            ok=False,
            latency_ms=latency_ms if latency_ms > 0 else None,
            status_code=int(status_code) if isinstance(status_code, int) else None,
            error=f"{url} {err}".strip(),
        ),
    ]


register_service_probe_provider(
    ServiceProbeProvider(name="llm", probe=probe_llm_service, priority=10),
)
