"""多机协同专用 Redis 配置。"""

from __future__ import annotations

from functools import lru_cache

from pallas.core.foundation.config.repo_settings import repo_env_raw_value

_FEDERATE_COORD_URL_KEY = "PALLAS_FEDERATE_COORD_REDIS_URL"


def _setting(key: str) -> str | None:
    raw = repo_env_raw_value(key)
    if raw is None:
        return None
    s = str(raw).strip()
    return s or None


def resolve_federate_redis_url() -> str | None:
    """联邦协调 Redis：显式 PALLAS_FEDERATE_COORD_REDIS_URL → bootstrap 落盘。"""
    explicit = _setting(_FEDERATE_COORD_URL_KEY)
    if explicit:
        return explicit
    try:
        from pallas.product.control_plane.store import load_bootstrap_coord_redis_url

        boot_url = load_bootstrap_coord_redis_url()
        if boot_url:
            return boot_url
    except Exception:
        pass
    return None


@lru_cache(maxsize=1)
def get_federate_redis_client():
    url = resolve_federate_redis_url()
    if not url:
        return None
    if not federate_redis_ping(url):
        return None
    try:
        import redis
    except ImportError:
        return None
    return redis.Redis.from_url(url, socket_connect_timeout=1.0, socket_timeout=2.0)


def clear_federate_redis_client_cache() -> None:
    get_federate_redis_client.cache_clear()
    federate_redis_available.cache_clear()


def federate_redis_ping(url: str) -> bool:
    try:
        import redis
    except ImportError:
        return False
    try:
        client = redis.Redis.from_url(url, socket_connect_timeout=1.0, socket_timeout=1.0)
        return bool(client.ping())
    except Exception as e:
        from urllib.parse import urlparse

        host = urlparse(url).hostname or ""
        if host:
            import socket

            try:
                socket.getaddrinfo(host, None)
            except socket.gaierror:
                from nonebot import logger

                logger.warning(
                    "federate coord redis: 无法解析主机 {}（请为 coord 配置 DNS A 记录）",
                    host,
                )
                return False
        from nonebot import logger

        logger.debug("federate coord redis ping failed host={}: {}", host or "?", e)
        return False


@lru_cache(maxsize=1)
def federate_redis_available() -> bool:
    url = resolve_federate_redis_url()
    return bool(url and federate_redis_ping(url))


def federate_claim_ttl_sec() -> int:
    raw = _setting("PALLAS_FEDERATE_CLAIM_TTL_SEC")
    if raw and raw.isdigit():
        return max(60, int(raw))
    try:
        from pallas.product.control_plane.store import load_bootstrap_claim_ttl_sec

        boot_ttl = load_bootstrap_claim_ttl_sec()
        if boot_ttl is not None:
            return boot_ttl
    except Exception:
        pass
    return 86400
