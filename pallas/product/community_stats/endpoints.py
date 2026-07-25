"""社区统计心跳 / stats 地址。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pallas.product.community_stats.config import CommunityStatsConfig

PRIMARY_HEARTBEAT = "https://stats.pallasbot.top/v1/heartbeat"
PRIMARY_CORPUS_API_BASE = "https://stats.pallasbot.top/v1/corpus"

# 历史备案备用域：仅识别为「自动模式」并改走正式中心，不再请求。
_LEGACY_FALLBACK_HEARTBEATS: frozenset[str] = frozenset({
    "https://pallas.togetsudo.com/v1/heartbeat",
    "http://pallas.togetsudo.com/v1/heartbeat",
})


def normalize_heartbeat_url(url: str) -> str:
    return (url or "").strip().rstrip("/")


def is_auto_endpoint_mode(cfg: CommunityStatsConfig) -> bool:
    """未配置自定义 endpoint，或仍为正式中心 / 历史备用域之一。"""
    ep = normalize_heartbeat_url(cfg.endpoint)
    if not ep or ep == PRIMARY_HEARTBEAT:
        return True
    return ep in _LEGACY_FALLBACK_HEARTBEATS


def custom_heartbeat_url(cfg: CommunityStatsConfig) -> str | None:
    if is_auto_endpoint_mode(cfg):
        return None
    ep = normalize_heartbeat_url(cfg.endpoint)
    if ep.endswith("/heartbeat"):
        return ep
    return ep + "/heartbeat" if ep else None


def heartbeat_urls_for_config(cfg: CommunityStatsConfig) -> list[str]:
    custom = custom_heartbeat_url(cfg)
    if custom:
        return [custom]
    return [PRIMARY_HEARTBEAT]


def stats_urls_for_config(cfg: CommunityStatsConfig) -> list[str]:
    from pallas.product.community_stats.stats_url import stats_url_from_endpoint

    return [stats_url_from_endpoint(u) for u in heartbeat_urls_for_config(cfg)]


def monitor_overview_urls_for_config(cfg: CommunityStatsConfig) -> list[str]:
    from pallas.product.community_stats.stats_url import monitor_overview_url_from_endpoint

    return [monitor_overview_url_from_endpoint(u) for u in heartbeat_urls_for_config(cfg)]


def corpus_hot_urls_for_config(cfg: CommunityStatsConfig) -> list[str]:
    from pallas.product.community_stats.stats_url import corpus_hot_url_from_endpoint

    return [corpus_hot_url_from_endpoint(u) for u in heartbeat_urls_for_config(cfg)]


def corpus_api_base_from_heartbeat(heartbeat_url: str) -> str:
    url = normalize_heartbeat_url(heartbeat_url)
    if url.endswith("/heartbeat"):
        return f"{url[: -len('/heartbeat')]}/corpus"
    if url.endswith("/corpus/enroll"):
        return url[: -len("/enroll")]
    return f"{url}/corpus" if url else PRIMARY_CORPUS_API_BASE


def corpus_api_base_from_enroll_url(enroll_url: str) -> str:
    return corpus_api_base_from_heartbeat(normalize_heartbeat_url(enroll_url))


def corpus_api_base_urls_for_config(cfg: CommunityStatsConfig) -> list[str]:
    custom = custom_heartbeat_url(cfg)
    if custom:
        return [corpus_api_base_from_heartbeat(custom)]
    return [PRIMARY_CORPUS_API_BASE]


def gallery_posts_urls_for_config(cfg: CommunityStatsConfig) -> list[str]:
    from pallas.product.community_stats.stats_url import gallery_posts_url_from_endpoint

    return [gallery_posts_url_from_endpoint(u) for u in heartbeat_urls_for_config(cfg)]
