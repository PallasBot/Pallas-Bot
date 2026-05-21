from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

import httpx

from src.common.service_probe import ServiceProbeResult, probe_http_get, probe_http_post_json
from src.common.webui.gateway_fields import (
    ALL_GATEWAY_FIELDS,
    MAA_GATEWAY_FIELDS,
    PALLAS_IMAGE_GATEWAY_FIELDS,
    SING_GATEWAY_FIELDS,
)

if TYPE_CHECKING:
    from src.plugins.maa.config import Config as MaaConfig
    from src.plugins.sing.config import Config as SingConfig

MAA_CATEGORY = "MAA远控"
SING_CATEGORY = "唱歌"
IMAGE_CATEGORY = "牛牛画画"


def _maa_hub_probe_note(results: list[ServiceProbeResult]) -> list[ServiceProbeResult]:
    """hub 探测未带 QQ 时仅命中入口，避免误读为 worker 已通。"""
    note = "hub 入口已响应（探测未带 QQ，不验证 worker 转发）"
    out: list[ServiceProbeResult] = []
    for r in results:
        if r.ok and r.latency_ms is not None:
            out.append(
                ServiceProbeResult(
                    category=r.category,
                    site=r.site,
                    ok=True,
                    latency_ms=r.latency_ms,
                    status_code=r.status_code,
                    error=note,
                ),
            )
        else:
            out.append(r)
    return out


async def probe_image_gateways() -> list[ServiceProbeResult]:
    """画画网关；刷新配置后探测，与牛牛画画命令共用 active_image_gen_settings。"""
    from nonebot import logger

    from src.plugins.pallas_image.config import active_image_gen_settings
    from src.plugins.pallas_image.gateway_probe import probe_all_backends

    try:
        settings = active_image_gen_settings()
    except Exception as e:  # noqa: BLE001
        logger.debug("connectivity image settings load failed: {}", e)
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
        logger.debug("connectivity image probe failed: {}", e)
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
) -> list[ServiceProbeResult]:
    from src.common.bot_runtime.roles import is_sharded_hub
    from src.common.shard.registry.config import is_sharding_active
    from src.plugins.maa.endpoints import resolve_maa_probe_http_endpoints

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
    if is_sharding_active() and is_sharded_hub():
        return _maa_hub_probe_note(results)
    return results


def sing_probe_urls(base: str, cfg: SingConfig | None = None) -> list[tuple[str, str]]:
    """与 Pallas-Bot-AI 对齐：GET /health（勿 GET /api/request，该路径仅 POST …/request/{id}）。"""
    _ = cfg
    root = base.rstrip("/")
    return [("健康检查", urljoin(f"{root}/", "health"))]


async def probe_sing_server(
    *,
    cfg: SingConfig | None = None,
    timeout_sec: float = 15.0,
) -> list[ServiceProbeResult]:
    from src.plugins.sing.config import get_sing_config, sing_server_url

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


async def probe_all_connectivity(*, timeout_sec: float = 15.0) -> list[ServiceProbeResult]:
    image_task = probe_image_gateways()
    maa_task = probe_maa_endpoints(timeout_sec=timeout_sec)
    sing_task = probe_sing_server(timeout_sec=timeout_sec)
    image_results, maa_results, sing_results = await asyncio.gather(image_task, maa_task, sing_task)
    return [*image_results, *maa_results, *sing_results]


def _draft_subset(values: dict[str, Any], keys: frozenset[str]) -> dict[str, Any]:
    return {k: v for k, v in values.items() if k in keys}


def _pallas_image_draft(values: dict[str, Any]) -> dict[str, Any]:
    from src.plugins.pallas_image.config import get_pallas_image_config

    base = get_pallas_image_config().model_dump(mode="python")
    base.update(_draft_subset(values, PALLAS_IMAGE_GATEWAY_FIELDS))
    return base


def _maa_cfg_from_draft(values: dict[str, Any]) -> MaaConfig:
    from src.plugins.maa.config import Config as MaaConfig
    from src.plugins.maa.config import get_maa_config

    base = get_maa_config().model_dump(mode="python")
    base.update(_draft_subset(values, MAA_GATEWAY_FIELDS))
    return MaaConfig.model_validate(base)


def _sing_cfg_from_draft(values: dict[str, Any]) -> SingConfig:
    from src.plugins.sing.config import Config as SingConfig
    from src.plugins.sing.config import get_sing_config

    base = get_sing_config().model_dump(mode="python")
    base.update(_draft_subset(values, SING_GATEWAY_FIELDS))
    return SingConfig.model_validate(base)


async def probe_all_connectivity_from_draft(
    values: dict[str, Any] | None = None,
    *,
    timeout_sec: float = 15.0,
) -> list[ServiceProbeResult]:
    raw = values or {}
    if not raw:
        return await probe_all_connectivity(timeout_sec=timeout_sec)
    unknown = set(raw.keys()) - ALL_GATEWAY_FIELDS
    if unknown:
        raise ValueError(f"未知配置项: {', '.join(sorted(unknown))}")
    from src.plugins.pallas_image.gateway_probe import image_gen_settings_from_draft, probe_all_backends

    async def image_from_draft() -> list[ServiceProbeResult]:
        settings = image_gen_settings_from_draft(_pallas_image_draft(raw))
        results = await probe_all_backends(settings)
        if not results:
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
        return results

    image_task = image_from_draft()
    maa_task = probe_maa_endpoints(cfg=_maa_cfg_from_draft(raw), timeout_sec=timeout_sec)
    sing_task = probe_sing_server(cfg=_sing_cfg_from_draft(raw), timeout_sec=timeout_sec)
    image_results, maa_results, sing_results = await asyncio.gather(image_task, maa_task, sing_task)
    return [*image_results, *maa_results, *sing_results]
