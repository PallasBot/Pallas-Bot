"""分片 Redis 可达性探测。"""

from __future__ import annotations


def shard_redis_doctor_lines() -> list[str]:
    from pallas.core.foundation.config.dotenv import apply_repo_settings_to_environ
    from pallas.core.platform.coord.redis_settings import (
        clear_coord_redis_settings_cache,
        coord_redis_enabled,
        coord_redis_mode,
        resolve_coord_redis_url,
    )

    apply_repo_settings_to_environ()
    clear_coord_redis_settings_cache()

    mode = coord_redis_mode()
    url = resolve_coord_redis_url() or ""
    try:
        import redis  # noqa: F401

        pkg = "yes"
    except ImportError:
        pkg = "no"

    lines = [f"coord redis policy: {mode}"]
    if url:
        lines.append(f"coord redis url: {url}")
    lines.append(f"coord redis package: {pkg}")
    if mode == "false":
        lines.append("coord redis: disabled")
        return lines
    if not url:
        lines.append("coord redis: 未配置 REDIS_URL")
        return lines
    if coord_redis_enabled():
        lines.append("coord redis: 可达")
        return lines
    if pkg == "no":
        lines.append("coord redis: 不可达（缺少 redis 包，可 uv sync --extra coord-redis）")
    else:
        lines.append("coord redis: 不可达")
    return lines
