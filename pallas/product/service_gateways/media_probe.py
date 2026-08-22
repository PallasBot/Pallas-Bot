"""画画、MAA、唱歌等服务探测。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

import httpx

from pallas.core.platform.plugin_runtime.resolve import import_plugin_submodule
from pallas.core.shared.ai_runtime_capability import AUTOMATION_MAA, IMAGE_GENERATE, MEDIA_SING
from pallas.core.shared.ai_runtime_failure import (
    CIRCUIT_CLOSED,
    FAILURE_RUNTIME_DISABLED,
    FAILURE_RUNTIME_UNAVAILABLE,
    HEALTH_DEGRADED,
    HEALTH_HEALTHY,
    HEALTH_UNHEALTHY,
    HEALTH_UNKNOWN,
    RUNTIME_DEGRADED,
    RUNTIME_DISABLED,
    RUNTIME_HEALTHY,
    failure_class_from_error,
)
from pallas.core.shared.service_probe import (
    ServiceProbeResult,
    build_runtime_probe_result,
    enrich_probe_result_capabilities,
    normalize_runtime_probe_results,
    patch_probe_result,
    probe_http_get,
    probe_http_post_json,
)
from pallas.product.service_gateways.registry import ServiceProbeProvider, register_service_probe_provider

if TYPE_CHECKING:
    from typing import Any as MaaConfig
    from typing import Any as SingConfig

MAA_CATEGORY = "MAA远控"
SING_CATEGORY = "唱歌"
IMAGE_CATEGORY = "牛牛画画"


def maa_hub_probe_note(results: list[ServiceProbeResult]) -> list[ServiceProbeResult]:
    note = "hub 入口已响应（探测未带 QQ，不验证 worker 转发）"
    return [
        patch_probe_result(
            item,
            error=note,
            runtime_state=RUNTIME_HEALTHY,
            runtime_detail=note,
        )
        if item.ok and item.latency_ms is not None
        else item
        for item in results
    ]


def normalize_maa_runtime_results(
    results: list[ServiceProbeResult],
) -> list[ServiceProbeResult]:
    return normalize_runtime_probe_results(results)


async def probe_image_gateways(*, draft_values: dict[str, Any] | None = None) -> list[ServiceProbeResult]:
    from importlib.util import find_spec

    from nonebot import logger

    if find_spec("pallas_plugin_draw") is None:
        return []
    draw_config = import_plugin_submodule("draw", "config")
    draw_probe = import_plugin_submodule("draw", "gateway_probe")
    active_image_gen_settings = draw_config.active_image_gen_settings
    image_gen_settings_from_draft = draw_probe.image_gen_settings_from_draft
    probe_all_backends = draw_probe.probe_all_backends

    settings: draw_config.ImageGenSettings
    try:
        if draft_values is not None:
            from pallas.product.service_gateways.draft import draw_draft_from_values

            settings = image_gen_settings_from_draft(draw_draft_from_values(draft_values))
        else:
            settings = active_image_gen_settings()
    except Exception as e:  # noqa: BLE001
        logger.debug("service_gateways image settings load failed: {}", e)
        return [
            build_runtime_probe_result(
                IMAGE_GENERATE,
                category=IMAGE_CATEGORY,
                site="网关",
                ok=False,
                latency_ms=None,
                status_code=None,
                error=str(e)[:120],
                failure_class=failure_class_from_error(str(e)[:120]),
                health_state=HEALTH_UNHEALTHY,
            ),
        ]
    if not settings.api_backends():
        return [
            build_runtime_probe_result(
                IMAGE_GENERATE,
                category=IMAGE_CATEGORY,
                site="网关",
                ok=False,
                latency_ms=None,
                status_code=None,
                error="尚未配置可用网关（需 base_url、api_key 或 api_backends）",
                failure_class=FAILURE_RUNTIME_UNAVAILABLE,
                health_state=HEALTH_UNHEALTHY,
            ),
        ]
    try:
        # Draw ≥4.1.0：仅插件直连网关，不再走 AI Runtime 绘图队列
        return await probe_all_backends(settings)
    except Exception as e:  # noqa: BLE001
        logger.debug("service_gateways image probe failed: {}", e)
        return [
            build_runtime_probe_result(
                IMAGE_GENERATE,
                category=IMAGE_CATEGORY,
                site="网关",
                ok=False,
                latency_ms=None,
                status_code=None,
                error=str(e)[:120],
                failure_class=failure_class_from_error(str(e)[:120]),
                health_state=HEALTH_UNHEALTHY,
            ),
        ]


async def probe_ai_media_task_runtime(
    *,
    base_url: str | None = None,
    timeout_sec: float = 10.0,
    category: str = IMAGE_CATEGORY,
    site: str = "媒体任务",
    capability: str = IMAGE_GENERATE,
) -> ServiceProbeResult | None:
    if base_url:
        base = base_url.rstrip("/")
    else:
        from pallas.product.llm.config import get_llm_config, llm_server_base_url

        base = llm_server_base_url(get_llm_config()).rstrip("/")
    if not base:
        return None
    url = f"{base}/api/media/tasks/runtime"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=timeout_sec)
        latency_ms = int(response.elapsed.total_seconds() * 1000) if response.elapsed else None
        if response.status_code != 200:
            return build_runtime_probe_result(
                capability,
                category=category,
                site=site,
                ok=False,
                latency_ms=latency_ms,
                status_code=response.status_code,
                error=f"媒体任务 runtime 状态 {response.status_code}",
                failure_class=FAILURE_RUNTIME_UNAVAILABLE,
                health_state=HEALTH_UNHEALTHY,
            )
        body = response.json()
        from pallas.product.llm.ai_health_parse import parse_media_tasks

        parsed = parse_media_tasks(body) or {}
        queue_depth = int(parsed.get("queue_depth") or body.get("queue_depth") or 0)
        active_tasks = int(parsed.get("active_tasks") or body.get("active_tasks") or 0)
        total_tasks = int(parsed.get("total_tasks") or body.get("total_tasks") or 0)
        detail = f"队列 {queue_depth} · 执行中 {active_tasks} · 累计 {total_tasks}"
        queue_hint = f"队列深度 {queue_depth}"
        busy = queue_depth > 3 or active_tasks > 2
        health_state_raw = str(parsed.get("health_state") or "").strip().lower()
        circuit_state_raw = str(parsed.get("circuit_state") or "closed").strip().lower()
        recent_failure = parsed.get("recent_failure_class")
        probe_health = HEALTH_DEGRADED if health_state_raw == "degraded" or busy else HEALTH_HEALTHY
        if health_state_raw == "unhealthy":
            probe_health = HEALTH_UNHEALTHY
        runtime_state = RUNTIME_HEALTHY
        if health_state_raw in {"degraded", "unhealthy"} or busy:
            runtime_state = RUNTIME_DEGRADED
        return build_runtime_probe_result(
            capability,
            category=category,
            site=site,
            ok=health_state_raw != "unhealthy",
            latency_ms=latency_ms,
            status_code=response.status_code,
            error=detail,
            runtime_state=runtime_state,
            runtime_detail=detail,
            health_state=probe_health,
            circuit_state=circuit_state_raw if circuit_state_raw in {"open", "half_open", "closed"} else CIRCUIT_CLOSED,
            recent_failure_class=str(recent_failure) if recent_failure else None,
            queue_load_hint=queue_hint,
        )
    except Exception as e:  # noqa: BLE001
        return build_runtime_probe_result(
            capability,
            category=category,
            site=site,
            ok=False,
            latency_ms=None,
            status_code=None,
            error=str(e)[:120],
            failure_class=failure_class_from_error(str(e)[:120]),
            health_state=HEALTH_UNHEALTHY,
        )


async def probe_maa_endpoints(
    *,
    cfg: MaaConfig | None = None,
    timeout_sec: float = 15.0,
    draft_values: dict[str, Any] | None = None,
) -> list[ServiceProbeResult]:
    from importlib.util import find_spec

    from pallas.core.platform.shard import context as shard_ctx

    if find_spec("pallas_plugin_maa") is None and find_spec("pallas_plugin_maa_hub") is None:
        return []
    maa_endpoints = import_plugin_submodule("maa", "endpoints")
    resolve_maa_probe_http_endpoints = maa_endpoints.resolve_maa_probe_http_endpoints

    if cfg is None and draft_values is not None:
        from pallas.product.service_gateways.draft import maa_cfg_from_draft

        cfg = maa_cfg_from_draft(draft_values)

    ep = resolve_maa_probe_http_endpoints(cfg)
    probe_body = {"user": "", "device": ""}
    report_body = {"user": "", "device": "", "task": "", "status": "", "payload": ""}
    async with httpx.AsyncClient() as client:
        get_r, report_r = await asyncio.gather(
            probe_http_post_json(
                client,
                category=MAA_CATEGORY,
                site="获取任务",
                url=ep.get_task_url,
                json_body=probe_body,
                timeout_sec=timeout_sec,
                capability=AUTOMATION_MAA,
            ),
            probe_http_post_json(
                client,
                category=MAA_CATEGORY,
                site="汇报任务",
                url=ep.report_status_url,
                json_body=report_body,
                timeout_sec=timeout_sec,
                capability=AUTOMATION_MAA,
            ),
        )
    results = enrich_probe_result_capabilities([get_r, report_r], AUTOMATION_MAA)
    if shard_ctx.sharding_active() and shard_ctx.is_hub():
        return maa_hub_probe_note(normalize_maa_runtime_results(results))
    return normalize_maa_runtime_results(results)


def sing_probe_urls(base: str, cfg: SingConfig | None = None) -> list[tuple[str, str]]:
    _ = cfg
    root = base.rstrip("/")
    return [("健康检查", urljoin(f"{root}/", "health"))]


def normalize_sing_runtime_results(
    results: list[ServiceProbeResult],
) -> list[ServiceProbeResult]:
    return normalize_runtime_probe_results(
        results,
        disabled_when=lambda item: "未启用" in str(item.error or ""),
        disabled_health_state=HEALTH_UNKNOWN,
    )


async def probe_sing_server(
    *,
    cfg: SingConfig | None = None,
    timeout_sec: float = 15.0,
    draft_values: dict[str, Any] | None = None,
) -> list[ServiceProbeResult]:
    from importlib.util import find_spec

    if find_spec("pallas_plugin_sing") is None:
        return []
    sing_config = import_plugin_submodule("sing", "config")
    get_sing_config = sing_config.get_sing_config
    sing_runtime_mode = sing_config.sing_runtime_mode
    sing_server_url = sing_config.sing_server_url

    if cfg is None and draft_values is not None:
        from pallas.product.service_gateways.draft import sing_cfg_from_draft

        cfg = sing_cfg_from_draft(draft_values)
    cfg = cfg or get_sing_config()
    if not cfg.sing_enable:
        return normalize_sing_runtime_results([
            build_runtime_probe_result(
                MEDIA_SING,
                category=SING_CATEGORY,
                site="服务",
                ok=False,
                latency_ms=None,
                status_code=None,
                error="未启用 sing_enable",
                runtime_state=RUNTIME_DISABLED,
                failure_class=FAILURE_RUNTIME_DISABLED,
                health_state=HEALTH_UNKNOWN,
            )
        ])
    base = sing_server_url(cfg)
    urls = sing_probe_urls(base, cfg)
    async with httpx.AsyncClient() as client:
        raw_results = [
            await probe_http_get(
                client,
                category=SING_CATEGORY,
                site=site,
                url=url,
                timeout_sec=timeout_sec,
                capability=MEDIA_SING,
            )
            for site, url in urls
        ]
    media_task_probe = await probe_ai_media_task_runtime(
        base_url=base,
        timeout_sec=timeout_sec,
        category=SING_CATEGORY,
        site="媒体任务",
        capability=MEDIA_SING,
    )
    if media_task_probe is not None:
        mode = sing_runtime_mode(cfg)
        media_task_probe = patch_probe_result(
            media_task_probe,
            runtime_detail=f"{media_task_probe.runtime_detail or ''} · 模式 {mode}".strip(" ·"),
        )
        raw_results.append(media_task_probe)
    return normalize_sing_runtime_results(enrich_probe_result_capabilities(raw_results, MEDIA_SING))


async def probe_media_services(*, timeout_sec: float = 15.0, draft_values=None) -> list[ServiceProbeResult]:
    from nonebot import logger

    async def _safe_await(coroutine, name: str) -> list[ServiceProbeResult]:
        try:
            return await coroutine
        except Exception as e:  # noqa: BLE001
            logger.debug("service_gateways {} probe failed: {}", name, e)
            return []

    image_task = probe_image_gateways(draft_values=draft_values)
    maa_task = probe_maa_endpoints(timeout_sec=timeout_sec, draft_values=draft_values)
    sing_task = probe_sing_server(timeout_sec=timeout_sec, draft_values=draft_values)

    image_results, maa_results, sing_results = await asyncio.gather(
        _safe_await(image_task, "images"),
        _safe_await(maa_task, "maa"),
        _safe_await(sing_task, "sing"),
    )
    return [*image_results, *maa_results, *sing_results]


register_service_probe_provider(
    ServiceProbeProvider(name="media", probe=probe_media_services, priority=20),
)
