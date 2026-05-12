from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot import logger

from .config import get_message_scrub_config
from .providers.baidu import BaiduTextReviewProvider, clear_baidu_token_cache
from .providers.json_http import JsonHttpReviewProvider

if TYPE_CHECKING:
    from .providers.protocol import ReviewProvider


def _baidu_configured() -> bool:
    cfg = get_message_scrub_config()
    return bool(cfg.scrub_baidu_api_key and cfg.scrub_baidu_secret_key)


def _default_provider_order() -> list[str]:
    order: list[str] = []
    if _baidu_configured():
        order.append("baidu")
    u = get_message_scrub_config().json_http_url()
    if u:
        order.append("json_http")
    return order


def _configured_provider_order() -> list[str]:
    cfg = get_message_scrub_config()
    if not cfg.scrub_review_providers_key_present:
        return _default_provider_order()
    return [p.strip().lower() for p in cfg.scrub_review_providers.split(",") if p.strip()]


def build_review_providers() -> list[ReviewProvider]:
    """按配置顺序构造审查实例（链式：任一返回 blocked 则拦截）。"""
    out: list[ReviewProvider] = []
    seen: set[str] = set()
    for name in _configured_provider_order():
        if name in seen:
            continue
        if name in ("json_http", "generic", "http"):
            url = get_message_scrub_config().json_http_url()
            if not url or "json_http" in seen:
                continue
            out.append(JsonHttpReviewProvider(url))
            seen.add("json_http")
        elif name == "baidu":
            if not _baidu_configured() or "baidu" in seen:
                continue
            out.append(BaiduTextReviewProvider())
            seen.add("baidu")
        else:
            logger.warning("message_scrub: unknown review provider id {!r}, skipped", name)
    return out


async def run_review_chain(*, plain_text: str, raw_message: str) -> bool:
    """依次调用审查提供者，任一判定拦截则返回 True；无提供者则 False。"""
    providers = build_review_providers()
    if not providers:
        return False
    fail_open = get_message_scrub_config().inbound_filter_api_fail_open
    for p in providers:
        try:
            if await p.is_blocked(plain_text=plain_text, raw_message=raw_message):
                return True
        except Exception as e:
            logger.debug("review provider [{}] failed: {}", p.id, e)
            if not fail_open:
                return True
    return False


def clear_remote_review_caches() -> None:
    clear_baidu_token_cache()
