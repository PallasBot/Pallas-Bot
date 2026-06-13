"""社区统计心跳 / stats 地址：正式域名 + 备案前备用，自动切换。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from src.features.community_stats.store import load_community_stats_state

if TYPE_CHECKING:
    from src.features.community_stats.config import CommunityStatsConfig

PRIMARY_HEARTBEAT = "https://stats.pallasbot.top/v1/heartbeat"
FALLBACK_HEARTBEAT = "https://pallas.togetsudo.com/v1/heartbeat"
PRIMARY_CORPUS_API_BASE = "https://stats.pallasbot.top/v1/corpus"
FALLBACK_CORPUS_API_BASE = "https://pallas.togetsudo.com/v1/corpus"

_BUILTIN_HEARTBEATS: frozenset[str] = frozenset({PRIMARY_HEARTBEAT, FALLBACK_HEARTBEAT})

# 走备用入口时，每隔若干秒再探测一次正式域名是否已可用（备案通过后可自动切回）
_PRIMARY_REPROBE_SEC = 6 * 3600


def normalize_heartbeat_url(url: str) -> str:
    return (url or "").strip().rstrip("/")


def is_auto_endpoint_mode(cfg: CommunityStatsConfig) -> bool:
    """未配置自定义 endpoint，或仍为内置主/备地址之一。"""
    ep = normalize_heartbeat_url(cfg.endpoint)
    if not ep:
        return True
    return ep in _BUILTIN_HEARTBEATS


def custom_heartbeat_url(cfg: CommunityStatsConfig) -> str | None:
    if is_auto_endpoint_mode(cfg):
        return None
    ep = normalize_heartbeat_url(cfg.endpoint)
    if ep.endswith("/heartbeat"):
        return ep
    return ep + "/heartbeat" if ep else None


def should_reprobe_primary(*, last_probe_unix: int) -> bool:
    if last_probe_unix <= 0:
        return True
    return int(time.time()) - last_probe_unix >= _PRIMARY_REPROBE_SEC


def heartbeat_urls_for_config(cfg: CommunityStatsConfig) -> list[str]:
    custom = custom_heartbeat_url(cfg)
    if custom:
        return [custom]
    state = load_community_stats_state()
    active = normalize_heartbeat_url(str(state.get("heartbeat_endpoint") or ""))
    last_probe = int(state.get("last_primary_probe_unix") or 0)
    primary = PRIMARY_HEARTBEAT
    fallback = FALLBACK_HEARTBEAT
    if active == fallback and not should_reprobe_primary(last_probe_unix=last_probe):
        return [fallback]
    return [primary, fallback]


def stats_urls_for_config(cfg: CommunityStatsConfig) -> list[str]:
    from src.features.community_stats.stats_url import stats_url_from_endpoint

    return [stats_url_from_endpoint(u) for u in heartbeat_urls_for_config(cfg)]


def monitor_overview_urls_for_config(cfg: CommunityStatsConfig) -> list[str]:
    from src.features.community_stats.stats_url import monitor_overview_url_from_endpoint

    return [monitor_overview_url_from_endpoint(u) for u in heartbeat_urls_for_config(cfg)]


def corpus_hot_urls_for_config(cfg: CommunityStatsConfig) -> list[str]:
    from src.features.community_stats.stats_url import corpus_hot_url_from_endpoint

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
    return [corpus_api_base_from_heartbeat(u) for u in heartbeat_urls_for_config(cfg)]
