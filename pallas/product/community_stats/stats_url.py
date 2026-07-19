"""由心跳 endpoint 推导公开 stats URL。"""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

_DEFAULT_STATS = "https://stats.pallasbot.top/v1/stats"
_DEFAULT_MONITOR = "https://stats.pallasbot.top/v1/monitor/overview"


def stats_url_from_endpoint(heartbeat_endpoint: str) -> str:
    ep = (heartbeat_endpoint or "").strip()
    if not ep:
        return _DEFAULT_STATS
    norm = ep.rstrip("/")
    if norm.endswith("/heartbeat"):
        return norm[: -len("/heartbeat")] + "/stats"
    parsed = urlparse(ep)
    if parsed.scheme and parsed.netloc:
        root = f"{parsed.scheme}://{parsed.netloc}"
        return urljoin(root + "/", "v1/stats")
    return _DEFAULT_STATS


def monitor_overview_url_from_endpoint(heartbeat_endpoint: str) -> str:
    ep = (heartbeat_endpoint or "").strip()
    if not ep:
        return _DEFAULT_MONITOR
    norm = ep.rstrip("/")
    if norm.endswith("/heartbeat"):
        return norm[: -len("/heartbeat")] + "/monitor/overview"
    parsed = urlparse(ep)
    if parsed.scheme and parsed.netloc:
        root = f"{parsed.scheme}://{parsed.netloc}"
        return urljoin(root + "/", "v1/monitor/overview")
    return _DEFAULT_MONITOR


def corpus_hot_url_from_endpoint(heartbeat_endpoint: str) -> str:
    ep = (heartbeat_endpoint or "").strip()
    if not ep:
        return "https://stats.pallasbot.top/v1/corpus/hot"
    norm = ep.rstrip("/")
    if norm.endswith("/heartbeat"):
        return norm[: -len("/heartbeat")] + "/corpus/hot"
    parsed = urlparse(ep)
    if parsed.scheme and parsed.netloc:
        root = f"{parsed.scheme}://{parsed.netloc}"
        return urljoin(root + "/", "v1/corpus/hot")
    return "https://stats.pallasbot.top/v1/corpus/hot"
