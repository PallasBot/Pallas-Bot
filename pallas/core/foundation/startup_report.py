"""聚合启动阶段关键事实，并在启动链尾输出成熟摘要。"""

from __future__ import annotations

import os
from collections import OrderedDict
from dataclasses import dataclass, field

from nonebot import get_driver, logger


@dataclass
class StartupFactCollector:
    facts: OrderedDict[str, str] = field(default_factory=OrderedDict)
    warnings: OrderedDict[str, str] = field(default_factory=OrderedDict)
    emitted: bool = False

    def set_fact(self, key: str, value: str | None) -> None:
        text = str(value or "").strip()
        if text:
            self.facts[key] = text

    def set_warning(self, key: str, value: str | None) -> None:
        text = str(value or "").strip()
        if text:
            self.warnings[key] = text


_collector = StartupFactCollector()


def register_startup_fact(key: str, value: str | None) -> None:
    _collector.set_fact(key, value)


def register_startup_warning(key: str, value: str | None) -> None:
    _collector.set_warning(key, value)


def reset_startup_report_for_tests() -> None:
    _collector.facts.clear()
    _collector.warnings.clear()
    _collector.emitted = False


def startup_report_snapshot() -> dict[str, dict[str, str] | bool]:
    return {
        "facts": dict(_collector.facts),
        "warnings": dict(_collector.warnings),
        "emitted": _collector.emitted,
    }


def _runtime_base_fields() -> list[str]:
    from pallas.core.foundation.bot_version import get_pallas_bot_version_for_reporting
    from pallas.core.platform.bot_runtime.roles import bot_role, is_sharded_worker

    driver = get_driver()
    cfg = driver.config
    role = str(bot_role())
    fields = [f"v={get_pallas_bot_version_for_reporting()}", f"role={role}"]

    if is_sharded_worker():
        shard_id = str(os.environ.get("PALLAS_SHARD_ID", "") or "").strip()
        if shard_id:
            fields.append(f"shard={shard_id}")

    host = str(getattr(cfg, "host", "") or "").strip() or "0.0.0.0"
    port = getattr(cfg, "port", None)
    if port not in (None, ""):
        fields.append(f"listen={host}:{port}")

    backend = str(os.environ.get("DB_BACKEND", "") or "").strip().lower()
    if backend:
        fields.append(f"db={backend}")

    return fields


def emit_startup_summary() -> None:
    if _collector.emitted:
        return
    _collector.emitted = True

    parts = _runtime_base_fields()
    parts.extend(f"{key}={value}" for key, value in _collector.facts.items())
    logger.info("[启动] {}", " | ".join(parts))

    if _collector.warnings:
        warning_text = " | ".join(f"{key}={value}" for key, value in _collector.warnings.items())
        logger.warning("[启动] 降级：{}", warning_text)
