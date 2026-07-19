"""向社区统计中心自动 enroll 语料 token。"""

from __future__ import annotations

import time

import httpx
from nonebot import logger

from pallas.core.foundation.db.context_repo_access import invalidate_shared_context_repository
from pallas.product.community_stats.config import get_community_stats_config
from pallas.product.community_stats.endpoints import (
    corpus_api_base_from_enroll_url,
    heartbeat_urls_for_config,
    is_auto_endpoint_mode,
    normalize_heartbeat_url,
)
from pallas.product.community_stats.reporter import _headers as community_stats_headers
from pallas.product.community_stats.store import load_or_create_deployment_id
from pallas.product.corpus.config import (
    auto_enroll_enabled,
    clear_corpus_config_cache,
    community_manual_configured,
    is_community_corpus_wanted,
)
from pallas.product.corpus.store import (
    corpus_community_enrollment_valid,
    load_corpus_community_state,
    save_corpus_community_state,
)
from pallas.product.message_scrub.quiet_http_loggers import scrub_http_log_noise

_HTTP_TIMEOUT_SEC = 15.0


def enroll_url_from_heartbeat(heartbeat_url: str) -> str:
    url = normalize_heartbeat_url(heartbeat_url)
    if url.endswith("/heartbeat"):
        return f"{url[: -len('/heartbeat')]}/corpus/enroll"
    return f"{url}/corpus/enroll"


def corpus_enroll_urls() -> list[str]:
    cfg = get_community_stats_config()
    return [enroll_url_from_heartbeat(u) for u in heartbeat_urls_for_config(cfg)]


def should_run_corpus_auto_enroll() -> bool:
    from pallas.product.community_stats.reporter import should_run_community_stats_reporter

    if not should_run_community_stats_reporter():
        return False
    if not is_community_corpus_wanted():
        return False
    if not auto_enroll_enabled():
        return False
    if community_manual_configured():
        return False
    return True


async def ensure_corpus_community_enrolled(*, force: bool = False) -> bool:
    """成功 enroll 或已有有效落盘 token 时返回 True。"""
    if not should_run_corpus_auto_enroll():
        from pallas.product.corpus.config import community_configured

        return community_configured() or corpus_community_enrollment_valid()

    state = load_corpus_community_state()
    if not force and corpus_community_enrollment_valid(state):
        return True

    deployment_id = load_or_create_deployment_id()
    cfg = get_community_stats_config()
    headers = community_stats_headers(cfg)
    payload = {"deployment_id": deployment_id}
    urls = corpus_enroll_urls()
    if not urls:
        logger.warning("corpus enroll: 无可用 enroll URL")
        return corpus_community_enrollment_valid(state)

    last_error = ""
    try:
        async with scrub_http_log_noise():
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SEC) as client:
                for endpoint in urls:
                    try:
                        resp = await client.post(endpoint, json=payload, headers=headers)
                    except httpx.HTTPError as e:
                        last_error = str(e)
                        logger.warning(f"corpus enroll failed endpoint={endpoint}: {e}")
                        continue
                    if resp.status_code != 200:
                        last_error = f"HTTP {resp.status_code}: {(resp.text or '')[:200]}"
                        logger.warning(f"corpus enroll HTTP {resp.status_code} endpoint={endpoint}")
                        continue
                    data = resp.json()
                    if not isinstance(data, dict):
                        last_error = "invalid json body"
                        continue
                    token = str(data.get("corpus_token") or "").strip()
                    server_api_base = str(data.get("api_base") or "").strip().rstrip("/")
                    derived_api_base = corpus_api_base_from_enroll_url(endpoint)
                    if is_auto_endpoint_mode(cfg):
                        api_base = derived_api_base
                    else:
                        api_base = server_api_base or derived_api_base
                    if not token or not api_base:
                        last_error = "missing corpus_token or api_base"
                        continue
                    policy = data.get("policy")
                    contribute = None
                    if isinstance(policy, dict) and "contribute" in policy:
                        contribute = bool(policy.get("contribute"))
                    expires_raw = data.get("expires_at")
                    expires_at = int(expires_raw) if expires_raw is not None else None
                    save_corpus_community_state(
                        api_base=api_base,
                        corpus_token=token,
                        expires_at=expires_at,
                        contribute=contribute,
                    )
                    clear_corpus_config_cache()
                    invalidate_shared_context_repository()
                    logger.info(
                        "corpus enroll: ok deployment_id={} api_base={}",
                        deployment_id,
                        api_base,
                    )
                    return True
    except httpx.HTTPError as e:
        last_error = str(e)
        logger.warning(f"corpus enroll failed: {e}")

    if last_error:
        logger.debug("corpus enroll: no endpoint succeeded last_error={}", last_error)
    return corpus_community_enrollment_valid(state)


async def maybe_refresh_corpus_enrollment_on_auth_failure() -> None:
    """远端语料 401 时可强制 re-enroll。"""
    if not should_run_corpus_auto_enroll():
        return
    state = load_corpus_community_state()
    enrolled_at = int(state.get("enrolled_at") or 0)
    if enrolled_at and int(time.time()) - enrolled_at < 300:
        return
    await ensure_corpus_community_enrolled(force=True)
