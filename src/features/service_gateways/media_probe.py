"""画画 / MAA / 唱歌等扩展服务探测（可选 provider）。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

import httpx

from src.features.service_gateways.registry import ServiceProbeProvider, register_service_probe_provider
from src.shared.service_probe import ServiceProbeResult, probe_http_get, probe_http_post_json

if TYPE_CHECKING:
    from src.plugins.maa.config import Config as MaaConfig
    from src.plugins.sing.config import Config as SingConfig

MAA_CATEGORY = "MAA远控"
SING_CATEGORY = "唱歌"
IMAGE_CATEGORY = "牛牛画画"


def maa_hub_probe_note(results: list[ServiceProbeResult]) -> list[ServiceProbeResult]:
    note = "hub 入口已响应（探测未带 QQ，不验证 worker 转发）"
    out: list[ServiceProbeResult] = []
    for item in results:
        if item.ok and item.latency_ms is not None:
            out.append(
                ServiceProbeResult(
                    category=item.category,
                    site=item.site,
                    ok=True,
                    latency_ms=item.latency_ms,
                    status_code=item.status_code,
                    error=note,
                ),
            )
        else:
            out.append(item)
    return out


async def probe_image_gateways(*, draft_values: dict[str, Any] | None = None) -> list[ServiceProbeResult]:
    from nonebot import logger

    from src.plugins.draw.config import active_image_gen_settings
    from src.plugins.draw.gateway_probe import image_gen_settings_from_draft, probe_all_backends

    try:
        if draft_values is not None:
            from src.features.service_gateways.draft import draw_draft_from_values

            settings = image_gen_settings_from_draft(draw_draft_from_values(draft_values))
        else:
            settings = active_image_gen_settings()
    except Exception as e:  # noqa: BLE001
        logger.debug("service_gateways image settings load failed: {}", e)
        return [
            ServiceProbeResult(
                category=IMAGE_CATEGORY,
                site="网关",
                ok=False,
                latency_ms=None,
                status_code=None,
                error=str(e)[:120],
            ),
        ]
    if not settings.api_backends():
        return [
            ServiceProbeResult(
                category=IMAGE_CATEGORY,
                site="网关",
                ok=False,
                latency_ms=None,
                status_code=None,
                error="尚未配置可用网关（需 base_url、api_key 或 api_backends）",
            ),
        ]
    try:
        return await probe_all_backends(settings)
    except Exception as e:  # noqa: BLE001
        logger.debug("service_gateways image probe failed: {}", e)
        return [
            ServiceProbeResult(
                category=IMAGE_CATEGORY,
                site="网关",
                ok=False,
                latency_ms=None,
                status_code=None,
                error=str(e)[:120],
            ),
        ]


async def probe_maa_endpoints(
    *,
    cfg: MaaConfig | None = None,
    timeout_sec: float = 15.0,
    draft_values: dict[str, Any] | None = None,
) -> list[ServiceProbeResult]:
    from src.platform.shard import context as shard_ctx
    from src.plugins.maa.endpoints import resolve_maa_probe_http_endpoints

    if cfg is None and draft_values is not None:
        from src.features.service_gateways.draft import maa_cfg_from_draft

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
            ),
            probe_http_post_json(
                client,
                category=MAA_CATEGORY,
                site="汇报任务",
                url=ep.report_status_url,
                json_body=report_body,
                timeout_sec=timeout_sec,
            ),
        )
    results = [get_r, report_r]
    if shard_ctx.sharding_active() and shard_ctx.is_hub():
        return maa_hub_probe_note(results)
    return results


def sing_probe_urls(base: str, cfg: SingConfig | None = None) -> list[tuple[str, str]]:
    _ = cfg
    root = base.rstrip("/")
    return [("健康检查", urljoin(f"{root}/", "health"))]


async def probe_sing_server(
    *,
    cfg: SingConfig | None = None,
    timeout_sec: float = 15.0,
    draft_values: dict[str, Any] | None = None,
) -> list[ServiceProbeResult]:
    from src.plugins.sing.config import get_sing_config, sing_server_url

    if cfg is None and draft_values is not None:
        from src.features.service_gateways.draft import sing_cfg_from_draft

        cfg = sing_cfg_from_draft(draft_values)
    cfg = cfg or get_sing_config()
    if not cfg.sing_enable:
        return [
            ServiceProbeResult(
                category=SING_CATEGORY,
                site="服务",
                ok=False,
                latency_ms=None,
                status_code=None,
                error="未启用 sing_enable",
            ),
        ]
    base = sing_server_url(cfg)
    urls = sing_probe_urls(base, cfg)
    async with httpx.AsyncClient() as client:
        return [
            await probe_http_get(
                client,
                category=SING_CATEGORY,
                site=site,
                url=url,
                timeout_sec=timeout_sec,
            )
            for site, url in urls
        ]


async def probe_media_services(*, timeout_sec: float = 15.0, draft_values=None) -> list[ServiceProbeResult]:
    image_task = probe_image_gateways(draft_values=draft_values)
    maa_task = probe_maa_endpoints(timeout_sec=timeout_sec, draft_values=draft_values)
    sing_task = probe_sing_server(timeout_sec=timeout_sec, draft_values=draft_values)
    image_results, maa_results, sing_results = await asyncio.gather(image_task, maa_task, sing_task)
    return [*image_results, *maa_results, *sing_results]


register_service_probe_provider(
    ServiceProbeProvider(name="media", probe=probe_media_services, priority=20),
)
